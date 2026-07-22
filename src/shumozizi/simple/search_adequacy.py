"""验证非光滑、多实体搜索的充分性与来源完整性。"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from typing import Any

from shumozizi.core.io import ContractError
from shumozizi.simple.selection import validate_selection_contract

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_DIRECTIONS = {"maximize", "minimize"}


def exact_best_so_far(
    scores: Sequence[float], *, objective_direction: str = "maximize"
) -> float:
    """按问题目标方向返回候选集合的 exact 最优值。

    Args:
        scores: 已独立精确评分的候选目标值。
        objective_direction: 问题合同声明的目标方向。

    Returns:
        当前候选集合的精确最优值。

    Raises:
        ValueError: 候选集合为空或目标方向不合法。
    """
    if not scores:
        raise ValueError("候选集合不能为空")
    if objective_direction not in _DIRECTIONS:
        raise ValueError("objective_direction 必须为 maximize 或 minimize")
    values = [float(value) for value in scores]
    return max(values) if objective_direction == "maximize" else min(values)


def _require_hash(value: Any, label: str) -> str:
    """验证收据中的 SHA-256，避免仅靠自报布尔字段。"""
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ContractError(f"challenge provenance 缺少有效 {label}")
    return value


def _independence_contract(contract: dict[str, Any] | None) -> dict[str, Any] | None:
    """规范化挑战独立性合同；缺失时保留旧记录的严格拒绝语义。"""
    if contract is None:
        return None
    direction = contract.get("objective_direction")
    warm_start = contract.get("allow_marked_warm_start")
    candidate_count = contract.get("minimum_independent_new_candidates")
    region_count = contract.get("minimum_independent_new_regions")
    if direction not in _DIRECTIONS:
        raise ContractError("挑战独立性合同必须声明 objective_direction")
    if not isinstance(warm_start, bool):
        raise ContractError("挑战独立性合同必须声明 allow_marked_warm_start")
    if isinstance(candidate_count, bool) or not isinstance(candidate_count, int) or candidate_count < 1:
        raise ContractError("挑战独立性合同必须要求至少一个独立新候选")
    if isinstance(region_count, bool) or not isinstance(region_count, int) or region_count < 1:
        raise ContractError("挑战独立性合同必须要求至少一个独立新区域")
    return {
        "objective_direction": direction,
        "allow_marked_warm_start": warm_start,
        "minimum_independent_new_candidates": candidate_count,
        "minimum_independent_new_regions": region_count,
    }


def _challenge_pool_diagnostics(
    incumbent_fingerprint: str,
    challenge_receipt: dict[str, Any],
    contract: dict[str, Any] | None,
) -> dict[str, Any]:
    """审计 warm start、新候选及实际精确评估的新区域。"""
    fingerprints = challenge_receipt["candidate_fingerprints"]
    incumbent_in_pool = incumbent_fingerprint in fingerprints
    if not incumbent_in_pool and contract is None:
        return {
            "warm_start_accepted": False,
            "independent_new_candidate_count": len(fingerprints),
            "independent_new_region_count": None,
        }
    if contract is None or not contract["allow_marked_warm_start"]:
        raise ContractError("challenge provenance 的候选池包含 incumbent")
    pool = challenge_receipt.get("candidate_pool")
    if not isinstance(pool, dict):
        raise ContractError("warm start 挑战缺少候选池与新区域审计")
    candidates = pool.get("candidates")
    regions = pool.get("evaluated_region_ids")
    if not isinstance(candidates, list) or not isinstance(regions, list):
        raise ContractError("warm start 挑战缺少独立新候选或新区域")
    if any(not isinstance(region, str) or not region for region in regions):
        raise ContractError("挑战的新区域标识不合法")
    candidate_map: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ContractError("挑战候选池条目必须为对象")
        fingerprint = candidate.get("fingerprint")
        role = candidate.get("role")
        region = candidate.get("region_id")
        if not isinstance(fingerprint, str) or fingerprint not in fingerprints:
            raise ContractError("挑战候选池与 candidate_fingerprints 不一致")
        if fingerprint in candidate_map:
            raise ContractError("挑战候选池 fingerprint 必须唯一")
        if role not in {"baseline", "warm_start", "independent_new"}:
            raise ContractError("挑战候选池 role 不合法")
        if not isinstance(region, str):
            raise ContractError("挑战候选池缺少 region_id")
        if not isinstance(candidate.get("exact_evaluated"), bool):
            raise ContractError("挑战候选池必须声明 exact_evaluated")
        candidate_map[fingerprint] = candidate
    if set(candidate_map) != set(fingerprints):
        raise ContractError("挑战候选池必须覆盖全部原始候选")
    incumbent_entry = candidate_map.get(incumbent_fingerprint)
    if incumbent_in_pool and (
        incumbent_entry is None or incumbent_entry["role"] not in {"baseline", "warm_start"}
    ):
        raise ContractError("incumbent 只能作为明确标记的 baseline/warm_start")
    independent = [
        item
        for fingerprint, item in candidate_map.items()
        if fingerprint != incumbent_fingerprint
        and item["role"] == "independent_new"
        and item["exact_evaluated"]
    ]
    independent_regions = {str(item["region_id"]) for item in independent if item["region_id"]}
    declared_regions = set(regions)
    if not independent_regions <= declared_regions:
        raise ContractError("挑战的新区域未被实际评估登记")
    if len(independent) < contract["minimum_independent_new_candidates"]:
        raise ContractError("挑战缺少合同要求的独立新候选")
    if len(independent_regions) < contract["minimum_independent_new_regions"]:
        raise ContractError("挑战缺少合同要求的新区域")
    return {
        "warm_start_accepted": incumbent_in_pool,
        "independent_new_candidate_count": len(independent),
        "independent_new_region_count": len(independent_regions),
    }


def _require_challenge_provenance(
    incumbent_receipt: dict[str, Any],
    challenge_receipt: dict[str, Any],
    independence_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """验证独立挑战的命令、候选池和冻结 incumbent 来源。"""
    required_incumbent = (
        "result_id",
        "candidate_fingerprint",
        "exact_output_sha256",
        "recomputed_output_sha256",
        "search_family",
        "recomputed_result_id",
    )
    if any(key not in incumbent_receipt for key in required_incumbent):
        raise ContractError("challenge provenance 缺少冻结 incumbent 收据")
    for key in ("candidate_fingerprint", "exact_output_sha256", "recomputed_output_sha256"):
        _require_hash(incumbent_receipt[key], f"incumbent.{key}")
    if not isinstance(incumbent_receipt["recomputed_result_id"], str) or not incumbent_receipt[
        "recomputed_result_id"
    ]:
        raise ContractError("challenge provenance 缺少 incumbent 独立 exact 重算结果")
    incumbent_family = incumbent_receipt["search_family"]
    if not isinstance(incumbent_family, dict) or not isinstance(incumbent_family.get("id"), str):
        raise ContractError("challenge provenance 缺少 incumbent 搜索族")
    _require_hash(incumbent_family.get("implementation_sha256"), "incumbent.family")

    required_challenge = (
        "command",
        "command_receipt_sha256",
        "input_hashes",
        "output_sha256",
        "search_family",
        "candidate_fingerprints",
    )
    if any(key not in challenge_receipt for key in required_challenge):
        raise ContractError("challenge provenance 缺少挑战执行收据")
    if not isinstance(challenge_receipt["command"], str) or not challenge_receipt["command"].strip():
        raise ContractError("challenge provenance 缺少挑战命令")
    for key in ("command_receipt_sha256", "output_sha256"):
        _require_hash(challenge_receipt[key], f"challenge.{key}")
    inputs = challenge_receipt["input_hashes"]
    if not isinstance(inputs, dict) or not inputs:
        raise ContractError("challenge provenance 缺少挑战输入哈希")
    for value in inputs.values():
        _require_hash(value, "challenge.input")
    challenge_family = challenge_receipt["search_family"]
    if not isinstance(challenge_family, dict) or not isinstance(challenge_family.get("id"), str):
        raise ContractError("challenge provenance 缺少挑战搜索族")
    challenge_implementation = _require_hash(
        challenge_family.get("implementation_sha256"), "challenge.family"
    )
    if (
        challenge_family["id"] == incumbent_family["id"]
        or challenge_implementation == incumbent_family["implementation_sha256"]
    ):
        raise ContractError("challenge provenance 的搜索族与 incumbent 不独立")
    fingerprints = challenge_receipt["candidate_fingerprints"]
    if not isinstance(fingerprints, list) or not fingerprints:
        raise ContractError("challenge provenance 缺少挑战候选指纹")
    normalized = [_require_hash(item, "challenge.candidate") for item in fingerprints]
    if len(set(normalized)) != len(normalized):
        raise ContractError("challenge provenance 的候选指纹不得重复")
    contract = _independence_contract(independence_contract)
    return _challenge_pool_diagnostics(
        incumbent_receipt["candidate_fingerprint"], challenge_receipt, contract
    )


def _metric_output_hash(result: dict[str, Any], metric: str, label: str) -> str:
    """读取已登记 exact 指标的输出哈希。"""
    source = result.get("metric_sources", {}).get(metric)
    if not isinstance(source, dict):
        raise ContractError(f"challenge provenance 缺少 {label} 的 exact 指标来源")
    return _require_hash(source.get("file_sha256"), f"{label}.exact_output")


def _verify_family_implementation(
    receipt: dict[str, Any], result: dict[str, Any], label: str
) -> None:
    """把搜索族实现哈希绑定到本次登记执行的输入。"""
    family = receipt.get("search_family")
    if not isinstance(family, dict):
        raise ContractError(f"challenge provenance 缺少 {label} 搜索族")
    implementation_file = family.get("implementation_file")
    implementation_hash = _require_hash(family.get("implementation_sha256"), f"{label}.family")
    if not isinstance(implementation_file, str) or not implementation_file:
        raise ContractError(f"challenge provenance 缺少 {label} 搜索实现文件")
    if result.get("input_hashes", {}).get(implementation_file) != implementation_hash:
        raise ContractError(f"challenge provenance 的 {label} 搜索实现未绑定登记输入")


def validate_registered_challenge_provenance(
    *,
    incumbent_receipt: dict[str, Any],
    challenge_receipt: dict[str, Any],
    incumbent_result: dict[str, Any],
    challenger_result: dict[str, Any],
    result_map: dict[str, dict[str, Any]],
    metric: str,
    fine_tolerance: float,
    independence_contract: dict[str, Any] | None = None,
) -> None:
    """将挑战收据绑定到已登记命令、输入、输出和独立精算执行。

    Args:
        incumbent_receipt: 冻结 incumbent 的收据。
        challenge_receipt: 独立挑战的收据。
        incumbent_result: 登记的 incumbent 执行。
        challenger_result: 当前待放行的挑战执行。
        result_map: 所有登记结果的 ID 映射。
        metric: 合同指定的 exact 指标。
        fine_tolerance: 用于比较独立重算 exact 值的合同容差。
        independence_contract: warm start、独立新候选与新区域的预登记合同。

    Raises:
        ContractError: 收据与登记执行或独立重算不一致。
    """
    if challenge_receipt.get("result_id") != challenger_result.get("result_id"):
        raise ContractError("challenge provenance 的挑战 result_id 与登记执行不一致")
    command = challenge_receipt.get("command")
    if command != challenger_result.get("command"):
        raise ContractError("challenge provenance 的挑战命令与登记执行不一致")
    if _require_hash(
        challenge_receipt.get("command_receipt_sha256"), "challenge.command_receipt"
    ) != hashlib.sha256(str(command).encode("utf-8")).hexdigest():
        raise ContractError("challenge provenance 的挑战命令收据哈希不一致")
    if challenge_receipt.get("input_hashes") != challenger_result.get("input_hashes"):
        raise ContractError("challenge provenance 的挑战输入哈希与登记执行不一致")
    if challenge_receipt.get("output_sha256") != _metric_output_hash(
        challenger_result, metric, "challenge"
    ):
        raise ContractError("challenge provenance 的挑战输出哈希与登记 exact 不一致")
    _verify_family_implementation(challenge_receipt, challenger_result, "challenge")

    if incumbent_receipt.get("result_id") != incumbent_result.get("result_id"):
        raise ContractError("challenge provenance 的 incumbent 未绑定候选登记")
    if incumbent_receipt.get("exact_output_sha256") != _metric_output_hash(
        incumbent_result, metric, "incumbent"
    ):
        raise ContractError("challenge provenance 的 incumbent 冻结输出哈希不一致")
    _verify_family_implementation(incumbent_receipt, incumbent_result, "incumbent")

    recomputed_id = incumbent_receipt.get("recomputed_result_id")
    recomputed = result_map.get(recomputed_id) if isinstance(recomputed_id, str) else None
    if recomputed is None or not recomputed.get("execution_valid"):
        raise ContractError("challenge provenance 的 incumbent 独立 exact 重算未登记")
    if recomputed.get("result_id") == incumbent_result.get("result_id"):
        raise ContractError("challenge provenance 的 incumbent 重算不得复用冻结执行")
    if recomputed.get("question_id") != incumbent_result.get("question_id"):
        raise ContractError("challenge provenance 的 incumbent 重算问题不一致")
    if incumbent_receipt.get("recomputed_output_sha256") != _metric_output_hash(
        recomputed, metric, "incumbent_recomputed"
    ):
        raise ContractError("challenge provenance 的 incumbent 重算输出哈希不一致")
    original_exact = incumbent_result.get("metrics", {}).get(metric)
    recomputed_exact = recomputed.get("metrics", {}).get(metric)
    if not isinstance(original_exact, (int, float)) or not isinstance(recomputed_exact, (int, float)):
        raise ContractError("challenge provenance 的 incumbent exact 指标不可比较")
    if abs(float(original_exact) - float(recomputed_exact)) > fine_tolerance:
        raise ContractError("challenge provenance 的 incumbent 独立 exact 重算数值不一致")
    _require_challenge_provenance(
        incumbent_receipt,
        challenge_receipt,
        independence_contract,
    )


def assess_independent_challenge(
    *,
    incumbent_exact: float,
    challenger_exact: float,
    incumbent_receipt: dict[str, Any],
    challenge_receipt: dict[str, Any],
    improvement_tolerance: float = 0.0,
    comparability_contract: dict[str, Any] | None = None,
    independence_contract: dict[str, Any] | None = None,
    semantic_error: bool = False,
) -> dict[str, Any]:
    """判断带执行收据的独立挑战是否足以支撑搜索充分性。

    可比阈值只有在当前问题合同明确预登记值、理由和计划哈希时才生效。函数不含
    通用百分比阈值；何为“足够接近”完全由问题合同定义。

    Args:
        incumbent_exact: 冻结 incumbent 的精确目标。
        challenger_exact: 挑战候选的精确目标。
        incumbent_receipt: incumbent 冻结与独立 exact 重算的收据。
        challenge_receipt: 挑战命令、输入、输出和候选池收据。
        improvement_tolerance: 当前问题合同冻结的精细评分容差。
        comparability_contract: 可选的预登记可比性合同。
        independence_contract: warm start、独立新候选与新区域的预登记合同。
        semantic_error: adapter 已发现的模型或 scorer 语义错误。

    Returns:
        搜索充分性状态、原因和可复核诊断。

    Raises:
        ContractError: 收据不具备独立性来源。
    """
    if isinstance(improvement_tolerance, bool) or improvement_tolerance < 0.0:
        raise ContractError("挑战改善容差不能为负")
    if not isinstance(incumbent_exact, (int, float)) or isinstance(incumbent_exact, bool):
        raise ContractError("incumbent exact 必须为数值")
    if not isinstance(challenger_exact, (int, float)) or isinstance(challenger_exact, bool):
        raise ContractError("challenger exact 必须为数值")
    pool_diagnostics = _require_challenge_provenance(
        incumbent_receipt,
        challenge_receipt,
        independence_contract,
    )
    normalized_contract = _independence_contract(independence_contract)
    direction = (
        normalized_contract["objective_direction"] if normalized_contract is not None else "maximize"
    )
    threshold: float | None = None
    if comparability_contract is not None:
        required = ("threshold", "reason", "plan_sha256")
        if any(key not in comparability_contract for key in required):
            raise ContractError("可比性合同缺少预登记字段")
        if not isinstance(comparability_contract["threshold"], (int, float)):
            raise ContractError("可比性合同阈值必须为数值")
        if not isinstance(comparability_contract["reason"], str) or not comparability_contract["reason"]:
            raise ContractError("可比性合同必须说明阈值理由")
        _require_hash(comparability_contract["plan_sha256"], "comparability.plan")
        threshold = float(comparability_contract["threshold"])
    incumbent = float(incumbent_exact)
    challenger = float(challenger_exact)
    tolerance = float(improvement_tolerance)
    directional_improvement = (
        challenger - incumbent if direction == "maximize" else incumbent - challenger
    )
    improved = directional_improvement > tolerance
    weaker = directional_improvement < -tolerance
    comparable = threshold is not None and (
        challenger >= threshold - tolerance
        if direction == "maximize"
        else challenger <= threshold + tolerance
    )

    if semantic_error:
        outcome = "model_or_scorer_semantic_error"
        incumbent_outcome = "requires_reassessment"
        search_adequacy = "failed"
        reasons = ["model_or_scorer_semantic_error_requires_analysis"]
    elif improved:
        outcome = "improved"
        incumbent_outcome = "replaced"
        search_adequacy = "passed"
        reasons = ["independent_challenge_improved_incumbent"]
    elif comparable:
        outcome = "stability_confirmed"
        incumbent_outcome = "stabilized"
        search_adequacy = "passed"
        reasons = ["independent_challenge_comparable_threshold_met"]
    elif weaker:
        outcome = "algorithm_weaker"
        incumbent_outcome = "preserved"
        search_adequacy = "passed"
        reasons = ["independent_challenge_algorithm_weaker"]
    else:
        outcome = "inconclusive"
        incumbent_outcome = "preserved"
        search_adequacy = "passed"
        reasons = ["independent_challenge_inconclusive_without_comparability_contract"]

    return {
        "search_adequacy": search_adequacy,
        "reasons": reasons,
        "incumbent_outcome": incumbent_outcome,
        "challenge_outcome": outcome,
        "challenger_replaces_incumbent": outcome == "improved",
        "diagnostics": {
            "incumbent_exact": incumbent,
            "challenger_exact": challenger,
            "objective_direction": direction,
            "directional_improvement": directional_improvement,
            "incumbent_exact_recomputed": True,
            "challenger_family": challenge_receipt["search_family"]["id"],
            "incumbent_family": incumbent_receipt["search_family"]["id"],
            "comparable_threshold": threshold,
            "improved_incumbent": improved,
            "meets_comparable_threshold": comparable,
            **pool_diagnostics,
        },
    }


def validate_coverage_evidence(
    selection_contract: dict[str, Any], coverage: dict[str, Any]
) -> dict[str, Any]:
    """检查实体变量、共同变量和交互变量的联合覆盖报告。

    Args:
        selection_contract: 包含每个真实变量组及其合同阈值的选择合同。
        coverage: 由已登记搜索执行输出的覆盖报告。

    Returns:
        通过状态、原因和逐组诊断。
    """
    validate_selection_contract(selection_contract)
    declared = selection_contract.get("coverage", {}).get("groups")
    reports = coverage.get("group_reports") if isinstance(coverage, dict) else None
    if not isinstance(declared, list) or not declared:
        raise ContractError("selection_contract 缺少 coverage.groups")
    if not isinstance(reports, list):
        raise ContractError("coverage evidence 缺少 group_reports")
    report_map = {
        item.get("id"): item
        for item in reports
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    reasons: list[str] = []
    diagnostics: list[dict[str, Any]] = []
    for group in declared:
        if not isinstance(group, dict) or not isinstance(group.get("id"), str):
            raise ContractError("coverage 合同组缺少 id")
        expected_variables = group.get("variables")
        minimum = group.get("minimum_joint_coverage")
        if (
            not isinstance(expected_variables, list)
            or not expected_variables
            or not all(isinstance(item, str) and item for item in expected_variables)
            or not isinstance(minimum, (int, float))
            or not 0.0 <= float(minimum) <= 1.0
        ):
            raise ContractError("coverage 合同组必须声明真实变量和 [0, 1] 联合覆盖阈值")
        report = report_map.get(group["id"])
        if report is None:
            reasons.append(f"coverage_group_missing:{group['id']}")
            continue
        actual_variables = report.get("variables")
        joint_coverage = report.get("joint_coverage")
        if actual_variables != expected_variables:
            reasons.append(f"coverage_group_variables_mismatch:{group['id']}")
            continue
        if not isinstance(joint_coverage, (int, float)):
            reasons.append(f"coverage_group_missing_joint_value:{group['id']}")
            continue
        passed = float(joint_coverage) >= float(minimum)
        diagnostics.append(
            {
                "id": group["id"],
                "joint_coverage": float(joint_coverage),
                "minimum_joint_coverage": float(minimum),
                "passed": passed,
            }
        )
        if not passed:
            reasons.append(f"coverage_group_below_contract:{group['id']}")
    return {"passed": not reasons, "reasons": reasons, "groups": diagnostics}


def validate_objective_semantics(
    selection_contract: dict[str, Any], semantics: dict[str, Any]
) -> dict[str, Any]:
    """确认代理、校准、精算和选择均遵循问题目标语义。"""
    validate_selection_contract(selection_contract)
    objective = selection_contract["objective"]
    expected = "union_marginal_gain" if objective["semantics"] == "union" else "additive_sum"
    required = ("surrogate", "calibration", "exact", "selection")
    reasons = [
        f"objective_semantics_mismatch:{field}"
        for field in required
        if semantics.get(field) != expected
    ]
    gains = semantics.get("entity_marginal_gains")
    if not isinstance(gains, list) or not gains or not all(isinstance(item, (int, float)) for item in gains):
        reasons.append("entity_marginal_gains_missing")
    return {
        "passed": not reasons,
        "reasons": reasons,
        "expected_semantics": expected,
        "zero_marginal_entities": (
            sum(float(item) == 0.0 for item in gains) if isinstance(gains, list) else 0
        ),
    }


def _top_indices(scores: Sequence[float], count: int, direction: str) -> set[int]:
    """按目标方向返回稳定的前 k 索引，避免相同分数时不可复现。"""
    if direction not in _DIRECTIONS:
        raise ValueError("objective_direction 必须为 maximize 或 minimize")

    def ordering(index: int) -> tuple[float, int]:
        """将方向语义收敛为稳定的升序排序键。"""
        value = float(scores[index])
        return (-value, index) if direction == "maximize" else (value, index)

    return set(sorted(range(len(scores)), key=ordering)[:count])


def _improves(
    candidate: float,
    baseline: float,
    *,
    direction: str,
    tolerance: float,
) -> bool:
    """按合同方向判断候选是否相对基线有实质改善。"""
    return (
        candidate > baseline + tolerance
        if direction == "maximize"
        else candidate < baseline - tolerance
    )


def assess_search_adequacy(
    *,
    exact_scores: Sequence[float],
    approximate_scores: Sequence[float],
    surrogate_scores: Sequence[float],
    local_surrogate_scores: Sequence[float],
    baseline_index: int,
    top_k: int,
    adequacy_contract: dict[str, Any],
    positive_epsilon: float = 1e-9,
    joint_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """量化由问题合同定义阈值的搜索校准充分性。

    假零仅在它确实改变候选筛选时视为灾难性误差。其余误差保留为诊断，避免
    将一个不影响决策的代理偏差机械升级为搜索失败。

    Args:
        exact_scores: 独立 exact scorer 输出的目标值。
        approximate_scores: 低成本近似评价输出。
        surrogate_scores: 用于候选筛选的代理输出。
        local_surrogate_scores: 局部扰动或边界邻域的代理输出。
        baseline_index: 合同中的基线候选索引。
        top_k: 合同声明的候选筛选规模。
        adequacy_contract: 目标方向、阈值和假零策略。
        positive_epsilon: 判断数值零的合同容差。
        joint_coverage: 从原始候选坐标重算的联合覆盖结果。

    Returns:
        通过状态、阻断原因和不阻断的校准诊断。

    Raises:
        ValueError: 输入长度、合同字段或目标方向不合法。
    """
    required_thresholds = (
        "minimum_top_k_recall",
        "minimum_improvement_sign_agreement",
        "minimum_local_variation",
    )
    if any(key not in adequacy_contract for key in (*required_thresholds, "objective_direction")):
        raise ValueError("adequacy_contract 缺少接受阈值")
    direction = adequacy_contract["objective_direction"]
    if direction not in _DIRECTIONS:
        raise ValueError("adequacy_contract 的 objective_direction 不合法")
    false_zero_policy = adequacy_contract.get("approximate_false_zero_policy", "catastrophic_only")
    if false_zero_policy != "catastrophic_only":
        raise ValueError("approximate_false_zero_policy 只能为 catastrophic_only")
    thresholds = {key: float(adequacy_contract[key]) for key in required_thresholds}
    if any(value < 0.0 for value in thresholds.values()):
        raise ValueError("adequacy_contract 阈值不能为负")
    count = len(exact_scores)
    if (
        count == 0
        or len(approximate_scores) != count
        or len(surrogate_scores) != count
        or not 0 <= baseline_index < count
        or top_k < 1
    ):
        raise ValueError("校准数组、基线索引或 top_k 不合法")
    exact = [float(value) for value in exact_scores]
    approximate = [float(value) for value in approximate_scores]
    surrogate = [float(value) for value in surrogate_scores]
    positives = [index for index, value in enumerate(exact) if abs(value) > positive_epsilon]
    approximate_false_zeros = [
        index
        for index in positives
        if abs(approximate[index]) <= positive_epsilon
        and abs(approximate[index] - exact[index]) > positive_epsilon
    ]
    surrogate_false_zeros = [
        index
        for index in positives
        if abs(surrogate[index]) <= positive_epsilon
        and abs(surrogate[index] - exact[index]) > positive_epsilon
    ]
    effective_k = min(top_k, count)
    exact_top = _top_indices(exact, effective_k, str(direction))
    approximate_top = _top_indices(approximate, effective_k, str(direction))
    surrogate_top = _top_indices(surrogate, effective_k, str(direction))
    top_k_recall = len(exact_top & surrogate_top) / effective_k
    baseline_exact = exact[baseline_index]
    baseline_surrogate = surrogate[baseline_index]
    comparable = [index for index in range(count) if index != baseline_index]
    improvement_pairs = [
        (
            _improves(
                exact[index],
                baseline_exact,
                direction=str(direction),
                tolerance=positive_epsilon,
            ),
            _improves(
                surrogate[index],
                baseline_surrogate,
                direction=str(direction),
                tolerance=positive_epsilon,
            ),
        )
        for index in comparable
    ]
    improvement_agreement = (
        sum(exact_improved == surrogate_improved for exact_improved, surrogate_improved in improvement_pairs)
        / len(improvement_pairs)
        if improvement_pairs
        else 1.0
    )
    local_variation = (
        max(float(value) for value in local_surrogate_scores)
        - min(float(value) for value in local_surrogate_scores)
        if local_surrogate_scores
        else 0.0
    )
    approximate_selection_affected = any(
        (
            index in exact_top and index not in approximate_top
            if direction == "maximize"
            else index not in exact_top and index in approximate_top
        )
        for index in approximate_false_zeros
    )
    surrogate_selection_affected = any(
        (
            index in exact_top and index not in surrogate_top
            if direction == "maximize"
            else index not in exact_top and index in surrogate_top
        )
        for index in surrogate_false_zeros
    )
    catastrophic_selection_error = approximate_selection_affected or surrogate_selection_affected
    blocking_reasons: list[str] = []
    diagnostic_reasons: list[str] = []
    if approximate_false_zeros:
        diagnostic_reasons.extend(["approximate_false_zero_detected", "approximate_false_zero_diagnostic"])
    if surrogate_false_zeros:
        diagnostic_reasons.extend(["surrogate_false_zero_detected", "surrogate_false_zero_diagnostic"])
    if catastrophic_selection_error:
        blocking_reasons.append("calibration_catastrophic_selection_error")
    if top_k_recall < thresholds["minimum_top_k_recall"]:
        blocking_reasons.append("surrogate_top_k_recall_insufficient")
    if improvement_agreement < thresholds["minimum_improvement_sign_agreement"]:
        blocking_reasons.append("surrogate_improvement_sign_disagrees")
    if local_variation < thresholds["minimum_local_variation"]:
        blocking_reasons.append("surrogate_local_flat")
    if joint_coverage is not None and not bool(joint_coverage.get("passed")):
        blocking_reasons.append("joint_domain_coverage_incomplete")
    return {
        "search_adequacy": "failed" if blocking_reasons else "passed",
        "reasons": [*blocking_reasons, *diagnostic_reasons] or ["calibration_passed"],
        "diagnostics": {
            "sample_count": count,
            "positive_exact_count": len(positives),
            "approximate_false_zero_count": len(approximate_false_zeros),
            "surrogate_false_zero_count": len(surrogate_false_zeros),
            "calibration_restart_required": catastrophic_selection_error,
            "objective_direction": direction,
            "approximate_false_zero_selection_affected": approximate_selection_affected,
            "surrogate_false_zero_selection_affected": surrogate_selection_affected,
            "top_k": effective_k,
            "top_k_recall": top_k_recall,
            "improvement_sign_agreement": improvement_agreement,
            "local_variation": local_variation,
            "contract": {
                **thresholds,
                "objective_direction": direction,
                "approximate_false_zero_policy": false_zero_policy,
            },
            "joint_coverage": joint_coverage,
        },
    }
