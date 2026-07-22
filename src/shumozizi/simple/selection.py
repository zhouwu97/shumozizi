"""维护按问题合同分组的已验证候选下界。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, resolve_inside, sha256_file
from shumozizi.simple.results import json_path_value, read_result_index, require_result_index
from shumozizi.simple.state import utc_now

REGISTRY_PATH = Path("results/candidate_registry.json")
_DIRECTIONS = {"maximize", "minimize"}
_SEMANTICS = {"additive", "union"}


def validate_selection_contract(
    contract: dict[str, Any], *, require_coverage: bool = False
) -> None:
    """校验候选可比性所需的最小问题合同。

    Args:
        contract: 由当前问题在搜索前冻结的选择合同。
        require_coverage: 为真时要求 adapter 合同声明可从原生坐标重算的覆盖度量。

    Raises:
        ContractError: 合同缺少目标、版本或容差等必要定义。
    """
    objective = contract.get("objective")
    if not isinstance(objective, dict):
        raise ContractError("selection_contract 缺少 objective")
    required = (
        "metric",
        "direction",
        "objective_version",
        "scorer_version",
        "constraint_version",
        "semantics",
        "fine_tolerance",
    )
    missing = [key for key in required if not isinstance(objective.get(key), str) or not objective[key]]
    if "fine_tolerance" in missing:
        missing.remove("fine_tolerance")
        if not isinstance(objective.get("fine_tolerance"), (int, float)):
            missing.append("fine_tolerance")
    if missing:
        raise ContractError(f"selection_contract objective 缺少: {', '.join(missing)}")
    if objective["direction"] not in _DIRECTIONS:
        raise ContractError("objective.direction 必须为 maximize 或 minimize")
    if objective["semantics"] not in _SEMANTICS:
        raise ContractError("objective.semantics 必须为 additive 或 union")
    if float(objective["fine_tolerance"]) < 0.0:
        raise ContractError("objective.fine_tolerance 不能为负")
    required_evidence = contract.get("required_evidence", [])
    if not isinstance(required_evidence, list) or any(
        not isinstance(item, str) or not item for item in required_evidence
    ):
        raise ContractError("selection_contract.required_evidence 必须为字符串数组")
    dependencies = contract.get("required_prior_questions", [])
    if not isinstance(dependencies, list) or any(
        not isinstance(item, str) or not item for item in dependencies
    ):
        raise ContractError("selection_contract.required_prior_questions 必须为字符串数组")
    adapter = contract.get("verification_adapter")
    if adapter is not None and (
        not isinstance(adapter, dict)
        or not isinstance(adapter.get("adapter_id"), str)
        or not adapter["adapter_id"]
        or not isinstance(adapter.get("adapter_version"), str)
        or not adapter["adapter_version"]
    ):
        raise ContractError("selection_contract.verification_adapter 必须包含 adapter_id 和 adapter_version")
    if not require_coverage:
        return
    coverage = contract.get("coverage")
    if not isinstance(coverage, dict):
        raise ContractError("selection_contract 缺少 coverage")
    variables = coverage.get("candidate_variables")
    if not isinstance(variables, list) or not variables or any(
        not isinstance(item, str) or not item for item in variables
    ) or len(set(variables)) != len(variables):
        raise ContractError("coverage.candidate_variables 必须是非空且唯一的原始坐标列表")
    groups = coverage.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ContractError("coverage.groups 必须为非空数组")
    identifiers: set[str] = set()
    covered: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            raise ContractError("coverage.groups 条目必须为对象")
        identifier = group.get("id")
        group_variables = group.get("variables")
        bounds = group.get("bounds")
        bins = group.get("bins_per_variable")
        minimum = group.get("minimum_joint_coverage")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise ContractError("coverage group id 必须唯一")
        identifiers.add(identifier)
        if group.get("metric") != "occupied_bins":
            raise ContractError("coverage group 必须声明 occupied_bins 原生联合覆盖")
        if not isinstance(group_variables, list) or not group_variables or any(
            not isinstance(item, str) or item not in variables for item in group_variables
        ) or len(set(group_variables)) != len(group_variables):
            raise ContractError("coverage group variables 必须引用完整原始坐标")
        if isinstance(bins, bool) or not isinstance(bins, int) or bins < 2:
            raise ContractError("coverage group bins_per_variable 必须是不小于 2 的整数")
        if isinstance(minimum, bool) or not isinstance(minimum, (int, float)) or not 0 <= float(minimum) <= 1:
            raise ContractError("coverage group minimum_joint_coverage 必须在 [0, 1]")
        if not isinstance(bounds, dict) or set(bounds) != set(group_variables):
            raise ContractError("coverage group bounds 必须覆盖每个原始坐标")
        for variable in group_variables:
            interval = bounds[variable]
            if (
                not isinstance(interval, list)
                or len(interval) != 2
                or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in interval)
                or float(interval[0]) >= float(interval[1])
            ):
                raise ContractError("coverage group bounds 必须是递增有限数值区间")
        covered.update(group_variables)
    if covered != set(variables):
        raise ContractError("coverage groups 必须覆盖每个 candidate_variables 原始坐标")


def selection_group_key(question_id: str, contract: dict[str, Any]) -> dict[str, str]:
    """生成仅由可比性定义组成的候选分组键。

    Args:
        question_id: 当前子问题编号。
        contract: 已校验的选择合同。

    Returns:
        能避免跨目标、评分器或约束比较的稳定分组键。
    """
    validate_selection_contract(contract)
    objective = contract["objective"]
    adapter = contract.get("verification_adapter")
    adapter_values = adapter if isinstance(adapter, dict) else {}
    return {
        "question_id": question_id,
        "metric": str(objective["metric"]),
        "direction": str(objective["direction"]),
        "objective_version": str(objective["objective_version"]),
        "scorer_version": str(objective["scorer_version"]),
        "constraint_version": str(objective["constraint_version"]),
        "semantics": str(objective["semantics"]),
        "fine_tolerance": str(float(objective["fine_tolerance"])),
        "adapter_id": str(adapter_values.get("adapter_id", "legacy")),
        "adapter_version": str(adapter_values.get("adapter_version", "legacy")),
    }


def _empty_registry(run_dir: Path) -> dict[str, Any]:
    """构造新运行的空候选登记。"""
    return {"schema_version": "1.0", "run_id": run_dir.name, "groups": []}


def _require_registry(payload: dict[str, Any], run_dir: Path) -> None:
    """验证候选登记的紧凑持久化结构。"""
    if payload.get("schema_version") != "1.0" or payload.get("run_id") != run_dir.name:
        raise ContractError("candidate_registry 版本或 run_id 不匹配")
    groups = payload.get("groups")
    if not isinstance(groups, list):
        raise ContractError("candidate_registry.groups 必须为数组")
    seen: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            raise ContractError("candidate_registry group 必须为对象")
        key = group.get("group")
        observations = group.get("observations")
        if not isinstance(key, dict) or not isinstance(observations, list):
            raise ContractError("candidate_registry group 缺少 group 或 observations")
        fingerprint = json.dumps(key, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if fingerprint in seen:
            raise ContractError("candidate_registry 存在重复分组")
        seen.add(fingerprint)
        if observations and (
            not isinstance(group.get("best_result_id"), str)
            or not isinstance(group.get("best_exact"), (int, float))
        ):
            raise ContractError("非空候选分组必须包含 best_result_id 和 best_exact")


def read_candidate_registry(run_dir: Path) -> dict[str, Any]:
    """读取候选登记；新运行尚未登记候选时返回空结构。

    Args:
        run_dir: v3 运行目录。

    Returns:
        已验证的候选登记。
    """
    path = run_dir / REGISTRY_PATH
    if not path.exists():
        return _empty_registry(run_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"candidate_registry 不可读取: {exc}") from exc
    _require_registry(payload, run_dir)
    return payload


def _find_group(registry: dict[str, Any], key: dict[str, str]) -> dict[str, Any]:
    """返回分组，缺失时在内存中创建。"""
    for group in registry["groups"]:
        if group["group"] == key:
            return group
    group = {"group": key, "observations": []}
    registry["groups"].append(group)
    return group


def _exact_metric(result: dict[str, Any], run_dir: Path, metric: str) -> float:
    """从登记的输出来源复验精确目标，而不信任内存指标副本。"""
    value = result.get("metrics", {}).get(metric)
    source = result.get("metric_sources", {}).get(metric)
    if not isinstance(value, (int, float)) or not isinstance(source, dict):
        raise ContractError(f"精确目标缺少可验证指标来源: {metric}")
    relative = source.get("file")
    expected_hash = source.get("file_sha256")
    json_path = source.get("json_path")
    if not all(isinstance(item, str) and item for item in (relative, expected_hash, json_path)):
        raise ContractError("精确目标来源结构不完整")
    if result.get("output_hashes", {}).get(relative) != expected_hash:
        raise ContractError("精确目标来源不是已登记输出")
    path = resolve_inside(run_dir, relative, must_exist=True)
    if sha256_file(path) != expected_hash:
        raise ContractError("精确目标来源哈希已漂移")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError("精确目标来源 JSON 不可读取") from exc
    if json_path_value(document, json_path) != value:
        raise ContractError("精确目标与登记来源不一致")
    return float(value)


def _better(candidate: float, incumbent: float, direction: str, tolerance: float) -> bool:
    """依据问题合同判断候选是否严格改善。"""
    if direction == "maximize":
        return candidate > incumbent + tolerance
    return candidate < incumbent - tolerance


def _worse(candidate: float, incumbent: float, direction: str, tolerance: float) -> bool:
    """依据问题合同判断候选是否实质退化。"""
    if direction == "maximize":
        return candidate < incumbent - tolerance
    return candidate > incumbent + tolerance


def _synchronize_current_results(index: dict[str, Any], registry: dict[str, Any]) -> None:
    """将每个合同分组的 incumbent 恢复为 current，避免低质量重跑覆盖它。"""
    active = {
        group["best_result_id"]
        for group in registry["groups"]
        if group.get("best_result_id")
    }
    for result in index["results"]:
        if result["result_id"] in active and result["execution_valid"]:
            result["status"] = "current"


def retain_verified_incumbents(run_dir: Path, result_id: str) -> None:
    """在候选未通过质量门时恢复已验证 incumbent。

    Args:
        run_dir: v3 运行目录。
        result_id: 未能放行且不应保留为 current 的结果。
    """
    registry = read_candidate_registry(run_dir)
    if not registry["groups"]:
        return
    index = read_result_index(run_dir)
    active = {
        group["best_result_id"]
        for group in registry["groups"]
        if group.get("best_result_id")
    }
    for result in index["results"]:
        if result["result_id"] == result_id and result_id not in active:
            result["status"] = "superseded"
    _synchronize_current_results(index, registry)
    require_result_index(index)
    atomic_json(run_dir / "results" / "index.json", index)


def register_verified_candidate(
    run_dir: Path,
    *,
    result_id: str,
    selection_contract: dict[str, Any],
) -> dict[str, Any]:
    """以精确、可追溯目标将候选写入分组登记。

    该函数仅处理同一问题合同内的“是否可替换 incumbent”。可行性、搜索充分性
    和问题有效性由质量层先行验证；低于已验证下界的结果仍保留观测记录，但不会
    替换当前事实结果。

    Args:
        run_dir: v3 运行目录。
        result_id: 已执行且待放行的结果 ID。
        selection_contract: 当前问题预先定义的可比性合同。

    Returns:
        包含替换决定和当前 best 的登记结果。

    Raises:
        ContractError: 结果、合同或精确指标来源不合法。
    """
    validate_selection_contract(selection_contract)
    index = read_result_index(run_dir)
    result = next((item for item in index["results"] if item["result_id"] == result_id), None)
    if (
        result is None
        or not result["execution_valid"]
        or result.get("execution_mode", "production") != "production"
    ):
        raise ContractError("候选必须是已登记且 execution_valid=true 的结果")
    objective = selection_contract["objective"]
    metric = str(objective["metric"])
    exact = _exact_metric(result, run_dir, metric)
    key = selection_group_key(result["question_id"], selection_contract)
    registry = read_candidate_registry(run_dir)
    group = _find_group(registry, key)
    tolerance = float(objective["fine_tolerance"])
    direction = str(objective["direction"])
    incumbent = group.get("best_exact")
    incumbent_id = group.get("best_result_id")
    if incumbent is None:
        accepted = True
        decision = "established_initial_lower_bound"
    elif _better(exact, float(incumbent), direction, tolerance):
        accepted = True
        decision = "improved_verified_lower_bound"
    elif _worse(exact, float(incumbent), direction, tolerance):
        accepted = False
        decision = "below_best_verified_lower_bound"
    else:
        accepted = False
        decision = "no_objective_progress_above_lower_bound"
    observation = {
        "result_id": result_id,
        "exact": exact,
        "metric": metric,
        "accepted": accepted,
        "decision": decision,
        "recorded_at": utc_now(),
    }
    group["observations"].append(observation)
    if accepted:
        group["best_result_id"] = result_id
        group["best_exact"] = exact
        if incumbent_id and incumbent_id != result_id:
            for item in index["results"]:
                if item["result_id"] == incumbent_id:
                    item["status"] = "superseded"
                    break
        result["status"] = "current"
    else:
        result["status"] = "superseded"
    _synchronize_current_results(index, registry)
    _require_registry(registry, run_dir)
    require_result_index(index)
    atomic_json(run_dir / REGISTRY_PATH, registry)
    atomic_json(run_dir / "results" / "index.json", index)
    return {
        "accepted": accepted,
        "decision": decision,
        "best_result_id": group.get("best_result_id"),
        "best_exact": group.get("best_exact"),
        "group": key,
    }
