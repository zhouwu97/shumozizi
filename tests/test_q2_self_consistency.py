"""验证 Q2 只由当前 run 的两条独立搜索记录自洽放行。"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

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


class Q2SelfConsistencyTests(unittest.TestCase):
    """覆盖双路径复核的真实评分与独立性不变量。"""

    def test_current_global_and_challenge_outputs_pass_self_consistency(self) -> None:
        """全域与挑战输出必须各自通过校准、覆盖和 exact 重算。"""
        review = load_run_module("q2_self_consistency")

        report = review.review_q2(
            RUN_DIR / "results/raw/q2_adequacy_global_r4.json",
            RUN_DIR / "results/raw/q2_adequacy_challenge_r3.json",
        )

        self.assertTrue(report["quality_assessment"]["feasibility_valid"])
        self.assertTrue(report["quality_assessment"]["baseline_preserved"])
        self.assertEqual("passed", report["quality_assessment"]["search_adequacy"])
        self.assertTrue(report["metrics"]["q2_search_adequacy_passed"])
        self.assertGreater(
            report["challenge_exact_fine_s"], report["global_exact_fine_s"]
        )


if __name__ == "__main__":
    unittest.main()
