"""验证实验视觉证据合同只约束可复验结构，不替代论文图计划。"""

from __future__ import annotations

import math
from pathlib import Path

from shumozizi.simple.visual_requirements import (
    derive_visual_requirements,
    suggest_figure_compositions,
    validate_declared_visual_data,
    validate_visual_document,
)


def _visual_output(*required_data: str) -> list[dict[str, object]]:
    """构造只用于语义合同测试的视觉输出声明。"""
    return [{"required_data": list(required_data)}]


def test_optimization_rejects_final_scalar_only_declaration() -> None:
    """优化题不能只声明最终目标值而遗漏结构、目标轨迹与约束边界。"""
    unit = {
        "question_id": "Q1",
        "unit_kind": "optimization",
        "visual_outputs": _visual_output("best_value"),
    }

    errors = validate_declared_visual_data(unit)

    assert any("structure" in error for error in errors)
    assert any("objective" in error for error in errors)
    assert any("constraints" in error for error in errors)


def test_held_out_declarations_cover_minimum_semantic_groups() -> None:
    """辽宁 B 题三问的事前字段声明应覆盖各自最低语义组。"""
    units = [
        {
            "question_id": "Q1",
            "unit_kind": "optimization",
            "visual_outputs": _visual_output(
                "hourly_arrivals",
                "hourly_processing",
                "inventory",
                "concurrent_workers",
                "shift_intervals",
            ),
        },
        {
            "question_id": "Q2",
            "unit_kind": "optimization",
            "visual_outputs": _visual_output(
                "early_deadline",
                "hourly_capacity",
                "low_productivity_workers",
                "inventory",
                "shift_intervals",
            ),
        },
        {
            "question_id": "Q3",
            "unit_kind": "coordination",
            "visual_outputs": _visual_output(
                "worker_day_matrix",
                "daily_demand",
                "daily_coverage",
                "rest_patterns",
                "active_windows",
            ),
        },
    ]

    assert [validate_declared_visual_data(unit) for unit in units] == [[], [], []]


def test_visual_document_rejects_final_scalar_only() -> None:
    """真实 JSON 只有最终标量时不能充当可绘图的实验结构。"""
    requirement = derive_visual_requirements({"unit_kind": "optimization"})

    errors = validate_visual_document(
        {"objective": 12.0},
        ["objective"],
        requirement,
    )

    assert any("只有标量" in error for error in errors)


def test_visual_document_rejects_empty_and_non_finite_structures() -> None:
    """空数组及 NaN、Infinity 会破坏后续绘图和独立复验。"""
    requirement = derive_visual_requirements({"unit_kind": "optimization"})
    document = {
        "shift_intervals": [],
        "objective_values": [1.0, math.nan],
        "constraint_slacks": [0.0, math.inf],
    }

    errors = validate_visual_document(
        document,
        ["shift_intervals", "objective_values", "constraint_slacks"],
        requirement,
    )

    assert any("shift_intervals 没有非空结构数据" in error for error in errors)
    assert any("objective_values 含非有限数值" in error for error in errors)
    assert any("constraint_slacks 含非有限数值" in error for error in errors)


def test_composition_suggestion_is_advisory_and_has_no_side_effect(
    tmp_path: Path,
) -> None:
    """多面板建议只提供构图候选，不写文件也不拥有阶段控制权。"""
    suggestion = suggest_figure_compositions(
        {"mathematical_object", "mechanism", "boundary", "decision"},
        information_structure="time",
        available_visual_outputs={"Q1-flow"},
    )

    assert suggestion["advisory_only"] is True
    assert suggestion["visual_archetype"] == "multi_panel_evidence_chain"
    assert [panel["panel"] for panel in suggestion["panels"]] == ["A", "B", "C", "D"]
    assert list(tmp_path.iterdir()) == []
