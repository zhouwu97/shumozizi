"""验证运行目录初始化和首次恢复入口。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INITIALIZER = REPO_ROOT / "scripts" / "codex" / "init_run.py"
VALIDATOR = REPO_ROOT / "scripts" / "codex" / "validate_state.py"


class InitRunCliTests(unittest.TestCase):
    """覆盖用户实际调用的初始化命令。"""

    def test_initializes_json_route_lock_template_and_valid_new_state(self) -> None:
        """新运行应可立即通过状态恢复校验。"""
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary)
            problem = repo_root / "problems" / "sample" / "problem.md"
            problem.parent.mkdir(parents=True)
            problem.write_text("求解一个最小数学建模问题。\n", encoding="utf-8")
            environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}

            initialized = subprocess.run(
                [
                    sys.executable,
                    str(INITIALIZER),
                    str(problem),
                    "--run-id",
                    "sample-001",
                    "--mode",
                    "training",
                    "--repo-root",
                    str(repo_root),
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
            )
            self.assertEqual(0, initialized.returncode, initialized.stderr)
            run_dir = repo_root / "runs" / "sample-001"
            self.assertTrue((run_dir / "brief" / "ROUTE_LOCK.template.json").is_file())
            self.assertFalse((run_dir / "brief" / "ROUTE_LOCK.template.yaml").exists())

            validated = subprocess.run(
                [sys.executable, str(VALIDATOR), str(run_dir)],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
            )
            payload = json.loads(validated.stdout)
            self.assertEqual(0, validated.returncode, payload["errors"])
            self.assertEqual("NEW", payload["status"])
            self.assertTrue(payload["valid"])


if __name__ == "__main__":
    unittest.main()
