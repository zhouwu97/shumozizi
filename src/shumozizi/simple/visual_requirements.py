"""推导和复验实验阶段的结构化视觉输出要求。

该模块只提供纯函数和不可变描述，不写运行目录，也不拥有论文阶段的控制权。
视觉字段仍由题目作者声明，但不同题型必须至少覆盖能支撑其结构论证的语义组。
v3.4 起同时按 ``mathematical_object`` 检查对象级最低结构字段：空间、网络、
概率转变、整数可行域等对象必须在实验阶段保存可复验的结构数据，而不是只保存
最终标量后到论文阶段临时拼图。
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

# 首批支持的数学对象枚举（7.2）。对象名不写具体题目，只描述模型对象本身。
MATHEMATICAL_OBJECTS = frozenset(
    {
        "spatial_geometry",
        "periodic_spatial_geometry",
        "contact_network",
        "periodic_contact_network",
        "geometric_oracle_comparison",
        "probability_transition",
        "uncertainty_threshold",
        "integer_feasible_region",
        "pareto_cost_reliability",
        "search_stability",
        "implementation_agreement",
        "shared_model_pipeline",
    }
)

# 论证角色：决定图在论证中的职责，不单独决定图种。
ARGUMENT_ROLES = frozenset(
    {
        "model_understanding",
        "decisive_evidence",
        "mechanism",
        "boundary",
        "tradeoff",
        "stability",
        "insight",
    }
)

# 对象级最低结构字段（7.4）：每个对象至少保存一组可复验结构数据。
# 每个语义组对应一个别名集合；required_data 命中任一别名即视为覆盖该组。
_OBJECT_GROUPS: dict[str, tuple[tuple[str, frozenset[str]], ...]] = {
    "spatial_geometry": (
        (
            "object_coordinates",
            frozenset({"coordinates", "coords", "positions", "starts", "ends", "particles", "segments"}),
        ),
        (
            "domain_boundary",
            frozenset({"boundary", "box", "bounds", "domain", "half_box", "domain_bounds"}),
        ),
    ),
    "periodic_spatial_geometry": (
        (
            "object_coordinates",
            frozenset({"coordinates", "coords", "positions", "starts", "ends", "particles", "segments"}),
        ),
        (
            "domain_boundary",
            frozenset({"boundary", "box", "bounds", "domain", "half_box", "domain_bounds"}),
        ),
        (
            "wrapped_fragments",
            frozenset({"wrapped_fragments", "fragments", "wrapped", "wrapped_segments", "wrapped_fragment"}),
        ),
        (
            "identity_map",
            frozenset({"identity_map", "identity", "identity_pairs", "wrapped_identity", "identity_map_json"}),
        ),
    ),
    "contact_network": (
        (
            "nodes",
            frozenset({"nodes", "particles", "vertices", "segments"}),
        ),
        (
            "edges",
            frozenset({"edges", "contact_edges", "contacts", "edge_list"}),
        ),
        (
            "electrodes",
            frozenset({"electrodes", "electrode_edges", "left_electrode", "right_electrode", "electrode"}),
        ),
        (
            "conductive_path_or_cut",
            frozenset({"conductive_path", "backbone", "conductive", "path", "cutset", "conductive_backbone"}),
        ),
    ),
    "periodic_contact_network": (
        (
            "nodes",
            frozenset({"nodes", "particles", "vertices", "segments"}),
        ),
        (
            "edges",
            frozenset({"edges", "contact_edges", "contacts", "edge_list"}),
        ),
        (
            "electrodes",
            frozenset({"electrodes", "electrode_edges", "left_electrode", "right_electrode", "electrode"}),
        ),
        (
            "conductive_path_or_cut",
            frozenset({"conductive_path", "backbone", "conductive", "path", "cutset", "conductive_backbone"}),
        ),
        (
            "identity_map",
            frozenset({"identity_map", "identity", "identity_pairs", "wrapped_identity", "identity_map_json"}),
        ),
    ),
    "geometric_oracle_comparison": (
        (
            "candidate_pairs",
            frozenset({"candidate_pairs", "pairs", "candidates", "edges", "candidate_edges"}),
        ),
        (
            "exact_distance",
            frozenset({"exact_distance", "solid_distance", "flat_distance", "distance"}),
        ),
        (
            "capsule_distance",
            frozenset({"capsule_distance", "axis_distance", "centerline", "centerline_distance"}),
        ),
    ),
    "probability_transition": (
        (
            "x_values",
            frozenset({"x", "n", "points", "volume_fraction", "counts", "abscissa"}),
        ),
        (
            "successes",
            frozenset({"successes", "success_count", "conductive_count", "success_counts"}),
        ),
        (
            "trials",
            frozenset({"trials", "sample_size", "n_trials", "repeats", "total"}),
        ),
        (
            "interval",
            frozenset({"wilson_interval", "wilson_low", "wilson_high", "interval", "confidence_interval", "ci"}),
        ),
        (
            "threshold",
            frozenset({"threshold", "target", "p0", "critical", "reliability_target"}),
        ),
    ),
    "uncertainty_threshold": (
        (
            "x_values",
            frozenset({"x", "n", "points", "counts", "abscissa"}),
        ),
        (
            "interval_low",
            frozenset({"wilson_low", "interval_low", "lower_bound", "low", "lb"}),
        ),
        (
            "threshold",
            frozenset({"threshold", "target", "p0", "critical", "reliability_target"}),
        ),
    ),
    "integer_feasible_region": (
        (
            "lattice_points",
            frozenset({"lattice_points", "grid", "points", "candidates", "lattice", "grid_points"}),
        ),
        (
            "feasible_mask",
            frozenset({"feasible_mask", "feasible", "feasible_marks", "is_feasible", "feasibility"}),
        ),
        (
            "constraint_margins",
            frozenset({"constraint_margins", "margins", "slacks", "margin", "constraint_slacks"}),
        ),
        (
            "costs",
            frozenset({"costs", "cost", "cost_yuan", "total_cost"}),
        ),
        (
            "selected_point",
            frozenset({"selected_point", "selected", "best", "answer", "optimal", "official"}),
        ),
    ),
    "pareto_cost_reliability": (
        (
            "candidate_points",
            frozenset({"candidate_points", "candidates", "points", "frontier", "solutions"}),
        ),
        (
            "dominance",
            frozenset({"dominance", "dominates", "pareto", "nondominated"}),
        ),
        (
            "formal_region",
            frozenset({"formal_region", "formal", "official", "formal_domain"}),
        ),
        (
            "sensitivity_region",
            frozenset({"sensitivity_region", "sensitivity", "zero_allowed", "domain_out", "sensitivity_domain"}),
        ),
    ),
    "search_stability": (
        (
            "seeds",
            frozenset({"seeds", "seed", "random_streams", "streams", "stream_ids"}),
        ),
        (
            "budget_or_samples",
            frozenset({"budget", "samples", "sample_size", "trials", "budget_or_samples", "repeats"}),
        ),
        (
            "quantile_bands",
            frozenset({"quantile_bands", "bands", "envelope", "percentiles", "quantiles", "band"}),
        ),
        (
            "stopping_point",
            frozenset({"stopping_point", "stop", "converged_at", "stopping", "stop_sample"}),
        ),
    ),
    "implementation_agreement": (
        (
            "classifications",
            frozenset({"classifications", "labels", "classification", "decisions"}),
        ),
        (
            "differences",
            frozenset({"differences", "diff", "disagreements", "deviation", "mismatches"}),
        ),
        (
            "critical_recheck",
            frozenset({"critical_point_recheck", "recheck", "critical", "critical_recheck"}),
        ),
    ),
    "shared_model_pipeline": (
        (
            "stages",
            frozenset({"stages", "nodes", "steps", "blocks"}),
        ),
        (
            "relations",
            frozenset({"relations", "edges", "links", "connections"}),
        ),
    ),
}

# 对象级最低字段组名集合，供单元级联合检查使用。
_OBJECT_GROUP_NAMES = frozenset(
    group_name
    for groups in _OBJECT_GROUPS.values()
    for group_name, _ in groups
)

# 空间、集合、网络、场、轨迹、决策面、可行域、区间或不确定性对象必须保存
# 结构化视觉输出，不能以"只解析标量"为由豁免。
NON_WAIVABLE_OBJECTS = frozenset(MATHEMATICAL_OBJECTS)


@dataclass(frozen=True)
class VisualRequirement:
    """一个建模单元的最低视觉数据语义合同。"""

    unit_kind: str
    obligations: frozenset[str]
    required_data_groups: tuple[tuple[str, frozenset[str]], ...]


_GROUPS: dict[str, tuple[tuple[str, frozenset[str]], ...]] = {
    "optimization": (
        (
            "structure",
            frozenset(
                {
                    "candidate_points",
                    "solution_set",
                    "search_trace",
                    "parameter_grid",
                    "routes",
                    "assignments",
                    "schedule",
                    "shift_intervals",
                    "intervals",
                    "days",
                    "hourly_arrivals",
                }
            ),
        ),
        (
            "objective",
            frozenset(
                {
                    "objective_values",
                    "scores",
                    "losses",
                    "objective",
                    "concurrent_workers",
                    "resource_allocation",
                    "daily_coverage",
                    "monthly_workers",
                    "hourly_processing",
                    "hourly_capacity",
                }
            ),
        ),
        (
            "constraints",
            frozenset(
                {
                    "feasible_mask",
                    "constraint_slacks",
                    "active_constraints",
                    "boundary",
                    "inventory",
                    "coverage",
                    "daily_demand",
                    "bottlenecks",
                    "audit",
                    "early_deadline",
                    "low_productivity_workers",
                }
            ),
        ),
    ),
    "simulation": (
        (
            "time",
            frozenset({"time", "time_grid", "timestamps"}),
        ),
        (
            "state",
            frozenset({
                "state_trajectory",
                "state_trajectories",
                "field_snapshots",
                "trajectory",
                "snapshots",
            }),
        ),
        (
            "events_or_control",
            frozenset({"events", "critical_events", "control_trajectory", "controls", "control"}),
        ),
    ),
    "data_modeling": (
        (
            "observed",
            frozenset({"observed", "observations", "actual", "targets", "data_distribution", "groups"}),
        ),
        (
            "predicted",
            frozenset({"predicted", "predictions", "fitted", "embedding", "cluster_labels"}),
        ),
        (
            "diagnostic",
            frozenset(
                {
                    "residuals",
                    "calibration",
                    "uncertainty",
                    "group_labels",
                    "scenario_distribution",
                    "bootstrap_quantiles",
                }
            ),
        ),
    ),
    "coordination": (
        (
            "assignment",
            frozenset({"assignments", "routes", "resource_allocation", "worker_day_matrix", "schedule"}),
        ),
        (
            "timing",
            frozenset({"intervals", "schedule", "event_times", "active_windows", "rest_patterns"}),
        ),
        (
            "objective",
            frozenset({"objective_values", "objective", "daily_coverage", "monthly_workers"}),
        ),
        (
            "constraints",
            frozenset({"constraint_slacks", "bottlenecks", "active_constraints", "daily_demand", "audit"}),
        ),
    ),
}


def derive_visual_requirements(unit: dict[str, Any]) -> VisualRequirement:
    """根据建模单元推导最低语义组，不读取外部文件。

    单元声明了数学对象时按对象级最低结构字段检查（7.4，对象比题型更精确）；
    未声明对象时回退到题型分组。
    """
    unit_kind = str(unit.get("unit_kind", unit.get("mode", "")))
    if declared_mathematical_objects(unit):
        groups = _object_groups(unit)
    else:
        groups = _GROUPS.get(unit_kind, ())
    obligations = {"mathematical_object", "mechanism", "boundary"} if groups else set()
    if unit.get("core_question") is True:
        obligations.add("decision")
    validation = unit.get("validation")
    if isinstance(validation, dict) and isinstance(validation.get("robustness"), dict):
        if validation["robustness"].get("required") is True:
            obligations.add("uncertainty")
    return VisualRequirement(unit_kind, frozenset(obligations), groups)


def _object_groups(unit: dict[str, Any]) -> tuple[tuple[str, frozenset[str]], ...]:
    """收集单元声明数学对象对应的最低结构字段组。"""
    groups: list[tuple[str, frozenset[str]]] = []
    seen: set[str] = set()
    for mathematical_object in sorted(declared_mathematical_objects(unit)):
        if mathematical_object not in MATHEMATICAL_OBJECTS:
            continue
        for name, aliases in _OBJECT_GROUPS.get(mathematical_object, ()):
            if name in seen:
                continue
            seen.add(name)
            groups.append((name, aliases))
    return tuple(groups)


def validate_declared_visual_data(unit: dict[str, Any]) -> list[str]:
    """检查 ``required_data`` 是否覆盖题型最低语义组与对象级最低结构字段。"""
    requirement = derive_visual_requirements(unit)
    if not requirement.required_data_groups:
        return []
    declared = {
        str(field).casefold()
        for output in unit.get("visual_outputs", [])
        if isinstance(output, dict)
        for field in output.get("required_data", [])
    }
    errors: list[str] = []
    for group_name, aliases in requirement.required_data_groups:
        if not declared.intersection({alias.casefold() for alias in aliases}):
            errors.append(
                f"{unit.get('question_id', unit.get('unit_id', '<unknown>'))}.visual_outputs "
                f"缺少最低视觉数据组 {group_name}"
            )
    return errors


def declared_mathematical_objects(unit: dict[str, Any]) -> frozenset[str]:
    """收集单元声明的数学对象：单元级字段与每个 visual_output 的对象字段。"""
    objects = {
        str(item)
        for item in unit.get("mathematical_objects", [])
        if isinstance(item, str) and item.strip()
    }
    objects.update(
        str(raw.get("mathematical_object", "")).strip()
        for raw in unit.get("visual_outputs", [])
        if isinstance(raw, dict)
        if str(raw.get("mathematical_object", "")).strip()
    )
    return frozenset(objects)


def validate_object_visual_data(unit: dict[str, Any]) -> list[str]:
    """按数学对象检查最低结构字段；对象必须对应真实可绘制的结构数据。

    每个声明了数学对象的 visual_output 至少覆盖该对象的一张最低字段组
    （7.4）。声明了多个对象时允许拆到不同 output，但单元级联合仍须覆盖
    每个对象的全部最低组。
    """
    errors: list[str] = []
    unit_objects = declared_mathematical_objects(unit)
    unknown = unit_objects - MATHEMATICAL_OBJECTS
    if unknown:
        errors.append(
            f"{unit.get('question_id', unit.get('unit_id', '<unknown>'))}.visual_outputs "
            f"包含未登记数学对象: {', '.join(sorted(unknown))}"
        )
    outputs = [
        raw
        for raw in unit.get("visual_outputs", [])
        if isinstance(raw, dict) and raw.get("required_data")
    ]
    declared = {
        str(field).casefold()
        for raw in outputs
        for field in raw.get("required_data", [])
    }
    for mathematical_object in sorted(unit_objects & MATHEMATICAL_OBJECTS):
        groups = _OBJECT_GROUPS.get(mathematical_object, ())
        for group_name, aliases in groups:
            if not declared.intersection({alias.casefold() for alias in aliases}):
                errors.append(
                    f"{unit.get('question_id', unit.get('unit_id', '<unknown>'))}."
                    f"visual_outputs 的数学对象 {mathematical_object} "
                    f"缺少最低结构字段组 {group_name}"
                )
    return errors


def _merge_groups(
    base: tuple[tuple[str, frozenset[str]], ...],
    extra: tuple[tuple[str, frozenset[str]], ...],
) -> tuple[tuple[str, frozenset[str]], ...]:
    """合并两组语义组；同名组按别名并集处理，避免重复报错。"""
    merged: dict[str, frozenset[str]] = {}
    for name, aliases in (*base, *extra):
        merged[name] = merged.get(name, frozenset()) | aliases
    return tuple(merged.items())


def _walk_fields(value: object, key: str) -> Iterable[object]:
    """递归查找 JSON 对象中的字段，允许结构数据按实体分组保存。"""
    if isinstance(value, dict):
        for name, child in value.items():
            if name == key:
                yield child
            yield from _walk_fields(child, key)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_fields(child, key)


def _is_non_empty_structure(value: object) -> bool:
    return isinstance(value, (list, dict)) and bool(value)


def _finite_numbers(value: object) -> bool:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, dict):
        return all(_finite_numbers(child) for child in value.values())
    if isinstance(value, list):
        return all(_finite_numbers(child) for child in value)
    return False


def validate_visual_document(
    document: dict[str, Any],
    required_data: Iterable[str],
    requirement: VisualRequirement,
) -> list[str]:
    """复验真实视觉 JSON 的字段、结构和有限数值。"""
    errors: list[str] = []
    fields = [str(field) for field in required_data]
    values_by_field: dict[str, list[object]] = {}
    all_values: list[object] = []
    for field in fields:
        values = list(_walk_fields(document, field))
        values_by_field[field] = values
        if not values:
            errors.append(f"缺少绘图字段: {field}")
            continue
        all_values.extend(values)
        if all(isinstance(value, (list, dict)) for value in values) and not any(
            _is_non_empty_structure(value) for value in values
        ):
            errors.append(f"绘图字段 {field} 没有非空结构数据")
        if not all(_finite_numbers(value) for value in values):
            errors.append(f"绘图字段 {field} 含非有限数值")

    if all_values and not any(_is_non_empty_structure(value) for value in all_values):
        errors.append("绘图数据只有标量或空结构，没有可复验的非空结构")

    for group_name, aliases in requirement.required_data_groups:
        group_values = [
            value
            for field, values in values_by_field.items()
            if field.casefold() in {alias.casefold() for alias in aliases}
            for value in values
        ]
        if group_values and not any(_is_non_empty_structure(value) for value in group_values):
            errors.append(f"绘图数据组 {group_name} 没有非空结构数据")
    return errors


def suggest_figure_compositions(
    obligations: Iterable[str],
    information_structure: str | None = None,
    available_visual_outputs: Iterable[str] = (),
) -> dict[str, Any]:
    """返回多面板构图建议；只读 advisory，不生成图计划或文件。"""
    values = {str(item) for item in obligations}
    panels: list[dict[str, str]] = []
    if "mathematical_object" in values:
        panels.append({"panel": "A", "role": "mathematical_object"})
    if "mechanism" in values:
        panels.append({"panel": "B", "role": "mechanism"})
    if "boundary" in values:
        panels.append({"panel": "C", "role": "boundary"})
    if "decision" in values or "comparison" in values:
        panels.append({"panel": "D", "role": "decision"})
    return {
        "advisory_only": True,
        "information_structure": information_structure,
        "available_visual_outputs": sorted({str(item) for item in available_visual_outputs}),
        "visual_archetype": (
            "multi_panel_evidence_chain" if len(panels) >= 3 else "route_score_comparison"
        ),
        "panels": panels,
    }
