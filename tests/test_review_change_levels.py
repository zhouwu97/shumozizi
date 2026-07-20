"""L0-L5 修改等级的状态回退和审核门失效测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json
from shumozizi.workflow.review_policy import get_review_stage_policy
from shumozizi.workflow.state_service import Actor, StateService


def _write_reviewed_state(tmp_path: Path, run_id: str) -> Path:
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    gate_ids = (
        "R1_MODELING",
        "R2_EXPERIMENT_q1",
        "R2_EXPERIMENT_q2",
        "R3_PAPER_LOGIC_q1",
        "R3_PAPER_LOGIC_q2",
        "R3_PAPER_LOGIC",
        "R4_FORMAT_VISUAL",
        "R5_STANDARD_FINAL",
    )
    atomic_json(
        run_dir / "state.json",
        {
            "schema_name": "workflow_state",
            "schema_version": "2.0",
            "run_schema_version": "2.0",
            "run_id": run_id,
            "problem_source": "problems/sample.md",
            "mode": "competition",
            "status": "WAITING_HUMAN_FINAL",
            "revision": 20,
            "completed_stages": ["PAPER_DRAFTED", "QA_RUNNING"],
            "active_stage": "final_approval",
            "route_locked": True,
            "paper_ready": True,
            "question_progress": {
                question: {track: "accepted" for track in ("model", "experiment", "paper", "review")}
                for question in ("q1", "q2")
            },
            "review_gates": {
                gate_id: {"status": "passed", "receipt": f"review/{gate_id}.json"}
                for gate_id in gate_ids
            },
            "artifacts": {},
            "last_updated_by": "test",
            "updated_at": "2026-07-20T00:00:00Z",
            "history": [],
        },
    )
    return run_dir


def test_l1_only_stales_r4_and_submission_snapshot(tmp_path: Path) -> None:
    run_dir = _write_reviewed_state(tmp_path, "l1")
    state = StateService(tmp_path).record_change_impact("l1", "L1", [], Actor("test"))

    assert state["status"] == "PAPER_DRAFTED"
    assert state["review_gates"]["R4_FORMAT_VISUAL"]["status"] == "stale"
    assert state["review_gates"]["R3_PAPER_LOGIC"]["status"] == "passed"
    assert state["review_gates"]["R5_STANDARD_FINAL"]["status"] == "passed"
    assert run_dir.joinpath("state.json").is_file()


def test_l2_does_not_stale_r1_or_r2(tmp_path: Path) -> None:
    _write_reviewed_state(tmp_path, "l2")
    state = StateService(tmp_path).record_change_impact("l2", "L2", ["q2"], Actor("test"))

    assert state["review_gates"]["R1_MODELING"]["status"] == "passed"
    assert state["review_gates"]["R2_EXPERIMENT_q2"]["status"] == "passed"
    assert state["review_gates"]["R3_PAPER_LOGIC_q2"]["status"] == "stale"
    assert state["question_progress"]["q2"]["paper"] == "stale"


def test_l4_stays_inside_approved_route(tmp_path: Path) -> None:
    _write_reviewed_state(tmp_path, "l4")
    state = StateService(tmp_path).record_change_impact("l4", "L4", ["q2"], Actor("test"))

    assert state["status"] == "MODEL_SPEC_READY"
    assert state["route_locked"] is True
    assert state["review_gates"]["R1_MODELING"]["status"] == "stale"
    assert state["review_gates"]["R2_EXPERIMENT_q1"]["status"] == "passed"
    assert state["question_progress"]["q1"]["model"] == "accepted"


def test_l5_returns_to_route_approval_and_stales_all_scopes(tmp_path: Path) -> None:
    _write_reviewed_state(tmp_path, "l5")
    state = StateService(tmp_path).record_change_impact("l5", "L5", [], Actor("test"))

    assert state["status"] == "WAITING_HUMAN_ROUTE"
    assert state["route_locked"] is False
    assert all(gate["status"] == "stale" for gate in state["review_gates"].values())
    assert state["question_progress"]["q1"]["model"] == "stale"
    assert state["question_progress"]["q2"]["review"] == "stale"


def test_local_r3_requires_question_r2_and_ready_paper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = tmp_path / "runs" / "local-r3"
    run_dir.mkdir(parents=True)
    service = StateService(tmp_path)
    state = {
        "status": "EXPERIMENTING",
        "question_progress": {"q1": {"experiment": "ready", "paper": "ready"}},
        "review_gates": {},
    }

    policy = get_review_stage_policy("R3_PAPER_LOGIC", run_dir, question_id="q1")
    assert "paper_source" in policy["mandatory_inputs"]
    assert "final_pdf" in policy["optional_inputs"]

    with pytest.raises(ContractError, match="审核门未通过"):
        service._check_review_gate_timing(run_dir, state, "R3_PAPER_LOGIC_q1", "q1")

    monkeypatch.setattr(service, "_require_passed_review_gates", lambda *_args: None)
    state["question_progress"]["q1"]["paper"] = "pending"
    with pytest.raises(ContractError, match="章节未完成"):
        service._check_review_gate_timing(run_dir, state, "R3_PAPER_LOGIC_q1", "q1")
    state["question_progress"]["q1"]["paper"] = "accepted"
    service._check_review_gate_timing(run_dir, state, "R3_PAPER_LOGIC_q1", "q1")
