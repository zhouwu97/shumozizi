"""验证 Capability-First v3 的最小状态转换边界。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shumozizi.core.io import ContractError
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.state import update_simple_state


class SimpleStateTransitionTests(unittest.TestCase):
    """验证阻断状态只能回到生产阶段，不能跳过恢复。"""

    def test_blocked_run_rejects_paper_but_allows_experiment_recovery(self) -> None:
        """阻断运行必须先恢复分析或实验，不能直接进入交付阶段。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "transition-test")
            update_simple_state(run_dir, phase="blocked")

            with self.assertRaisesRegex(ContractError, "blocked.*paper"):
                update_simple_state(run_dir, phase="paper")

            recovered = update_simple_state(run_dir, phase="experiment", current_question="Q2")

        self.assertEqual("experiment", recovered["phase"])
        self.assertEqual("Q2", recovered["current_question"])


if __name__ == "__main__":
    unittest.main()
