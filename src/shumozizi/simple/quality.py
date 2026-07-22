"""将 v3 的质量放行建立在可复验执行证据而非调用方声明上。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import ContractError, atomic_json, load_json, resolve_inside, sha256_file
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.simple.results import (
    json_path_value,
    read_result_index,
    require_result_index,
    verify_current_result_files,
)
from shumozizi.simple.search_adequacy import (
    assess_independent_challenge,
    validate_coverage_evidence,
    validate_objective_semantics,
    validate_registered_challenge_provenance,
)
from shumozizi.simple.selection import (
    read_candidate_registry,
    register_verified_candidate,
    retain_verified_incumbents,
    selection_group_key,
    validate_selection_contract,
)
from shumozizi.simple.state import read_simple_state, utc_now

QUALITY_PATH = Path("results/quality.json")
SEARCH_ADEQUACY = ("passed", "failed", "not_assessed")
RESULT_ROLES = ("diagnostic", "candidate", "accepted", "rejected")
EVIDENCE_FIELDS = (
    "feasibility",
    "exact_recomputed",
    "search_adequacy",
    "problem_effectiveness",
)


def _schema() -> dict[str, Any]:
    """读取结果质量层的 Schema。"""
    return load_json(resolve_repo_root(Path(__file__)) / "schemas/simple_result_quality.schema.json")


def _schema_errors(payload: dict[str, Any]) -> list[str]:
    """返回质量文档的 Schema 错误。"""
    validator = Draft202012Validator(_schema(), format_checker=FormatChecker())
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    ]


def require_quality(payload: dict[str, Any]) -> None:
    """确保质量记录符合版本化、不可降级的放行不变量。"""
    errors = _schema_errors(payload)
    if errors:
        raise ContractError("; ".join(errors))
    version = payload["schema_version"]
    for item in payload["assessments"]:
        if version == "1.0":
            # v1 历史记录不含来源链；保留可读性但绝不作为当前放行证据。
            continue
        evidence = item.get("evidence")
        if not isinstance(evidence, dict):
            raise ContractError("v2 质量记录必须包含 evidence")
        eligible = (
            item["execution_valid"]
            and item["feasibility_valid"]
            and item["exact_recomputed"]
            and item["search_adequacy"] == "passed"
            and item["problem_effectiveness"] == "progressed"
            and item["result_role"] == "accepted"
        )
        if item["paper_allowed"] != eligible:
            raise ContractError("paper_allowed 必须由已验证质量层自动推出")


def read_result_quality(run_dir: Path) -> dict[str, Any]:
    """读取质量层；尚未评估的运行返回 v2 空登记。"""
    path = run_dir / QUALITY_PATH
    if not path.exists():
        payload = {"schema_version": "2.0", "run_id": run_dir.name, "assessments": []}
        require_quality(payload)
        return payload
    payload = load_json(path)
    require_quality(payload)
    return payload


def _read_evidence(
    run_dir: Path,
    result_map: dict[str, dict[str, Any]],
    reference: dict[str, Any],
    *,
    require_expected: bool,
) -> tuple[Any, dict[str, str]]:
    """从已登记输出按路径和哈希读取一个质量证据字段。"""
    required = ("result_id", "file", "json_path")
    if require_expected:
        required = (*required, "expected")
    if any(key not in reference for key in required):
        raise ContractError("quality evidence 缺少 result_id、file、json_path 或 expected")
    result_id = reference["result_id"]
    result = result_map.get(result_id)
    if result is None or not result["execution_valid"]:
        raise ContractError("quality evidence 未绑定 execution_valid 的已登记结果")
    file_name = reference["file"]
    json_path = reference["json_path"]
    if not isinstance(file_name, str) or not isinstance(json_path, str):
        raise ContractError("quality evidence 路径必须为字符串")
    expected_hash = result["output_hashes"].get(file_name)
    if expected_hash is None:
        raise ContractError("quality evidence 文件不是已登记输出")
    recorded_hash = reference.get("file_sha256")
    if recorded_hash is not None and recorded_hash != expected_hash:
        raise ContractError("quality evidence 记录哈希与登记输出不一致")
    path = resolve_inside(run_dir, file_name, must_exist=True)
    if sha256_file(path) != expected_hash:
        raise ContractError("quality evidence 输出哈希已漂移")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError("quality evidence JSON 不可读取") from exc
    actual = json_path_value(document, json_path)
    if require_expected and reference["expected"] is not None and actual != reference["expected"]:
        raise ContractError("quality evidence 与预期字段值不一致")
    return actual, {
        "result_id": str(result_id),
        "file": file_name,
        "json_path": json_path,
        "file_sha256": expected_hash,
    }


def _require_evidence(
    run_dir: Path,
    result_map: dict[str, dict[str, Any]],
    evidence: dict[str, Any],
    selection_contract: dict[str, Any],
    *,
    require_expected: bool = True,
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    """解析并验证所有放行所需的来源链。"""
    required = [*EVIDENCE_FIELDS, *selection_contract.get("required_evidence", [])]
    missing = [key for key in required if key not in evidence]
    if missing:
        raise ContractError(f"quality evidence 缺少: {', '.join(missing)}")
    values: dict[str, Any] = {}
    sources: dict[str, dict[str, str]] = {}
    for key in dict.fromkeys(required):
        reference = evidence[key]
        if not isinstance(reference, dict):
            raise ContractError(f"quality evidence {key} 必须为对象")
        values[key], sources[key] = _read_evidence(
            run_dir,
            result_map,
            reference,
            require_expected=require_expected,
        )
    return values, sources


def _legacy_diagnostic_assessment(
    run_dir: Path,
    *,
    result_id: str,
    result_role: str,
    reasons: list[str],
) -> dict[str, Any]:
    """把遗留自报质量降为不可放行诊断，避免静默绕过 v2。"""
    result = next(
        (item for item in read_result_index(run_dir)["results"] if item["result_id"] == result_id), None
    )
    if result is None:
        raise ContractError(f"结果不存在: {result_id}")
    return {
        "result_id": result_id,
        "execution_valid": bool(result["execution_valid"]),
        "feasibility_valid": False,
        "exact_recomputed": False,
        "search_adequacy": "not_assessed",
        "problem_effectiveness": "not_assessed",
        "result_role": "candidate" if result_role == "accepted" else result_role,
        "paper_allowed": False,
        "evidence": {},
        "selection_contract": None,
        "reasons": list(dict.fromkeys([*reasons, "legacy_unverified_quality_claim"])),
        "assessed_at": utc_now(),
    }


def _assess_result_quality(
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
    """从登记输出中的证据链派生质量与候选放行决定。

    旧布尔参数只被保留用于把历史诊断迁为不可放行记录；任何 accepted 结果必须
    传入 ``assessment``，且所有质量判断均由已登记输出的哈希和 JSON 字段复验。

    Args:
        run_dir: v3 运行目录。
        result_id: 待评估的已登记结果。
        assessment: 包含选择合同、证据引用和原因的 v2 评估请求。
        feasibility_valid: 仅兼容旧诊断调用，不可用于放行。
        baseline_preserved: 仅兼容旧诊断调用，不可用于放行。
        search_adequacy: 仅兼容旧诊断调用，不可用于放行。
        result_role: 仅兼容旧诊断调用，不可用于放行。
        reasons: 机器生成的说明原因。

    Returns:
        已写入的质量记录。

    Raises:
        ContractError: 证据、候选合同或质量请求不满足协议。
    """
    del feasibility_valid, baseline_preserved, search_adequacy
    if assessment is None:
        if result_role == "accepted":
            raise ContractError("accepted 质量记录必须提供可验证 evidence")
        record = _legacy_diagnostic_assessment(
            run_dir,
            result_id=result_id,
            result_role=result_role or "diagnostic",
            reasons=reasons or ["legacy_quality_call"],
        )
    else:
        requested_role = assessment.get("result_role")
        selection_contract = assessment.get("selection_contract")
        evidence = assessment.get("evidence")
        request_reasons = assessment.get("reasons")
        if requested_role not in RESULT_ROLES:
            raise ContractError("quality assessment 的 result_role 不合法")
        if requested_role != "accepted":
            raise ContractError("v2 evidence assessment 只用于申请 accepted 放行")
        if not isinstance(selection_contract, dict):
            raise ContractError("quality assessment 缺少 selection_contract")
        if not isinstance(evidence, dict):
            raise ContractError("quality assessment 缺少 evidence")
        if not isinstance(request_reasons, list) or not request_reasons or any(
            not isinstance(reason, str) or not reason.strip() for reason in request_reasons
        ):
            raise ContractError("quality assessment 必须包含非空机器原因")
        validate_selection_contract(selection_contract)
        index = read_result_index(run_dir)
        result_map = {item["result_id"]: item for item in index["results"]}
        result = result_map.get(result_id)
        if result is None:
            raise ContractError(f"结果不存在: {result_id}")
        values, sources = _require_evidence(run_dir, result_map, evidence, selection_contract)
        feasibility = values["feasibility"] is True
        exact_recomputed = values["exact_recomputed"] is True
        adequate = values["search_adequacy"] == "passed"
        effective = values["problem_effectiveness"] == "progressed"
        validation_reasons: list[str] = []
        if "coverage" in values:
            coverage = validate_coverage_evidence(selection_contract, values["coverage"])
            if not coverage["passed"]:
                validation_reasons.extend(coverage["reasons"])
                adequate = False
        if "objective_semantics" in values:
            semantics = validate_objective_semantics(selection_contract, values["objective_semantics"])
            if not semantics["passed"]:
                validation_reasons.extend(semantics["reasons"])
                effective = False
        if "independent_challenge" in values:
            challenge = values["independent_challenge"]
            if not isinstance(challenge, dict):
                raise ContractError("independent_challenge evidence 必须为对象")
            challenger_exact = challenge.get("challenger_exact")
            candidate_exact = result["metrics"].get(selection_contract["objective"]["metric"])
            if challenger_exact != candidate_exact:
                raise ContractError("independent_challenge exact 值与当前候选指标不一致")
            group_key = selection_group_key(result["question_id"], selection_contract)
            registry = read_candidate_registry(run_dir)
            group = next(
                (item for item in registry["groups"] if item["group"] == group_key), None
            )
            incumbent_id = group.get("best_result_id") if group else None
            incumbent = result_map.get(incumbent_id) if isinstance(incumbent_id, str) else None
            if incumbent is None:
                raise ContractError("independent_challenge 缺少已冻结的 registry incumbent")
            validate_registered_challenge_provenance(
                incumbent_receipt=challenge["incumbent_receipt"],
                challenge_receipt=challenge["challenge_receipt"],
                incumbent_result=incumbent,
                challenger_result=result,
                result_map=result_map,
                metric=str(selection_contract["objective"]["metric"]),
                fine_tolerance=float(selection_contract["objective"]["fine_tolerance"]),
            )
            challenge_report = assess_independent_challenge(
                incumbent_exact=float(challenge["incumbent_exact"]),
                challenger_exact=float(challenger_exact),
                incumbent_receipt=challenge["incumbent_receipt"],
                challenge_receipt=challenge["challenge_receipt"],
                improvement_tolerance=float(selection_contract["objective"]["fine_tolerance"]),
                comparability_contract=challenge.get("comparability_contract"),
                follow_up_contract=challenge.get("follow_up_contract"),
            )
            if challenge_report["search_adequacy"] != "passed":
                validation_reasons.extend(challenge_report["reasons"])
                adequate = False
        selection: dict[str, Any] | None = None
        base_eligible = bool(result["execution_valid"] and feasibility and exact_recomputed and adequate and effective)
        if base_eligible:
            require_prior_question_quality(run_dir, result["question_id"])
            selection = register_verified_candidate(
                run_dir, result_id=result_id, selection_contract=selection_contract
            )
            validation_reasons.append(str(selection["decision"]))
        else:
            retain_verified_incumbents(run_dir, result_id)
        paper_allowed = bool(base_eligible and selection and selection["accepted"])
        record = {
            "result_id": result_id,
            "execution_valid": bool(result["execution_valid"]),
            "feasibility_valid": feasibility,
            "exact_recomputed": exact_recomputed,
            "search_adequacy": "passed" if adequate else "failed",
            "problem_effectiveness": "progressed" if effective else "failed",
            "result_role": "accepted" if paper_allowed else "candidate",
            "paper_allowed": paper_allowed,
            "evidence": sources,
            "selection_contract": selection_contract,
            "reasons": list(dict.fromkeys([*request_reasons, *validation_reasons])),
            "assessed_at": utc_now(),
        }
    payload = read_result_quality(run_dir)
    if payload["schema_version"] == "1.0":
        # 历史 run 保持只读兼容；新写入在同一文件中会先升级到 v2，旧记录降级为诊断。
        payload = {
            "schema_version": "2.0",
            "run_id": run_dir.name,
            "assessments": [],
        }
    payload["assessments"] = [
        item for item in payload["assessments"] if item["result_id"] != result_id
    ]
    payload["assessments"].append(record)
    require_quality(payload)
    atomic_json(run_dir / QUALITY_PATH, payload)
    return record


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
    """评估结果质量，并在无效申请异常时恢复已验证 incumbent。

    Args:
        run_dir: v3 运行目录。
        result_id: 待评估结果 ID。
        assessment: v2 证据化放行申请。
        feasibility_valid: 遗留诊断参数，不可放行。
        baseline_preserved: 遗留诊断参数，不可放行。
        search_adequacy: 遗留诊断参数，不可放行。
        result_role: 遗留诊断角色。
        reasons: 遗留诊断原因。

    Returns:
        写入质量层的记录。

    Raises:
        ContractError: 证据或候选合同不满足协议。
    """
    try:
        return _assess_result_quality(
            run_dir,
            result_id=result_id,
            assessment=assessment,
            feasibility_valid=feasibility_valid,
            baseline_preserved=baseline_preserved,
            search_adequacy=search_adequacy,
            result_role=result_role,
            reasons=reasons,
        )
    except (ContractError, KeyError, TypeError, ValueError):
        # 执行器可能已临时 supersede incumbent；无效放行申请不能留下退化 current。
        try:
            retain_verified_incumbents(run_dir, result_id)
        except ContractError:
            pass
        raise


def result_quality(run_dir: Path, result_id: str) -> dict[str, Any] | None:
    """返回一个结果的最新质量评估。"""
    return next(
        (item for item in read_result_quality(run_dir)["assessments"] if item["result_id"] == result_id),
        None,
    )


def quality_allows_paper(run_dir: Path, result_id: str) -> bool:
    """仅在当前执行、证据和候选下界均未漂移时允许论文消费结果。

    质量记录是一次评估的快照，不能成为输出后来被篡改后的永久通行证。因此每次
    放行查询均重新核验登记文件和已持久化的证据引用；对失败保持关闭而不是信任
    旧布尔字段。

    Args:
        run_dir: v3 运行目录。
        result_id: 准备被论文或下游问题消费的结果 ID。

    Returns:
        当且仅当结果仍是当前合同组的可复验证 incumbent 时返回 ``True``。
    """
    try:
        quality = read_result_quality(run_dir)
        # v1 记录及其自报布尔字段没有可重放的来源链，永不用于新的放行。
        if quality["schema_version"] != "2.0":
            return False
        index = read_result_index(run_dir)
        result_map = {item["result_id"]: item for item in index["results"]}
        result = result_map.get(result_id)
        assessment = next(
            (item for item in quality["assessments"] if item["result_id"] == result_id), None
        )
        if not (
            result
            and result["status"] == "current"
            and result["execution_valid"]
            and assessment
            and assessment.get("paper_allowed")
            and assessment.get("feasibility_valid")
            and assessment.get("exact_recomputed")
            and assessment.get("search_adequacy") == "passed"
            and assessment.get("problem_effectiveness") == "progressed"
            and assessment.get("result_role") == "accepted"
        ):
            return False
        selection_contract = assessment.get("selection_contract")
        evidence = assessment.get("evidence")
        if not isinstance(selection_contract, dict) or not isinstance(evidence, dict):
            return False
        validate_selection_contract(selection_contract)

        # 先复验完整执行，再读取持久化 evidence。后者不携带调用时 expected 值，
        # 但仍将每个路径、哈希和 JSON 读取绑定至登记执行。
        execution = verify_current_result_files(run_dir)
        if not execution["success"] or result_id not in execution["checked_result_ids"]:
            return False
        values, _ = _require_evidence(
            run_dir,
            result_map,
            evidence,
            selection_contract,
            require_expected=False,
        )
        if not (
            values["feasibility"] is True
            and values["exact_recomputed"] is True
            and values["search_adequacy"] == "passed"
            and values["problem_effectiveness"] == "progressed"
        ):
            return False
        if "coverage" in values and not validate_coverage_evidence(
            selection_contract, values["coverage"]
        )["passed"]:
            return False
        if "objective_semantics" in values and not validate_objective_semantics(
            selection_contract, values["objective_semantics"]
        )["passed"]:
            return False

        group_key = selection_group_key(result["question_id"], selection_contract)
        registry = read_candidate_registry(run_dir)
        group = next((item for item in registry["groups"] if item["group"] == group_key), None)
        metric = selection_contract["objective"]["metric"]
        if not (
            group
            and group.get("best_result_id") == result_id
            and isinstance(group.get("best_exact"), (int, float))
            and group["best_exact"] == result["metrics"].get(metric)
        ):
            return False
        return True
    except (ContractError, KeyError, TypeError, ValueError):
        return False


def require_prior_question_quality(run_dir: Path, downstream_question: str) -> None:
    """要求下游问题消费上一问仍为 current 的有效质量记录。

    Args:
        run_dir: v3 运行目录。
        downstream_question: 准备放行的子问题编号。

    Raises:
        ContractError: 前一必答问题缺少未降级的放行结果。
    """
    state = read_simple_state(run_dir)
    questions = state["required_questions"]
    if downstream_question not in questions:
        return
    position = questions.index(downstream_question)
    if position == 0:
        return
    predecessor = questions[position - 1]
    index = read_result_index(run_dir)
    candidates = [item["result_id"] for item in index["results"] if item["question_id"] == predecessor]
    if not any(quality_allows_paper(run_dir, result_id) for result_id in candidates):
        raise ContractError(f"{downstream_question} 不能放行：{predecessor} 缺少有效且未降级的质量记录")


def migrate_legacy_result_quality(run_dir: Path) -> dict[str, Any]:
    """从旧执行索引剥离 use_status，并将其显式降级为不可放行诊断。"""
    index = load_json(run_dir / "results" / "index.json")
    migrated: list[str] = []
    for result in index["results"]:
        if "use_status" in result:
            result.pop("use_status")
            migrated.append(result["result_id"])
    require_result_index(index)
    if migrated:
        atomic_json(run_dir / "results" / "index.json", index)
    return {"migrated_result_ids": migrated}
