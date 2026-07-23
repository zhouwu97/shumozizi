"""验证 Q3 专用的组合时序搜索不退化为单弹四维覆盖。"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

import numpy as np

RUN_DIR = Path(__file__).resolve().parents[1] / "runs" / "cumcm-2025-a-v3-001"
RUN_CODE = RUN_DIR / "code"
if str(RUN_CODE) not in sys.path:
    sys.path.insert(0, str(RUN_CODE))


def load_run_module(name: str):
    """从唯一真实 run 加载待验证模块。"""
    path = RUN_CODE / f"{name}.py"
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"无法加载运行模块: {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


class Q3IntervalSearchTests(unittest.TestCase):
    """覆盖 Q3 的三弹协同变量和覆盖证据。"""

    def test_global_designs_cover_decomposed_eight_dimensional_domain(self) -> None:
        """全域设计必须同时覆盖共同飞行、三投放时序、三引信与交叉单元。"""
        search = load_run_module("q3_interval_search")
        coverage = search.decomposed_coverage(
            search.design_rows(seed=20250738, count=64, family="global")
        )

        self.assertTrue(coverage["passed"])
        self.assertTrue(coverage["flight_joint"]["passed"])
        self.assertTrue(coverage["temporal_joint"]["passed"])
        self.assertTrue(coverage["fuse_joint"]["passed"])
        self.assertTrue(coverage["cross_joint"]["passed"])

    def test_overlapped_intervals_do_not_add_and_zero_third_marginal_is_not_synergy(self) -> None:
        """三弹并集必须去重，零边际第三弹只能如实记录而不能宣称协同。"""
        search = load_run_module("q3_interval_search")
        scoring = load_run_module("coverage_scoring")
        q2 = json.loads(
            (RUN_DIR / "results/raw/q2_self_consistency_r2.json").read_text(encoding="utf-8")
        )
        candidate = scoring.Candidate(**q2["selected_candidate"])
        _, mask = scoring.candidate_coverage_mask(candidate, mode="fine")
        atoms = tuple(
            search.IntervalAtom(candidate=scoring.Candidate(**asdict(candidate)), mask=mask)
            for _ in range(3)
        )
        evidence = search.union_evidence(atoms)

        self.assertGreater(evidence["overlap_fine_s"], 0.0)
        self.assertAlmostEqual(evidence["individual_fine_s"][0], evidence["union_fine_s"], places=6)
        self.assertEqual(0.0, evidence["third_marginal_fine_s"])
        self.assertFalse(evidence["three_bomb_synergy_claimed"])

    def test_diagonal_designs_fail_decomposed_combination_coverage(self) -> None:
        """仅让八维变量同步变化的对角线样本不能伪装为组合覆盖。"""
        search = load_run_module("q3_interval_search")
        diagonal = [np.full(8, (index + 0.5) / 32.0) for index in range(32)]
        coverage = search.decomposed_coverage(diagonal)

        self.assertFalse(coverage["passed"])
        self.assertFalse(coverage["temporal_joint"]["passed"])

    def test_challenge_plan_freezes_threshold_without_strategy_parameters(self) -> None:
        """挑战计划只冻结哈希、exact 值和阈值，不能向搜索器泄露 incumbent 参数。"""
        planner = load_run_module("q3_challenge_plan")
        plan = planner.build_plan(RUN_DIR / "results/raw/q3_adequacy_global_r1.json")

        self.assertEqual("preregistered_challenge_plan", plan["kind"])
        self.assertTrue(plan["policy"]["candidate_pool_must_exclude_incumbent"])
        self.assertGreater(plan["preregistered_comparability_threshold_fine_s"], 0.0)
        self.assertNotIn("selected_strategy", plan["incumbent"])

    def test_postfreeze_review_accepts_independent_comparable_candidate(self) -> None:
        """候选冻结后才可读取计划；同一 exact 复现阈值即可通过挑战复核。"""
        planner = load_run_module("q3_challenge_plan")
        reviewer = load_run_module("q3_challenge_review")
        incumbent_path = RUN_DIR / "results/raw/q3_adequacy_global_r1.json"
        candidate = json.loads(incumbent_path.read_text(encoding="utf-8"))
        candidate["family"] = "challenge"
        candidate["stages"]["candidate_pool_contains_incumbent"] = False
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate_path = root / "candidate.json"
            plan_path = root / "plan.json"
            candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
            plan_path.write_text(json.dumps(planner.build_plan(incumbent_path)), encoding="utf-8")
            report = reviewer.review_challenge(candidate_path, plan_path)

        self.assertTrue(report["metrics"]["q3_search_adequacy_passed"])
        self.assertTrue(report["challenge"]["diagnostics"]["meets_comparable_threshold"])
        self.assertTrue(report["incumbent_recompute"]["hash_verified"])

    def test_interval_beam_preserves_common_flight_and_one_second_spacing(self) -> None:
        """精确并集 DP 只能返回满足 Q3 同机硬约束的三弹策略。"""
        search = load_run_module("q3_interval_search")
        scoring = load_run_module("coverage_scoring")
        q2 = json.loads(
            (RUN_DIR / "results/raw/q2_self_consistency_r2.json").read_text(encoding="utf-8")
        )
        first = scoring.Candidate(**q2["selected_candidate"])
        maximum = scoring.maximum_fuse_time_s("FY1")
        atoms = []
        for offset in (0.0, 1.0, 2.0):
            candidate = scoring.candidate_from_feasible_parameters(
                heading_rad=first.heading_rad,
                speed_mps=first.speed_mps,
                drop_time_s=first.drop_time_s + offset,
                fuse_fraction=first.fuse_time_s / maximum,
            )
            _, mask = scoring.candidate_coverage_mask(candidate, mode="fine")
            atoms.append(search.IntervalAtom(candidate=candidate, mask=mask))
        strategy, _ = search.interval_beam_select(atoms)

        self.assertTrue(search.validate_strategy(strategy))


if __name__ == "__main__":
    unittest.main()
