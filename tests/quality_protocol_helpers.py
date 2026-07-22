"""构造 v2 质量协议测试所需的可复验执行证据。"""

from __future__ import annotations

from typing import Any


def standard_selection_contract() -> dict[str, Any]:
    """返回最小但完整的加性目标选择合同。"""
    return {
        "objective": {
            "metric": "objective",
            "direction": "maximize",
            "objective_version": "test-objective-v1",
            "scorer_version": "test-scorer-v1",
            "constraint_version": "test-constraint-v1",
            "semantics": "additive",
            "fine_tolerance": 0.0,
        },
        "coverage": {
            "groups": [
                {
                    "id": "decision",
                    "variables": ["decision"],
                    "minimum_joint_coverage": 1.0,
                }
            ]
        },
        "required_evidence": ["coverage", "objective_semantics"],
    }


def standard_quality_document(
    objective: float,
    *,
    search_adequacy: str = "passed",
    problem_effectiveness: str = "progressed",
) -> dict[str, Any]:
    """返回由测试执行输出承载的质量证据字段。"""
    return {
        "feasible": True,
        "exact_recomputed": True,
        "search_adequacy": search_adequacy,
        "problem_effectiveness": problem_effectiveness,
        "coverage": {
            "group_reports": [
                {
                    "id": "decision",
                    "variables": ["decision"],
                    "joint_coverage": 1.0,
                }
            ]
        },
        "objective_semantics": {
            "surrogate": "additive_sum",
            "calibration": "additive_sum",
            "exact": "additive_sum",
            "selection": "additive_sum",
            "entity_marginal_gains": [objective],
        },
    }


def evidence_backed_assessment(
    result_id: str,
    output_file: str,
    *,
    search_adequacy: str = "passed",
    problem_effectiveness: str = "progressed",
) -> dict[str, Any]:
    """构造由已登记 JSON 输出复验的 accepted 申请。"""
    def reference(path: str, expected: object) -> dict[str, object]:
        return {
            "result_id": result_id,
            "file": output_file,
            "json_path": path,
            "expected": expected,
        }

    return {
        "result_role": "accepted",
        "selection_contract": standard_selection_contract(),
        "evidence": {
            "feasibility": reference("quality.feasible", True),
            "exact_recomputed": reference("quality.exact_recomputed", True),
            "search_adequacy": reference(
                "quality.search_adequacy", search_adequacy
            ),
            "problem_effectiveness": reference(
                "quality.problem_effectiveness", problem_effectiveness
            ),
            "coverage": reference("quality.coverage", None),
            "objective_semantics": reference("quality.objective_semantics", None),
        },
        "reasons": ["test_evidence_chain"],
    }
