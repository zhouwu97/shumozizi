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
SIMPLE_INITIALIZER = REPO_ROOT / "scripts" / "codex" / "init_simple_run.py"
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
            self.assertTrue((run_dir / "experiments" / "plans").is_dir())
            self.assertTrue((run_dir / "claims").is_dir())
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

    def test_competition_v32_defaults_to_longform_scientific_draft(self) -> None:
        """README 主入口创建 v3.2 运行时必须默认走长篇 Author 路径。"""
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary)
            environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}

            initialized = subprocess.run(
                [
                    sys.executable,
                    str(INITIALIZER),
                    "--workflow",
                    "competition-first-v3.2",
                    "--run-id",
                    "competition-001",
                    "--question",
                    "Q1",
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
            draft_mode = json.loads(
                (repo_root / "runs" / "competition-001" / "paper" / "draft-mode.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual("longform_scientific_draft", draft_mode["default_mode"])

    def test_simple_initializer_uses_the_same_longform_default(self) -> None:
        """轻量入口必须复用主入口的 Author 首稿默认值。"""
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary)
            environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}

            initialized = subprocess.run(
                [
                    sys.executable,
                    str(SIMPLE_INITIALIZER),
                    "--run-id",
                    "simple-competition-001",
                    "--question",
                    "Q1",
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
            draft_mode = json.loads(
                (
                    repo_root
                    / "runs"
                    / "simple-competition-001"
                    / "paper"
                    / "draft-mode.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual("longform_scientific_draft", draft_mode["default_mode"])


if __name__ == "__main__":
    unittest.main()
