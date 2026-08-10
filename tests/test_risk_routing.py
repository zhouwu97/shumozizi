"""验证前置风险攻击、双速分流和主张边界不会污染正式答案链。"""

from __future__ import annotations

import pytest

from shumozizi.core.io import ContractError
from shumozizi.simple.modeling_units import _derive_v14_non_search_outcome
from shumozizi.simple.risk_routing import (
    default_risk_package,
    validate_risk_assessment,
    validate_risk_package,
)


def _result(
    result_id: str,
    *,
    mode: str,
    created_at: str,
    metrics: dict[str, object] | None = None,
) -> dict[str, object]:
    """构造只含风险路由所需事实的执行结果。"""
    return {
        "result_id": result_id,
        "question_id": "Q1",
        "execution_mode": mode,
        "execution_valid": True,
        "created_at": created_at,
        "metrics": metrics or {},
    }


def _assessment(
    package: dict[str, object], *, boundary_label: str = "conditional_on_assumption"
) -> dict[str, object]:
    """为风险包构造已触发的真实攻击结论。"""
    checks = package["checks"]
    assert isinstance(checks, list)
    outcomes = [
        {
            "check_id": check["check_id"],
            "outcome": "triggered" if index == 0 else "clear",
            "finding": "最低成本攻击发现当前路线不能保持无条件唯一性。",
            "result_ids": [f"risk-{index}"],
        }
        for index, check in enumerate(checks)
        if isinstance(check, dict)
    ]
    boundary: dict[str, object] = {
        "label": boundary_label,
        "statement": "在固定结构假设下报告条件结果，不把补偿带误写成唯一真值。",
    }
    if boundary_label == "conditional_on_assumption":
        boundary["assumptions"] = ["目标参数与 nuisance 参数的补偿关系保持在已检验范围内。"]
    if boundary_label == "sensitivity_only":
        boundary["range_result_ids"] = ["risk-0", "primary"]
    return {
        "outcomes": outcomes,
        "completed_before_first_production": True,
        "route": "deepening",
        "route_rationale": "攻击触发后需要增加 profile 或联合验证，不能按快速路线结束。",
        "claim_boundary": boundary,
    }


def test_core_optimization_template_includes_scorer_and_decomposition_attacks() -> None:
    """多主体优化题的自动模板必须先攻击 scorer 与分解语义。"""
    raw = default_risk_package(
        question_id="Q1",
        core_question=True,
        unit_kind="optimization",
        semantic_risk_signals={"multiple_entities", "decompose_then_combine"},
    )
    package = validate_risk_package(
        raw,
        label="Q1.risk_package",
        core_question=True,
        unit_kind="optimization",
        semantic_risk_signals={"multiple_entities", "decompose_then_combine"},
    )

    assert package is not None
    assert {item["kind"] for item in package["checks"]} == {
        "scorer_preflight",
        "decomposition_counterexample",
    }
    assert len(package["fast_entry_conditions"]) == 4


def test_triggered_risk_cannot_keep_an_unconditional_claim() -> None:
    """攻击推翻唯一性时，无法用无条件标签把问题藏进论文局限性。"""
    raw = default_risk_package(
        question_id="Q1",
        core_question=False,
        unit_kind="evaluation",
        semantic_risk_signals=set(),
    )
    package = validate_risk_package(
        raw,
        label="Q1.risk_package",
        core_question=False,
        unit_kind="evaluation",
        semantic_risk_signals=set(),
    )
    assert package is not None
    results = {
        "risk-0": _result(
            "risk-0", mode="exploration", created_at="2026-01-01T00:00:00Z"
        ),
        "primary": _result(
            "primary", mode="production", created_at="2026-01-01T00:01:00Z"
        ),
    }

    with pytest.raises(ContractError, match="条件结果或范围"):
        validate_risk_assessment(
            _assessment(raw, boundary_label="unconditional"),
            package=package,
            results=results,
            question_id="Q1",
            label="Q1.actual.risk_assessment",
            require_before_first_production=True,
        )


def test_risk_boundary_is_attached_to_the_formal_answer() -> None:
    """条件边界必须自动随 objective_answer 进入 answer-map 与 Author Pass。"""
    raw = default_risk_package(
        question_id="Q1",
        core_question=False,
        unit_kind="evaluation",
        semantic_risk_signals=set(),
    )
    package = validate_risk_package(
        raw,
        label="Q1.risk_package",
        core_question=False,
        unit_kind="evaluation",
        semantic_risk_signals=set(),
    )
    assert package is not None
    results = {
        "risk-0": _result(
            "risk-0", mode="exploration", created_at="2026-01-01T00:00:00Z"
        ),
        "primary": _result(
            "primary",
            mode="production",
            created_at="2026-01-01T00:01:00Z",
            metrics={
                "objective": 1.0,
                "feasible": True,
                "hard_constraints_passed": True,
            },
        ),
    }
    plan = {
        "unit_id": "Q1-evaluation",
        "question_id": "Q1",
        "unit_kind": "evaluation",
        "primary_method": "fixed-evaluator",
        "exact_metric": "objective",
        "endpoint_resolution_status": "determined",
        "risk_package": package,
    }
    actual = {
        "primary_result_id": "primary",
        "risk_assessment": _assessment(raw),
    }

    outcome = _derive_v14_non_search_outcome(actual, plan, results)

    objective = outcome["objective_answer"]
    assert isinstance(objective, dict)
    assert objective["claim_boundary"]["label"] == "conditional_on_assumption"
    assert any("条件或范围" in warning for warning in outcome["warnings"])
