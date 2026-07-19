"""用真实执行夹具验证统计预测与确定性优化的主张闭环。"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest

from shumozizi.results.metrics import materialize_metric
from tests.runtime_helpers import REPO_ROOT, RuntimeFixture
from tests.test_semantic_schemas import experiment_plan, route_lock

EVALUATE_CLAIMS = REPO_ROOT / "scripts/runtime/evaluate_claims.py"
FIXTURE_ROOT = REPO_ROOT / "tests/fixtures"


class P0DRealFixtureTests(unittest.TestCase):
    """夹具必须经过真实执行、指标来源和 sealed result 准入。"""

    def setUp(self) -> None:
        self.fixture = RuntimeFixture()
        for relative in ("brief", "data", "experiments/plans", "claims"):
            (self.fixture.run_dir / relative).mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.fixture.close()

    def test_statistical_prediction_fixture_supports_claim(self) -> None:
        """线性拟合从真实 CSV 验证集改善均值基线并支持主张。"""
        source = FIXTURE_ROOT / "p0d_statistical"
        shutil.copyfile(source / "predict.py", self.fixture.run_dir / "code/predict.py")
        shutil.copyfile(source / "data.csv", self.fixture.run_dir / "data/statistical.csv")

        baseline_metrics = self._run_result(
            execution_id="stat-baseline-exec",
            result_id="stat-baseline",
            mode="baseline",
            input_path="data/statistical.csv",
            output_path="results/stat-baseline.json",
            metrics=[("validation_rmse", "/validation_rmse")],
            cycle="baseline",
        )
        primary_metrics = self._run_result(
            execution_id="stat-primary-exec",
            result_id="stat-primary",
            mode="primary",
            input_path="data/statistical.csv",
            output_path="results/stat-primary.json",
            metrics=[("validation_rmse", "/validation_rmse")],
            cycle="primary",
            baseline_result_id="stat-baseline",
        )
        self.assertGreater(baseline_metrics["validation_rmse"]["final_value"], 0)
        self.assertLess(primary_metrics["validation_rmse"]["final_value"], 1e-12)

        claim_id, prediction_id = "IC-STAT-01", "P-STAT-01"
        self._write_route_lock(claim_id, prediction_id, "统计预测机制降低验证误差")
        self._write_plan(
            "STAT-E1",
            "stat-baseline",
            claim_id,
            prediction_id,
            metric="validation_rmse",
            relation="relative_decrease",
            threshold=0.5,
        )

        evidence = self._evaluate_claims()

        self.assertEqual("supported", evidence["claims"][0]["status"])
        self.assertEqual("passed", evidence["claims"][0]["prediction_checks"][0]["status"])

    def test_deterministic_optimization_fixture_rejects_and_supports_none(self) -> None:
        """穷举优化真实输出不足以达到预设阈值时拒绝主张，并可声明无创新。"""
        source = FIXTURE_ROOT / "p0d_optimization"
        shutil.copyfile(source / "solve.py", self.fixture.run_dir / "code/solve.py")
        shutil.copyfile(source / "problem.json", self.fixture.run_dir / "data/problem.json")

        baseline_metrics = self._run_result(
            execution_id="opt-baseline-exec",
            result_id="opt-baseline",
            mode="baseline",
            input_path="data/problem.json",
            output_path="results/opt-baseline.json",
            metrics=[("objective", "/objective")],
            cycle="baseline",
        )
        primary_metrics = self._run_result(
            execution_id="opt-primary-exec",
            result_id="opt-primary",
            mode="primary",
            input_path="data/problem.json",
            output_path="results/opt-primary.json",
            metrics=[("objective", "/objective")],
            cycle="primary",
            baseline_result_id="opt-baseline",
        )
        self.assertGreater(primary_metrics["objective"]["final_value"], baseline_metrics["objective"]["final_value"])

        claim_id, prediction_id = "IC-OPT-01", "P-OPT-01"
        self._write_route_lock(claim_id, prediction_id, "确定性优化机制显著提高资源利用目标")
        self._write_plan(
            "OPT-E1",
            "opt-baseline",
            claim_id,
            prediction_id,
            metric="objective",
            relation="relative_increase",
            threshold=0.2,
            role="falsification",
        )

        rejected = self._evaluate_claims()

        self.assertEqual("rejected", rejected["claims"][0]["status"])
        self.assertEqual("failed", rejected["claims"][0]["prediction_checks"][0]["status"])

        lock = json.loads(
            (self.fixture.run_dir / "brief/ROUTE_LOCK.json").read_text(encoding="utf-8")
        )
        lock["innovation_claims"] = []
        self.fixture.write_json("brief/ROUTE_LOCK.json", lock)
        none = self._evaluate_claims()

        self.assertEqual("none", none["claimability"])
        self.assertEqual([], none["claims"])

    def _run_result(
        self,
        *,
        execution_id: str,
        result_id: str,
        mode: str,
        input_path: str,
        output_path: str,
        metrics: list[tuple[str, str]],
        cycle: str,
        baseline_result_id: str | None = None,
    ) -> dict[str, dict]:
        """登记一次 manifest、执行记录、指标 provenance 和 accepted result。"""
        script = "code/predict.py" if result_id.startswith("stat-") else "code/solve.py"
        manifest = self.fixture.write_json(
            f"executions/manifests/{execution_id}.json",
            {
                "schema_name": "execution_manifest",
                "schema_version": "2.0",
                "execution_id": execution_id,
                "program": "python",
                "args": [script, input_path, output_path, mode],
                "cwd": ".",
                "timeout_seconds": 30,
                "input_files": [script, input_path],
                "expected_outputs": [output_path],
                "random_seed": 42,
            },
        )
        executed = self.fixture.run_executor(manifest)
        self.assertEqual(0, executed.returncode, executed.stdout + executed.stderr)
        record = json.loads(
            (self.fixture.run_dir / f"executions/{execution_id}/execution_record.json").read_text(
                encoding="utf-8"
            )
        )
        output = next(item for item in record["output_files"] if item["path"] == output_path)
        provenances: dict[str, dict] = {}
        candidate_metrics = []
        for metric_name, selector in metrics:
            metric_id = f"{result_id}-{metric_name}"
            provenance = materialize_metric(
                self.fixture.run_dir,
                {
                    "metric_spec_id": metric_id,
                    "execution_record_id": execution_id,
                    "output_artifact": {"path": output_path, "sha256": output["sha256"]},
                    "extractor": {"id": "json-pointer", "selector": selector},
                    "raw_unit": "dimensionless",
                    "transform": None,
                    "final_unit": "dimensionless",
                },
            )
            provenances[metric_name] = provenance
            candidate_metrics.append(
                {
                    "name": metric_name,
                    "metric_spec_id": metric_id,
                    "value": provenance["final_value"],
                    "unit": provenance["final_unit"],
                }
            )
        candidate = {
            "result_id": result_id,
            "question_id": "Q1",
            "cycle": cycle,
            "execution_record_id": execution_id,
            "metrics": candidate_metrics,
            "conclusion": "真实夹具完成并产生结构化结果。",
            "constraint_checks": [{"check_id": "feasible", "passed": True}],
            "validation_checks": [{"check_id": "holdout_or_optimality", "passed": True}],
            "baseline_result_id": baseline_result_id,
            "innovation_claims": [],
        }
        self.fixture.write_json(f"results/candidates/{result_id}.json", candidate)
        accepted = self.fixture.run_acceptor(result_id)
        self.assertEqual(0, accepted.returncode, accepted.stdout + accepted.stderr)
        return provenances

    def _write_route_lock(self, claim_id: str, prediction_id: str, claim_text: str) -> None:
        """写入仅用于评估的结构化路线锁。"""
        lock = route_lock()
        lock["run_id"] = self.fixture.run_dir.name
        claim = lock["innovation_claims"][0]
        claim.update(
            {
                "claim_id": claim_id,
                "claim": claim_text,
                "prediction_ids": [prediction_id],
            }
        )
        self.fixture.write_json("brief/ROUTE_LOCK.json", lock)

    def _write_plan(
        self,
        experiment_id: str,
        baseline_result_id: str,
        claim_id: str,
        prediction_id: str,
        *,
        metric: str,
        relation: str,
        threshold: float,
        role: str = "required_support",
    ) -> None:
        """写入真实结果对应的结构化实验计划。"""
        plan = experiment_plan()
        plan.update(
            {
                "run_id": self.fixture.run_dir.name,
                "experiment_id": experiment_id,
                "question_id": "Q1",
                "baseline_result_ids": [baseline_result_id],
                "prediction_ids": [prediction_id],
                "claim_ids": [claim_id],
            }
        )
        plan["comparison_rule"]["predicates"] = [
            {
                "prediction_id": prediction_id,
                "role": role,
                "metric": metric,
                "relation": relation,
                "threshold": threshold,
                "unit": "dimensionless",
                "aggregation": "primary_result",
            }
        ]
        self.fixture.write_json(f"experiments/plans/{experiment_id}.json", plan)

    def _evaluate_claims(self) -> dict:
        """通过公开 CLI 生成 claim evidence。"""
        completed = subprocess.run(
            [sys.executable, str(EVALUATE_CLAIMS), str(self.fixture.run_dir), "--refresh"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        return json.loads(completed.stdout)


if __name__ == "__main__":
    unittest.main()
