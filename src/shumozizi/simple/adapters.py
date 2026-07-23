"""执行并复验每题可插拔的候选、精评和搜索审计 adapter。"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path, PurePath
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    load_json,
    resolve_inside,
    sha256_file,
)
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.simple.execution import execute_simple_experiment
from shumozizi.simple.results import read_result_index, safe_result_id
from shumozizi.simple.selection import validate_selection_contract
from shumozizi.simple.state import read_simple_state, utc_now

VERIFICATION_DIRECTORY = Path("results/verification")
STAGE_NAMES = ("candidate_generator", "exact_scorer", "search_auditor")
ADAPTER_SCHEMA_VERSION = "1.2"
_FORBIDDEN_GENERATOR_FIELDS = {
    "feasible",
    "exact_recomputed",
    "search_adequacy",
    "problem_effectiveness",
    "quality",
    "metrics",
}


def _schema(name: str) -> dict[str, Any]:
    """读取 adapter 协议的 JSON Schema。

    Args:
        name: Schema 文件名。

    Returns:
        已解析的 Schema。
    """
    root = resolve_repo_root(Path(__file__))
    return load_json(root / "schemas" / name)


def _require_schema(payload: dict[str, Any], name: str, label: str) -> None:
    """确保对象满足对应的协议 Schema。

    Args:
        payload: 待校验对象。
        name: Schema 文件名。
        label: 用于错误信息的对象名称。

    Raises:
        ContractError: Schema 校验失败。
    """
    validator = Draft202012Validator(_schema(name), format_checker=FormatChecker())
    errors = [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    ]
    if errors:
        raise ContractError(f"{label} 不符合协议: {'; '.join(errors)}")


def _safe_argument(value: Any) -> str:
    """校验 adapter 的单个无 Shell 参数。

    Args:
        value: 原始参数。

    Returns:
        已校验的参数字符串。

    Raises:
        ContractError: 参数可能引入路径越界或 Shell 组合语义。
    """
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ContractError("adapter 参数必须是非空字符串")
    if any(token in value for token in ("|", ">", "<", "&&", ";")):
        raise ContractError("adapter 参数不允许 Shell 组合语义")
    path = PurePath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ContractError("adapter 参数不允许绝对路径或目录穿越")
    return value


def _stage_contract(
    contract: dict[str, Any],
    stage_name: str,
    *,
    run_dir: Path | None,
) -> dict[str, Any]:
    """读取并约束一个受控 adapter 阶段。

    Args:
        contract: 已通过基础 Schema 的 adapter 合同。
        stage_name: 三段式协议中的阶段名称。

    Returns:
        已校验的阶段合同。

    Raises:
        ContractError: 阶段字段或其路径不符合受控执行边界。
    """
    stages = contract["stages"]
    stage = stages[stage_name]
    implementation = stage["implementation_file"]
    supplied_sources = stage.get("source_files")
    output_file = stage["output_file"]
    arguments = stage["arguments"]
    input_files = stage["input_files"]
    artifact_files = stage.get("artifact_files", [])
    if not isinstance(implementation, str) or not implementation.startswith("code/"):
        raise ContractError(f"{stage_name} 实现必须位于 code/ 下")
    if Path(implementation).suffix.lower() != ".py":
        raise ContractError(f"{stage_name} 仅允许运行受控 Python 实现")
    _safe_argument(implementation)
    if not isinstance(output_file, str) or not output_file.startswith("results/raw/"):
        raise ContractError(f"{stage_name} 输出必须位于 results/raw/ 下")
    if Path(output_file).suffix.lower() != ".json":
        raise ContractError(f"{stage_name} 输出必须为 JSON")
    _safe_argument(output_file)
    if not isinstance(arguments, list) or not all(isinstance(item, str) for item in arguments):
        raise ContractError(f"{stage_name} arguments 必须是字符串数组")
    if not isinstance(input_files, list) or not all(isinstance(item, str) for item in input_files):
        raise ContractError(f"{stage_name} input_files 必须是字符串数组")
    if not isinstance(artifact_files, list) or not all(
        isinstance(item, str) for item in artifact_files
    ):
        raise ContractError(f"{stage_name} artifact_files 必须是字符串数组")
    if stage_name != "exact_scorer" and artifact_files:
        raise ContractError("只有 exact_scorer 可以登记受控附属产物")
    normalized_artifacts = [_safe_argument(item) for item in artifact_files]
    if len(set(normalized_artifacts)) != len(normalized_artifacts):
        raise ContractError(f"{stage_name} artifact_files 不能重复")
    for artifact in normalized_artifacts:
        if not artifact.startswith("results/raw/") or Path(artifact).suffix.lower() != ".json":
            raise ContractError("exact_scorer 附属产物必须是 results/raw/ 下的 JSON")
        if artifact == output_file:
            raise ContractError("exact_scorer 附属产物不能与精确评分输出重复")
    normalized_inputs = [_safe_argument(item) for item in input_files]
    source_schema_version = contract["schema_version"]
    if source_schema_version == "1.1":
        if not isinstance(supplied_sources, list) or not all(
            isinstance(item, str) for item in supplied_sources
        ):
            raise ContractError(f"{stage_name} source_files 必须是字符串数组")
        normalized_sources = [_safe_argument(item) for item in supplied_sources]
        if len(set(normalized_sources)) != len(normalized_sources):
            raise ContractError(f"{stage_name} source_files 不能重复")
        for source_file in normalized_sources:
            if not source_file.startswith("code/") or Path(source_file).suffix.lower() != ".py":
                raise ContractError(f"{stage_name} source_files 只能登记 code/ 下的 Python 源码")
        if implementation not in normalized_inputs:
            raise ContractError(f"{stage_name} 必须把实现源码登记为输入")
        if implementation not in normalized_sources:
            raise ContractError(f"{stage_name} 必须把实现源码登记为 source_files")
        if not set(normalized_sources).issubset(normalized_inputs):
            raise ContractError(f"{stage_name} source_files 必须同时登记为输入")
    else:
        # v1.2 的作者只声明真正的数据输入；本地源码闭包由运行时计算并冻结。
        if supplied_sources is None:
            if run_dir is None:
                raise ContractError("v1.2 adapter 需要 run_dir 才能计算本地源码闭包")
            if any(item.startswith("code/") for item in normalized_inputs):
                raise ContractError(
                    f"{stage_name} v1.2 input_files 只能填写非源码输入；源码闭包由运行时生成"
                )
            normalized_sources = sorted(_local_source_closure(run_dir, implementation))
            normalized_inputs = list(dict.fromkeys([*normalized_sources, *normalized_inputs]))
        else:
            if not isinstance(supplied_sources, list) or not all(
                isinstance(item, str) for item in supplied_sources
            ):
                raise ContractError(f"{stage_name} source_files 必须是字符串数组")
            normalized_sources = [_safe_argument(item) for item in supplied_sources]
            if len(set(normalized_sources)) != len(normalized_sources):
                raise ContractError(f"{stage_name} source_files 不能重复")
            for source_file in normalized_sources:
                if not source_file.startswith("code/") or Path(source_file).suffix.lower() != ".py":
                    raise ContractError(f"{stage_name} source_files 只能登记 code/ 下的 Python 源码")
            if implementation not in normalized_sources:
                raise ContractError(f"{stage_name} 必须把实现源码登记为 source_files")
            if not set(normalized_sources).issubset(normalized_inputs):
                raise ContractError(f"{stage_name} source_files 必须同时登记为输入")
            non_source_code_inputs = set(normalized_inputs) - set(normalized_sources)
            if any(item.startswith("code/") for item in non_source_code_inputs):
                raise ContractError(
                    f"{stage_name} v1.2 input_files 不得伪装登记额外源码；请使用运行时闭包"
                )
            if run_dir is not None:
                discovered = _local_source_closure(run_dir, implementation)
                if set(normalized_sources) != discovered:
                    raise ContractError(
                        f"{stage_name} v1.2 运行时源码闭包与冻结 source_files 不一致"
                    )
    return {
        "implementation_file": implementation,
        "source_files": normalized_sources,
        "arguments": [_safe_argument(item) for item in arguments],
        "input_files": list(dict.fromkeys(normalized_inputs)),
        "output_file": output_file,
        "artifact_files": normalized_artifacts,
    }


def validate_adapter_contract(
    contract: dict[str, Any],
    *,
    run_dir: Path | None = None,
    require_current: bool = False,
) -> dict[str, Any]:
    """校验每题 adapter 合同及三段式输入输出依赖。

    Args:
        contract: adapter 作者提供的合同对象或历史冻结合同。
        run_dir: 新版作者合同计算源码闭包所需的当前运行目录。
        require_current: 为 ``True`` 时拒绝新建历史格式合同。

    Returns:
        深拷贝语义的规范化合同。

    Raises:
        ContractError: 合同缺少必要阶段、使用不受控路径或未声明原始输入依赖。
    """
    _require_schema(contract, "simple_validation_adapter.schema.json", "adapter 合同")
    if require_current and contract["schema_version"] != ADAPTER_SCHEMA_VERSION:
        raise ContractError(f"新建 adapter 合同必须使用 schema_version {ADAPTER_SCHEMA_VERSION}")
    selection_contract = contract["selection_contract"]
    if not isinstance(selection_contract, dict):
        raise ContractError("adapter 合同缺少 selection_contract")
    validate_selection_contract(selection_contract, require_coverage=True)
    stages = {
        name: _stage_contract(contract, name, run_dir=run_dir)
        for name in STAGE_NAMES
    }
    declared_outputs = [
        output
        for name in STAGE_NAMES
        for output in (stages[name]["output_file"], *stages[name]["artifact_files"])
    ]
    if len(set(declared_outputs)) != len(declared_outputs):
        raise ContractError("三段 adapter 的输出路径不能重复")
    generator_output = stages["candidate_generator"]["output_file"]
    exact_output = stages["exact_scorer"]["output_file"]
    if generator_output not in stages["exact_scorer"]["input_files"]:
        raise ContractError("exact_scorer 必须把原始 candidate pool 作为登记输入")
    auditor_inputs = stages["search_auditor"]["input_files"]
    if generator_output not in auditor_inputs or exact_output not in auditor_inputs:
        raise ContractError("search_auditor 必须读取原始 pool/trace 和 exact scorer 输出")
    implementations = [stages[name]["implementation_file"] for name in STAGE_NAMES]
    if len(set(implementations)) != len(implementations):
        raise ContractError("三段 adapter 必须使用彼此独立的实现文件")
    for index, first_stage in enumerate(STAGE_NAMES):
        first_sources = set(stages[first_stage]["source_files"])
        for second_stage in STAGE_NAMES[index + 1 :]:
            shared_sources = sorted(first_sources & set(stages[second_stage]["source_files"]))
            if shared_sources:
                raise ContractError(
                    "三段 adapter 不得共享本地 source_files: " + ", ".join(shared_sources)
                )
    normalized_selection = json.loads(json.dumps(selection_contract))
    normalized_selection["verification_adapter"] = {
        "adapter_id": str(contract["adapter_id"]),
        "adapter_version": str(contract["adapter_version"]),
    }
    validate_selection_contract(normalized_selection, require_coverage=True)
    return {
        "schema_version": str(contract["schema_version"]),
        "adapter_id": str(contract["adapter_id"]),
        "adapter_version": str(contract["adapter_version"]),
        "selection_contract": normalized_selection,
        "stages": stages,
    }


def _numeric(value: Any, label: str) -> float:
    """读取有限数值，排除布尔值和 NaN。

    Args:
        value: 待读取值。
        label: 错误信息中的字段名称。

    Returns:
        浮点数值。

    Raises:
        ContractError: 值不是有限数值。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{label} 必须是数值")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ContractError(f"{label} 必须是有限数值")
    return normalized


def _candidate_variables(selection_contract: dict[str, Any]) -> list[str]:
    """返回合同冻结的原始候选坐标名称。

    Args:
        selection_contract: 已校验的选择合同。

    Returns:
        有序原始候选坐标。
    """
    return list(selection_contract["coverage"]["candidate_variables"])


def _validate_candidate_generation(
    document: dict[str, Any],
    *,
    adapter_id: str,
    adapter_version: str,
    selection_contract: dict[str, Any],
) -> list[dict[str, Any]]:
    """验证生成器只提供原始候选、参数、代理值和完整轨迹。

    Args:
        document: candidate generator 输出。
        adapter_id: 合同中的 adapter 标识。
        adapter_version: 合同中的 adapter 版本。
        selection_contract: 已冻结的选择合同。

    Returns:
        已验证候选列表。

    Raises:
        ContractError: 输出混入质量结论、坐标投影或轨迹不完整。
    """
    expected_fields = {
        "schema_name",
        "adapter_id",
        "adapter_version",
        "candidate_variables",
        "candidates",
        "search_trace",
    }
    unexpected = set(document) - expected_fields
    if unexpected:
        raise ContractError(f"candidate_generator 输出包含未允许字段: {', '.join(sorted(unexpected))}")
    forbidden = set(document) & _FORBIDDEN_GENERATOR_FIELDS
    if forbidden:
        raise ContractError("candidate_generator 不得自证质量结论")
    if document.get("schema_name") != "candidate_generation":
        raise ContractError("candidate_generator 输出 schema_name 不匹配")
    if document.get("adapter_id") != adapter_id or document.get("adapter_version") != adapter_version:
        raise ContractError("candidate_generator adapter 版本不匹配")
    variables = _candidate_variables(selection_contract)
    if document.get("candidate_variables") != variables:
        raise ContractError("candidate_generator 原始坐标变量与合同不一致")
    candidates = document.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ContractError("candidate_generator 必须输出非空原始 candidate pool")
    candidate_ids: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ContractError("candidate pool 条目必须为对象")
        required = {"id", "coordinates", "parameters", "proxy_value", "role"}
        if set(candidate) != required:
            raise ContractError("candidate pool 条目只能包含 id、coordinates、parameters、proxy_value 和 role")
        identifier = candidate["id"]
        if not isinstance(identifier, str) or not identifier or identifier in candidate_ids:
            raise ContractError("candidate pool 的 id 必须唯一")
        candidate_ids.add(identifier)
        if candidate["role"] not in {"baseline", "warm_start", "search", "exploration"}:
            raise ContractError("candidate pool role 不合法")
        coordinates = candidate["coordinates"]
        parameters = candidate["parameters"]
        if not isinstance(coordinates, dict) or not isinstance(parameters, dict):
            raise ContractError("candidate pool 必须保留原始 coordinates 和 parameters")
        if set(coordinates) != set(variables) or set(parameters) != set(variables):
            raise ContractError("candidate pool 原始坐标不完整，不能用投影、平均或首值替代")
        for name in variables:
            coordinate = _numeric(coordinates[name], f"candidate.{identifier}.coordinates.{name}")
            parameter = _numeric(parameters[name], f"candidate.{identifier}.parameters.{name}")
            if coordinate != parameter:
                raise ContractError("candidate 的 parameters 必须保留与 coordinates 一致的原始标量")
        proxy_value = candidate["proxy_value"]
        if proxy_value is not None:
            _numeric(proxy_value, f"candidate.{identifier}.proxy_value")
    trace = document.get("search_trace")
    if not isinstance(trace, list) or not trace:
        raise ContractError("candidate_generator 必须输出完整 search_trace")
    traced_ids: set[str] = set()
    for event in trace:
        if not isinstance(event, dict):
            raise ContractError("search_trace 条目必须为对象")
        if not isinstance(event.get("step"), int) or event["step"] < 0:
            raise ContractError("search_trace.step 必须是非负整数")
        candidate_id = event.get("candidate_id")
        if candidate_id not in candidate_ids:
            raise ContractError("search_trace 包含未出现在原始 pool 的候选")
        if not isinstance(event.get("event"), str) or not event["event"]:
            raise ContractError("search_trace.event 必须是非空字符串")
        traced_ids.add(candidate_id)
    if traced_ids != candidate_ids:
        raise ContractError("search_trace 必须覆盖原始 candidate pool 的每个候选")
    return candidates


def recompute_joint_coverage(
    selection_contract: dict[str, Any], candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    """从原始坐标重算合同声明的占用网格联合覆盖。

    Args:
        selection_contract: 带变量域、分箱数和分组的选择合同。
        candidates: 经生成器结构校验的原始候选。

    Returns:
        覆盖是否通过、逐组占用单元数和联合覆盖率。

    Raises:
        ContractError: 合同或候选坐标无法支持原生联合覆盖计算。
    """
    validate_selection_contract(selection_contract, require_coverage=True)
    reports: list[dict[str, Any]] = []
    reasons: list[str] = []
    for group in selection_contract["coverage"]["groups"]:
        variables = group["variables"]
        bins = int(group["bins_per_variable"])
        bounds = group["bounds"]
        occupied: set[tuple[int, ...]] = set()
        for candidate in candidates:
            cell: list[int] = []
            for variable in variables:
                lower, upper = (float(item) for item in bounds[variable])
                value = _numeric(candidate["coordinates"][variable], f"coverage.{variable}")
                if value < lower or value > upper:
                    raise ContractError(f"candidate 坐标超出 coverage 合同边界: {variable}")
                ratio = (value - lower) / (upper - lower)
                cell.append(min(bins - 1, int(math.floor(ratio * bins))))
            occupied.add(tuple(cell))
        possible_cells = bins ** len(variables)
        joint_coverage = len(occupied) / possible_cells
        passed = joint_coverage >= float(group["minimum_joint_coverage"])
        report = {
            "id": group["id"],
            "variables": variables,
            "metric": "occupied_bins",
            "occupied_cells": len(occupied),
            "possible_cells": possible_cells,
            "joint_coverage": joint_coverage,
            "minimum_joint_coverage": float(group["minimum_joint_coverage"]),
            "passed": passed,
        }
        reports.append(report)
        if not passed:
            reasons.append(f"coverage_group_below_contract:{group['id']}")
    return {"passed": not reasons, "reasons": reasons, "group_reports": reports}


def _validate_exact_scores(
    document: dict[str, Any],
    *,
    candidates: list[dict[str, Any]],
    adapter_id: str,
    adapter_version: str,
    selection_contract: dict[str, Any],
) -> dict[str, Any]:
    """验证独立 scorer 针对原始 pool 重算全部候选。

    Args:
        document: exact scorer 输出。
        candidates: 已验证原始候选。
        adapter_id: 合同中的 adapter 标识。
        adapter_version: 合同中的 adapter 版本。
        selection_contract: 已冻结的选择合同。

    Returns:
        选中候选对应的精确评分。

    Raises:
        ContractError: scorer 没有完整重算候选、输出版本漂移或指标不一致。
    """
    required = {
        "schema_name",
        "adapter_id",
        "adapter_version",
        "candidate_scores",
        "selected_candidate_id",
        "metrics",
    }
    if set(document) != required:
        raise ContractError("exact_scorer 输出字段不符合独立精确评分协议")
    if document.get("schema_name") != "exact_scores":
        raise ContractError("exact_scorer 输出 schema_name 不匹配")
    if document.get("adapter_id") != adapter_id or document.get("adapter_version") != adapter_version:
        raise ContractError("exact_scorer adapter 版本不匹配")
    scores = document.get("candidate_scores")
    if not isinstance(scores, list) or not scores:
        raise ContractError("exact_scorer 必须输出每个原始候选的评分")
    expected_ids = {str(candidate["id"]) for candidate in candidates}
    score_map: dict[str, dict[str, Any]] = {}
    for score in scores:
        if not isinstance(score, dict) or set(score) != {
            "candidate_id",
            "feasible",
            "objective",
            "constraint_violations",
        }:
            raise ContractError("exact_scorer 候选评分字段不合法")
        candidate_id = score["candidate_id"]
        if not isinstance(candidate_id, str) or candidate_id in score_map:
            raise ContractError("exact_scorer candidate_id 必须唯一")
        if candidate_id not in expected_ids:
            raise ContractError("exact_scorer 评分包含 pool 外候选")
        if not isinstance(score["feasible"], bool):
            raise ContractError("exact_scorer feasible 必须为布尔值")
        _numeric(score["objective"], f"exact.{candidate_id}.objective")
        if not isinstance(score["constraint_violations"], list) or not all(
            isinstance(item, str) for item in score["constraint_violations"]
        ):
            raise ContractError("exact_scorer constraint_violations 必须是字符串数组")
        score_map[candidate_id] = score
    if set(score_map) != expected_ids:
        raise ContractError("exact_scorer 必须独立评分原始 pool 的所有候选")
    selected_id = document.get("selected_candidate_id")
    selected = score_map.get(selected_id) if isinstance(selected_id, str) else None
    if selected is None:
        raise ContractError("exact_scorer 选中候选不在评分结果中")
    if not selected["feasible"] or selected["constraint_violations"]:
        raise ContractError("exact_scorer 不能选择不可行候选")
    metric = selection_contract["objective"]["metric"]
    metrics = document.get("metrics")
    if not isinstance(metrics, dict) or metric not in metrics:
        raise ContractError("exact_scorer 输出缺少选择合同指定的精确指标")
    metric_value = _numeric(metrics[metric], f"metrics.{metric}")
    if metric_value != _numeric(selected["objective"], "selected objective"):
        raise ContractError("exact_scorer 指标必须等于选中候选的精确目标")
    return selected


def _top_indices(values: list[float], count: int, direction: str) -> set[int]:
    """按目标方向稳定选择前 k 个候选索引。"""
    reverse = direction == "maximize"
    ordering = sorted(enumerate(values), key=lambda item: (item[1], -item[0]), reverse=reverse)
    return {index for index, _ in ordering[:count]}


def _calibration_metrics(
    candidates: list[dict[str, Any]],
    exact_document: dict[str, Any],
    direction: str,
    top_k: int,
) -> dict[str, float]:
    """从 raw proxy 与 independent exact 分数重算决策相关基础指标。"""
    score_map = {
        score["candidate_id"]: _numeric(score["objective"], "exact objective")
        for score in exact_document["candidate_scores"]
    }
    if any(candidate["proxy_value"] is None for candidate in candidates):
        raise ContractError("search_auditor 的校准需要每个原始候选保留 proxy_value")
    exact = [score_map[candidate["id"]] for candidate in candidates]
    proxy = [_numeric(candidate["proxy_value"], "proxy_value") for candidate in candidates]
    effective_k = min(max(top_k, 1), len(candidates))
    exact_top = _top_indices(exact, effective_k, direction)
    proxy_top = _top_indices(proxy, effective_k, direction)
    top_k_recall = len(exact_top & proxy_top) / effective_k
    baseline_index = next(
        (index for index, item in enumerate(candidates) if item["role"] in {"baseline", "warm_start"}),
        0,
    )
    comparisons = [index for index in range(len(candidates)) if index != baseline_index]
    if not comparisons:
        agreement = 1.0
    else:
        baseline_exact = exact[baseline_index]
        baseline_proxy = proxy[baseline_index]
        pairs = [
            (
                value > baseline_exact if direction == "maximize" else value < baseline_exact,
                proxy[index] > baseline_proxy if direction == "maximize" else proxy[index] < baseline_proxy,
            )
            for index, value in ((index, exact[index]) for index in comparisons)
        ]
        agreement = sum(exact_improved == proxy_improved for exact_improved, proxy_improved in pairs) / len(pairs)
    return {
        "top_k_recall": top_k_recall,
        "improvement_sign_agreement": agreement,
    }


def _validate_audit(
    document: dict[str, Any],
    *,
    candidates: list[dict[str, Any]],
    exact_document: dict[str, Any],
    adapter_id: str,
    adapter_version: str,
    selection_contract: dict[str, Any],
) -> dict[str, Any]:
    """验证审计器基于原始 pool、trace 和 exact 输出给出可复验判断。

    Args:
        document: search auditor 输出。
        candidates: 原始候选。
        exact_document: 独立 exact scorer 输出。
        adapter_id: 合同中的 adapter 标识。
        adapter_version: 合同中的 adapter 版本。
        selection_contract: 已冻结的选择合同。

    Returns:
        通用层重算并复验后的审计摘要。

    Raises:
        ContractError: 覆盖、校准或 adapter 身份与原始产物不一致。
    """
    required = {
        "schema_name",
        "adapter_id",
        "adapter_version",
        "candidate_count",
        "exact_candidate_count",
        "coverage",
        "calibration",
        "challenge",
    }
    if set(document) != required:
        raise ContractError("search_auditor 输出字段不符合审计协议")
    if document.get("schema_name") != "search_audit":
        raise ContractError("search_auditor 输出 schema_name 不匹配")
    if document.get("adapter_id") != adapter_id or document.get("adapter_version") != adapter_version:
        raise ContractError("search_auditor adapter 版本不匹配")
    if document.get("candidate_count") != len(candidates):
        raise ContractError("search_auditor candidate_count 与原始 pool 不一致")
    if document.get("exact_candidate_count") != len(exact_document["candidate_scores"]):
        raise ContractError("search_auditor exact_candidate_count 与独立评分不一致")
    recomputed_coverage = recompute_joint_coverage(selection_contract, candidates)
    reported_coverage = document.get("coverage")
    if not isinstance(reported_coverage, dict):
        raise ContractError("search_auditor 缺少 coverage 审计")
    reported_groups = reported_coverage.get("group_reports")
    if not isinstance(reported_groups, list):
        raise ContractError("search_auditor coverage 缺少 group_reports")
    expected_reports = recomputed_coverage["group_reports"]
    if len(reported_groups) != len(expected_reports):
        raise ContractError("search_auditor coverage 分组数量不匹配")
    for reported, expected in zip(reported_groups, expected_reports, strict=True):
        if not isinstance(reported, dict):
            raise ContractError("search_auditor coverage 条目必须为对象")
        for key in ("id", "variables", "metric", "occupied_cells", "possible_cells"):
            if reported.get(key) != expected[key]:
                raise ContractError("search_auditor coverage 未从原始坐标正确重算")
        reported_value = _numeric(reported.get("joint_coverage"), "audit coverage")
        if not math.isclose(reported_value, float(expected["joint_coverage"]), rel_tol=0.0, abs_tol=1e-12):
            raise ContractError("search_auditor joint_coverage 与原始坐标重算不一致")
    calibration = document.get("calibration")
    if not isinstance(calibration, dict):
        raise ContractError("search_auditor 缺少 calibration")
    if calibration.get("status") not in {"passed", "failed"}:
        raise ContractError("search_auditor calibration.status 不合法")
    decision_metrics = calibration.get("decision_metrics")
    if not isinstance(decision_metrics, dict):
        raise ContractError("search_auditor calibration 缺少决策相关指标")
    required_metrics = {
        "top_k_recall",
        "improvement_sign_agreement",
        "boundary_high_value_error",
        "filtering_false_negative_rate",
    }
    if not required_metrics <= set(decision_metrics):
        raise ContractError("search_auditor calibration 缺少决策相关指标")
    for key in required_metrics:
        _numeric(decision_metrics[key], f"calibration.{key}")
    top_k = decision_metrics.get("top_k", 1)
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise ContractError("search_auditor calibration.top_k 必须为正整数")
    derived = _calibration_metrics(
        candidates,
        exact_document,
        str(selection_contract["objective"]["direction"]),
        top_k,
    )
    for key, expected in derived.items():
        actual = _numeric(decision_metrics[key], f"calibration.{key}")
        if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-12):
            raise ContractError(f"search_auditor {key} 未从 raw pool/exact 重新计算")
    errors = calibration.get("catastrophic_errors")
    if not isinstance(errors, list) or not all(isinstance(item, str) and item for item in errors):
        raise ContractError("search_auditor catastrophic_errors 必须是字符串数组")
    challenge = document.get("challenge")
    if not isinstance(challenge, dict) or not isinstance(challenge.get("outcome"), str):
        raise ContractError("search_auditor challenge 缺少 outcome")
    if challenge["outcome"] not in {
        "not_requested",
        "improved",
        "stability_confirmed",
        "uninformative_weaker",
        "model_or_scorer_semantic_error",
    }:
        raise ContractError("search_auditor challenge.outcome 不合法")
    return {
        "coverage": recomputed_coverage,
        "calibration_passed": calibration["status"] == "passed" and not errors,
        "calibration": calibration,
        "challenge": challenge,
    }


def _stage_result_id(result_id: str, stage_name: str) -> str:
    """返回阶段执行的稳定结果 ID。"""
    return result_id if stage_name == "exact_scorer" else f"{result_id}.{stage_name}"


def _controlled_command(implementation_file: str, arguments: list[str]) -> str:
    """构造只调用当前 Python 解释器和运行目录源码的命令。"""
    return subprocess.list2cmdline([sys.executable, implementation_file, *arguments])


def _existing_local_module_files(base: Path, parts: tuple[str, ...], code_root: Path) -> set[Path]:
    """解析一个 import 目标在运行目录 ``code/`` 下实际加载的源码。"""
    if not parts:
        return set()
    target = base.joinpath(*parts)
    candidates = [target.with_suffix(".py"), target / "__init__.py"]
    for index in range(1, len(parts)):
        candidates.append(base.joinpath(*parts[:index], "__init__.py"))
    resolved: set[Path] = set()
    for candidate in candidates:
        if not candidate.is_file():
            continue
        path = candidate.resolve()
        if path.is_relative_to(code_root):
            resolved.add(path)
    return resolved


def _local_import_files(source: Path, code_root: Path) -> set[Path]:
    """提取静态 import 中能够解析到当前 run 本地 ``code/`` 的文件。"""
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    except SyntaxError as exc:
        raise ContractError(f"adapter 源码无法解析: {source.name}: {exc.msg}") from exc
    imports: set[Path] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.update(
                    _existing_local_module_files(
                        code_root,
                        tuple(alias.name.split(".")),
                        code_root,
                    )
                )
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        base = code_root
        if node.level:
            base = source.parent
            for _ in range(node.level - 1):
                base = base.parent
        module_parts = tuple(node.module.split(".")) if node.module else ()
        if module_parts:
            imports.update(_existing_local_module_files(base, module_parts, code_root))
        for alias in node.names:
            if alias.name == "*":
                continue
            imports.update(
                _existing_local_module_files(
                    base,
                    (*module_parts, alias.name),
                    code_root,
                )
            )
    return imports


def _local_source_closure(run_dir: Path, implementation_file: str) -> set[str]:
    """递归计算入口源码经静态 import 可达的 run 内本地源码闭包。"""
    root = run_dir.resolve()
    code_root = (root / "code").resolve()
    entry = resolve_inside(root, implementation_file, must_exist=True)
    if not entry.is_relative_to(code_root):
        raise ContractError("adapter 实现源码必须位于当前 run 的 code/ 目录")
    pending = [entry]
    visited: set[Path] = set()
    while pending:
        source = pending.pop()
        if source in visited:
            continue
        visited.add(source)
        pending.extend(_local_import_files(source, code_root) - visited)
    return {path.relative_to(root).as_posix() for path in visited}


def _verify_declared_source_files(
    run_dir: Path,
    *,
    stage_name: str,
    stage: dict[str, Any],
) -> set[str]:
    """拒绝未登记或多登记的本地 adapter 源码依赖。"""
    declared = set(stage["source_files"])
    for relative in declared:
        resolve_inside(run_dir, relative, must_exist=True)
    discovered = _local_source_closure(run_dir, stage["implementation_file"])
    missing = sorted(discovered - declared)
    unexpected = sorted(declared - discovered)
    if missing:
        raise ContractError(
            f"{stage_name} 存在未登记的本地依赖 source_files: " + ", ".join(missing)
        )
    if unexpected:
        raise ContractError(
            f"{stage_name} source_files 包含未使用的本地源码: " + ", ".join(unexpected)
        )
    return discovered


def _run_stage(
    run_dir: Path,
    *,
    result_id: str,
    question_id: str,
    stage_name: str,
    stage: dict[str, Any],
) -> dict[str, Any]:
    """通过普通执行记录器运行一个已受控 adapter 阶段。"""
    implementation = resolve_inside(run_dir, stage["implementation_file"], must_exist=True)
    if implementation.suffix.lower() != ".py":
        raise ContractError("adapter 实现必须是 Python 文件")
    _verify_declared_source_files(run_dir, stage_name=stage_name, stage=stage)
    for relative in stage["input_files"]:
        resolve_inside(run_dir, relative, must_exist=True)
    command = _controlled_command(stage["implementation_file"], stage["arguments"])
    result = execute_simple_experiment(
        run_dir,
        result_id=_stage_result_id(result_id, stage_name),
        question_id=question_id,
        kind=f"adapter-{stage_name}",
        command=command,
        expected_outputs=[stage["output_file"], *stage["artifact_files"]],
        input_files=stage["input_files"],
        metrics_from=stage["output_file"] if stage_name == "exact_scorer" else None,
        require_fresh_outputs=True,
        provisional=True,
    )
    if not result["success"] or not isinstance(result["result"], dict):
        raise ContractError(f"adapter {stage_name} 执行失败: {result['error']}")
    return result["result"]


def _receipt_from_result(result: dict[str, Any], stage: dict[str, Any]) -> dict[str, Any]:
    """从已登记执行提取阶段 provenance 收据。"""
    implementation = stage["implementation_file"]
    output_file = stage["output_file"]
    implementation_hash = result.get("input_hashes", {}).get(implementation)
    output_hash = result.get("output_hashes", {}).get(output_file)
    if not isinstance(implementation_hash, str) or not isinstance(output_hash, str):
        raise ContractError("adapter 阶段缺少源码或输出哈希")
    source_hashes: dict[str, str] = {}
    for source_file in stage["source_files"]:
        source_hash = result.get("input_hashes", {}).get(source_file)
        if not isinstance(source_hash, str):
            raise ContractError("adapter 阶段缺少登记源码哈希")
        source_hashes[source_file] = source_hash
    artifact_hashes: dict[str, str] = {}
    for artifact in stage["artifact_files"]:
        artifact_hash = result.get("output_hashes", {}).get(artifact)
        if not isinstance(artifact_hash, str):
            raise ContractError("exact_scorer 附属产物缺少输出哈希")
        artifact_hashes[artifact] = artifact_hash
    command = str(result["command"])
    return {
        "result_id": result["result_id"],
        "implementation_file": implementation,
        "implementation_sha256": implementation_hash,
        "source_files": list(stage["source_files"]),
        "source_hashes": source_hashes,
        "command": command,
        "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
        "input_hashes": result["input_hashes"],
        "output_file": output_file,
        "output_sha256": output_hash,
        "artifact_hashes": artifact_hashes,
    }


def run_verification_protocol(
    run_dir: Path,
    *,
    result_id: str,
    question_id: str,
    contract: dict[str, Any],
) -> dict[str, Any]:
    """执行候选生成、独立精评和独立搜索审计，并冻结其 provenance。

    Args:
        run_dir: 当前 v3 运行目录。
        result_id: 选中 exact 结果的 ID。
        question_id: 当前子问题 ID。
        contract: 每题 adapter 合同。

    Returns:
        成功状态、各阶段结果和供质量层使用的 verification 引用。

    Raises:
        ContractError: adapter 合同、受控执行或任一产物不满足协议。
    """
    identifier = safe_result_id(result_id)
    root = run_dir.resolve()
    state = read_simple_state(root)
    normalized = validate_adapter_contract(contract, run_dir=root, require_current=True)
    verification_dir = root / VERIFICATION_DIRECTORY
    verification_dir.mkdir(parents=True, exist_ok=True)
    contract_file = VERIFICATION_DIRECTORY / f"{identifier}.adapter.json"
    atomic_json(root / contract_file, normalized)
    contract_hash = sha256_file(root / contract_file)

    generator_result = _run_stage(
        root,
        result_id=identifier,
        question_id=question_id,
        stage_name="candidate_generator",
        stage=normalized["stages"]["candidate_generator"],
    )
    generator_document = load_json(
        resolve_inside(root, normalized["stages"]["candidate_generator"]["output_file"], must_exist=True)
    )
    candidates = _validate_candidate_generation(
        generator_document,
        adapter_id=normalized["adapter_id"],
        adapter_version=normalized["adapter_version"],
        selection_contract=normalized["selection_contract"],
    )

    exact_result = _run_stage(
        root,
        result_id=identifier,
        question_id=question_id,
        stage_name="exact_scorer",
        stage=normalized["stages"]["exact_scorer"],
    )
    exact_document = load_json(
        resolve_inside(root, normalized["stages"]["exact_scorer"]["output_file"], must_exist=True)
    )
    selected = _validate_exact_scores(
        exact_document,
        candidates=candidates,
        adapter_id=normalized["adapter_id"],
        adapter_version=normalized["adapter_version"],
        selection_contract=normalized["selection_contract"],
    )

    audit_result = _run_stage(
        root,
        result_id=identifier,
        question_id=question_id,
        stage_name="search_auditor",
        stage=normalized["stages"]["search_auditor"],
    )
    audit_document = load_json(
        resolve_inside(root, normalized["stages"]["search_auditor"]["output_file"], must_exist=True)
    )
    audit = _validate_audit(
        audit_document,
        candidates=candidates,
        exact_document=exact_document,
        adapter_id=normalized["adapter_id"],
        adapter_version=normalized["adapter_version"],
        selection_contract=normalized["selection_contract"],
    )
    stage_results = {
        "candidate_generator": generator_result,
        "exact_scorer": exact_result,
        "search_auditor": audit_result,
    }
    receipts = {
        stage_name: _receipt_from_result(stage_results[stage_name], normalized["stages"][stage_name])
        for stage_name in STAGE_NAMES
    }
    implementation_hashes = {receipt["implementation_sha256"] for receipt in receipts.values()}
    if len(implementation_hashes) != len(STAGE_NAMES):
        raise ContractError("三段 adapter 实现源码哈希必须独立")
    receipt = {
        "schema_version": ADAPTER_SCHEMA_VERSION,
        "run_id": root.name,
        "result_id": identifier,
        "question_id": question_id,
        "execution_mode": state["execution_mode"],
        "adapter": {
            "adapter_id": normalized["adapter_id"],
            "adapter_version": normalized["adapter_version"],
            "contract_file": contract_file.as_posix(),
            "contract_sha256": contract_hash,
        },
        "stages": receipts,
        "created_at": utc_now(),
    }
    _require_schema(receipt, "simple_verification_protocol.schema.json", "verification 收据")
    receipt_file = VERIFICATION_DIRECTORY / f"{identifier}.json"
    atomic_json(root / receipt_file, receipt)
    return {
        "success": True,
        "candidate_result_id": generator_result["result_id"],
        "exact_result_id": exact_result["result_id"],
        "audit_result_id": audit_result["result_id"],
        "selected_candidate_id": selected["candidate_id"],
        "exact_artifact_files": list(receipts["exact_scorer"]["artifact_hashes"]),
        "audit": audit,
        "verification": {
            "protocol_file": receipt_file.as_posix(),
            "protocol_sha256": sha256_file(root / receipt_file),
        },
    }


def _verification_reference(reference: dict[str, Any]) -> tuple[str, str]:
    """读取质量层对 verification 收据的路径和哈希引用。"""
    file_name = reference.get("protocol_file")
    expected_hash = reference.get("protocol_sha256")
    if not isinstance(file_name, str) or not file_name.startswith("results/verification/"):
        raise ContractError("verification 必须引用 results/verification/ 下的收据")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise ContractError("verification 缺少 protocol_sha256")
    return file_name, expected_hash


def _verify_stage_receipt(
    run_dir: Path,
    *,
    stage_name: str,
    stage_receipt: dict[str, Any],
    stage_contract: dict[str, Any],
    result_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """复验阶段的受控命令、源码、输入与输出没有漂移。"""
    result_id = stage_receipt["result_id"]
    result = result_map.get(result_id)
    if result is None or not result.get("execution_valid"):
        raise ContractError(f"{stage_name} 缺少 execution_valid 的登记执行")
    if stage_receipt["implementation_file"] != stage_contract["implementation_file"]:
        raise ContractError(f"{stage_name} adapter 实现路径漂移")
    if stage_receipt["source_files"] != stage_contract["source_files"]:
        raise ContractError(f"{stage_name} adapter source_files 路径漂移")
    source_hashes = stage_receipt["source_hashes"]
    if not isinstance(source_hashes, dict) or set(source_hashes) != set(
        stage_contract["source_files"]
    ):
        raise ContractError(f"{stage_name} adapter source_files 哈希登记不一致")
    _verify_declared_source_files(run_dir, stage_name=stage_name, stage=stage_contract)
    if stage_receipt["output_file"] != stage_contract["output_file"]:
        raise ContractError(f"{stage_name} adapter 输出路径漂移")
    command = stage_receipt["command"]
    expected_command = _controlled_command(
        stage_contract["implementation_file"], stage_contract["arguments"]
    )
    if command != expected_command or result.get("command") != expected_command:
        raise ContractError(f"{stage_name} adapter 命令不受控或已漂移")
    command_hash = hashlib.sha256(expected_command.encode("utf-8")).hexdigest()
    if stage_receipt["command_sha256"] != command_hash:
        raise ContractError(f"{stage_name} adapter 命令哈希不一致")
    for relative, expected_hash in stage_receipt["input_hashes"].items():
        if result.get("input_hashes", {}).get(relative) != expected_hash:
            raise ContractError(f"{stage_name} adapter 登记输入哈希不一致")
        actual = sha256_file(resolve_inside(run_dir, relative, must_exist=True))
        if actual != expected_hash:
            raise ContractError(f"{stage_name} adapter 输入已漂移: {relative}")
    implementation = stage_contract["implementation_file"]
    if stage_receipt["implementation_sha256"] != stage_receipt["input_hashes"].get(implementation):
        raise ContractError(f"{stage_name} adapter 源码哈希不一致")
    for source_file, source_hash in source_hashes.items():
        if source_hash != stage_receipt["input_hashes"].get(source_file):
            raise ContractError(f"{stage_name} adapter 源码收据哈希不一致")
    output = stage_contract["output_file"]
    output_hash = stage_receipt["output_sha256"]
    if result.get("output_hashes", {}).get(output) != output_hash:
        raise ContractError(f"{stage_name} adapter 输出未绑定登记执行")
    if sha256_file(resolve_inside(run_dir, output, must_exist=True)) != output_hash:
        raise ContractError(f"{stage_name} adapter 输出已漂移")
    artifact_hashes = stage_receipt.get("artifact_hashes")
    expected_artifacts = stage_contract["artifact_files"]
    if not isinstance(artifact_hashes, dict) or set(artifact_hashes) != set(expected_artifacts):
        raise ContractError(f"{stage_name} adapter 附属产物登记不一致")
    for artifact in expected_artifacts:
        artifact_hash = artifact_hashes.get(artifact)
        if not isinstance(artifact_hash, str):
            raise ContractError(f"{stage_name} adapter 附属产物哈希不合法")
        if result.get("output_hashes", {}).get(artifact) != artifact_hash:
            raise ContractError(f"{stage_name} adapter 附属产物未绑定登记执行")
        if sha256_file(resolve_inside(run_dir, artifact, must_exist=True)) != artifact_hash:
            raise ContractError(f"{stage_name} adapter 附属产物已漂移: {artifact}")
    return result


def verify_verification_protocol(run_dir: Path, reference: dict[str, Any]) -> dict[str, Any]:
    """重新验证 adapter 收据及其原始候选、精评和审计产物。

    Args:
        run_dir: 当前 v3 运行目录。
        reference: 质量层保存的收据路径和哈希。

    Returns:
        放行所需的可行性、精评、充分性和 provenance 摘要。

    Raises:
        ContractError: 任一路径、命令、哈希、版本或 adapter 产物发生漂移。
    """
    root = run_dir.resolve()
    file_name, expected_hash = _verification_reference(reference)
    receipt_path = resolve_inside(root, file_name, must_exist=True)
    if sha256_file(receipt_path) != expected_hash:
        raise ContractError("verification 收据哈希已漂移")
    receipt = load_json(receipt_path)
    _require_schema(receipt, "simple_verification_protocol.schema.json", "verification 收据")
    if receipt["run_id"] != root.name:
        raise ContractError("verification 收据 run_id 不匹配")
    if receipt["execution_mode"] not in {"production", "exploration"}:
        raise ContractError("verification 收据 execution_mode 不合法")
    contract_path = resolve_inside(root, receipt["adapter"]["contract_file"], must_exist=True)
    if sha256_file(contract_path) != receipt["adapter"]["contract_sha256"]:
        raise ContractError("adapter 合同哈希已漂移")
    contract = validate_adapter_contract(load_json(contract_path), run_dir=root)
    if (
        contract["adapter_id"] != receipt["adapter"]["adapter_id"]
        or contract["adapter_version"] != receipt["adapter"]["adapter_version"]
    ):
        raise ContractError("adapter 合同身份或版本不一致")
    index = read_result_index(root)
    result_map = {item["result_id"]: item for item in index["results"]}
    stages = {
        name: _verify_stage_receipt(
            root,
            stage_name=name,
            stage_receipt=receipt["stages"][name],
            stage_contract=contract["stages"][name],
            result_map=result_map,
        )
        for name in STAGE_NAMES
    }
    source_hashes = {receipt["stages"][name]["implementation_sha256"] for name in STAGE_NAMES}
    if len(source_hashes) != len(STAGE_NAMES):
        raise ContractError("adapter 三段源码不独立")
    generator_document = load_json(
        resolve_inside(root, contract["stages"]["candidate_generator"]["output_file"], must_exist=True)
    )
    candidates = _validate_candidate_generation(
        generator_document,
        adapter_id=contract["adapter_id"],
        adapter_version=contract["adapter_version"],
        selection_contract=contract["selection_contract"],
    )
    exact_document = load_json(
        resolve_inside(root, contract["stages"]["exact_scorer"]["output_file"], must_exist=True)
    )
    selected = _validate_exact_scores(
        exact_document,
        candidates=candidates,
        adapter_id=contract["adapter_id"],
        adapter_version=contract["adapter_version"],
        selection_contract=contract["selection_contract"],
    )
    audit_document = load_json(
        resolve_inside(root, contract["stages"]["search_auditor"]["output_file"], must_exist=True)
    )
    audit = _validate_audit(
        audit_document,
        candidates=candidates,
        exact_document=exact_document,
        adapter_id=contract["adapter_id"],
        adapter_version=contract["adapter_version"],
        selection_contract=contract["selection_contract"],
    )
    exact_result = stages["exact_scorer"]
    if exact_result["result_id"] != receipt["result_id"]:
        raise ContractError("verification exact_scorer 必须绑定质量申请的 result_id")
    if exact_result.get("question_id") != receipt["question_id"]:
        raise ContractError("verification exact_scorer question_id 不匹配")
    if exact_result.get("execution_mode", "production") != receipt["execution_mode"]:
        raise ContractError("verification exact_scorer execution_mode 不匹配")
    metric = contract["selection_contract"]["objective"]["metric"]
    if exact_result.get("metrics", {}).get(metric) != selected["objective"]:
        raise ContractError("登记 exact 指标与 scorer 选中候选不一致")
    return {
        "result_id": receipt["result_id"],
        "question_id": receipt["question_id"],
        "execution_mode": receipt["execution_mode"],
        "selection_contract": contract["selection_contract"],
        "adapter": receipt["adapter"],
        "feasibility_valid": True,
        "exact_recomputed": True,
        "search_adequacy": "passed" if audit["coverage"]["passed"] and audit["calibration_passed"] else "failed",
        "problem_effectiveness": "progressed",
        "coverage": audit["coverage"],
        "calibration": audit["calibration"],
        "challenge": audit["challenge"],
        "stage_result_ids": {name: stages[name]["result_id"] for name in STAGE_NAMES},
    }
