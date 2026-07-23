"""验证真实 CUMCM 2025 A 运行的恢复性求解边界。"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from shumozizi.core.io import ContractError
from shumozizi.simple.execution import execute_simple_experiment
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.quality import assess_result_quality
from shumozizi.simple.state import update_simple_state
from tests.capability_flow_helpers import prepare_minimal_capability_route

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_CODE = REPO_ROOT / "runs" / "cumcm-2025-a-v3-001" / "code"
if str(RUN_CODE) not in sys.path:
    sys.path.insert(0, str(RUN_CODE))


def load_run_module(name: str):
    """从唯一真实 run 加载待验证模块。

    Args:
        name: 不含扩展名的运行内模块名。

    Returns:
        已加载的模块对象。
    """
    path = RUN_CODE / f"{name}.py"
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"无法加载运行模块: {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


class Cumcm2025ARecoveryTests(unittest.TestCase):
    """只覆盖当前真实 run 的 Q1/Q2 恢复性不变量。"""

    def test_q1_baseline_recovers_with_shared_candidate_scorer(self) -> None:
        """Q1 固定策略必须在候选评分器中恢复已登记的粗细评分。"""
        scoring = load_run_module("coverage_scoring")
        baseline = scoring.q1_fixed_baseline()

        coarse = scoring.score_candidate(baseline, mode="proxy")
        fine = scoring.score_candidate(baseline, mode="fine")

        self.assertAlmostEqual(1.4, coarse.duration_s, delta=0.051)
        self.assertAlmostEqual(1.392, fine.duration_s, delta=0.003)
        self.assertTrue(coarse.feasible)
        self.assertTrue(fine.feasible)

    def test_q2_seed_pool_forces_baseline_and_never_returns_worse_fine_score(self) -> None:
        """Q2 退化搜索必须可回退基线，不能输出零分随机候选。"""
        scoring = load_run_module("coverage_scoring")
        recovery = load_run_module("q2_recovery")
        baseline = scoring.q1_fixed_baseline()
        deliberately_worse = scoring.Candidate(
            heading_rad=0.0,
            speed_mps=140.0,
            drop_time_s=50.0,
            fuse_time_s=0.1,
        )

        pool = recovery.seed_candidate_pool(seed=20250724, random_count=0)
        selected, diagnostics = recovery.select_final_candidate([baseline, deliberately_worse])

        self.assertEqual(baseline, pool[0])
        self.assertEqual(baseline, selected)
        self.assertEqual("failed_to_improve", diagnostics["improvement_status"])
        self.assertGreaterEqual(
            diagnostics["selected_fine_score"], diagnostics["baseline_fine_score"]
        )
        self.assertTrue(diagnostics["baseline_recovered"])

    def test_feasible_multi_bomb_score_recovers_its_single_bomb_baseline(self) -> None:
        """多弹并集评分必须保留其中已知可行单弹的细算遮蔽时长。"""
        scoring = load_run_module("coverage_scoring")
        baseline = scoring.q1_fixed_baseline()
        extra_bomb = scoring.candidate_from_feasible_parameters(
            heading_rad=baseline.heading_rad,
            speed_mps=baseline.speed_mps,
            drop_time_s=4.0,
            fuse_fraction=0.50,
        )

        single = scoring.score_candidate(baseline, mode="fine")
        union = scoring.score_strategy([baseline, extra_bomb], mode="fine", missile="M1")

        self.assertTrue(union.feasible)
        self.assertGreaterEqual(union.duration_s + 0.001, single.duration_s)

    def test_q3_pool_forces_recovered_q2_strategy_and_never_returns_worse_fine_score(self) -> None:
        """Q3 三弹搜索必须保留 Q2 已验证策略，并以同一细算评分器兜底。"""
        recovery = load_run_module("q3_recovery")
        baseline = recovery.q3_baseline(
            RUN_CODE.parent / "results" / "raw" / "q2_recovery_seed_20250724.json"
        )
        pool = recovery.seed_strategy_pool(baseline, seed=20250726, random_count=0)
        selected, diagnostics = recovery.select_final_strategy([baseline])

        self.assertEqual(baseline, pool[0])
        self.assertEqual(baseline, selected)
        self.assertTrue(diagnostics["baseline_recovered"])
        self.assertEqual("failed_to_improve", diagnostics["improvement_status"])
        self.assertGreaterEqual(
            diagnostics["selected_fine_score"], diagnostics["baseline_fine_score"]
        )

    def test_q3_final_selection_recomputes_a_usable_seed_with_shared_fine_scorer(self) -> None:
        """Q3 提交前必须从科学成功种子重算细网格，而非复制声明值。"""
        finalizer = load_run_module("q3_finalize")
        selected, document = finalizer.select_reproducible_strategy(
            [
                RUN_CODE.parent / "results" / "raw" / "q3_recovery_seed_20250726.json",
                RUN_CODE.parent / "results" / "raw" / "q3_recovery_seed_20250727.json",
            ]
        )

        self.assertEqual(3, len(selected))
        self.assertTrue(document["metrics"]["q3_scientific_success"])
        self.assertAlmostEqual(2.237, document["metrics"]["q3_selected_fine_s"], delta=0.003)

    def test_q3_is_blocked_without_two_usable_q2_recovery_records(self) -> None:
        """Q2 的恢复证据不足时，代码入口必须拒绝启动 Q3。"""
        progression = load_run_module("problem_progression")
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "isolated-progress")
            prepare_minimal_capability_route(run_dir)
            update_simple_state(run_dir, current_question="Q2")

            with self.assertRaisesRegex(ContractError, "Q2"):
                progression.require_prior_question_success(run_dir, "Q3")

    def test_q2_legacy_self_consistency_cannot_bypass_adapter_verification(self) -> None:
        """旧 Q2 自洽标记不得绕过三段独立验证后解锁 Q3。"""
        progression = load_run_module("problem_progression")
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "adequacy-progress")
            prepare_minimal_capability_route(run_dir)
            update_simple_state(run_dir, current_question="Q2")
            script = run_dir / "code" / "q2.py"
            script.write_text(
                "from pathlib import Path\n"
                "import json\n"
                "Path('results/raw/q2.json').write_text(\n"
                "    json.dumps({'metrics': {'q2_search_adequacy_passed': True}}),\n"
                "    encoding='utf-8',\n"
                ")\n",
                encoding="utf-8",
            )
            execute_simple_experiment(
                run_dir,
                result_id="q2_self_consistency",
                question_id="Q2",
                kind="self-consistency",
                command=f'"{sys.executable}" code/q2.py',
                expected_outputs=["results/raw/q2.json"],
                metrics_from="results/raw/q2.json",
            )
            with self.assertRaisesRegex(ContractError, "adapter verification"):
                assess_result_quality(
                    run_dir,
                    result_id="q2_self_consistency",
                    feasibility_valid=True,
                    baseline_preserved=True,
                    search_adequacy="passed",
                    result_role="accepted",
                    reasons=["search_adequacy_passed"],
                )

            with self.assertRaisesRegex(ContractError, "Q2"):
                progression.require_prior_question_success(run_dir, "Q3")

    def test_q3_raw_search_cannot_bypass_adapter_verification_for_q4(self) -> None:
        """Q3 单路径自报质量不得绕过独立验证后解锁 Q4。"""
        progression = load_run_module("problem_progression")
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "q3-raw-progress")
            prepare_minimal_capability_route(run_dir)
            update_simple_state(run_dir, current_question="Q3")
            script = run_dir / "code" / "q3.py"
            script.write_text(
                "from pathlib import Path\n"
                "import json\n"
                "Path('results/raw/q3.json').write_text(\n"
                "    json.dumps({'metrics': {'q3_search_adequacy_passed': True}}),\n"
                "    encoding='utf-8',\n"
                ")\n",
                encoding="utf-8",
            )
            execute_simple_experiment(
                run_dir,
                result_id="q3_raw_search",
                question_id="Q3",
                kind="adequacy-challenge-r1",
                command=f'"{sys.executable}" code/q3.py',
                expected_outputs=["results/raw/q3.json"],
                metrics_from="results/raw/q3.json",
            )
            with self.assertRaisesRegex(ContractError, "adapter verification"):
                assess_result_quality(
                    run_dir,
                    result_id="q3_raw_search",
                    feasibility_valid=True,
                    baseline_preserved=True,
                    search_adequacy="passed",
                    result_role="accepted",
                    reasons=["raw_search_only"],
                )

            with self.assertRaisesRegex(ContractError, "Q3"):
                progression.require_prior_question_success(run_dir, "Q4")

    def test_q2_global_family_covers_full_angle_ring_not_only_baseline_neighborhood(self) -> None:
        """弱上游基线不得收窄 Q2 的航向、速度、投放或近零引信搜索域。"""
        search = load_run_module("q2_search_adequacy")
        candidates = search.global_candidates(seed=20250730, count=256)
        coverage = search.domain_coverage(candidates)

        self.assertTrue(coverage["passed"])
        self.assertEqual(16, coverage["heading_bins_covered"])
        self.assertLessEqual(coverage["fuse_fraction_min"], 0.01)
        self.assertLessEqual(coverage["drop_min_s"], 0.2)

    def test_q2_joint_coverage_rejects_diagonal_samples_with_complete_marginals(self) -> None:
        """航向等边际完整但四维样本仅沿对角线时不得宣称全域覆盖。"""
        search = load_run_module("q2_search_adequacy")
        diagonal = [
            search._from_unit(np.array([(index + 0.5) / 16, index / 15, index / 15, index / 15]))  # noqa: SLF001
            for index in range(16)
        ]
        coverage = search.domain_coverage(diagonal)

        self.assertEqual(16, coverage["heading_bins_covered"])
        self.assertFalse(coverage["passed"])
        self.assertLess(coverage["joint_coverage_ratio"], 0.10)

    def test_q3_global_family_keeps_full_ring_and_joint_domain(self) -> None:
        """Q3 的 Q2 下界只能作恢复锚点，不得压缩新的八维全域域。"""
        search = load_run_module("q3_search_adequacy")
        strategies = search.global_strategies(seed=20250736, count=256)
        coverage = search.domain_coverage(strategies)

        self.assertTrue(coverage["passed"])
        self.assertEqual(16, coverage["heading_bins_covered"])
        self.assertGreaterEqual(coverage["joint_coverage_ratio"], 0.55)
        self.assertTrue(search.valid(strategies[0]))


if __name__ == "__main__":
    unittest.main()
