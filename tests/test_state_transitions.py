"""验证主状态转换与分阶段审核门。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError
from shumozizi.workflow.reviews import (
    create_review_request,
    materialize_review_receipt,
    write_review_report,
)
from shumozizi.workflow.state_service import (
    TRANSITIONS,
    Actor,
    StateService,
    WorkflowEvent,
)


def test_waiting_final_can_return_to_paper_fix() -> None:
    """视觉复核发现问题时不得被终稿等待状态锁死。"""
    assert TRANSITIONS[("WAITING_HUMAN_FINAL", WorkflowEvent.FIX_APPLIED)] == "PAPER_DRAFTED"


def test_qa_pass_cannot_enter_final_without_current_review_receipts(tmp_path: Path) -> None:
    """E2E 门禁：缺少 R3/R4/R5/J0 回执时不得进入最终人工确认。"""
    run_dir = tmp_path / "runs" / "gate-test"
    (run_dir / "review").mkdir(parents=True)
    state = {
        "schema_name": "workflow_state",
        "schema_version": "2.0",
        "run_schema_version": "2.0",
        "run_id": "gate-test",
        "problem_source": "problems/sample.md",
        "mode": "competition",
        "status": "QA_RUNNING",
        "revision": 7,
        "completed_stages": ["PAPER_DRAFTED"],
        "active_stage": "qa",
        "route_locked": True,
        "paper_ready": True,
        "question_progress": {},
        "review_gates": {
            "R3_PAPER_LOGIC": {"status": "pending", "receipt": None},
            "R4_FORMAT_VISUAL": {"status": "pending", "receipt": None},
            "R5_STANDARD_FINAL": {"status": "pending", "receipt": None},
            "J0_FINAL_BLIND_JUDGE": {"status": "pending", "receipt": None},
        },
        "artifacts": {},
        "last_updated_by": "test",
        "updated_at": "2026-07-19T00:00:00Z",
        "history": [],
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (run_dir / "review" / "QA_AGGREGATE.json").write_text(
        json.dumps({"status": "pass", "hard_failures": []}), encoding="utf-8"
    )

    with pytest.raises(ContractError, match="R3_PAPER_LOGIC"):
        StateService(tmp_path).transition(
            "gate-test",
            WorkflowEvent.QA_PASSED,
            Actor("test"),
            [],
        )


def test_formal_experiment_cannot_start_before_r1_passes(tmp_path: Path) -> None:
    """MODEL_SPEC_READY 后必须先通过 R1，才能进入 EXPERIMENTING。"""
    run_dir = tmp_path / "runs" / "r1-test"
    run_dir.mkdir(parents=True)
    state = {
        "schema_name": "workflow_state",
        "schema_version": "2.0",
        "run_schema_version": "2.0",
        "run_id": "r1-test",
        "problem_source": "problems/sample.md",
        "mode": "competition",
        "status": "MODEL_SPEC_READY",
        "revision": 3,
        "completed_stages": ["ROUTE_LOCKED"],
        "active_stage": "experiment",
        "route_locked": True,
        "paper_ready": False,
        "question_progress": {},
        "review_gates": {"R1_MODELING": {"status": "pending", "receipt": None}},
        "artifacts": {},
        "last_updated_by": "test",
        "updated_at": "2026-07-19T00:00:00Z",
        "history": [],
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(ContractError, match="R1_MODELING"):
        StateService(tmp_path).transition(
            "r1-test",
            WorkflowEvent.EXPERIMENT_STARTED,
            Actor("test"),
            [],
        )


def test_results_cannot_finish_before_each_question_r2_passes(tmp_path: Path) -> None:
    """问级实验完成后必须通过对应 R2，才能汇总为 RESULTS_ACCEPTED。"""
    run_dir = tmp_path / "runs" / "r2-test"
    run_dir.mkdir(parents=True)
    state = {
        "schema_name": "workflow_state",
        "schema_version": "2.0",
        "run_schema_version": "2.0",
        "run_id": "r2-test",
        "problem_source": "problems/sample.md",
        "mode": "competition",
        "status": "EXPERIMENTING",
        "revision": 5,
        "completed_stages": ["MODEL_SPEC_READY"],
        "active_stage": "experiment",
        "route_locked": True,
        "paper_ready": False,
        "question_progress": {"Q1": {"experiment": "accepted"}},
        "review_gates": {
            "R1_MODELING": {"status": "passed", "receipt": "review/r1/receipt.json"},
            "R2_EXPERIMENT_Q1": {"status": "pending", "receipt": None},
        },
        "artifacts": {},
        "last_updated_by": "test",
        "updated_at": "2026-07-19T00:00:00Z",
        "history": [],
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(ContractError, match="R2_EXPERIMENT_Q1"):
        StateService(tmp_path).transition(
            "r2-test",
            WorkflowEvent.RESULTS_ADMITTED,
            Actor("test"),
            [],
        )


def test_qa_cannot_start_before_r3_and_r4_pass(tmp_path: Path) -> None:
    """完整论文和 PDF 必须先通过 R3/R4，才能进入机械 QA。"""
    run_dir = tmp_path / "runs" / "paper-review-test"
    run_dir.mkdir(parents=True)
    state = {
        "schema_name": "workflow_state",
        "schema_version": "2.0",
        "run_schema_version": "2.0",
        "run_id": "paper-review-test",
        "problem_source": "problems/sample.md",
        "mode": "competition",
        "status": "PAPER_DRAFTED",
        "revision": 9,
        "completed_stages": ["RESULTS_ACCEPTED"],
        "active_stage": "qa",
        "route_locked": True,
        "paper_ready": True,
        "question_progress": {},
        "review_gates": {
            "R3_PAPER_LOGIC": {"status": "pending", "receipt": None},
            "R4_FORMAT_VISUAL": {"status": "pending", "receipt": None},
        },
        "artifacts": {},
        "last_updated_by": "test",
        "updated_at": "2026-07-19T00:00:00Z",
        "history": [],
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(ContractError, match="R3_PAPER_LOGIC"):
        StateService(tmp_path).transition(
            "paper-review-test",
            WorkflowEvent.QA_STARTED,
            Actor("test"),
            [],
        )


def test_real_r1_receipt_is_recorded_before_experiment(tmp_path: Path) -> None:
    """真实绑定的 R1 回执经 StateService 登记后才能启动实验。"""
    run_dir = tmp_path / "runs" / "r1-record-test"
    (run_dir / "brief").mkdir(parents=True)
    state = {
        "schema_name": "workflow_state",
        "schema_version": "2.0",
        "run_schema_version": "2.0",
        "run_id": "r1-record-test",
        "problem_source": "problems/sample.md",
        "mode": "competition",
        "status": "MODEL_SPEC_READY",
        "revision": 3,
        "completed_stages": ["ROUTE_LOCKED"],
        "active_stage": "experiment",
        "route_locked": True,
        "paper_ready": False,
        "question_progress": {},
        "review_gates": {"R1_MODELING": {"status": "pending", "receipt": None}},
        "artifacts": {},
        "last_updated_by": "test",
        "updated_at": "2026-07-19T00:00:00Z",
        "history": [],
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    model_spec = run_dir / "brief" / "model_spec.json"
    model_spec.write_text(json.dumps({"run_id": "r1-record-test"}), encoding="utf-8")
    request = create_review_request(
        run_dir,
        "R1_MODELING",
        {"model_spec": model_spec},
    )
    request_doc = json.loads(request.read_text(encoding="utf-8"))
    report = write_review_report(
        request,
        {
            "schema_name": "review_report",
            "schema_version": "2.0",
            "request_id": request_doc["request_id"],
            "run_id": "r1-record-test",
            "stage": "R1_MODELING",
            "review_round_id": request_doc["review_round_id"],
            "verdict": "ACCEPT",
            "findings": [],
            "read_only_confirmed": True,
            "generated_at": "2026-07-19T00:00:00Z",
        },
    )
    receipt = materialize_review_receipt(request, report)
    service = StateService(tmp_path)

    recorded = service.record_review_gate(
        "r1-record-test", "R1_MODELING", receipt, Actor("review-coordinator")
    )
    progressed = service.transition(
        "r1-record-test", WorkflowEvent.EXPERIMENT_STARTED, Actor("experiment"), []
    )

    assert recorded["review_gates"]["R1_MODELING"]["status"] == "passed"
    assert progressed["status"] == "EXPERIMENTING"
