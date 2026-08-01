"""推导和复验实验阶段的结构化视觉输出要求。

该模块只提供纯函数和不可变描述，不写运行目录，也不拥有论文阶段的控制权。
视觉字段仍由题目作者声明，但不同题型必须至少覆盖能支撑其结构论证的语义组。
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


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
    """根据建模单元推导最低语义组，不读取外部文件。"""
    unit_kind = str(unit.get("unit_kind", unit.get("mode", "")))
    groups = _GROUPS.get(unit_kind, ())
    obligations = {"mathematical_object", "mechanism", "boundary"} if groups else set()
    if unit.get("core_question") is True:
        obligations.add("decision")
    validation = unit.get("validation")
    if isinstance(validation, dict) and isinstance(validation.get("robustness"), dict):
        if validation["robustness"].get("required") is True:
            obligations.add("uncertainty")
    return VisualRequirement(unit_kind, frozenset(obligations), groups)


def validate_declared_visual_data(unit: dict[str, Any]) -> list[str]:
    """检查 ``required_data`` 是否覆盖题型最低语义组。"""
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
