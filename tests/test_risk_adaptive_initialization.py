"""验证新 Competition-First 运行默认启用风险自适应执行策略。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError
from shumozizi.simple.execution import execute_simple_experiment
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.state import enable_risk_adaptive_execution_policy


def test_v32_cli_initializes_risk_adaptive_exploration(tmp_path: Path) -> None:
    """新 v3.2 CLI 运行必须先探索，不能依赖 Agent 主动切换旧 production 默认。"""
    runner = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "codex"
        / "init_simple_run.py"
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(runner),
            "--repo-root",
            str(tmp_path),
            "--run-id",
            "risk-adaptive-default",
            "--workflow-version",
            "3.2",
            "--question",
            "Q1",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    state = json.loads(
        (Path(payload["run_dir"]) / "state" / "run.json").read_text(encoding="utf-8")
    )
    assert state["execution_mode"] == "exploration"
    assert state["execution_policy"] == "risk-adaptive-v1"


def test_risk_adaptive_production_is_blocked_before_command_without_risk_route(
    tmp_path: Path,
) -> None:
    """风险自适应运行未闭合前置攻击时，production 命令不得被启动。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "risk-gate",
        required_questions=["Q1"],
        workflow_version="3.2",
        initial_execution_mode="exploration",
        execution_policy="risk-adaptive-v1",
    )
    script = run_dir / "code" / "must_not_run.py"
    script.write_text(
        "from pathlib import Path\nPath('command-ran.txt').write_text('ran')\n",
        encoding="utf-8",
    )

    with pytest.raises(ContractError, match="风险|risk|MODELING_UNITS"):
        execute_simple_experiment(
            run_dir,
            result_id="premature-production",
            question_id="Q1",
            kind="baseline",
            command=f'{sys.executable} "{script}"',
            expected_outputs=["command-ran.txt"],
            execution_mode="production",
        )

    assert not (run_dir / "command-ran.txt").exists()


def test_legacy_v32_run_without_production_can_be_safely_migrated(
    tmp_path: Path,
) -> None:
    """旧默认创建但尚未正式求解的运行应可无损切换到新策略。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "legacy-clean-run",
        required_questions=["Q1"],
        workflow_version="3.2",
    )

    state = enable_risk_adaptive_execution_policy(run_dir)

    assert state["execution_mode"] == "exploration"
    assert state["execution_policy"] == "risk-adaptive-v1"
    assert state["revision"] == 1
