"""验证 Capability-First v3 通用质量放行协议。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from shumozizi.core.io import ContractError
from shumozizi.simple.execution import execute_simple_experiment
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.quality import (
    assess_result_quality,
    quality_allows_paper,
    require_prior_question_quality,
)
from shumozizi.simple.search_adequacy import (
    assess_independent_challenge,
    validate_coverage_evidence,
    validate_objective_semantics,
)
from shumozizi.simple.selection import read_candidate_registry


class CapabilityQualityProtocolTests(unittest.TestCase):
    """覆盖跨题型可复用的候选选择与质量证据边界。"""

    def _run_result(
        self,
        run_dir: Path,
        *,
        result_id: str,
        question_id: str,
        objective: float,
        quality: dict[str, object],
    ) -> None:
        """生成带可追溯质量证据的临时真实执行结果。"""
        script = run_dir / "code" / f"{result_id}.py"
        output = f"results/raw/{result_id}.json"
        document = {"metrics": {"objective": objective}, "quality": quality}
        script.write_text(
            "from pathlib import Path\n"
            "import json\n"
            f"Path({output!r}).write_text(json.dumps({document!r}), encoding='utf-8')\n",
            encoding="utf-8",
        )
        executed = execute_simple_experiment(
            run_dir,
            result_id=result_id,
            question_id=question_id,
            kind="search",
            command=f'"{sys.executable}" code/{result_id}.py',
            expected_outputs=[output],
            metrics_from=output,
        )
        self.assertTrue(executed["success"], executed["error"])

    @staticmethod
    def _contract(*, scorer_version: str = "fine-v1", constraint_version: str = "c-v1") -> dict[str, object]:
        """构造带并集和覆盖要求的最小选择合同。"""
        return {
            "objective": {
                "metric": "objective",
                "direction": "maximize",
                "objective_version": "objective-v1",
                "scorer_version": scorer_version,
                "constraint_version": constraint_version,
                "semantics": "union",
                "fine_tolerance": 0.001,
            },
            "coverage": {
                "groups": [
                    {"id": "flight", "variables": ["heading", "speed"], "minimum_joint_coverage": 0.5},
                    {
                        "id": "entity-1",
                        "variables": ["u1.drop", "u1.fuse"],
                        "minimum_joint_coverage": 0.5,
                    },
                    {
                        "id": "entity-2",
                        "variables": ["u2.drop", "u2.fuse"],
                        "minimum_joint_coverage": 0.5,
                    },
                    {
                        "id": "interaction",
                        "variables": ["u1.drop", "u2.drop", "u1.fuse", "u2.fuse"],
                        "minimum_joint_coverage": 0.5,
                    },
                ]
            },
            "required_evidence": ["coverage", "objective_semantics"],
        }

    @classmethod
    def _quality_document(cls, *, contract: dict[str, object], objective: float) -> dict[str, object]:
        """构造输出内的机器质量证据；路径和哈希由运行时复验。"""
        coverage = {
            "group_reports": [
                {"id": group["id"], "variables": group["variables"], "joint_coverage": 0.75}
                for group in contract["coverage"]["groups"]  # type: ignore[index]
            ]
        }
        return {
            "feasible": True,
            "exact_recomputed": True,
            "search_adequacy": "passed",
            "problem_effectiveness": "progressed",
            "objective_value": objective,
            "coverage": coverage,
            "objective_semantics": {
                "surrogate": "union_marginal_gain",
                "calibration": "union_marginal_gain",
                "exact": "union_marginal_gain",
                "selection": "union_marginal_gain",
                "entity_marginal_gains": [objective, 0.0],
            },
        }

    @staticmethod
    def _reference(result_id: str, file_name: str, path: str, expected: object) -> dict[str, object]:
        """构造必须由已登记输出解析的质量证据引用。"""
        return {
            "result_id": result_id,
            "file": file_name,
            "json_path": path,
            "expected": expected,
        }

    def _assess(
        self,
        run_dir: Path,
        *,
        result_id: str,
        contract: dict[str, object],
        search_status: str = "passed",
    ) -> dict[str, object]:
        """以同一执行输出的可验证字段放行结果。"""
        output = f"results/raw/{result_id}.json"
        evidence = {
            "feasibility": self._reference(result_id, output, "quality.feasible", True),
            "exact_recomputed": self._reference(
                result_id, output, "quality.exact_recomputed", True
            ),
            "search_adequacy": self._reference(
                result_id, output, "quality.search_adequacy", search_status
            ),
            "problem_effectiveness": self._reference(
                result_id, output, "quality.problem_effectiveness", "progressed"
            ),
            "coverage": self._reference(result_id, output, "quality.coverage", None),
            "objective_semantics": self._reference(
                result_id, output, "quality.objective_semantics", None
            ),
        }
        for key in contract.get("required_evidence", []):
            if key not in evidence:
                evidence[key] = self._reference(result_id, output, f"quality.{key}", None)
        return assess_result_quality(
            run_dir,
            result_id=result_id,
            assessment={
                "result_role": "accepted",
                "selection_contract": contract,
                "evidence": evidence,
                "reasons": ["test_evidence_chain"],
            },
        )

    def test_later_lower_exact_valid_candidate_cannot_replace_verified_best(self) -> None:
        """同组较低精确目标即使可行也不能覆盖已验证下界。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "registry-lower")
            contract = self._contract()
            self._run_result(
                run_dir,
                result_id="best",
                question_id="Q3",
                objective=10.0,
                quality=self._quality_document(contract=contract, objective=10.0),
            )
            first = self._assess(run_dir, result_id="best", contract=contract)
            self._run_result(
                run_dir,
                result_id="lower",
                question_id="Q3",
                objective=9.0,
                quality=self._quality_document(contract=contract, objective=9.0),
            )
            lower = self._assess(run_dir, result_id="lower", contract=contract)

            registry = read_candidate_registry(run_dir)
            self.assertTrue(first["paper_allowed"])
            self.assertFalse(lower["paper_allowed"])
            self.assertEqual("best", registry["groups"][0]["best_result_id"])
            self.assertIn("below_best_verified_lower_bound", lower["reasons"])
            self.assertTrue(quality_allows_paper(run_dir, "best"))
            self.assertFalse(quality_allows_paper(run_dir, "lower"))

    def test_registry_grouping_respects_objective_scorer_and_constraint_versions(self) -> None:
        """版本不同的目标、评分器或约束不能共享候选下界。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "registry-versions")
            first_contract = self._contract()
            second_contract = self._contract(scorer_version="fine-v2")
            self._run_result(
                run_dir,
                result_id="v1",
                question_id="Q3",
                objective=10.0,
                quality=self._quality_document(contract=first_contract, objective=10.0),
            )
            self._assess(run_dir, result_id="v1", contract=first_contract)
            self._run_result(
                run_dir,
                result_id="v2",
                question_id="Q3",
                objective=9.0,
                quality=self._quality_document(contract=second_contract, objective=9.0),
            )
            second = self._assess(run_dir, result_id="v2", contract=second_contract)

            registry = read_candidate_registry(run_dir)
            self.assertTrue(second["paper_allowed"])
            self.assertEqual(2, len(registry["groups"]))

    def test_fake_independence_flags_cannot_bypass_provenance(self) -> None:
        """JSON 自报独立性不能替代命令、候选和哈希来源。"""
        with self.assertRaisesRegex(ContractError, "provenance"):
            assess_independent_challenge(
                incumbent_exact=10.0,
                challenger_exact=11.0,
                challenge_receipt={
                    "independent_family": True,
                    "candidate_pool_contains_incumbent": False,
                },
                incumbent_receipt={"exact_output_sha256": "0" * 64},
            )

    def test_challenge_receipt_must_match_registered_execution(self) -> None:
        """格式完整但未绑定实际命令的挑战收据不能覆盖已验证 incumbent。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "challenge-receipt-binding")
            contract = self._contract()
            self._run_result(
                run_dir,
                result_id="incumbent",
                question_id="Q3",
                objective=10.0,
                quality=self._quality_document(contract=contract, objective=10.0),
            )
            self._assess(run_dir, result_id="incumbent", contract=contract)

            contract["required_evidence"].append("independent_challenge")  # type: ignore[index]
            challenged_quality = self._quality_document(contract=contract, objective=11.0)
            challenged_quality["independent_challenge"] = {
                "incumbent_exact": 10.0,
                "challenger_exact": 11.0,
                "incumbent_receipt": {
                    "result_id": "incumbent",
                    "candidate_fingerprint": "a" * 64,
                    "exact_output_sha256": "b" * 64,
                    "recomputed_output_sha256": "b" * 64,
                    "search_family": {"id": "global", "implementation_sha256": "c" * 64},
                },
                "challenge_receipt": {
                    "result_id": "challenger",
                    "command": "python unregistered.py",
                    "command_receipt_sha256": "d" * 64,
                    "input_hashes": {"problem.json": "e" * 64},
                    "output_sha256": "f" * 64,
                    "search_family": {
                        "id": "challenge",
                        "implementation_sha256": "1" * 64,
                    },
                    "candidate_fingerprints": ["2" * 64],
                },
            }
            self._run_result(
                run_dir,
                result_id="challenger",
                question_id="Q3",
                objective=11.0,
                quality=challenged_quality,
            )

            with self.assertRaisesRegex(ContractError, "挑战命令"):
                self._assess(run_dir, result_id="challenger", contract=contract)

            registry = read_candidate_registry(run_dir)
            self.assertEqual("incumbent", registry["groups"][0]["best_result_id"])
            self.assertTrue(quality_allows_paper(run_dir, "incumbent"))

    def test_eight_dimensional_projection_to_four_dimensions_is_rejected(self) -> None:
        """均值或首值投影不能冒充多实体联合及交互覆盖。"""
        contract = self._contract()
        projected = {
            "group_reports": [
                {"id": "flight", "variables": ["heading", "speed"], "joint_coverage": 1.0},
                {"id": "entity", "variables": ["mean_drop", "mean_fuse"], "joint_coverage": 1.0},
            ]
        }

        report = validate_coverage_evidence(contract, projected)

        self.assertFalse(report["passed"])
        self.assertIn("coverage_group_missing:entity-1", report["reasons"])
        self.assertIn("coverage_group_missing:interaction", report["reasons"])

    def test_union_contract_rejects_sum_surrogate_but_allows_zero_marginal_entity(self) -> None:
        """并集目标禁止按实体相加，单个零边际不应被误判为不可行。"""
        contract = self._contract()
        summed = {
            "surrogate": "sum_entities",
            "calibration": "sum_entities",
            "exact": "union_marginal_gain",
            "selection": "sum_entities",
            "entity_marginal_gains": [3.0, 0.0],
        }
        valid_union = {
            "surrogate": "union_marginal_gain",
            "calibration": "union_marginal_gain",
            "exact": "union_marginal_gain",
            "selection": "union_marginal_gain",
            "entity_marginal_gains": [3.0, 0.0],
        }

        self.assertFalse(validate_objective_semantics(contract, summed)["passed"])
        self.assertTrue(validate_objective_semantics(contract, valid_union)["passed"])

    def test_no_objective_progress_cannot_be_released_even_with_zero_marginal_validity(self) -> None:
        """复现旧单实体解并增加零边际实体不是当前问题的有效进展。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "zero-marginal")
            contract = self._contract()
            self._run_result(
                run_dir,
                result_id="incumbent",
                question_id="Q3",
                objective=10.0,
                quality=self._quality_document(contract=contract, objective=10.0),
            )
            self._assess(run_dir, result_id="incumbent", contract=contract)
            self._run_result(
                run_dir,
                result_id="replay",
                question_id="Q3",
                objective=10.0,
                quality=self._quality_document(contract=contract, objective=10.0),
            )
            replay = self._assess(run_dir, result_id="replay", contract=contract)

            self.assertFalse(replay["paper_allowed"])
            self.assertIn("no_objective_progress_above_lower_bound", replay["reasons"])

    def test_evidence_hash_drift_revokes_an_accepted_result(self) -> None:
        """放行后输出发生漂移时，后续质量门必须重新拒绝该结果。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "quality-evidence-drift")
            contract = self._contract()
            self._run_result(
                run_dir,
                result_id="accepted",
                question_id="Q3",
                objective=10.0,
                quality=self._quality_document(contract=contract, objective=10.0),
            )
            self._assess(run_dir, result_id="accepted", contract=contract)
            output = run_dir / "results" / "raw" / "accepted.json"
            output.write_text(json.dumps({"metrics": {"objective": 11.0}}), encoding="utf-8")

            self.assertFalse(quality_allows_paper(run_dir, "accepted"))

    def test_downstream_q4_and_q5_require_non_degraded_previous_quality(self) -> None:
        """Q4、Q5 放行必须消费上一问仍有效且未降级的质量记录。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(
                Path(temporary), "downstream", required_questions=["Q3", "Q4", "Q5"]
            )
            contract = self._contract()
            self._run_result(
                run_dir,
                result_id="q3",
                question_id="Q3",
                objective=10.0,
                quality=self._quality_document(contract=contract, objective=10.0),
            )
            self._assess(run_dir, result_id="q3", contract=contract)
            require_prior_question_quality(run_dir, "Q4")

            degraded = self._quality_document(contract=contract, objective=10.0)
            degraded["search_adequacy"] = "failed"
            self._run_result(
                run_dir,
                result_id="q3-degraded",
                question_id="Q3",
                objective=9.0,
                quality=degraded,
            )
            failed = self._assess(
                run_dir,
                result_id="q3-degraded",
                contract=contract,
                search_status="failed",
            )

            self.assertFalse(failed["paper_allowed"])
            require_prior_question_quality(run_dir, "Q4")
            with self.assertRaisesRegex(ContractError, "Q4"):
                require_prior_question_quality(run_dir, "Q5")

    def test_normal_independent_adequate_search_path_remains_allowed(self) -> None:
        """不同搜索族、冻结 incumbent 和预登记可比条件齐备时允许通过。"""
        report = assess_independent_challenge(
            incumbent_exact=10.0,
            challenger_exact=10.2,
            incumbent_receipt={
                "result_id": "incumbent",
                "candidate_fingerprint": "a" * 64,
                "exact_output_sha256": "b" * 64,
                "recomputed_output_sha256": "b" * 64,
                "recomputed_result_id": "incumbent-recomputed",
                "search_family": {"id": "global", "implementation_sha256": "c" * 64},
            },
            challenge_receipt={
                "command": "python code/challenge.py",
                "command_receipt_sha256": "d" * 64,
                "input_hashes": {"problem.json": "e" * 64},
                "output_sha256": "f" * 64,
                "search_family": {"id": "challenge", "implementation_sha256": "1" * 64},
                "candidate_fingerprints": ["2" * 64],
            },
        )

        self.assertEqual("passed", report["search_adequacy"])
        self.assertIn("independent_challenge_improved_incumbent", report["reasons"])

    def test_raw_boolean_assessment_cannot_release_result(self) -> None:
        """质量接口不再允许调用方凭布尔字段直接把结果写为 accepted。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "raw-boolean")
            self._run_result(
                run_dir,
                result_id="candidate",
                question_id="Q1",
                objective=1.0,
                quality={},
            )

            with self.assertRaisesRegex(ContractError, "evidence"):
                assess_result_quality(
                    run_dir,
                    result_id="candidate",
                    feasibility_valid=True,
                    baseline_preserved=True,
                    search_adequacy="passed",
                    result_role="accepted",
                    reasons=["caller_claim"],
                )


if __name__ == "__main__":
    unittest.main()
