"""验证高风险优化的搜索充分性性质与对抗情形。"""

from __future__ import annotations

import unittest

from shumozizi.core.io import ContractError
from shumozizi.simple.search_adequacy import (
    assess_independent_challenge,
    assess_search_adequacy,
    exact_best_so_far,
)

ADEQUACY_CONTRACT = {
    "objective_direction": "maximize",
    "minimum_top_k_recall": 0.5,
    "minimum_improvement_sign_agreement": 0.5,
    "minimum_local_variation": 0.1,
    "approximate_false_zero_policy": "catastrophic_only",
}


def _independence_contract(
    *,
    objective_direction: str = "maximize",
    minimum_independent_new_candidates: int = 1,
    minimum_independent_new_regions: int = 1,
) -> dict[str, object]:
    """构造挑战独立性和 warm start 的预登记合同。"""
    return {
        "objective_direction": objective_direction,
        "allow_marked_warm_start": True,
        "minimum_independent_new_candidates": minimum_independent_new_candidates,
        "minimum_independent_new_regions": minimum_independent_new_regions,
    }


def _receipts(
    *,
    include_incumbent: bool = False,
    independent_candidate_count: int = 1,
    independent_regions: tuple[str, ...] = ("new-region-a",),
) -> tuple[dict[str, object], dict[str, object]]:
    """构造带候选池角色和新区域证据的最小挑战收据。"""
    incumbent = {
        "result_id": "incumbent",
        "candidate_fingerprint": "a" * 64,
        "exact_output_sha256": "b" * 64,
        "recomputed_output_sha256": "b" * 64,
        "recomputed_result_id": "incumbent-recomputed",
        "search_family": {"id": "global", "implementation_sha256": "c" * 64},
    }
    fingerprints: list[str] = []
    candidates: list[dict[str, object]] = []
    if include_incumbent:
        fingerprints.append("a" * 64)
        candidates.append(
            {
                "fingerprint": "a" * 64,
                "role": "warm_start",
                "region_id": "incumbent-region",
                "exact_evaluated": True,
            }
        )
    for index, fingerprint_prefix in enumerate(("d", "2", "3", "4")[:independent_candidate_count]):
        region_id = independent_regions[index % len(independent_regions)] if independent_regions else ""
        fingerprint = fingerprint_prefix * 64
        fingerprints.append(fingerprint)
        candidates.append(
            {
                "fingerprint": fingerprint,
                "role": "independent_new",
                "region_id": region_id,
                "exact_evaluated": True,
            }
        )
    challenge = {
        "command": "python code/challenge.py",
        "command_receipt_sha256": "e" * 64,
        "input_hashes": {"problem.json": "f" * 64},
        "output_sha256": "0" * 64,
        "search_family": {"id": "challenge", "implementation_sha256": "1" * 64},
        "candidate_fingerprints": fingerprints,
        "candidate_pool": {
            "candidates": candidates,
            "evaluated_region_ids": sorted(
                {
                    str(candidate["region_id"])
                    for candidate in candidates
                    if candidate["role"] == "independent_new" and candidate["region_id"]
                }
            ),
        },
    }
    return incumbent, challenge


class SearchAdequacyTests(unittest.TestCase):
    """仅测试当前问题的评价与门控性质。"""

    def test_decision_relevant_calibration_error_is_catastrophic(self) -> None:
        """漏掉 exact 最优候选并改写 top-k 决策时必须阻断。"""
        report = assess_search_adequacy(
            exact_scores=[0.0, 10.0, 1.0, 0.0],
            approximate_scores=[0.0, 0.0, 1.0, 0.0],
            surrogate_scores=[0.1, 0.05, 0.9, 0.2],
            local_surrogate_scores=[0.1, 0.1, 0.1],
            baseline_index=0,
            top_k=1,
            adequacy_contract=ADEQUACY_CONTRACT,
        )

        self.assertEqual("failed", report["search_adequacy"])
        self.assertIn("calibration_catastrophic_selection_error", report["reasons"])
        self.assertTrue(report["diagnostics"]["calibration_restart_required"])

    def test_exact_recompute_and_candidate_expansion_never_lower_best_so_far(self) -> None:
        """代理赢家必须经 exact 重算，扩充候选不能使 best-so-far 变差。"""
        before = exact_best_so_far([1.0, 1.7])
        after = exact_best_so_far([1.0, 1.7, 0.2, 2.1])

        self.assertEqual(1.7, before)
        self.assertEqual(2.1, after)
        self.assertGreaterEqual(after, before)

    def test_noncatastrophic_false_zero_is_diagnostic_not_restart(self) -> None:
        """低价值假零未改变筛选决策时只能留下诊断，不能阻断搜索。"""
        report = assess_search_adequacy(
            exact_scores=[0.0, 10.0, 1.0, 0.5],
            approximate_scores=[0.0, 10.0, 0.0, 0.5],
            surrogate_scores=[0.1, 9.0, 0.2, 0.3],
            local_surrogate_scores=[0.1, 0.3, 0.7],
            baseline_index=0,
            top_k=1,
            adequacy_contract=ADEQUACY_CONTRACT,
        )

        self.assertEqual("passed", report["search_adequacy"])
        self.assertIn("approximate_false_zero_diagnostic", report["reasons"])
        self.assertFalse(report["diagnostics"]["calibration_restart_required"])

    def test_minimize_direction_uses_low_scores_for_top_k_calibration(self) -> None:
        """最小化问题必须按低 exact 值判断 top-k，不能复用最大化排序。"""
        contract = {**ADEQUACY_CONTRACT, "objective_direction": "minimize"}
        report = assess_search_adequacy(
            exact_scores=[10.0, 2.0, 1.0],
            approximate_scores=[10.0, 2.0, 1.0],
            surrogate_scores=[10.0, 1.0, 2.0],
            local_surrogate_scores=[0.1, 0.3, 0.7],
            baseline_index=0,
            top_k=1,
            adequacy_contract=contract,
        )

        self.assertEqual("failed", report["search_adequacy"])
        self.assertIn("surrogate_top_k_recall_insufficient", report["reasons"])
        self.assertEqual("minimize", report["diagnostics"]["objective_direction"])

    def test_joint_coverage_failure_rejects_marginally_complete_samples(self) -> None:
        """仅各维边际覆盖而联合区域退化时，质量门必须失败。"""
        report = assess_search_adequacy(
            exact_scores=[1.0, 1.2, 0.2, 0.1],
            approximate_scores=[1.0, 1.2, 0.2, 0.1],
            surrogate_scores=[0.8, 1.0, 0.3, 0.2],
            local_surrogate_scores=[0.2, 0.5],
            baseline_index=0,
            top_k=2,
            adequacy_contract=ADEQUACY_CONTRACT,
            joint_coverage={"passed": False, "reason": "diagonal_only"},
        )

        self.assertEqual("failed", report["search_adequacy"])
        self.assertIn("joint_domain_coverage_incomplete", report["reasons"])

    def test_marked_warm_start_with_new_candidates_and_region_supports_challenge(self) -> None:
        """共享 baseline 只要显式标注且探索新区域，仍可构成独立挑战。"""
        incumbent, challenge = _receipts(
            include_incumbent=True,
            independent_candidate_count=2,
            independent_regions=("new-region-a",),
        )

        report = assess_independent_challenge(
            incumbent_exact=2.577,
            challenger_exact=2.700,
            incumbent_receipt=incumbent,
            challenge_receipt=challenge,
            independence_contract=_independence_contract(
                minimum_independent_new_candidates=2,
                minimum_independent_new_regions=1,
            ),
        )

        self.assertEqual("passed", report["search_adequacy"])
        self.assertTrue(report["diagnostics"]["warm_start_accepted"])
        self.assertEqual(2, report["diagnostics"]["independent_new_candidate_count"])
        self.assertEqual(1, report["diagnostics"]["independent_new_region_count"])

    def test_copied_incumbent_without_new_region_is_rejected_as_challenge(self) -> None:
        """仅复制 incumbent 的 warm start 不得伪装成探索性挑战。"""
        incumbent, challenge = _receipts(
            include_incumbent=True,
            independent_candidate_count=0,
            independent_regions=(),
        )

        with self.assertRaisesRegex(ContractError, "独立新候选|新区域"):
            assess_independent_challenge(
                incumbent_exact=2.577,
                challenger_exact=2.577,
                incumbent_receipt=incumbent,
                challenge_receipt=challenge,
                independence_contract=_independence_contract(),
            )

    def test_nonimproving_comparable_challenge_stabilizes_incumbent(self) -> None:
        """独立且满足可比合同的非改善挑战应增强 incumbent 稳定性。"""
        incumbent, challenge = _receipts()
        report = assess_independent_challenge(
            incumbent_exact=5.282,
            challenger_exact=5.120,
            incumbent_receipt=incumbent,
            challenge_receipt=challenge,
            comparability_contract={
                "threshold": 5.018,
                "reason": "预登记的独立校准容差",
                "plan_sha256": "2" * 64,
            },
            independence_contract=_independence_contract(),
        )

        self.assertEqual("passed", report["search_adequacy"])
        self.assertIn("independent_challenge_comparable_threshold_met", report["reasons"])
        self.assertTrue(report["diagnostics"]["incumbent_exact_recomputed"])
        self.assertEqual("stabilized", report["incumbent_outcome"])
        self.assertFalse(report["challenger_replaces_incumbent"])

    def test_weaker_challenger_never_replaces_verified_incumbent(self) -> None:
        """覆盖充分但更差的挑战只能说明算法较弱，不能回退 incumbent。"""
        incumbent, challenge = _receipts()
        report = assess_independent_challenge(
            incumbent_exact=5.0,
            challenger_exact=4.0,
            incumbent_receipt=incumbent,
            challenge_receipt=challenge,
            independence_contract=_independence_contract(),
        )

        self.assertEqual("preserved", report["incumbent_outcome"])
        self.assertEqual("algorithm_weaker", report["challenge_outcome"])
        self.assertFalse(report["challenger_replaces_incumbent"])

    def test_minimization_challenger_replaces_incumbent_only_when_exact_score_lowers(self) -> None:
        """最小化合同下较低的 exact objective 才是对 incumbent 的有效改善。"""
        incumbent, challenge = _receipts()
        report = assess_independent_challenge(
            incumbent_exact=5.0,
            challenger_exact=4.0,
            incumbent_receipt=incumbent,
            challenge_receipt=challenge,
            independence_contract=_independence_contract(objective_direction="minimize"),
        )

        self.assertEqual("passed", report["search_adequacy"])
        self.assertTrue(report["challenger_replaces_incumbent"])


if __name__ == "__main__":
    unittest.main()
