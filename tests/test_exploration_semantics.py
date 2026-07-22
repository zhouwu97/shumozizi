"""验证探索路径不污染生产候选、论文和下游放行。"""

from __future__ import annotations

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
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import update_simple_state


class ExplorationSemanticsTests(unittest.TestCase):
    """覆盖探索可继续诊断、生产仍需有效上游质量的边界。"""

    def test_exploration_downstream_is_diagnostic_but_production_remains_gated(self) -> None:
        """探索可读取弱上游诊断，不能写入论文或绕过生产前序质量。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(
                Path(temporary),
                "exploration-boundary",
                required_questions=["Q1", "Q2"],
            )
            update_simple_state(run_dir, execution_mode="exploration", current_question="Q2")
            script = run_dir / "code" / "explore_q2.py"
            script.write_text(
                "import json\n"
                "from pathlib import Path\n"
                "Path('results/raw/explore-q2.json').write_text(\n"
                "    json.dumps({'metrics': {'objective': 1.0}}), encoding='utf-8'\n"
                ")\n",
                encoding="utf-8",
            )
            result = execute_simple_experiment(
                run_dir,
                result_id="explore_q2",
                question_id="Q2",
                kind="search",
                command=f'"{sys.executable}" code/explore_q2.py',
                expected_outputs=["results/raw/explore-q2.json"],
                metrics_from="results/raw/explore-q2.json",
            )
            diagnostic = assess_result_quality(
                run_dir,
                result_id="explore_q2",
                result_role="diagnostic",
                reasons=["exploration_only"],
            )

            self.assertTrue(result["success"], result["error"])
            self.assertEqual("exploration", read_result_index(run_dir)["results"][0]["execution_mode"])
            self.assertEqual("diagnostic", read_result_index(run_dir)["results"][0]["status"])
            self.assertEqual("diagnostic", diagnostic["result_role"])
            self.assertFalse(quality_allows_paper(run_dir, "explore_q2"))
            require_prior_question_quality(run_dir, "Q2", execution_mode="exploration")

            update_simple_state(run_dir, execution_mode="production")
            with self.assertRaisesRegex(ContractError, "Q2"):
                require_prior_question_quality(run_dir, "Q2", execution_mode="production")


if __name__ == "__main__":
    unittest.main()
