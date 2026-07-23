"""验证 Q3 双路径自洽复核不会接受伪挑战。"""

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


class Q3SelfConsistencyTests(unittest.TestCase):
    """覆盖不注入 incumbent 且必须可比复现或改善的质量门。"""

    def test_equal_challenger_is_rejected_even_when_other_declarations_pass(self) -> None:
        """挑战者复现 incumbent 不能被伪装为独立搜索成功。"""
        search = load_run_module("q3_search_adequacy")
        review = load_run_module("q3_self_consistency")
        scoring = load_run_module("coverage_scoring")
        strategy = search._strategy_from_unit(np.full(8, 0.25))  # noqa: SLF001
        score = scoring.score_strategy(list(strategy), mode="fine", missile="M1")
        document = {
            "question_id": "Q3",
            "family": "global",
            "selected_strategy": [asdict(item) for item in strategy],
            "metrics": {
                "q3_selected_fine_s": score.duration_s,
                "q3_baseline_preserved": True,
            },
            "calibration": {
                "search_adequacy": "passed",
                "sampling": {
                    "surrogate_top_k_used": False,
                    "family_counts": {
                        "independent_lhs": 1,
                        "boundary": 1,
                        "event_neighborhood": 1,
                    },
                },
            },
            "domain_coverage": {"passed": True},
        }
        challenger = json.loads(json.dumps(document))
        challenger["family"] = "challenge"
        challenger["challenge"] = {
            "search_adequacy": "passed",
            "diagnostics": {
                "candidate_pool_contains_incumbent": False,
                "independent_family": True,
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            global_path = root / "global.json"
            challenge_path = root / "challenge.json"
            global_path.write_text(json.dumps(document), encoding="utf-8")
            challenge_path.write_text(json.dumps(challenger), encoding="utf-8")
            report = review.review_q3(global_path, challenge_path)

        self.assertFalse(report["metrics"]["q3_search_adequacy_passed"])
        self.assertFalse(report["checks"]["challenge_comparable_or_improved"])
        self.assertEqual("candidate", report["quality_assessment"]["result_role"])

    def test_preregistered_comparable_challenge_is_accepted_after_exact_recompute(self) -> None:
        """冻结后达到预登记阈值的独立复现可与改善一样支持充分性。"""
        search = load_run_module("q3_search_adequacy")
        review = load_run_module("q3_self_consistency")
        scoring = load_run_module("coverage_scoring")
        strategy = search._strategy_from_unit(np.full(8, 0.25))  # noqa: SLF001
        score = scoring.score_strategy(list(strategy), mode="fine", missile="M1")
        document = {
            "question_id": "Q3",
            "family": "global",
            "selected_strategy": [asdict(item) for item in strategy],
            "metrics": {
                "q3_selected_fine_s": score.duration_s,
                "q3_baseline_preserved": True,
            },
            "calibration": {
                "search_adequacy": "passed",
                "sampling": {
                    "surrogate_top_k_used": False,
                    "family_counts": {
                        "independent_lhs": 1,
                        "boundary": 1,
                        "event_neighborhood": 1,
                    },
                },
            },
            "domain_coverage": {"passed": True},
        }
        challenger = json.loads(json.dumps(document))
        challenger["family"] = "challenge-review"
        challenger["challenge"] = {
            "search_adequacy": "passed",
            "diagnostics": {
                "candidate_pool_contains_incumbent": False,
                "independent_family": True,
                "incumbent_recomputed": True,
                "threshold_preregistered": True,
                "meets_comparable_threshold": True,
                "improved_incumbent": False,
            },
        }
        challenger["incumbent_recompute"] = {
            "hash_verified": True,
            "matches_preregistered_exact": True,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            global_path = root / "global.json"
            challenge_path = root / "challenge.json"
            global_path.write_text(json.dumps(document), encoding="utf-8")
            challenge_path.write_text(json.dumps(challenger), encoding="utf-8")
            report = review.review_q3(global_path, challenge_path)

        self.assertTrue(report["metrics"]["q3_search_adequacy_passed"])
        self.assertTrue(report["checks"]["challenge_comparable_or_improved"])
        self.assertEqual("accepted", report["quality_assessment"]["result_role"])


if __name__ == "__main__":
    unittest.main()
