"""验证 Q4 三机全域搜索的联合覆盖与硬约束。"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

RUN_CODE = Path(__file__).resolve().parents[1] / "runs" / "cumcm-2025-a-v3-001" / "code"
if str(RUN_CODE) not in sys.path:
    sys.path.insert(0, str(RUN_CODE))


def load(name: str):
    specification = importlib.util.spec_from_file_location(name, RUN_CODE / f"{name}.py")
    if specification is None or specification.loader is None:
        raise RuntimeError(name)
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


class Q4MultiUavSearchTests(unittest.TestCase):
    """覆盖多平台变量不能退化为 FY1 局部域。"""

    def test_global_designs_cover_each_uav_and_cross_heading_space(self) -> None:
        search = load("q4_multi_uav_search")
        coverage = search.domain_coverage(
            search.design_rows(seed=20250740, count=64, family="global")
        )

        self.assertTrue(coverage["passed"])
        self.assertTrue(all(item["passed"] for item in coverage["per_uav_joint"]))
        self.assertTrue(coverage["heading_cross_joint"]["passed"])

    def test_exact_final_selection_cannot_discard_feasible_baseline(self) -> None:
        search = load("q4_multi_uav_search")
        baseline = search.q3_lower_bound(
            RUN_CODE.parent / "results/raw/q3_interval_self_consistency_r1.json"
        )
        bad = tuple(
            search.candidate_from_feasible_parameters(
                heading_rad=0.0,
                speed_mps=70.0,
                drop_time_s=0.0,
                fuse_fraction=0.01,
                uav=uav,
                missile="M1",
            )
            for uav in search.UAVS_Q4
        )
        selected, score = search.choose_with_baseline(baseline, bad)

        self.assertEqual(baseline, selected)
        self.assertGreater(score, 0.0)
