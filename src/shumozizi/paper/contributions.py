"""把论文贡献表述限制在当前题目的可复验生产证据之内。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, relative_inside
from shumozizi.core.schema import require_valid
from shumozizi.simple.quality import quality_allows_paper
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import read_simple_state, utc_now

CONTRIBUTION_LEDGER_SCHEMA = "contribution_ledger"
CONTRIBUTION_LEDGER_VERSION = "2.0"
CONTRIBUTION_LEDGER_PATH = Path("paper/contribution_ledger.json")
CONTRIBUTION_CATEGORIES = {
    "structural_discovery",
    "modeling_transformation",
    "algorithm_design",
    "empirical_finding",
    "expression_organization",
}
GENERIC_SOURCE_SCOPES = {
    "generic_skill",
    "quality_protocol",
    "off_the_shelf_algorithm",
    "standard_figure",
    "method_combination",
    "engineering_implementation",
}
COMPARISON_DIRECTIONS = {"higher_is_better", "lower_is_better"}
INNOVATION_EVIDENCE_MODES = {"distinct_results", "exact_artifacts"}


def _output_path(run_dir: Path, output_path: Path | None) -> Path:
    """解析运行目录内的贡献账本输出路径。"""
    candidate = run_dir / CONTRIBUTION_LEDGER_PATH if output_path is None else output_path
    if not candidate.is_absolute():
        candidate = run_dir / candidate
    try:
        relative_inside(run_dir, candidate)
    except ContractError as exc:
        raise ContractError("贡献账本必须写入当前运行目录") from exc
    return candidate.resolve()


def _require_production_state(run_dir: Path) -> dict[str, Any]:
    """确保账本来自 production，而非探索诊断。"""
    state = read_simple_state(run_dir)
    if state.get("execution_mode") != "production":
        raise ContractError("探索结果不能登记为论文贡献")
    return state


def _required_string(item: Mapping[str, Any], key: str) -> str:
    """读取非空贡献字段并提供稳定的协议错误。"""
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"贡献条目缺少非空字段: {key}")
    return value.strip()


def _required_strings(item: Mapping[str, Any], key: str) -> list[str]:
    """读取唯一的非空字符串数组。"""
    values = item.get(key)
    if (
        not isinstance(values, list)
        or not values
        or any(not isinstance(value, str) or not value.strip() for value in values)
        or len(set(values)) != len(values)
    ):
        raise ContractError(f"贡献条目 {key} 必须是非空且唯一的字符串数组")
    return [value.strip() for value in values]


def _innovation_evidence(
    run_dir: Path,
    item: Mapping[str, Any],
    evidence_result_ids: list[str],
) -> tuple[dict[str, Any] | None, bool]:
    """规范化数学创新声明所需的机制到消融证据链。

    这里不判断数学主张是否真实成立；题目 adapter 和评审仍负责该判断。通用层仅保证
    作者把机制、可检验预测、对照改善和单组件消融绑定到同一当前运行的生产证据。

    Args:
        run_dir: 当前 Capability-First v3 运行目录。
        item: 作者提交的贡献条目。
        evidence_result_ids: 条目声明的全部当前运行证据结果。

    Returns:
        规范化的创新证据链及其当前有效性；未声明时返回 ``(None, False)``。

    Raises:
        ContractError: 已提供的证据链结构不完整或未纳入条目总证据。
    """
    raw_chain = item.get("innovation_evidence")
    if raw_chain is None:
        return None, False
    if not isinstance(raw_chain, Mapping):
        raise ContractError("innovation_evidence 必须是对象")
    evidence_mode = _required_string(raw_chain, "evidence_mode")
    if evidence_mode not in INNOVATION_EVIDENCE_MODES:
        raise ContractError("innovation_evidence.evidence_mode 不支持")
    primary_result_id = _required_string(raw_chain, "primary_result_id")
    if primary_result_id not in evidence_result_ids:
        raise ContractError("创新证据链 primary 结果必须列入 evidence_result_ids")
    comparison_direction = _required_string(raw_chain, "comparison_direction")
    if comparison_direction not in COMPARISON_DIRECTIONS:
        raise ContractError("comparison_direction 必须为 higher_is_better 或 lower_is_better")
    chain = {
        "mechanism_difference": _required_string(raw_chain, "mechanism_difference"),
        "testable_prediction": _required_string(raw_chain, "testable_prediction"),
        "comparison_metric": _required_string(raw_chain, "comparison_metric"),
        "comparison_direction": comparison_direction,
        "comparison_improvement": _required_string(raw_chain, "comparison_improvement"),
        "single_component_ablation": _required_string(
            raw_chain, "single_component_ablation"
        ),
        "evidence_mode": evidence_mode,
        "primary_result_id": primary_result_id,
    }
    if evidence_mode == "distinct_results":
        comparison_result_ids = _required_strings(raw_chain, "comparison_result_ids")
        ablation_result_ids = _required_strings(raw_chain, "ablation_result_ids")
        shared_primary = set(comparison_result_ids) & set(ablation_result_ids)
        if (
            len(comparison_result_ids) < 2
            or len(ablation_result_ids) < 2
            or shared_primary != {primary_result_id}
        ):
            raise ContractError(
                "对照与单组件消融必须各含独立结果，并且只共享一个 primary 结果"
            )
        chain_result_ids = set(comparison_result_ids) | set(ablation_result_ids)
        if not chain_result_ids.issubset(evidence_result_ids):
            raise ContractError("创新证据链结果必须同时列入 evidence_result_ids")
        chain["comparison_result_ids"] = comparison_result_ids
        chain["ablation_result_ids"] = ablation_result_ids
    else:
        comparison_artifact_files = _required_strings(raw_chain, "comparison_artifact_files")
        ablation_artifact_files = _required_strings(raw_chain, "ablation_artifact_files")
        if set(comparison_artifact_files) & set(ablation_artifact_files):
            raise ContractError("对照与单组件消融必须绑定独立 exact scorer 附属产物")
        _require_primary_artifacts(
            run_dir,
            primary_result_id,
            [*comparison_artifact_files, *ablation_artifact_files],
        )
        chain_result_ids = {primary_result_id}
        chain["comparison_artifact_files"] = comparison_artifact_files
        chain["ablation_artifact_files"] = ablation_artifact_files
    chain["evidence_valid"] = all(
        quality_allows_paper(run_dir, result_id) for result_id in chain_result_ids
    )
    return chain, chain["evidence_valid"]


def _require_primary_artifacts(
    run_dir: Path, primary_result_id: str, artifact_files: list[str]
) -> None:
    """确保创新链附属产物属于仍受协议保护的 exact scorer 结果。

    Args:
        run_dir: 当前 Capability-First v3 运行目录。
        primary_result_id: 作为论文事实根的 current primary 结果。
        artifact_files: 需要作为对照或消融证据的相对 JSON 文件。

    Raises:
        ContractError: 附属产物越界、未登记为 primary 输出或不在原始结果目录。
    """
    result = next(
        (
            item
            for item in read_result_index(run_dir)["results"]
            if item["result_id"] == primary_result_id
        ),
        None,
    )
    output_hashes = result.get("output_hashes") if isinstance(result, Mapping) else None
    if not isinstance(output_hashes, Mapping):
        raise ContractError("创新链 primary 结果缺少受控输出哈希")
    for artifact_file in artifact_files:
        if not artifact_file.startswith("results/raw/") or not artifact_file.endswith(".json"):
            raise ContractError("创新链附属产物必须是 results/raw/ 下的 JSON")
        if artifact_file not in output_hashes:
            raise ContractError("创新链附属产物未绑定到 primary exact scorer 输出")


def _validate_recorded_innovation_evidence(
    run_dir: Path, chain: Mapping[str, Any], evidence_result_ids: list[str]
) -> set[str]:
    """复验已写入账本的创新链角色和证据归属。

    Args:
        run_dir: 当前 Capability-First v3 运行目录。
        chain: 账本中已规范化的创新证据链。
        evidence_result_ids: 贡献条目声明的全部证据结果。

    Returns:
        链路实际引用的结果 ID 集合。

    Raises:
        ContractError: 角色、比较口径或证据归属被篡改。
    """
    evidence_mode = _required_string(chain, "evidence_mode")
    if evidence_mode not in INNOVATION_EVIDENCE_MODES:
        raise ContractError("创新链 evidence_mode 非法")
    primary_result_id = _required_string(chain, "primary_result_id")
    if primary_result_id not in evidence_result_ids:
        raise ContractError("创新链 primary 结果未绑定到贡献 evidence_result_ids")
    _required_string(chain, "mechanism_difference")
    _required_string(chain, "testable_prediction")
    _required_string(chain, "comparison_metric")
    if _required_string(chain, "comparison_direction") not in COMPARISON_DIRECTIONS:
        raise ContractError("创新链 comparison_direction 非法")
    _required_string(chain, "comparison_improvement")
    _required_string(chain, "single_component_ablation")
    if not isinstance(chain.get("evidence_valid"), bool):
        raise ContractError("创新链 evidence_valid 必须为布尔值")
    if evidence_mode == "distinct_results":
        comparison_result_ids = _required_strings(chain, "comparison_result_ids")
        ablation_result_ids = _required_strings(chain, "ablation_result_ids")
        shared_primary = set(comparison_result_ids) & set(ablation_result_ids)
        if (
            len(comparison_result_ids) < 2
            or len(ablation_result_ids) < 2
            or shared_primary != {primary_result_id}
        ):
            raise ContractError("创新链的对照、primary 与消融角色不独立")
        chain_result_ids = set(comparison_result_ids) | set(ablation_result_ids)
        if not chain_result_ids.issubset(evidence_result_ids):
            raise ContractError("创新链结果未完整绑定到贡献 evidence_result_ids")
        return chain_result_ids
    comparison_artifact_files = _required_strings(chain, "comparison_artifact_files")
    ablation_artifact_files = _required_strings(chain, "ablation_artifact_files")
    if set(comparison_artifact_files) & set(ablation_artifact_files):
        raise ContractError("创新链的对照与消融附属产物不独立")
    _require_primary_artifacts(
        run_dir,
        primary_result_id,
        [*comparison_artifact_files, *ablation_artifact_files],
    )
    return {primary_result_id}


def _record_contribution(run_dir: Path, item: Mapping[str, Any]) -> dict[str, Any]:
    """由声明来源和当前证据派生一条不可夸大的贡献记录。"""
    contribution_id = _required_string(item, "contribution_id")
    category = _required_string(item, "category")
    if category not in CONTRIBUTION_CATEGORIES:
        raise ContractError(f"不支持的贡献类别: {category}")
    source_scope = _required_string(item, "source_scope")
    if source_scope not in {"problem_specific", *GENERIC_SOURCE_SCOPES}:
        raise ContractError(f"不支持的贡献来源范围: {source_scope}")
    requested_math_innovation = item.get("requested_math_innovation")
    if not isinstance(requested_math_innovation, bool):
        raise ContractError("贡献条目 requested_math_innovation 必须为布尔值")
    evidence_result_ids = _required_strings(item, "evidence_result_ids")
    limitations = _required_strings(item, "limitations")
    innovation_evidence, innovation_evidence_valid = _innovation_evidence(
        run_dir, item, evidence_result_ids
    )
    evidence_valid = all(
        quality_allows_paper(run_dir, result_id) for result_id in evidence_result_ids
    )
    record: dict[str, Any] = {
        "contribution_id": contribution_id,
        "category": category,
        "statement": _required_string(item, "statement"),
        "source_scope": source_scope,
        "evidence_result_ids": evidence_result_ids,
        "evidence_valid": evidence_valid,
        "limitations": limitations,
        "requested_math_innovation": requested_math_innovation,
    }
    if innovation_evidence is not None:
        record["innovation_evidence"] = innovation_evidence
    if not evidence_valid:
        record.update(
            {
                "status": "rejected_unverified",
                "math_innovation_allowed": False,
                "downgrade_reason": "当前 run 缺少仍为 production/current/accepted 的证据结果",
            }
        )
    elif category == "expression_organization":
        record.update(
            {
                "status": "expression_only",
                "math_innovation_allowed": False,
                "downgrade_reason": "表达组织可改善叙事，但不是题目特定数学创新",
            }
        )
    elif source_scope in GENERIC_SOURCE_SCOPES:
        record.update(
            {
                "status": "downgraded_to_method_combination",
                "math_innovation_allowed": False,
                "downgrade_reason": "通用 Skill、质量协议、现成算法、常规图表或工程实现不能作为题目数学创新",
            }
        )
    elif requested_math_innovation:
        if innovation_evidence_valid:
            record.update(
                {
                    "status": "accepted_problem_specific",
                    "math_innovation_allowed": True,
                }
            )
        else:
            record.update(
                {
                    "status": "downgraded_missing_innovation_evidence",
                    "math_innovation_allowed": False,
                    "downgrade_reason": (
                        "题目数学创新还需绑定机制差异、可检验预测、对照改善和单组件消融的当前生产证据"
                    ),
                }
            )
    else:
        record.update(
            {
                "status": "recorded_not_math_claim",
                "math_innovation_allowed": False,
                "downgrade_reason": "作者未将该题目特定发现声明为数学创新",
            }
        )
    return record


def _innovation_disclosure(contributions: list[dict[str, Any]]) -> dict[str, str]:
    """生成论文必须遵守的创新性如实披露。"""
    if any(item["math_innovation_allowed"] for item in contributions):
        return {
            "mode": "problem_specific_math_contribution",
            "required_statement": "论文只将账本中已绑定当前运行证据和限制的题目特定贡献表述为数学创新。",
        }
    return {
        "mode": "method_combination_engineering",
        "required_statement": "本工作以方法组合与工程实现为主，未声明经当前运行证据支持的题目特定数学创新。",
    }


def build_contribution_ledger(
    run_dir: Path,
    *,
    contributions: list[Mapping[str, Any]],
    output_path: Path | None = None,
) -> dict[str, Any]:
    """建立问题特定贡献账本，并降级不能充当数学创新的条目。

    Args:
        run_dir: 当前 Capability-First v3 运行目录。
        contributions: 作者声明的贡献条目；每项必须给出类别、当前结果和限制。
        output_path: 可选的运行目录内账本输出路径。

    Returns:
        含逐项写作权限和总披露语句的可审计账本。

    Raises:
        ContractError: 条目不完整、运行不在 production 或输出越界。
    """
    if not isinstance(contributions, list):
        raise ContractError("contributions 必须是数组；空数组表示不声明题目特定创新")
    state = _require_production_state(run_dir.resolve())
    records = [_record_contribution(run_dir.resolve(), item) for item in contributions]
    if len({item["contribution_id"] for item in records}) != len(records):
        raise ContractError("贡献条目 contribution_id 不得重复")
    ledger = {
        "schema_name": CONTRIBUTION_LEDGER_SCHEMA,
        "schema_version": CONTRIBUTION_LEDGER_VERSION,
        "run_id": state["run_id"],
        "state_revision": state["revision"],
        "execution_mode": "production",
        "contributions": records,
        "innovation_disclosure": _innovation_disclosure(records),
        "generated_at": utc_now(),
    }
    require_valid(ledger, CONTRIBUTION_LEDGER_SCHEMA)
    atomic_json(_output_path(run_dir.resolve(), output_path), ledger)
    return ledger


def verify_contribution_ledger(
    run_dir: Path,
    *,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    """复验贡献账本中的 production 结果仍未失效。

    Args:
        run_dir: 当前 Capability-First v3 运行目录。
        ledger_path: 可选的账本路径。

    Returns:
        含有效性和错误列表的复验结果。
    """
    root = run_dir.resolve()
    path = _output_path(root, ledger_path)
    errors: list[str] = []
    try:
        ledger = load_json(path)
        require_valid(ledger, CONTRIBUTION_LEDGER_SCHEMA)
        state = _require_production_state(root)
        if ledger["run_id"] != state["run_id"]:
            errors.append("贡献账本 run_id 与运行目录不一致")
        if ledger["state_revision"] > state["revision"]:
            errors.append("贡献账本来自未来 state revision")
        for item in ledger["contributions"]:
            currently_valid = all(
                quality_allows_paper(root, result_id)
                for result_id in item["evidence_result_ids"]
            )
            if item["evidence_valid"] != currently_valid:
                errors.append(f"贡献 {item['contribution_id']} 的当前证据状态已变化")
            if item["math_innovation_allowed"] and (
                item["category"] == "expression_organization"
                or item["source_scope"] in GENERIC_SOURCE_SCOPES
                or not currently_valid
            ):
                errors.append(f"贡献 {item['contribution_id']} 非法声明为数学创新")
            innovation_evidence = item.get("innovation_evidence")
            if item["math_innovation_allowed"]:
                if not isinstance(innovation_evidence, Mapping):
                    errors.append(f"贡献 {item['contribution_id']} 缺少数学创新证据链")
                    continue
                try:
                    chain_result_ids = _validate_recorded_innovation_evidence(
                        root, innovation_evidence, item["evidence_result_ids"]
                    )
                except ContractError as exc:
                    errors.append(f"贡献 {item['contribution_id']} 的创新证据链无效: {exc}")
                    continue
                chain_currently_valid = all(
                    quality_allows_paper(root, result_id)
                    for result_id in chain_result_ids
                )
                if innovation_evidence["evidence_valid"] != chain_currently_valid:
                    errors.append(f"贡献 {item['contribution_id']} 的创新证据链状态已变化")
                if item["status"] != "accepted_problem_specific":
                    errors.append(f"贡献 {item['contribution_id']} 的数学创新状态不一致")
            elif item["status"] == "accepted_problem_specific":
                errors.append(f"贡献 {item['contribution_id']} 非法保留数学创新状态")
    except (ContractError, KeyError, OSError, TypeError, ValueError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors, "ledger_path": str(path)}


def require_math_innovation_allowed(
    run_dir: Path, ledger: Mapping[str, Any], contribution_id: str
) -> dict[str, Any]:
    """要求指定条目可作为题目特定数学创新写入论文。

    Args:
        run_dir: 当前 Capability-First v3 运行目录，用于重放生产证据。
        ledger: 已生成的贡献账本文档。
        contribution_id: 准备写成数学创新的贡献 ID。

    Returns:
        对应的贡献条目副本。

    Raises:
        ContractError: 条目不存在或仅可作为方法组合/工程实现表述。
    """
    require_valid(dict(ledger), CONTRIBUTION_LEDGER_SCHEMA)
    root = run_dir.resolve()
    state = _require_production_state(root)
    if ledger["run_id"] != state["run_id"]:
        raise ContractError("贡献账本 run_id 与当前运行不一致")
    item = next(
        (
            candidate
            for candidate in ledger["contributions"]
            if candidate["contribution_id"] == contribution_id
        ),
        None,
    )
    if item is None:
        raise ContractError(f"贡献账本中不存在条目: {contribution_id}")
    innovation_evidence = item.get("innovation_evidence")
    try:
        chain_result_ids = (
            _validate_recorded_innovation_evidence(
                root, innovation_evidence, item["evidence_result_ids"]
            )
            if isinstance(innovation_evidence, Mapping)
            else set()
        )
    except ContractError as exc:
        raise ContractError(f"贡献 {contribution_id} 的创新证据链无效: {exc}") from exc
    evidence_current = all(
        quality_allows_paper(root, result_id) for result_id in item["evidence_result_ids"]
    )
    chain_current = bool(chain_result_ids) and all(
        quality_allows_paper(root, result_id) for result_id in chain_result_ids
    )
    allowed = (
        item["math_innovation_allowed"] is True
        and item["status"] == "accepted_problem_specific"
        and item["source_scope"] == "problem_specific"
        and item["category"] != "expression_organization"
        and item["evidence_valid"] is True
        and evidence_current
        and isinstance(innovation_evidence, Mapping)
        and innovation_evidence.get("evidence_valid") is True
        and chain_current
    )
    if not allowed:
        raise ContractError(
            f"贡献 {contribution_id} 不得包装为题目数学创新: "
            f"{item.get('downgrade_reason', '缺少题目特定证据')}"
        )
    return dict(item)
