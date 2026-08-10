"""验证探索路径不污染生产候选、论文和下游放行。"""

from __future__ import annotations

import json
import subprocess
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

    def test_cli_exploration_never_replaces_current_production_result(self) -> None:
        """CLI 省略用途时继承运行状态，显式 production 仍可覆盖该状态。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "cli-exploration-boundary")
            script = run_dir / "code" / "write_result.py"
            script.write_text(
                "import json\n"
                "import sys\n"
                "from pathlib import Path\n"
                "Path(sys.argv[1]).write_text(\n"
                "    json.dumps({'metrics': {'objective': 1.0}}), encoding='utf-8'\n"
                ")\n",
                encoding="utf-8",
            )
            runner = (
                Path(__file__).resolve().parents[1]
                / "scripts"
                / "runtime"
                / "run_simple_experiment.py"
            )

            def run_cli(
                *,
                result_id: str,
                output: str,
                mode: str | None,
                kind: str = "baseline",
            ) -> dict[str, object]:
                """调用真实 CLI，避免只覆盖内部 Python 参数转发。"""
                command = [
                    sys.executable,
                    str(runner),
                    str(run_dir),
                    "--question",
                    "Q1",
                    "--kind",
                    kind,
                    "--result-id",
                    result_id,
                    "--command",
                    f'"{sys.executable}" code/write_result.py {output}',
                    "--expect",
                    output,
                    "--metrics-from",
                    output,
                ]
                if mode is not None:
                    command.extend(["--execution-mode", mode])
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=False,
                )
                self.assertEqual(0, completed.returncode, completed.stderr)
                return json.loads(completed.stdout)

            production = run_cli(
                result_id="production_baseline",
                output="results/raw/production-baseline.json",
                mode="production",
            )
            self.assertTrue(production["success"])

            # 旧 CLI 调用本来继承运行状态；新增参数不能让漏传 mode 的探索命令
            # 悄然写入 production。需要正式重跑时必须显式声明 production。
            update_simple_state(run_dir, execution_mode="exploration")
            inherited_exploration = run_cli(
                result_id="inherited_exploration",
                output="results/raw/inherited-exploration.json",
                mode=None,
                kind="sanity",
            )
            self.assertTrue(inherited_exploration["success"])

            explicit_production = run_cli(
                result_id="explicit_production",
                output="results/raw/explicit-production.json",
                mode="production",
                kind="sanity",
            )
            self.assertTrue(explicit_production["success"])

            exploration = run_cli(
                result_id="exploration_baseline",
                output="results/raw/exploration-baseline.json",
                mode="exploration",
            )
            self.assertTrue(exploration["success"])

            indexed = {
                item["result_id"]: item for item in read_result_index(run_dir)["results"]
            }
            self.assertEqual("current", indexed["production_baseline"]["status"])
            self.assertEqual("exploration", indexed["inherited_exploration"]["execution_mode"])
            self.assertEqual("diagnostic", indexed["inherited_exploration"]["status"])
            self.assertTrue(indexed["inherited_exploration"]["provisional"])
            self.assertEqual("production", indexed["explicit_production"]["execution_mode"])
            self.assertEqual("current", indexed["explicit_production"]["status"])
            self.assertFalse(indexed["explicit_production"]["provisional"])
            self.assertEqual("diagnostic", indexed["exploration_baseline"]["status"])
            self.assertEqual("exploration", indexed["exploration_baseline"]["execution_mode"])
            self.assertTrue(indexed["exploration_baseline"]["provisional"])

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
