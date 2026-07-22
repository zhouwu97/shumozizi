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
    "minimum_top_k_recall": 0.5,
    "minimum_improvement_sign_agreement": 0.5,
    "minimum_local_variation": 0.1,
}


def _receipts(*, include_incumbent: bool = False) -> tuple[dict[str, object], dict[str, object]]:
    """构造带可验证字段的最小独立挑战收据。"""
    incumbent = {
        "result_id": "incumbent",
        "candidate_fingerprint": "a" * 64,
        "exact_output_sha256": "b" * 64,
        "recomputed_output_sha256": "b" * 64,
        "recomputed_result_id": "incumbent-recomputed",
        "search_family": {"id": "global", "implementation_sha256": "c" * 64},
    }
    fingerprints = ["a" * 64] if include_incumbent else ["d" * 64]
    challenge = {
        "command": "python code/challenge.py",
        "command_receipt_sha256": "e" * 64,
        "input_hashes": {"problem.json": "f" * 64},
        "output_sha256": "0" * 64,
        "search_family": {"id": "challenge", "implementation_sha256": "1" * 64},
        "candidate_fingerprints": fingerprints,
    }
    return incumbent, challenge


class SearchAdequacyTests(unittest.TestCase):
    """仅测试当前问题的评价与门控性质。"""

    def test_flat_boolean_evaluator_is_rejected_despite_positive_exact_island(self) -> None:
        """粗布尔近似漏掉窄正值岛且局部无区分时必须失败。"""
        report = assess_search_adequacy(
            exact_scores=[1.392, 0.0, 0.82, 0.0],
            approximate_scores=[1.4, 0.0, 0.0, 0.0],
            surrogate_scores=[0.9, 0.01, 0.6, 0.02],
            local_surrogate_scores=[0.9, 0.9, 0.9],
            baseline_index=0,
            top_k=2,
            adequacy_contract=ADEQUACY_CONTRACT,
        )

        self.assertEqual("failed", report["search_adequacy"])
        self.assertIn("approximate_false_zero_detected", report["reasons"])
        self.assertIn("surrogate_local_flat", report["reasons"])

    def test_exact_recompute_and_candidate_expansion_never_lower_best_so_far(self) -> None:
        """代理赢家必须经 exact 重算，扩充候选不能使 best-so-far 变差。"""
        before = exact_best_so_far([1.0, 1.7])
        after = exact_best_so_far([1.0, 1.7, 0.2, 2.1])

        self.assertEqual(1.7, before)
        self.assertEqual(2.1, after)
        self.assertGreaterEqual(after, before)

    def test_sparse_false_zero_requires_dense_restart_even_below_old_rate(self) -> None:
        """稀疏正岛中的单个近似假零也不得直接放行。"""
        report = assess_search_adequacy(
            exact_scores=[1.392, 0.61, 0.0, 0.0, 0.0, 0.0, 0.0],
            approximate_scores=[1.4, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            surrogate_scores=[0.9, 0.52, 0.03, 0.02, 0.01, 0.04, 0.05],
            local_surrogate_scores=[0.1, 0.3, 0.7],
            baseline_index=0,
            top_k=2,
            adequacy_contract=ADEQUACY_CONTRACT,
        )

        self.assertEqual("failed", report["search_adequacy"])
        self.assertIn("approximate_false_zero_requires_dense_recalibration", report["reasons"])
        self.assertTrue(report["diagnostics"]["calibration_restart_required"])

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

    def test_challenger_that_only_matches_incumbent_is_not_a_success(self) -> None:
        """把 incumbent 塞进候选池后的“不差”比较不能伪装成挑战。"""
        incumbent, challenge = _receipts(include_incumbent=True)
        with self.assertRaisesRegex(ContractError, "候选池包含 incumbent"):
            assess_independent_challenge(
                incumbent_exact=2.577,
                challenger_exact=2.577,
                incumbent_receipt=incumbent,
                challenge_receipt=challenge,
            )

    def test_independent_challenger_can_meet_preregistered_comparability_threshold(self) -> None:
        """挑战不注入 incumbent 且达到预登记阈值时可作为独立复现证据。"""
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
        )

        self.assertEqual("passed", report["search_adequacy"])
        self.assertIn("independent_challenge_comparable_threshold_met", report["reasons"])
        self.assertTrue(report["diagnostics"]["incumbent_exact_recomputed"])

    def test_nonimproving_challenge_requires_one_bounded_follow_up(self) -> None:
        """挑战未达标时必须冻结一次加密或换族搜索，而不能自动放行较差候选。"""
        incumbent, challenge = _receipts()

        with self.assertRaisesRegex(ContractError, "有界 follow-up"):
            assess_independent_challenge(
                incumbent_exact=5.0,
                challenger_exact=4.0,
                incumbent_receipt=incumbent,
                challenge_receipt=challenge,
            )

        report = assess_independent_challenge(
            incumbent_exact=5.0,
            challenger_exact=4.0,
            incumbent_receipt=incumbent,
            challenge_receipt=challenge,
            follow_up_contract={
                "strategy": "densification",
                "max_attempts": 1,
                "reason": "独立挑战未达到已冻结下界",
            },
        )

        self.assertEqual("failed", report["search_adequacy"])
        self.assertEqual("densification", report["follow_up"]["strategy"])
        self.assertEqual(1, report["follow_up"]["max_attempts"])


if __name__ == "__main__":
    unittest.main()
