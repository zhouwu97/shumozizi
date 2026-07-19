"""验证 P0a 语义契约的正反向 Schema 边界。"""

from __future__ import annotations

import copy
import unittest

from shumozizi.claims.evaluator import EVALUATOR_VERSION
from shumozizi.core.schema import validate_document

SHA = "a" * 64


def mechanism_signature() -> dict:
    """返回完整机制签名夹具。"""
    return {
        "decision_object": "选择每个时段的决策变量",
        "core_assumptions": ["组间存在异质性"],
        "relation_form": "非线性平滑关系",
        "uncertainty_treatment": "参数与观测误差联合传播",
        "decision_rule": "风险调整期望损失最小化",
        "expected_advantage": "降低小样本组偏差",
        "failure_boundary": "组间方差退化为零",
    }


def prediction(prediction_id: str, direction: str) -> dict:
    """返回带方向对应阈值的可检验预测。"""
    result = {
        "prediction_id": prediction_id,
        "metric": "validation_rmse",
        "expected_direction": direction,
    }
    if direction in {"increase", "decrease"}:
        result["minimum_effect"] = 0.05
    else:
        result["maximum_relative_loss"] = 0.03
    return result


def comparison_predicate(prediction_id: str, role: str = "required_support") -> dict:
    """返回结构化比较谓词。"""
    return {
        "prediction_id": prediction_id,
        "role": role,
        "metric": "validation_rmse",
        "relation": "relative_decrease_at_most",
        "threshold": 0.03,
        "unit": "dimensionless",
        "aggregation": "primary_result",
    }


def innovation_claim() -> dict:
    """返回候选路线中的完整创新主张。"""
    return {
        "claim_id": "IC-Q1-01",
        "claim": "风险调整机制改善验证集表现",
        "mechanism": "风险惩罚改变方案排序",
        "baseline_difference": "基线只最小化平均误差",
        "testable_predictions": [
            prediction("P-Q1-01", "decrease"),
            prediction("P-Q1-02", "not_decrease_beyond"),
        ],
        "falsified_if": ["验证误差未达到最低改善阈值"],
        "comparison_predicates": [comparison_predicate("P-Q1-01")],
        "required_experiment_roles": ["baseline", "primary", "ablation"],
        "paper_allowed_only_if_supported": True,
    }


def candidate() -> dict:
    """返回带 P0a 扩展字段的候选路线。"""
    return {
        "route_id": "route_a",
        "name": "风险调整路线",
        "problem_interpretation": "根据输入数据建立可复现的优化与验证模型。",
        "mathematical_nature": "约束优化",
        "baseline": "线性基线模型",
        "primary_model": "风险调整模型",
        "innovation": "加入风险惩罚机制",
        "validation": "比较、消融和边界测试",
        "computational_cost": "中等",
        "risks": ["数据规模不足"],
        "fallback": {
            "route_id": "route_b",
            "trigger_conditions": ["主模型在预算内无法收敛"],
        },
        "mechanism_signature": mechanism_signature(),
        "innovation_claims": [innovation_claim()],
        "minimal_probe_plan": {
            "purpose": "判断风险结构是否有必要",
            "compared_routes": ["route_a", "route_b"],
            "data_scope": "20% stratified sample",
            "budget_seconds": 120,
            "metrics": ["validation_rmse"],
            "selection_rule": "验证误差改善至少 5% 且总体误差不恶化超过 3%",
        },
    }


def route_candidates() -> dict:
    """返回扩展后的路线候选文档。"""
    second = copy.deepcopy(candidate())
    second["route_id"] = "route_b"
    second["name"] = "固定效应基线"
    return {
        "schema_name": "route_candidates",
        "schema_version": "2.0",
        "run_id": "semantic-test",
        "run_config_lock_sha256": SHA,
        "problem_summary": "这是一个用于验证语义契约的可复验数学建模问题摘要。",
        "ambiguities": [],
        "ambiguity_review": {"performed": True, "none_reason": "题面没有改变模型的实质歧义"},
        "material_ambiguities": [],
        "recommended_route_id": "route_a",
        "recommendation_reason": "机制签名完整且实验计划可验证。",
        "candidates": [candidate(), second],
    }


def route_lock() -> dict:
    """返回带结构化创新主张的路线锁。"""
    claim = innovation_claim()
    return {
        "schema_name": "route_lock",
        "schema_version": "2.0",
        "run_id": "semantic-test",
        "approved": True,
        "selected_route_id": "route_a",
        "run_config_lock_sha256": SHA,
        "route_candidates_sha256": SHA,
        "approval_receipt_sha256": SHA,
        "problem_interpretation": "根据输入数据建立可复现的优化与验证模型。",
        "primary_route": "风险调整模型",
        "fallback_route": "固定效应基线",
        "required_baselines": ["Q1-B0"],
        "innovation_claims": [
            {
                "claim_id": claim["claim_id"],
                "claim": claim["claim"],
                "mechanism": claim["mechanism"],
                "baseline_id": "Q1-B0",
                "baseline_difference": claim["baseline_difference"],
                "prediction_ids": ["P-Q1-01", "P-Q1-02"],
                "required_experiment_roles": ["baseline", "primary", "ablation"],
                "falsified_if": claim["falsified_if"],
                "paper_allowed_only_if_supported": True,
            }
        ],
        "validation": ["比较、消融和边界测试"],
        "resource_limits": {
            "max_main_experiment_cycles_per_question": 3,
            "max_web_searches": 5,
            "max_full_self_reviews": 1,
            "route_drift_budget_ratio": 0.3,
        },
        "approved_by": "human",
        "approved_at": "2026-07-19T00:00:00Z",
        "route_selection_mode": "direct",
        "mechanism_signature": mechanism_signature(),
    }


def experiment_plan() -> dict:
    """返回完整实验计划。"""
    return {
        "schema_name": "experiment_plan",
        "schema_version": "2.0",
        "run_id": "semantic-test",
        "experiment_id": "Q1-E1",
        "question_id": "Q1",
        "experiment_role": "primary",
        "hypothesis": "风险调整能改善验证集表现",
        "prediction_ids": ["P-Q1-01", "P-Q1-02"],
        "baseline_result_ids": ["Q1-B0"],
        "metrics": ["validation_rmse"],
        "comparison_rule": {
            "predicates": [comparison_predicate("P-Q1-01")],
            "supported_if": "all_required_predictions_pass",
            "partially_supported_if": "at_least_one_required_prediction_passes",
            "rejected_if": "any_falsification_condition_passes",
            "otherwise": "inconclusive",
        },
        "randomness_plan": {"applicable": False, "reason": "该实验使用确定性求解器"},
        "stop_rule": "达到预算或连续两次改进低于 0.5%",
        "expected_outputs": ["metrics.json", "comparison.csv"],
        "claim_ids": ["IC-Q1-01"],
        "route_lock_sha256": SHA,
    }


def claim_evidence(status: str = "supported") -> dict:
    """返回完整主张证据文档。"""
    return {
        "schema_name": "claim_evidence",
        "schema_version": "2.0",
        "run_id": "semantic-test",
        "evaluator_version": EVALUATOR_VERSION,
        "route_lock_sha256": SHA,
        "result_registry_sha256": SHA,
        "experiment_plan_sha256": SHA,
        "comparison_output_sha256": SHA,
        "stale": False,
        "claims": [
            {
                "claim_id": "IC-Q1-01",
                "status": status,
                "evidence_result_ids": ["Q1-B0", "Q1-P1"],
                "prediction_checks": [
                    {
                        "prediction_id": "P-Q1-01",
                        "role": "required_support",
                        "status": "passed",
                        "observed": 0.08,
                        "required": 0.05,
                    }
                ],
                "required_experiment_roles": ["baseline", "primary", "ablation"],
                "satisfied_experiment_roles": ["baseline", "primary", "ablation"],
                "missing_experiment_roles": [],
                "paper_permissions": {
                    "contribution_section": status == "supported",
                    "results_section": True,
                    "limitations_section": True,
                },
            }
        ],
    }


class SemanticSchemaTests(unittest.TestCase):
    """覆盖 P0a 新增契约的有效和拒绝分支。"""

    def assert_valid(self, document: dict, name: str) -> None:
        self.assertEqual([], validate_document(document, name))

    def assert_invalid(self, document: dict, name: str, field: str) -> None:
        errors = validate_document(document, name)
        self.assertTrue(errors)
        self.assertTrue(any(field in error for error in errors), errors)

    def test_extended_route_candidates_accepts_structured_semantics(self) -> None:
        self.assert_valid(route_candidates(), "route_candidates")

    def test_route_candidates_rejects_incomplete_mechanism_signature(self) -> None:
        document = route_candidates()
        del document["candidates"][0]["mechanism_signature"]["failure_boundary"]
        self.assert_invalid(document, "route_candidates", "failure_boundary")

    def test_extended_route_lock_accepts_direct_selection(self) -> None:
        self.assert_valid(route_lock(), "route_lock")

    def test_route_lock_rejects_probe_then_select(self) -> None:
        document = route_lock()
        document["route_selection_mode"] = "probe_then_select"
        self.assert_invalid(document, "route_lock", "route_selection_mode")

    def test_experiment_plan_accepts_deterministic_randomness_plan(self) -> None:
        self.assert_valid(experiment_plan(), "experiment_plan")

    def test_experiment_plan_rejects_applicable_randomness_without_seeds(self) -> None:
        document = experiment_plan()
        document["randomness_plan"] = {"applicable": True}
        self.assert_invalid(document, "experiment_plan", "seeds")

    def test_experiment_plan_rejects_predicate_without_role(self) -> None:
        document = experiment_plan()
        del document["comparison_rule"]["predicates"][0]["role"]
        self.assert_invalid(document, "experiment_plan", "role")

    def test_claim_evidence_accepts_supported_claim(self) -> None:
        self.assert_valid(claim_evidence(), "claim_evidence")

    def test_claim_evidence_accepts_claimability_none_without_claims(self) -> None:
        document = claim_evidence()
        document["claimability"] = "none"
        document["claimability_reason"] = "本问题不声明方法创新"
        document["claims"] = []
        self.assert_valid(document, "claim_evidence")

    def test_claim_evidence_rejects_stale_without_reason(self) -> None:
        document = claim_evidence()
        document["stale"] = True
        self.assert_invalid(document, "claim_evidence", "stale_reason")

    def test_legacy_sealed_result_with_innovation_claims_remains_readable(self) -> None:
        """旧 Run 的 innovation_claims 封存格式仍应通过兼容读取。"""
        document = {
            "schema_name": "sealed_result",
            "schema_version": "2.0",
            "result_id": "Q1-P1",
            "run_id": "legacy-run",
            "question_id": "Q1",
            "cycle": "primary",
            "execution_record_id": "exec-Q1-P1",
            "metrics": [
                {
                    "name": "rmse",
                    "metric_spec_id": "metric-Q1-P1",
                    "value": 1.0,
                    "unit": "dimensionless",
                }
            ],
            "conclusion": "旧格式结果。",
            "constraint_checks": [{"passed": True}],
            "validation_checks": [{"passed": True}],
            "baseline_result_id": "Q1-B0",
            "innovation_claims": [],
            "paper_allowed": True,
            "accepted_by": "legacy-agent",
            "accepted_at": "2026-07-19T00:00:00Z",
        }

        self.assert_valid(document, "sealed_result")


if __name__ == "__main__":
    unittest.main()
