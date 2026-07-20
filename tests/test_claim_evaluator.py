"""验证 P0b 主张评估只消费 accepted 结果和结构化谓词。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shumozizi.claims.evaluator import evaluate_claim_documents, evaluate_claims
from tests.test_semantic_schemas import experiment_plan, route_lock


def registry_row(result_id: str, cycle: str, status: str = "accepted") -> dict:
    """返回最小合法结果注册表条目。"""
    return {
        "result_id": result_id,
        "question_id": "Q1",
        "cycle": cycle,
        "status": status,
        "paper_allowed": status == "accepted",
        "execution_record_id": f"exec-{result_id}",
        "metric_spec_ids": [f"metric-{result_id}"],
        "sealed_result_path": f"results/sealed/{result_id}.result.json",
        "result_seal_path": f"results/sealed/{result_id}.seal.json",
        "supersedes_result_id": None,
    }


def sealed_result(result_id: str, value: float) -> dict:
    """返回评估器所需的最小 sealed result 事实。"""
    return {
        "result_id": result_id,
        "metrics": [{"name": "validation_rmse", "value": value, "unit": "dimensionless"}],
    }


def evaluation_documents(
    target_value: float,
    *,
    target_status: str = "accepted",
    include_second_predicate: bool = False,
) -> tuple[dict, dict, list[dict], dict[str, dict]]:
    """构造纯内存评估输入。"""
    lock = route_lock()
    lock["innovation_claims"][0]["required_experiment_roles"] = ["baseline", "primary"]
    plan = experiment_plan()
    plan["comparison_rule"]["predicates"][0]["relation"] = "relative_decrease"
    plan["comparison_rule"]["predicates"][0]["threshold"] = 0.1
    if include_second_predicate:
        plan["comparison_rule"]["predicates"].append(
            {
                "prediction_id": "P-Q1-02",
                "role": "required_support",
                "metric": "missing_metric",
                "relation": "stable",
                "threshold": 0.01,
                "unit": "dimensionless",
                "aggregation": "primary_result",
            }
        )
    registry = {
        "schema_name": "result_registry",
        "schema_version": "2.0",
        "run_id": "semantic-test",
        "results": [
            registry_row("Q1-B0", "baseline"),
            registry_row("Q1-P1", "primary", target_status),
        ],
    }
    sealed = {
        "Q1-B0": sealed_result("Q1-B0", 10.0),
        "Q1-P1": sealed_result("Q1-P1", target_value),
    }
    return lock, registry, [plan], sealed


class ClaimEvaluatorTests(unittest.TestCase):
    """覆盖主张状态、生命周期筛选和输入绑定。"""

    def test_all_structured_predicates_passing_support_claim(self) -> None:
        lock, registry, plans, sealed = evaluation_documents(8.0)

        evidence, _ = evaluate_claim_documents(lock, registry, plans, sealed)

        self.assertEqual("supported", evidence["claims"][0]["status"])
        self.assertEqual("passed", evidence["claims"][0]["prediction_checks"][0]["status"])

    def test_failed_falsification_rejects_claim_even_when_text_is_confident(self) -> None:
        lock, registry, plans, sealed = evaluation_documents(12.0)
        lock["innovation_claims"][0]["claim"] = "无论数值如何变化，本主张都必然成立"
        plans[0]["comparison_rule"]["predicates"][0]["role"] = "falsification"

        evidence, _ = evaluate_claim_documents(lock, registry, plans, sealed)

        self.assertEqual("rejected", evidence["claims"][0]["status"])
        self.assertEqual("failed", evidence["claims"][0]["prediction_checks"][0]["status"])
        self.assertEqual("accepted", registry["results"][1]["status"])

    def test_partial_predicate_results_are_partially_supported(self) -> None:
        lock, registry, plans, sealed = evaluation_documents(
            8.0, include_second_predicate=True
        )

        evidence, _ = evaluate_claim_documents(lock, registry, plans, sealed)

        self.assertEqual("partially_supported", evidence["claims"][0]["status"])
        self.assertEqual(
            ["passed", "inconclusive"],
            [item["status"] for item in evidence["claims"][0]["prediction_checks"]],
        )

    def test_required_support_pass_and_fail_is_partially_supported(self) -> None:
        """非致命支持预测一过一败时不应直接拒绝创新主张。"""
        lock, registry, plans, sealed = evaluation_documents(8.0)
        predicates = plans[0]["comparison_rule"]["predicates"]
        predicates[0]["role"] = "required_support"
        predicates.append(
            {
                "prediction_id": "P-Q1-02",
                "role": "required_support",
                "metric": "validation_rmse",
                "relation": "stable",
                "threshold": 0.01,
                "unit": "dimensionless",
                "aggregation": "primary_result",
            }
        )

        evidence, _ = evaluate_claim_documents(lock, registry, plans, sealed)

        self.assertEqual("partially_supported", evidence["claims"][0]["status"])
        self.assertEqual(
            ["passed", "failed"],
            [item["status"] for item in evidence["claims"][0]["prediction_checks"]],
        )

    def test_non_accepted_result_is_not_used_as_evidence(self) -> None:
        lock, registry, plans, sealed = evaluation_documents(8.0, target_status="rejected")

        evidence, _ = evaluate_claim_documents(lock, registry, plans, sealed)

        self.assertEqual("inconclusive", evidence["claims"][0]["status"])
        self.assertEqual([], evidence["claims"][0]["evidence_result_ids"])

    def test_missing_required_ablation_is_inconclusive(self) -> None:
        """路线锁要求的消融未完成时不得提前支持创新主张。"""
        lock, registry, plans, sealed = evaluation_documents(8.0)
        lock["innovation_claims"][0]["required_experiment_roles"].append("ablation")

        evidence, _ = evaluate_claim_documents(lock, registry, plans, sealed)

        claim = evidence["claims"][0]
        self.assertEqual("inconclusive", claim["status"])
        self.assertEqual(["ablation"], claim["missing_experiment_roles"])

    def test_robustness_plan_without_accepted_result_is_inconclusive(self) -> None:
        """仅存在稳健性计划而没有 accepted/sealed result 不算完成该角色。"""
        lock, registry, plans, sealed = evaluation_documents(8.0)
        lock["innovation_claims"][0]["required_experiment_roles"].append("robustness")
        robustness_plan = experiment_plan()
        robustness_plan["experiment_id"] = "Q1-R1"
        robustness_plan["experiment_role"] = "robustness"
        robustness_plan["comparison_rule"]["predicates"][0]["aggregation"] = (
            "robustness_result"
        )
        plans.append(robustness_plan)

        evidence, _ = evaluate_claim_documents(lock, registry, plans, sealed)

        claim = evidence["claims"][0]
        self.assertEqual("inconclusive", claim["status"])
        self.assertEqual(["robustness"], claim["missing_experiment_roles"])

    def test_all_required_experiment_roles_allow_supported_claim(self) -> None:
        """baseline、primary、ablation 均有有效结果时允许支持主张。"""
        lock, registry, plans, sealed = evaluation_documents(8.0)
        lock["innovation_claims"][0]["required_experiment_roles"].append("ablation")
        registry["results"].append(registry_row("Q1-A1", "ablation"))
        sealed["Q1-A1"] = sealed_result("Q1-A1", 8.5)
        ablation_plan = experiment_plan()
        ablation_plan["experiment_id"] = "Q1-A1"
        ablation_plan["experiment_role"] = "ablation"
        ablation_plan["comparison_rule"]["predicates"][0]["relation"] = (
            "relative_decrease"
        )
        ablation_plan["comparison_rule"]["predicates"][0]["threshold"] = 0.1
        ablation_plan["comparison_rule"]["predicates"][0]["aggregation"] = (
            "ablation_result"
        )
        plans.append(ablation_plan)

        evidence, _ = evaluate_claim_documents(lock, registry, plans, sealed)

        claim = evidence["claims"][0]
        self.assertEqual("supported", claim["status"])
        self.assertEqual(
            ["baseline", "primary", "ablation"],
            claim["satisfied_experiment_roles"],
        )
        self.assertEqual([], claim["missing_experiment_roles"])

    def test_no_structured_claim_is_claimability_none(self) -> None:
        lock, registry, plans, sealed = evaluation_documents(8.0)
        lock["innovation_claims"] = [{"claim_id": "legacy", "claim": "自由文本主张"}]

        evidence, _ = evaluate_claim_documents(lock, registry, plans, sealed)

        self.assertEqual("none", evidence["claimability"])
        self.assertEqual([], evidence["claims"])

    def test_route_lock_change_marks_existing_evidence_stale_without_touching_sealed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            self._write_files(run_dir, *evaluation_documents(8.0))
            sealed_path = run_dir / "results/sealed/Q1-B0.result.json"
            before = sealed_path.read_bytes()
            with patch(
                "shumozizi.claims.evaluator.verify_sealed_result",
                return_value={"valid": True, "errors": []},
            ):
                evaluate_claims(run_dir, refresh=True)
                route_path = run_dir / "brief/ROUTE_LOCK.json"
                changed = json.loads(route_path.read_text(encoding="utf-8"))
                changed["primary_route"] = "改动后的路线描述"
                self._write_json(route_path, changed)
                stale = evaluate_claims(run_dir)

            self.assertTrue(stale["stale"])
            self.assertIn("route_lock_sha256", stale["stale_reason"])
            self.assertEqual(before, sealed_path.read_bytes())

    def test_evaluator_version_change_marks_existing_evidence_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            self._write_files(run_dir, *evaluation_documents(8.0))
            with patch(
                "shumozizi.claims.evaluator.verify_sealed_result",
                return_value={"valid": True, "errors": []},
            ):
                evaluate_claims(run_dir, evaluator_version="1.0.0", refresh=True)
                stale = evaluate_claims(run_dir, evaluator_version="2.0.0")

            self.assertTrue(stale["stale"])
            self.assertIn("evaluator_version", stale["stale_reason"])

    def test_experiment_plan_change_marks_existing_evidence_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            self._write_files(run_dir, *evaluation_documents(8.0))
            with patch(
                "shumozizi.claims.evaluator.verify_sealed_result",
                return_value={"valid": True, "errors": []},
            ):
                evaluate_claims(run_dir, refresh=True)
                plan_path = run_dir / "experiments/plans/Q1-E1.json"
                changed = json.loads(plan_path.read_text(encoding="utf-8"))
                changed["stop_rule"] = "改变后的停止规则"
                self._write_json(plan_path, changed)
                stale = evaluate_claims(run_dir)

            self.assertTrue(stale["stale"])
            self.assertIn("experiment_plan_sha256", stale["stale_reason"])

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        """以 UTF-8 写入测试 JSON。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def _write_files(
        cls,
        run_dir: Path,
        lock: dict,
        registry: dict,
        plans: list[dict],
        sealed: dict[str, dict],
    ) -> None:
        """创建文件系统入口所需的最小运行目录。"""
        cls._write_json(run_dir / "brief/ROUTE_LOCK.json", lock)
        cls._write_json(run_dir / "results/result_registry.json", registry)
        for plan in plans:
            cls._write_json(run_dir / "experiments/plans" / f"{plan['experiment_id']}.json", plan)
        for result_id, document in sealed.items():
            cls._write_json(run_dir / f"results/sealed/{result_id}.result.json", document)
            cls._write_json(run_dir / f"results/sealed/{result_id}.seal.json", {})
        (run_dir / "claims").mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    unittest.main()
