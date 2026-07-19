"""验证主状态转换与分阶段审核门。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, sha256_file
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


def _qa_running_state(run_id: str) -> dict:
    """构造可登记 R5/J0 的最小合法 QA_RUNNING 状态。"""
    return {
        "schema_name": "workflow_state",
        "schema_version": "2.0",
        "run_schema_version": "2.0",
        "run_id": run_id,
        "problem_source": "problems/sample.md",
        "mode": "competition",
        "status": "QA_RUNNING",
        "revision": 7,
        "completed_stages": ["PAPER_DRAFTED"],
        "active_stage": "qa",
        "route_locked": True,
        "paper_ready": True,
        "question_progress": {},
        "review_gates": {},
        "artifacts": {},
        "last_updated_by": "test",
        "updated_at": "2026-07-19T00:00:00Z",
        "history": [],
    }


def _record_review(
    service: StateService,
    run_dir: Path,
    stage: str,
    gate_id: str,
    verdict: str,
    *,
    findings: list[dict] | None = None,
    rating: bool = False,
) -> dict:
    """创建并登记真实审核请求、报告和回执。"""
    bound = run_dir / "paper/final.pdf"
    request = create_review_request(run_dir, stage, {"final_pdf": bound})
    request_doc = json.loads(request.read_text(encoding="utf-8"))
    report = {
        "schema_name": "review_report",
        "schema_version": "2.0",
        "request_id": request_doc["request_id"],
        "run_id": run_dir.name,
        "stage": stage,
        "review_round_id": request_doc["review_round_id"],
        "verdict": verdict,
        "findings": findings or [],
        "read_only_confirmed": True,
        "generated_at": "2026-07-19T00:00:00Z",
    }
    if rating:
        report["rating"] = {
            "grade": verdict,
            "confidence": "high",
            "basis": ["冻结提交包"],
            "downgrade_reasons": [],
            "expert_estimate": True,
        }
    report_path = write_review_report(request, report)
    receipt = materialize_review_receipt(request, report_path)
    return service.record_review_gate(run_dir.name, gate_id, receipt, Actor("review"))


def _write_minimal_production(repo_root: Path, run_dir: Path) -> None:
    """为审核时机测试写入哈希闭合的最小论文生产包。"""
    bound_files = {
        "mathmodel_paper": repo_root / "skills/mathmodel-paper/SKILL.md",
        "writing_skill": repo_root / "skills/5writing/SKILL.md",
        "typst_author": repo_root / "skills/typst-author/SKILL.md",
        "competition_template": repo_root / "profiles/generic.json",
        "model_spec": run_dir / "reports/model_spec.md",
        "claim_gate": run_dir / "paper/claim_gate.json",
    }
    for path in bound_files.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n" if path.name == "claim_gate.json" else "测试绑定\n", encoding="utf-8")
    section = run_dir / "paper/main.typ"
    section.write_text("= 测试论文\n", encoding="utf-8")
    registry = run_dir / "results/result_registry.json"
    atomic_json(
        registry,
        {
            "schema_name": "result_registry",
            "schema_version": "2.0",
            "run_id": run_dir.name,
            "results": [],
        },
    )
    bindings = {
        name: {
            "path": path.relative_to(repo_root if repo_root in path.parents else run_dir).as_posix(),
            "sha256": sha256_file(path),
        }
        for name, path in bound_files.items()
    }
    bindings["result_registry"] = {
        "path": "results/result_registry.json",
        "sha256": sha256_file(registry),
    }
    bindings["section_files"] = [
        {"path": "paper/main.typ", "sha256": sha256_file(section)}
    ]
    bindings["figures_used"] = []
    plan_path = run_dir / "paper/paper_plan.json"
    atomic_json(
        plan_path,
        {
            "schema_name": "paper_plan",
            "schema_version": "2.0",
            "run_id": run_dir.name,
            "referenced_result_ids": [],
            "bindings": bindings,
            "final_pdf_path": "paper/final.pdf",
        },
    )
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    atomic_json(
        run_dir / "paper/PAPER_BUILD_RECEIPT.json",
        {
            "schema_name": "paper_build_receipt",
            "schema_version": "2.0",
            "run_id": run_dir.name,
            "plan_path": "paper/paper_plan.json",
            "plan_sha256": sha256_file(plan_path),
            "state_revision": state["revision"],
            "final_pdf_path": "paper/final.pdf",
            "final_pdf_sha256": sha256_file(run_dir / "paper/final.pdf"),
            "generated_at": "2026-07-19T00:00:00Z",
        },
    )
    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "schema_name": "figure_plan",
            "schema_version": "2.0",
            "run_id": run_dir.name,
            "figures": [],
        },
    )


@pytest.mark.parametrize(
    ("verdict", "findings", "expected_status"),
    [
        ("PROCEED", [], "passed"),
        ("DO_NOT_PROCEED", [], "failed"),
        ("ADVISORY", [], "passed"),
        (
            "ADVISORY",
            [
                {
                    "finding_id": "J0-P1",
                    "severity": "P1",
                    "title": "关键结论证据不足",
                    "evidence": ["最终 PDF 第 3 页"],
                    "remediation": "修正证据链",
                    "status": "open",
                }
            ],
            "failed",
        ),
    ],
)
def test_j0_verdict_semantics_are_enforced_and_retained(
    tmp_path: Path,
    verdict: str,
    findings: list[dict],
    expected_status: str,
) -> None:
    """J0 否决和严重问题必须阻断，普通 advisory 只保留警告。"""
    run_dir = tmp_path / "runs" / f"j0-{verdict.lower()}-{len(findings)}"
    (run_dir / "paper").mkdir(parents=True)
    (run_dir / "review").mkdir()
    (run_dir / "paper/final.pdf").write_bytes(b"PDF")
    atomic_json(run_dir / "state.json", _qa_running_state(run_dir.name))
    atomic_json(run_dir / "review/QA_AGGREGATE.json", {"status": "pass", "hard_failures": []})
    _write_minimal_production(tmp_path, run_dir)
    service = StateService(tmp_path)
    _record_review(
        service,
        run_dir,
        "R5_COMPREHENSIVE",
        "R5_STANDARD_FINAL",
        "B",
        rating=True,
    )

    state = _record_review(
        service,
        run_dir,
        "J0_FINAL_BLIND_JUDGE",
        "J0_FINAL_BLIND_JUDGE",
        verdict,
        findings=findings,
    )

    gate = state["review_gates"]["J0_FINAL_BLIND_JUDGE"]
    assert gate["status"] == expected_status
    assert gate["verdict"] == verdict
