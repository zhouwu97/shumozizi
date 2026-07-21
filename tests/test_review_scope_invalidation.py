"""问级审核失效与 finding 定向返工测试。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.workflow.repair import create_repair_plan
from shumozizi.workflow.state_service import Actor, StateService
from tests.test_review_change_levels import _write_reviewed_state


def _accepted_adjudication(report_path: Path, *, effective_level: str) -> Path:
    """为直接测试 repair producer 写入一份已接受裁决。"""
    report = load_json(report_path)
    finding = report["findings"][0]
    path = report_path.with_name("REVIEW_ADJUDICATION.json")
    atomic_json(
        path,
        {
            "schema_name": "review_adjudication",
            "schema_version": "2.0",
            "run_id": report["run_id"],
            "request_id": report["request_id"],
            "stage": report["stage"],
            "state_revision": 0,
            "review_report_sha256": sha256_file(report_path),
            "decisions": [
                {
                    "finding_id": finding["finding_id"],
                    "reviewer_severity": finding["severity"],
                    "main_decision": "accepted",
                    "effective_severity": finding["severity"],
                    "gate_effect": "block",
                    "decision_reason": "独立核验后接受",
                    "confirmation_evidence": ["test:confirmed"],
                    "counter_evidence": [],
                    "resolution_evidence_type": None,
                    "effective_change_level": effective_level,
                    "affected_questions": finding["affected_questions"],
                    "required_retests": [],
                    "route_reapproval_required": effective_level == "L5",
                }
            ],
            "unresolved_conflicts": [],
            "generated_by": "production_main_ai",
            "generated_at": "2026-07-20T00:00:00Z",
        },
    )
    return path


def test_q2_l3_preserves_q1_r2_and_local_r3(tmp_path: Path) -> None:
    _write_reviewed_state(tmp_path, "q2-l3")
    state = StateService(tmp_path).record_change_impact(
        "q2-l3", "L3", ["q2"], Actor("test")
    )

    assert state["review_gates"]["R2_EXPERIMENT_q1"]["status"] == "passed"
    assert state["review_gates"]["R3_PAPER_LOGIC_q1"]["status"] == "passed"
    assert state["review_gates"]["R2_EXPERIMENT_q2"]["status"] == "stale"
    assert state["review_gates"]["R3_PAPER_LOGIC_q2"]["status"] == "stale"
    assert state["question_progress"]["q1"]["experiment"] == "accepted"
    assert state["question_progress"]["q2"]["experiment"] == "stale"


def test_scope_invalidation_rejects_unknown_question(tmp_path: Path) -> None:
    _write_reviewed_state(tmp_path, "unknown-question")

    with pytest.raises(ContractError, match="未知问题"):
        StateService(tmp_path).record_change_impact(
            "unknown-question", "L3", ["q3"], Actor("test")
        )


def test_repair_plan_uses_finding_scope_instead_of_review_number(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs/repair-scope"
    report_dir = run_dir / "review/r5/round-1"
    report_dir.mkdir(parents=True)
    atomic_json(report_dir / "review_request.json", {"question_id": None})
    report_path = report_dir / "review_report.json"
    atomic_json(
        report_path,
        {
            "schema_name": "review_report",
            "schema_version": "2.0",
            "request_id": "request-1",
            "run_id": "repair-scope",
            "stage": "R3_PAPER_LOGIC",
            "review_round_id": "round-1",
            "request_sha256": "a" * 64,
            "input_manifest_sha256": "b" * 64,
            "session_sha256": "c" * 64,
            "verdict": "MAJOR_REVISION",
            "findings": [
                {
                    "finding_id": "R3-F1",
                    "severity": "P1",
                    "title": "第二问结果已变化",
                    "evidence": ["paper/sections/q2.typ"],
                    "remediation": "重跑第二问证据链",
                    "status": "open",
                    "affected_stage": "R2_EXPERIMENT",
                    "affected_questions": ["q2"],
                    "change_level": "L3",
                    "change_class": "IMPLEMENTATION_DETAIL",
                    "route_impact": "none",
                    "changed_route_core_fields": [],
                }
            ],
            "read_only_confirmed": True,
            "generated_at": "2026-07-20T00:00:00Z",
        },
    )

    adjudication = _accepted_adjudication(report_path, effective_level="L3")
    repair = load_json(create_repair_plan(run_dir, report_path, adjudication))

    assert repair["change_level"] == "L3"
    assert repair["affected_questions"] == ["q2"]
    assert "R2_EXPERIMENT_q2" in repair["required_retests"]
    assert repair["route_reapproval_required"] is False


def test_material_route_impact_is_normalized_to_l5(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs/repair-route"
    report_dir = run_dir / "review/r3/round-1"
    report_dir.mkdir(parents=True)
    report_path = report_dir / "review_report.json"
    atomic_json(
        report_path,
        {
            "schema_name": "review_report",
            "schema_version": "2.0",
            "request_id": "request-2",
            "run_id": "repair-route",
            "stage": "R3_PAPER_LOGIC",
            "review_round_id": "round-1",
            "request_sha256": "a" * 64,
            "input_manifest_sha256": "b" * 64,
            "session_sha256": "c" * 64,
            "verdict": "MAJOR_REVISION",
            "findings": [
                {
                    "finding_id": "R3-F2",
                    "severity": "P1",
                    "title": "核心目标函数改变",
                    "evidence": ["paper/main.typ"],
                    "remediation": "重新确认路线",
                    "affected_questions": ["q1"],
                    "change_level": "L4",
                    "change_class": "SPEC_COMPLETION",
                    "route_impact": "material",
                    "changed_route_core_fields": ["objective"],
                }
            ],
            "read_only_confirmed": True,
            "generated_at": "2026-07-20T00:00:00Z",
        },
    )

    adjudication = _accepted_adjudication(report_path, effective_level="L5")
    repair = load_json(create_repair_plan(run_dir, report_path, adjudication))

    assert repair["change_level"] == "L5"
    assert repair["route_reapproval_required"] is True
    assert repair["required_retests"] == ["HUMAN_ROUTE_REAPPROVAL"]


def test_missing_j0_does_not_block_final_review_gate_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from shumozizi.workflow import integrity

    run_dir = tmp_path / "runs" / "without-j0"
    (run_dir / "problem").mkdir(parents=True)
    (run_dir / "review").mkdir()
    atomic_json(run_dir / "problem/PROBLEM_MANIFEST.json", {"questions": []})
    state = {
        "review_gates": {
            gate_id: {"status": "passed", "receipt": f"review/{gate_id}.json"}
            for gate_id in (
                "R1_MODELING",
                "R3_PAPER_LOGIC",
                "R4_FORMAT_VISUAL",
                "R5_STANDARD_FINAL",
            )
        }
    }
    for gate_id in state["review_gates"]:
        path = run_dir / state["review_gates"][gate_id]["receipt"]
        path.write_text("{}\n", encoding="utf-8")
        state["review_gates"][gate_id]["receipt_sha256"] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    monkeypatch.setattr(
        integrity,
        "verify_review_receipt",
        lambda *_args, **_kwargs: {"valid": True, "errors": []},
    )
    errors: list[str] = []

    integrity._verify_final_review_gates(run_dir, state, errors)

    assert errors == []
