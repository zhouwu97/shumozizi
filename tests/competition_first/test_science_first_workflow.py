from __future__ import annotations

from pathlib import Path

from shumozizi.paper.advanced_figure_policy import advanced_figure_quota_payload
from shumozizi.paper.policy import workflow_quality_policy
from shumozizi.paper.readiness import _advanced_figure_quota_errors
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.science_checkpoint import (
    require_science_checkpoint,
    science_checkpoint_status,
    update_science_checkpoint,
)
from shumozizi.simple.state import read_simple_state, update_simple_state


def _new_run(tmp_path: Path) -> Path:
    return initialize_simple_run(
        tmp_path,
        "science-first",
        workflow_version="3.2",
        required_questions=["Q1"],
        initial_execution_mode="exploration",
        execution_policy="science-first-v1",
        quality_policy="science-editorial-v1",
    )


def test_new_science_first_run_has_thin_checkpoint_and_editorial_policy(tmp_path: Path) -> None:
    run_dir = _new_run(tmp_path)
    state = read_simple_state(run_dir)
    assert state["execution_policy"] == "science-first-v1"
    assert workflow_quality_policy(run_dir) == "science-editorial-v1"
    assert not science_checkpoint_status(run_dir)["ready"]


def test_checkpoint_requires_challenger_and_falsification_before_ready(tmp_path: Path) -> None:
    run_dir = _new_run(tmp_path)
    update_science_checkpoint(
        run_dir,
        {
            "semantic_contract": {
                "objective": "minimize cost",
                "information_set": "only data available at t",
                "time_and_units": "15 minute and kWh",
                "settlement_and_terminal_rules": "contract settlement at horizon end",
                "aggregation": "sum over periods",
            },
            "routes": {"baseline": "rule", "challenger": "joint", "scorer": "exact"},
            "falsification": {
                "minimum_counterexample": "future price is unavailable",
                "expected_result": "future price must not change action",
            },
        },
        status="ready",
    )
    assert science_checkpoint_status(run_dir)["ready"]
    assert require_science_checkpoint(run_dir)["status"] == "ready"


def test_science_first_checkpoint_replaces_full_experiment_schema_gate(tmp_path: Path) -> None:
    run_dir = _new_run(tmp_path)
    update_science_checkpoint(
        run_dir,
        {
            "semantic_contract": {
                "objective": "minimize cost",
                "information_set": "data available at t",
                "time_and_units": "period and kWh",
                "settlement_and_terminal_rules": "settle at horizon end",
                "aggregation": "sum over periods",
            },
            "routes": {"baseline": "rule", "challenger": "joint", "scorer": "exact"},
            "falsification": {"minimum_counterexample": "future data", "expected_result": "no leakage"},
        },
        status="ready",
    )
    state = update_simple_state(run_dir, phase="experiment")
    assert state["phase"] == "experiment"


def test_science_editorial_policy_does_not_block_on_figure_count(tmp_path: Path) -> None:
    run_dir = _new_run(tmp_path)
    assert _advanced_figure_quota_errors(run_dir) == []
    payload = advanced_figure_quota_payload(4)
    assert payload["minimum_formal_current_figures"] == 13
