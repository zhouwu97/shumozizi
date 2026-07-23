"""将 v3 结果放行绑定到独立 adapter 的可重放验证收据。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.simple.adapters import verify_verification_protocol
from shumozizi.simple.results import read_result_index, require_result_index
from shumozizi.simple.review import scientific_review_status
from shumozizi.simple.selection import (
    read_candidate_registry,
    register_verified_candidate,
    retain_verified_incumbents,
    selection_group_key,
    validate_selection_contract,
)
from shumozizi.simple.state import read_simple_state, utc_now

QUALITY_PATH = Path("results/quality.json")
RESULT_ROLES = {"diagnostic", "candidate", "accepted", "rejected"}


def _schema() -> dict[str, Any]:
    """读取结果质量层的版本化 Schema。"""
    return load_json(
        resolve_repo_root(Path(__file__)) / "schemas/simple_result_quality.schema.json"
    )


def _schema_errors(payload: dict[str, Any]) -> list[str]:
    """返回质量文档的 Schema 校验错误。"""
    validator = Draft202012Validator(_schema(), format_checker=FormatChecker())
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    ]


def require_quality(payload: dict[str, Any]) -> None:
    """确保质量记录遵守独立验证与探索隔离的不变量。

    Args:
        payload: 待校验的质量文档。

    Raises:
        ContractError: Schema 或 v3 放行派生关系不合法。
    """
    errors = _schema_errors(payload)
    if errors:
        raise ContractError("; ".join(errors))
    if payload["schema_version"] != "3.0":
        return
    for item in payload["assessments"]:
        eligible = (
            item["execution_mode"] == "production"
            and item["execution_valid"]
            and item["feasibility_valid"]
            and item["exact_recomputed"]
            and item["search_adequacy"] == "passed"
            and item["problem_effectiveness"] == "progressed"
            and item["result_role"] == "accepted"
            and isinstance(item["verification"], dict)
            and isinstance(item["selection_contract"], dict)
        )
        if item["paper_allowed"] != eligible:
            raise ContractError("v3 paper_allowed 必须由独立 verification 收据自动推出")
        if item["execution_mode"] == "exploration" and item["result_role"] == "accepted":
            raise ContractError("exploration 结果不得登记为 accepted")


def read_result_quality(run_dir: Path) -> dict[str, Any]:
    """读取质量层；不存在时返回新的 v3 空文档。

    Args:
        run_dir: v3 运行目录。

    Returns:
        已校验的质量文档。
    """
    path = run_dir / QUALITY_PATH
    if not path.exists():
        payload = {"schema_version": "3.0", "run_id": run_dir.name, "assessments": []}
        require_quality(payload)
        return payload
    payload = load_json(path)
    require_quality(payload)
    return payload


def _result_map(run_dir: Path) -> dict[str, dict[str, Any]]:
    """返回按结果 ID 索引的执行记录。"""
    return {item["result_id"]: item for item in read_result_index(run_dir)["results"]}


def _result_mode(result: dict[str, Any]) -> str:
    """读取结果用途；缺失字段只能按历史生产记录解释。"""
    return str(result.get("execution_mode", "production"))


def _legacy_record(
    result: dict[str, Any], *, result_role: str, reasons: list[str]
) -> dict[str, Any]:
    """把没有独立收据的请求降级为不可放行诊断。"""
    return {
        "result_id": result["result_id"],
        "execution_mode": _result_mode(result),
        "execution_valid": bool(result["execution_valid"]),
        "feasibility_valid": False,
        "exact_recomputed": False,
        "search_adequacy": "not_assessed",
        "problem_effectiveness": "not_assessed",
        "result_role": "diagnostic" if result_role == "accepted" else result_role,
        "paper_allowed": False,
        "verification": None,
        "selection_contract": None,
        "reasons": list(dict.fromkeys([*reasons, "legacy_unverified_quality_claim"])),
        "assessed_at": utc_now(),
    }


def _upgrade_quality_payload(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """把 v1/v2 质量历史保留为 v3 diagnostic/unverified 记录。

    Args:
        run_dir: v3 运行目录。
        payload: 已通过旧 Schema 的质量文档。

    Returns:
        可继续写入的 v3 质量文档。
    """
    if payload["schema_version"] == "3.0":
        return payload
    results = _result_map(run_dir)
    assessments: list[dict[str, Any]] = []
    for legacy in payload["assessments"]:
        result = results.get(legacy["result_id"])
        if result is None:
            continue
        legacy_reasons = legacy.get("reasons", [])
        reasons = [item for item in legacy_reasons if isinstance(item, str) and item]
        assessments.append(
            _legacy_record(
                result,
                result_role=str(legacy.get("result_role", "diagnostic")),
                reasons=[*reasons, f"migrated_quality_v{payload['schema_version']}"],
            )
        )
    upgraded = {"schema_version": "3.0", "run_id": run_dir.name, "assessments": assessments}
    require_quality(upgraded)
    return upgraded


def _store_record(run_dir: Path, record: dict[str, Any]) -> dict[str, Any]:
    """原子替换一个结果的最新质量记录。"""
    payload = _upgrade_quality_payload(run_dir, read_result_quality(run_dir))
    payload["assessments"] = [
        item for item in payload["assessments"] if item["result_id"] != record["result_id"]
    ]
    payload["assessments"].append(record)
    require_quality(payload)
    atomic_json(run_dir / QUALITY_PATH, payload)
    return record


def _same_contract(provided: dict[str, Any], verified: dict[str, Any]) -> bool:
    """比较调用方声明与冻结 adapter 合同，忽略运行时注入的身份镜像。"""
    left = json.loads(json.dumps(provided))
    right = json.loads(json.dumps(verified))
    left.pop("verification_adapter", None)
    right.pop("verification_adapter", None)
    return json.dumps(left, ensure_ascii=False, sort_keys=True) == json.dumps(
        right, ensure_ascii=False, sort_keys=True
    )


def _accepted_record(
    run_dir: Path,
    *,
    result_id: str,
    assessment: dict[str, Any],
) -> dict[str, Any]:
    """从独立 verification receipt 派生唯一可接受的 production 质量记录."""
    reasons = assessment.get("reasons")
    verification = assessment.get("verification")
    provided_contract = assessment.get("selection_contract")
    if (
        not isinstance(reasons, list)
        or not reasons
        or any(not isinstance(item, str) or not item.strip() for item in reasons)
    ):
        raise ContractError("quality assessment 必须包含非空机器原因")
    if not isinstance(verification, dict):
        raise ContractError("accepted 质量记录必须提供独立 adapter verification")
    verified = verify_verification_protocol(run_dir, verification)
    if verified["result_id"] != result_id:
        raise ContractError("verification 收据 result_id 与质量申请不一致")
    contract = verified["selection_contract"]
    validate_selection_contract(contract, require_coverage=True)
    if provided_contract is not None:
        if not isinstance(provided_contract, dict):
            raise ContractError("selection_contract 必须是对象")
        validate_selection_contract(provided_contract, require_coverage=True)
        if not _same_contract(provided_contract, contract):
            raise ContractError(
                "quality assessment 的 selection_contract 与冻结 adapter 合同不一致"
            )
    results = _result_map(run_dir)
    result = results.get(result_id)
    if result is None:
        raise ContractError(f"结果不存在: {result_id}")
    if result["question_id"] != verified["question_id"]:
        raise ContractError("verification 收据 question_id 与登记执行不一致")
    if verified["execution_mode"] != "production" or _result_mode(result) != "production":
        raise ContractError("exploration 结果不得申请 accepted")
    challenge = verified["challenge"]
    semantic_error = challenge.get("outcome") == "model_or_scorer_semantic_error"
    base_eligible = bool(
        result["execution_valid"]
        and verified["feasibility_valid"]
        and verified["exact_recomputed"]
        and verified["search_adequacy"] == "passed"
        and verified["problem_effectiveness"] == "progressed"
        and not semantic_error
    )
    validation_reasons: list[str] = []
    selection: dict[str, Any] | None = None
    if semantic_error:
        validation_reasons.append("model_or_scorer_semantic_error_requires_analysis")
    if base_eligible:
        require_prior_question_quality(
            run_dir,
            result["question_id"],
            execution_mode="production",
            selection_contract=contract,
        )
        selection = register_verified_candidate(
            run_dir, result_id=result_id, selection_contract=contract
        )
        validation_reasons.append(str(selection["decision"]))
    else:
        retain_verified_incumbents(run_dir, result_id)
    paper_allowed = bool(base_eligible and selection and selection["accepted"])
    return {
        "result_id": result_id,
        "execution_mode": "production",
        "execution_valid": bool(result["execution_valid"]),
        "feasibility_valid": bool(verified["feasibility_valid"]),
        "exact_recomputed": bool(verified["exact_recomputed"]),
        "search_adequacy": str(verified["search_adequacy"]),
        "problem_effectiveness": (
            "failed" if semantic_error else str(verified["problem_effectiveness"])
        ),
        "result_role": "accepted" if paper_allowed else "candidate",
        "paper_allowed": paper_allowed,
        "verification": {
            "protocol_file": verification["protocol_file"],
            "protocol_sha256": verification["protocol_sha256"],
        },
        "selection_contract": contract,
        "reasons": list(dict.fromkeys([*reasons, *validation_reasons])),
        "assessed_at": utc_now(),
    }


def assess_result_quality(
    run_dir: Path,
    *,
    result_id: str,
    assessment: dict[str, Any] | None = None,
    feasibility_valid: bool | None = None,
    baseline_preserved: bool | None = None,
    search_adequacy: str | None = None,
    result_role: str | None = None,
    reasons: list[str] | None = None,
) -> dict[str, Any]:
    """评估结果质量；只有独立三段式协议可写入 accepted。

    旧布尔参数和旧 ``evidence`` 对象只保留为诊断迁移入口，绝不能放行结果。

    Args:
        run_dir: v3 运行目录。
        result_id: 待评估的登记结果。
        assessment: 新协议请求；accepted 时必须包含 verification receipt。
        feasibility_valid: 遗留诊断兼容参数。
        baseline_preserved: 遗留诊断兼容参数。
        search_adequacy: 遗留诊断兼容参数。
        result_role: 遗留诊断角色。
        reasons: 诊断原因。

    Returns:
        新写入的质量记录。

    Raises:
        ContractError: accepted 请求缺少独立收据或 provenance 已漂移。
    """
    del feasibility_valid, baseline_preserved, search_adequacy
    try:
        results = _result_map(run_dir)
        result = results.get(result_id)
        if result is None:
            raise ContractError(f"结果不存在: {result_id}")
        if assessment is None:
            requested_role = result_role or "diagnostic"
            if requested_role not in RESULT_ROLES:
                raise ContractError("quality assessment 的 result_role 不合法")
            if requested_role == "accepted":
                raise ContractError("accepted 质量记录必须提供独立 adapter verification")
            record = _legacy_record(
                result,
                result_role=requested_role,
                reasons=reasons or ["legacy_quality_call"],
            )
        else:
            requested_role = assessment.get("result_role")
            if requested_role not in RESULT_ROLES:
                raise ContractError("quality assessment 的 result_role 不合法")
            if requested_role == "accepted":
                record = _accepted_record(run_dir, result_id=result_id, assessment=assessment)
            else:
                request_reasons = assessment.get("reasons")
                if not isinstance(request_reasons, list) or not request_reasons:
                    request_reasons = reasons or ["diagnostic_quality_request"]
                record = _legacy_record(
                    result,
                    result_role=str(requested_role),
                    reasons=[str(item) for item in request_reasons if str(item)],
                )
        return _store_record(run_dir, record)
    except (ContractError, KeyError, TypeError, ValueError):
        # 执行器可能暂时 supersede 了 incumbent；失败申请绝不能留下较弱结果为 current。
        try:
            retain_verified_incumbents(run_dir, result_id)
        except ContractError:
            pass
        raise


def result_quality(run_dir: Path, result_id: str) -> dict[str, Any] | None:
    """返回一个结果最新的质量记录。"""
    return next(
        (
            item
            for item in read_result_quality(run_dir)["assessments"]
            if item["result_id"] == result_id
        ),
        None,
    )


def _quality_allows_local_facts(run_dir: Path, result_id: str) -> bool:
    """验证结果自身的三段证据链，不把内部一致性误写成科学正确性。"""
    try:
        quality = read_result_quality(run_dir)
        if quality["schema_version"] != "3.0":
            return False
        results = _result_map(run_dir)
        result = results.get(result_id)
        assessment = next(
            (item for item in quality["assessments"] if item["result_id"] == result_id), None
        )
        if not (
            result
            and result["status"] == "current"
            and _result_mode(result) == "production"
            and result["execution_valid"]
            and assessment
            and assessment["execution_mode"] == "production"
            and assessment["paper_allowed"]
            and assessment["result_role"] == "accepted"
            and isinstance(assessment["verification"], dict)
        ):
            return False
        verified = verify_verification_protocol(run_dir, assessment["verification"])
        if (
            verified["result_id"] != result_id
            or verified["execution_mode"] != "production"
            or not verified["feasibility_valid"]
            or not verified["exact_recomputed"]
            or verified["search_adequacy"] != "passed"
            or verified["problem_effectiveness"] != "progressed"
            or verified["challenge"].get("outcome") == "model_or_scorer_semantic_error"
        ):
            return False
        contract = verified["selection_contract"]
        stored_contract = assessment.get("selection_contract")
        if not isinstance(stored_contract, dict) or not _same_contract(stored_contract, contract):
            return False
        group_key = selection_group_key(result["question_id"], contract)
        registry = read_candidate_registry(run_dir)
        group = next((item for item in registry["groups"] if item["group"] == group_key), None)
        metric = contract["objective"]["metric"]
        return bool(
            group
            and group.get("best_result_id") == result_id
            and group.get("best_exact") == result["metrics"].get(metric)
        )
    except (ContractError, KeyError, TypeError, ValueError):
        return False


def quality_allows_paper(run_dir: Path, result_id: str) -> bool:
    """在结果链与独立科学红队同时通过时放行论文事实消费。

    Args:
        run_dir: v3 运行目录。
        result_id: 准备被论文、图表或正式下游问题消费的结果 ID。

    Returns:
        当且仅当结果仍是完整独立证据链的 registry incumbent 时为真。
    """
    if not _quality_allows_local_facts(run_dir, result_id):
        return False
    return bool(scientific_review_status(run_dir).get("allowed"))


def require_prior_question_quality(
    run_dir: Path,
    downstream_question: str,
    *,
    execution_mode: str | None = None,
    selection_contract: dict[str, Any] | None = None,
) -> None:
    """在 production 下要求合同声明的前序问题仍有 current accepted 结果。

    Args:
        run_dir: v3 运行目录。
        downstream_question: 准备继续的子问题编号。
        execution_mode: 显式用途；省略时读取当前状态。
        selection_contract: 可选的题目依赖合同。

    Raises:
        ContractError: production 前序依赖没有有效 production/current/accepted 结果。
    """
    state = read_simple_state(run_dir)
    mode = execution_mode or str(state["execution_mode"])
    if mode not in {"production", "exploration"}:
        raise ContractError("execution_mode 必须为 production 或 exploration")
    if mode == "exploration":
        return
    if selection_contract is not None and "required_prior_questions" in selection_contract:
        predecessors = list(selection_contract["required_prior_questions"])
    else:
        questions = state["required_questions"]
        if downstream_question not in questions:
            return
        position = questions.index(downstream_question)
        predecessors = [] if position == 0 else [questions[position - 1]]
    index = read_result_index(run_dir)
    for predecessor in predecessors:
        candidates = [
            item["result_id"]
            for item in index["results"]
            if item["question_id"] == predecessor and _result_mode(item) == "production"
        ]
        if not any(_quality_allows_local_facts(run_dir, result_id) for result_id in candidates):
            raise ContractError(
                f"{downstream_question} 不能放行：{predecessor} 缺少有效且未降级的质量记录"
            )


def migrate_legacy_result_quality(run_dir: Path) -> dict[str, Any]:
    """迁移旧索引和旧质量声明，并将它们显式降为 diagnostic/unverified。

    Args:
        run_dir: 需要一次性迁移的 v3 运行目录。

    Returns:
        已清除旧索引字段和已降级质量记录的结果 ID。
    """
    index = load_json(run_dir / "results" / "index.json")
    migrated_results: list[str] = []
    for result in index["results"]:
        if "use_status" in result:
            result.pop("use_status")
            migrated_results.append(result["result_id"])
    require_result_index(index)
    if migrated_results:
        atomic_json(run_dir / "results" / "index.json", index)
    original = read_result_quality(run_dir)
    upgraded = _upgrade_quality_payload(run_dir, original)
    if original["schema_version"] != "3.0":
        atomic_json(run_dir / QUALITY_PATH, upgraded)
    return {
        "migrated_result_ids": migrated_results,
        "migrated_assessment_ids": [item["result_id"] for item in upgraded["assessments"]],
    }
