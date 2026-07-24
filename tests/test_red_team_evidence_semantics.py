"""验证红队证据的科学结论能够约束审核标签。"""

from __future__ import annotations

import pytest

from shumozizi.core.io import ContractError
from shumozizi.simple.review import (
    _summarize_evidence_verdicts,
    _validate_action_activation_evidence,
    _validate_geometry_continuous_evidence,
)


def _action_evidence(**changes: object) -> dict[str, object]:
    """构造覆盖第 4、5 枚动作的合格插入挑战。"""
    payload: dict[str, object] = {
        "question_id": "Q5",
        "allowed_action_count": 15,
        "incumbent_active_count": 3,
        "unused_actions_exist": True,
        "discrete_activation_variables": ["z_1", "z_2", "z_3"],
        "variable_bounds_sha256": "a" * 64,
        "exact_scorer_sha256": "b" * 64,
        "objective_direction": "maximize",
        "improvement_tolerance": 1e-6,
        "evaluation_budget": 100,
        "seeds": [11, 29],
        "first_feasible_evaluation": 3,
        "feasible_rate": 0.8,
        "proxy_exact_max_error": 0.01,
        "best_so_far": [10.0, 10.0],
        "coverage_method": "insertion_local_optimization",
        "coverage_details": {},
        "rounds": [
            {"active_count": 4, "evaluation_count": 40, "best_exact": 10.0},
            {"active_count": 5, "evaluation_count": 40, "best_exact": 10.0},
        ],
        "consecutive_no_improvement_rounds": 2,
        "incumbent_exact": 10.0,
        "challenge_best_exact": 10.0,
        "verdict": "incumbent_competitive",
    }
    payload.update(changes)
    return payload


@pytest.mark.parametrize(
    ("kind", "evidence", "expected_reason"),
    [
        (
            "independent-recompute",
            {"verdict": "inconsistent"},
            "independent-recompute:inconsistent",
        ),
        (
            "counterexample",
            {"verdict": "counterexample_found"},
            "counterexample:counterexample_found",
        ),
        (
            "small-enumeration",
            {"mismatches": 1, "verdict": "inconsistent"},
            "small-enumeration:mismatches=1",
        ),
        (
            "property-test",
            {"failures": 1, "verdict": "fail"},
            "property-test:failures=1",
        ),
    ],
)
def test_negative_evidence_blocks_pass(
    kind: str, evidence: dict[str, object], expected_reason: str
) -> None:
    """任何已复验的科学反例都不能被人工 pass 标签覆盖。"""
    assessment = _summarize_evidence_verdicts([(kind, evidence)])

    assert not assessment["pass_allowed"]
    assert expected_reason in assessment["blocking_reasons"]


@pytest.mark.parametrize("verdict", ["incumbent_not_competitive", "inconclusive"])
def test_unsuccessful_search_challenge_blocks_competition_promotion(verdict: str) -> None:
    """挑战失败或无结论时不能把 incumbent 抬为 qualified/strong。"""
    assessment = _summarize_evidence_verdicts(
        [("search-challenge", {"verdict": verdict})]
    )

    assert not assessment["promotion_allowed"]
    assert f"search-challenge:{verdict}" in assessment["promotion_blockers"]


def test_consistent_checks_allow_pass_and_promotion() -> None:
    """一致复算、零失败性质测试和成功挑战应保留放行能力。"""
    assessment = _summarize_evidence_verdicts(
        [
            ("independent-recompute", {"verdict": "consistent"}),
            ("property-test", {"failures": 0, "verdict": "pass"}),
            ("search-challenge", {"verdict": "incumbent_competitive"}),
        ]
    )

    assert assessment["pass_allowed"]
    assert assessment["promotion_allowed"]


def test_two_nonimproving_insertion_rounds_cover_unused_action_risk() -> None:
    """连续两轮新增动作无增益时，才可支持当前激活数量的竞争力。"""
    _validate_action_activation_evidence(_action_evidence())


def test_fourth_action_improvement_revokes_incumbent() -> None:
    """第 4 枚动作产生 exact 改善时，旧 incumbent 必须判为不竞争。"""
    evidence = _action_evidence(
        best_so_far=[10.0, 10.5],
        challenge_best_exact=10.5,
        consecutive_no_improvement_rounds=0,
        verdict="incumbent_not_competitive",
    )
    _validate_action_activation_evidence(evidence)
    assessment = _summarize_evidence_verdicts(
        [("action-activation-challenge", evidence)]
    )

    assert not assessment["pass_allowed"]


def test_incomplete_insertion_search_cannot_claim_competitive() -> None:
    """只试第 4 枚或未连续稳定时不能声称完整动作空间已覆盖。"""
    evidence = _action_evidence(
        rounds=[{"active_count": 4, "evaluation_count": 40, "best_exact": 10.0}],
        consecutive_no_improvement_rounds=1,
    )

    with pytest.raises(ContractError, match="verdict"):
        _validate_action_activation_evidence(evidence)


def test_geometry_continuous_validation_requires_distinct_sampled_name() -> None:
    """连续量与采样近似同名会隐藏离散化误差，必须拒绝。"""
    evidence = {
        "question_id": "Q1",
        "continuous_quantity": "minimum_margin",
        "sampled_approximation": "minimum_margin",
        "verification_method": "interval_verification",
        "discretization_error_bound": None,
        "critical_cases": {
            "left_endpoint": True,
            "right_endpoint": True,
            "tangent": True,
            "degenerate": True,
            "outside_segment": True,
        },
        "verdict": "pass",
    }

    with pytest.raises(ContractError, match="不同变量名"):
        _validate_geometry_continuous_evidence(evidence)


def test_missing_geometry_boundary_case_blocks_pass() -> None:
    """随机内部点不能替代左右端点和退化反例的完整覆盖。"""
    evidence = {
        "question_id": "Q1",
        "continuous_quantity": "minimum_margin_continuous",
        "sampled_approximation": "minimum_margin_grid",
        "verification_method": "continuous_1d_optimization",
        "discretization_error_bound": None,
        "critical_cases": {
            "left_endpoint": True,
            "right_endpoint": False,
            "tangent": True,
            "degenerate": True,
            "outside_segment": True,
        },
        "verdict": "fail",
    }
    _validate_geometry_continuous_evidence(evidence)
    assessment = _summarize_evidence_verdicts(
        [("geometry-continuous-validation", evidence)]
    )
    assert not assessment["pass_allowed"]
