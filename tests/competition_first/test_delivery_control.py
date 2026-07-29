"""验证 Competition-First v3.2 的交付节奏和范围控制。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.paper.readiness import validate_required_figure_consumption
from shumozizi.simple import review as simple_review
from shumozizi.simple.competition import write_next_experiments
from shumozizi.simple.delivery import (
    DELIVERY_CONTROL_PATH,
    PDF_MILESTONES_PATH,
    WORK_LOG_PATH,
    advance_delivery_phase,
    approve_workflow_p0_patch,
    freeze_pdf_milestone,
    next_required_action,
    record_work_session,
    require_delivery_action_allowed,
    start_work_session,
    stop_work_session,
    verify_workflow_source_lock,
    work_log_summary,
)
from shumozizi.simple.figures import write_figure_plan
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.review_tasks import (
    create_review_task_receipt,
    persist_review_task_creation_event,
)


def _run(
    tmp_path: Path,
    *,
    total_hours: float | None = 12,
    require_web_review: bool = False,
) -> Path:
    """创建带交付控制的最小 v3.2 运行。"""
    return initialize_simple_run(
        tmp_path,
        "delivery-control",
        required_questions=["Q1"],
        total_hours=total_hours,
        workflow_version="3.2",
        require_web_review=require_web_review,
    )


def _passing_blind_report() -> str:
    """返回单问通过盲评及其同源结构化结果。"""
    structured = {
        "cold_read": {
            "input_scope": "frozen_pdf_only",
            "direct_answers_found_within_3_minutes": {"Q1": True},
            "one_sentence_contribution": "论文给出可定位的单问模型、结果与直接答案。",
            "cross_question_inheritance_understood": True,
            "first_five_pages_establish_data_intuition": True,
            "hero_figures_identified": {"Q1": True},
            "report_like_pages": [],
        },
        "structure": {
            field: "pass"
            for field in (
                "problem_restatement",
                "problem_analysis",
                "assumptions",
                "symbols_and_data",
                "four_questions",
                "model_evaluation",
            )
        },
        "argument_findings": {
            "Q1": {
                "missing_roles": [],
                "pages": [1],
                "finding": "Q1 的数学对象、推导、求解、结果、机制和验证均可定位。",
            }
        },
        "question_progression": {
            "status": "pass",
            "interchangeable_questions": False,
            "links": [],
            "summary": "当前只有一个必答问题，不存在跨问交换或继承歧义。",
        },
        "narrative_risks": [],
        "review_summary": "独立盲评未发现阻断问题，单问论证和直接答案均可在 PDF 中定位。",
    }
    return (
        "# PDF 盲评\n\n未发现 P0/P1，论文可进入机械终检。\n\n"
        "## 结构化盲评结果\n```json\n"
        + json.dumps(structured, ensure_ascii=False, indent=2)
        + "\n```\n"
    )


def _at(started_at: str, minutes: float) -> str:
    """返回相对运行开始时间的 RFC 3339 时间。"""
    start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    return (start + timedelta(minutes=minutes)).astimezone(UTC).isoformat().replace(
        "+00:00", "Z"
    )


def _move_past_first_pdf_deadline(run_dir: Path) -> None:
    """把交付时钟移到首版 PDF 截止后一刻。"""
    control = load_json(run_dir / DELIVERY_CONTROL_PATH)
    control["started_at"] = _at(control["started_at"], -481)
    atomic_json(run_dir / DELIVERY_CONTROL_PATH, control)


def _mark_pdf_milestone(run_dir: Path, name: str) -> None:
    """写入无需编译器的当前 PDF 里程碑夹具。"""
    document = load_json(run_dir / PDF_MILESTONES_PATH)
    if name == "first_reviewable":
        path = run_dir / "paper/draft-1.pdf"
        path.write_bytes(b"%PDF-1.4\nreviewable fixture\n")
        record = {
            "path": "paper/draft-1.pdf",
            "sha256": sha256_file(path),
            "source_pdf_sha256": sha256_file(path),
            "frozen_at": "2026-07-28T00:00:00Z",
        }
    else:
        path = run_dir / "paper/candidate.pdf"
        final = run_dir / "paper/final.pdf"
        path.write_bytes(b"%PDF-1.4\ncandidate fixture\n")
        final.write_bytes(path.read_bytes())
        record = {
            "path": "paper/candidate.pdf",
            "sha256": sha256_file(path),
            "source_pdf_sha256": sha256_file(final),
            "frozen_at": "2026-07-28T00:10:00Z",
        }
    document.setdefault("milestones", {})[name] = record
    atomic_json(run_dir / PDF_MILESTONES_PATH, document)


def _figure_plan(run_dir: Path) -> dict[str, object]:
    """构造含一张正文主图的最小 FIGURE_PLAN 2.1。"""
    return {
        "schema_name": "figure_plan",
        "schema_version": "2.1",
        "run_id": run_dir.name,
        "visual_decisions": [
            {
                "question_id": "Q1",
                "status": "required",
                "reason": "核心路线差异需要由统一指标比较图直接展示。",
            }
        ],
        "figures": [
            {
                "figure_id": "q1-main",
                "preferred": "skills/mathmodel-figure-templates",
                "fallback": "skills/3coding-visual",
                "selected_skill": "skills/3coding-visual",
                "template_id": "custom",
                "selection_reason": "直接展示核心问题的决定性结果。",
                "question_id": "Q1",
                "role": "decisive_evidence",
                "claim": "主路线相对自然基线取得稳定改善。",
                "source_result_ids": ["q1-final"],
                "script": "code/figures/q1.py",
                "output": "figures/current/q1-main.pdf",
                "paper_section": "paper/sections/q1.tex",
                "caption": "主路线与自然基线的统一指标比较",
                "latex_label": "fig:q1-main",
                "explanation_anchor": "改善来自约束激活后的方案重排",
                "required": True,
            }
        ],
    }


def test_v32_initialization_freezes_delivery_plan_and_work_log(tmp_path: Path) -> None:
    """新运行必须立即拥有可执行的交付时间表和真实工时账本。"""
    run_dir = _run(tmp_path)

    control = load_json(run_dir / DELIVERY_CONTROL_PATH)
    work_log = load_json(run_dir / WORK_LOG_PATH)

    assert control["delivery_plan"] == {
        "total_minutes": 720.0,
        "analysis_soft_limit": 90.0,
        "experiment_soft_limit": 300.0,
        "first_reviewable_pdf_deadline": 480.0,
        "candidate_pdf_deadline": 600.0,
        "blind_review_deadline": 660.0,
        "final_deadline": 720.0,
    }
    assert control["workflow_source_locked"] is True
    assert control["protocol_patch_budget_minutes"] == 30.0
    assert work_log["entries"] == []
    assert work_log["phase_sessions"][0]["phase"] == "analysis"


def test_first_pdf_deadline_overrides_normal_experiment_work(tmp_path: Path) -> None:
    """到第一版截止点后，唯一 P0 动作必须切换为产出可审阅 PDF。"""
    run_dir = _run(tmp_path)
    started_at = load_json(run_dir / DELIVERY_CONTROL_PATH)["started_at"]

    action = next_required_action(run_dir, now=_at(started_at, 481))

    assert action["next_action"] == "generate_first_reviewable_pdf"
    assert action["priority"] == "P0_DELIVERY"
    assert "add_new_route" in action["forbidden_actions"]
    assert "modify_workflow_schema" in action["forbidden_actions"]


def test_delivery_action_permission_is_enforced_after_first_pdf_deadline(
    tmp_path: Path,
) -> None:
    """截止后范围冻结必须是公共硬门，而不只是 status 中的建议。"""
    run_dir = _run(tmp_path)
    control = load_json(run_dir / DELIVERY_CONTROL_PATH)
    control["started_at"] = _at(control["started_at"], -481)
    atomic_json(run_dir / DELIVERY_CONTROL_PATH, control)

    with pytest.raises(ContractError, match="add_new_route"):
        require_delivery_action_allowed(run_dir, "add_new_route")

    require_delivery_action_allowed(run_dir, "paper_write")


def test_early_first_draft_freezes_scope_but_opens_review_repair(tmp_path: Path) -> None:
    """提前完成首版也应立即冻结框架，同时允许评审驱动实验返修。"""
    run_dir = _run(tmp_path)
    write_next_experiments(
        run_dir,
        {
            "experiments": [
                {"experiment_id": "probe-q1", "decision": "形成首版主结果。"}
            ]
        },
    )
    _mark_pdf_milestone(run_dir, "first_reviewable")

    with pytest.raises(ContractError, match="add_new_route"):
        require_delivery_action_allowed(run_dir, "add_new_route")
    repaired = write_next_experiments(
        run_dir,
        {
            "experiments": [
                {"experiment_id": "probe-q1", "decision": "形成首版主结果。"},
                {
                    "experiment_id": "review-sensitivity",
                    "decision": "检验阈值是否改变直接答案。",
                    "review_finding": "首版 PDF 评审指出关键阈值缺少敏感性分析。",
                },
            ]
        },
    )

    assert repaired["experiments"][-1]["experiment_id"] == "review-sensitivity"
    assert "add_new_route" in next_required_action(run_dir)["forbidden_actions"]


def test_review_finding_allows_bounded_experiment_addition_before_candidate(
    tmp_path: Path,
) -> None:
    """首版后可按评审发现补实验，但候选冻结后停止扩展。"""
    run_dir = _run(tmp_path)
    plan = {
        "experiments": [
            {"experiment_id": "probe-q1", "decision": "决定 Q1 是否启用结构路线。"}
        ]
    }
    write_next_experiments(run_dir, plan)
    _move_past_first_pdf_deadline(run_dir)

    plan["experiments"][0]["decision"] = "修正 Q1 既有 probe 的执行说明。"
    assert write_next_experiments(run_dir, plan)["experiments"][0]["experiment_id"] == "probe-q1"

    plan["experiments"].append(
        {"experiment_id": "probe-q1-extra", "decision": "增加新的非阻断性搜索。"}
    )
    with pytest.raises(ContractError, match="first_reviewable"):
        write_next_experiments(run_dir, plan)
    _mark_pdf_milestone(run_dir, "first_reviewable")
    plan["experiments"][-1]["review_finding"] = (
        "PDF 评审指出主结论缺少关键阈值敏感性证据。"
    )
    assert write_next_experiments(run_dir, plan)["experiments"][-1][
        "experiment_id"
    ] == "probe-q1-extra"

    _mark_pdf_milestone(run_dir, "candidate")
    plan["experiments"].append(
        {
            "experiment_id": "probe-q1-too-late",
            "decision": "候选冻结后不应执行。",
            "review_finding": "候选冻结之后才提出的额外科学内容请求。",
        }
    )
    with pytest.raises(ContractError, match="候选 PDF 已冻结"):
        write_next_experiments(run_dir, plan)


def test_review_finding_allows_new_figure_before_candidate(
    tmp_path: Path,
) -> None:
    """评审发现可触发一张新主图，普通装饰扩图仍被拒绝。"""
    run_dir = _run(tmp_path)
    plan = _figure_plan(run_dir)
    write_figure_plan(run_dir, plan)
    _move_past_first_pdf_deadline(run_dir)

    plan["figures"][0]["caption"] = "修订后的主路线与自然基线比较"
    assert write_figure_plan(run_dir, plan)["figures"][0]["figure_id"] == "q1-main"

    added = dict(plan["figures"][0])
    added["figure_id"] = "q1-extra"
    added["latex_label"] = "fig:q1-extra"
    plan["figures"].append(added)
    with pytest.raises(ContractError, match="first_reviewable"):
        write_figure_plan(run_dir, plan)
    _mark_pdf_milestone(run_dir, "first_reviewable")
    added["review_finding"] = "PDF 评审指出全篇缺少训练选择与验证隔离流程图。"
    assert write_figure_plan(run_dir, plan)["figures"][-1]["figure_id"] == "q1-extra"


def test_delivery_cutoff_blocks_extra_reviews_but_keeps_blind_review_available(
    tmp_path: Path,
) -> None:
    """截止后拒绝扩张审核任务，但主链 PDF 盲评仍必须可创建。"""
    run_dir = _run(tmp_path)
    report = run_dir / "review/PAPER_BLIND_REVIEW.md"
    report.write_text("# PDF 盲评\n\n当前没有确认的 P0/P1。\n", encoding="utf-8")
    _move_past_first_pdf_deadline(run_dir)
    common = {
        "model_id": "fixture-model",
        "prompt_sha256": "a" * 64,
        "input_bindings": {},
        "report_file": "review/PAPER_BLIND_REVIEW.md",
        "thread_id": "fixture-thread",
    }

    with pytest.raises(ContractError, match="create_extra_review_task"):
        create_review_task_receipt(
            run_dir,
            task_id="extra-follow-up",
            task_type="scientific_follow_up",
            **common,
        )

    receipt = create_review_task_receipt(
        run_dir,
        task_id="required-paper-blind",
        task_type="paper_blind_open",
        **common,
    )
    assert receipt.is_file()


def test_delivery_controller_reaches_submission_and_invalidates_stale_blind_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """公开推进器必须贯通草稿、候选、盲评、终检与提交包。"""
    run_dir = _run(tmp_path)
    # CUMCM 结构与版面审计由专用适配器测试覆盖；这里仅验证交付推进器。
    monkeypatch.setattr(
        "shumozizi.paper.cumcm_adapter.require_cumcm_paper_review_audit",
        lambda _run: None,
    )
    monkeypatch.setattr(
        "shumozizi.paper.cumcm_adapter.require_cumcm_layout_audit",
        lambda _run: None,
    )
    control_path = run_dir / DELIVERY_CONTROL_PATH
    original_started_at = load_json(control_path)["started_at"]

    # 本测试聚焦交付控制器；建模证据、科学挑战和编译器细节由各自测试覆盖。
    monkeypatch.setattr(
        "shumozizi.simple.objective_consequences.require_objective_candidate_plan",
        lambda _run: None,
    )
    monkeypatch.setattr(
        "shumozizi.simple.modeling_units.require_v32_modeling_plan", lambda _run: None
    )
    monkeypatch.setattr(
        "shumozizi.simple.objective_semantics.objective_semantics_review_required",
        lambda _run: False,
    )
    assert advance_delivery_phase(run_dir)["to_phase"] == "experiment"

    _move_past_first_pdf_deadline(run_dir)
    assert next_required_action(run_dir)["next_action"] == "generate_first_reviewable_pdf"
    (run_dir / "paper/draft-1.pdf").write_bytes(b"%PDF-1.4\nreviewable-draft\n")
    atomic_json(run_dir / "paper/reviewable-draft-receipt.json", {"fixture": True})
    monkeypatch.setattr(
        "shumozizi.paper.compiler.verify_reviewable_draft_receipt",
        lambda _run: {"valid": True, "errors": []},
    )
    freeze_pdf_milestone(run_dir, "first_reviewable")
    control = load_json(control_path)
    control["started_at"] = original_started_at
    atomic_json(control_path, control)

    monkeypatch.setattr(
        "scripts.qa.metric_ledger.require_v32_metric_ledger_for_paper", lambda _run: None
    )
    monkeypatch.setattr(simple_review, "require_paper_generation_allowed", lambda _run: None)
    monkeypatch.setattr(
        "shumozizi.simple.objective_consequences.require_objective_consequences",
        lambda _run: None,
    )
    monkeypatch.setattr(
        "shumozizi.simple.modeling_units.require_v32_experiment_evidence",
        lambda _run: None,
    )
    monkeypatch.setattr(
        "shumozizi.paper.templates.require_materialized_template", lambda _run: {}
    )
    assert advance_delivery_phase(run_dir)["to_phase"] == "paper"

    with pytest.raises(ContractError, match="final.pdf"):
        freeze_pdf_milestone(run_dir, "candidate")
    final_pdf = run_dir / "paper/final.pdf"
    original_pdf = b"%PDF-1.4\nstrict-candidate\n"
    final_pdf.write_bytes(original_pdf)
    atomic_json(run_dir / "paper/compile-receipt.json", {"fixture": True})
    monkeypatch.setattr(
        "shumozizi.paper.compiler.verify_paper_compile_receipt",
        lambda _run: {"valid": True, "errors": []},
    )
    freeze_pdf_milestone(run_dir, "candidate")
    assert advance_delivery_phase(run_dir)["to_phase"] == "paper_review"

    missing_review = advance_delivery_phase(run_dir)
    assert missing_review["advanced"] is False
    assert "盲审" in missing_review["blocked_by"][0]

    packet = simple_review.build_review_packet(run_dir, kind="paper-blind")
    manifest_file = (
        f"review/packet/paper-blind/{packet['packet_id']}/manifest.json"
    )
    report = run_dir / "review/PAPER_BLIND_REVIEW.md"
    report.write_text(_passing_blind_report(), encoding="utf-8")
    bindings = {
        "packet": {
            "manifest_file": manifest_file,
            "manifest_sha256": sha256_file(run_dir / manifest_file),
        }
    }
    event = persist_review_task_creation_event(
        run_dir,
        event_file="review/tasks/creation-events/e2e-paper-blind.json",
        raw_event={
            "schema_name": "review_task_creation_event",
            "schema_version": "1.0",
            "provider": "codex",
            "raw_task_id": "e2e-paper-blind-task",
            "raw_thread_id": "e2e-paper-blind-thread",
            "creation_mode": "create_thread",
            "parent_context_inherited": False,
            "created_at": "2026-07-27T00:00:00Z",
        },
    )
    receipt = create_review_task_receipt(
        run_dir,
        task_id="e2e-paper-blind",
        task_type="paper_blind_open",
        model_id="fixture-model",
        prompt_sha256=simple_review.paper_blind_review_prompt_sha256(
            run_dir, manifest_file
        ),
        input_bindings=bindings,
        report_file="review/PAPER_BLIND_REVIEW.md",
        creation_event_file=event.relative_to(run_dir).as_posix(),
    )
    monkeypatch.setattr(
        simple_review,
        "_v32_scientific_challenge_status",
        lambda _run: {
            "allowed": True,
            "review": {"task_receipt": {"thread_id": "e2e-scientific-thread"}},
        },
    )
    simple_review.import_paper_blind_review(
        run_dir,
        manifest_file=manifest_file,
        verdict="pass",
        highest_severity="none",
        reviewer_thread_id="e2e-paper-blind-thread",
        task_receipt_file=receipt.relative_to(run_dir).as_posix(),
    )
    assert simple_review.paper_blind_review_status(run_dir)["allowed"] is True

    final_pdf.write_bytes(b"%PDF-1.4\nchanged-after-review\n")
    stale = simple_review.paper_blind_review_status(run_dir)
    assert stale["allowed"] is False
    assert "重新盲评" in stale["reason"]
    final_pdf.write_bytes(original_pdf)
    assert simple_review.paper_blind_review_status(run_dir)["allowed"] is True
    assert advance_delivery_phase(run_dir)["to_phase"] == "verify"

    monkeypatch.setattr(
        simple_review,
        "scientific_review_status",
        lambda _run: {
            "allowed": True,
            "submission_ready": True,
            "competition_strength": "strong",
        },
    )
    monkeypatch.setattr(simple_review, "mechanical_qa_status", lambda _run: {"allowed": True})
    monkeypatch.setattr(
        "shumozizi.simple.results.verify_current_result_files",
        lambda _run: {"success": True},
    )
    monkeypatch.setattr(
        "shumozizi.simple.figures.verify_current_figure_files",
        lambda _run: {"success": True},
    )
    assert advance_delivery_phase(run_dir)["to_phase"] == "complete"

    submission = simple_review.materialize_submission_package(run_dir)
    assert {item["role"] for item in submission["files"]} == {"final_pdf"}
    assert (run_dir / "paper/submission/final.pdf").is_file()


def test_delivery_deadline_blocks_phase_advance(tmp_path: Path) -> None:
    """已到期的 PDF 动作未完成时，推进器不能绕过它切换阶段。"""
    run_dir = _run(tmp_path)
    control = load_json(run_dir / DELIVERY_CONTROL_PATH)
    control["started_at"] = _at(control["started_at"], -481)
    atomic_json(run_dir / DELIVERY_CONTROL_PATH, control)

    result = advance_delivery_phase(run_dir)

    assert result["advanced"] is False
    assert result["action"]["next_action"] == "generate_first_reviewable_pdf"
    assert result["action"]["priority"] == "P0_DELIVERY"
    assert "generate_first_reviewable_pdf" in result["blocked_by"][0]


def test_candidate_pdf_is_required_before_paper_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """paper 阶段不能在候选 PDF 缺失时进入独立审核。"""
    from shumozizi.simple.state import update_simple_state

    run_dir = _run(tmp_path)
    state_path = run_dir / "state/run.json"
    state = load_json(state_path)
    state["phase"] = "paper"
    atomic_json(state_path, state)
    monkeypatch.setattr(
        "shumozizi.paper.templates.require_materialized_template", lambda _run_dir: None
    )

    with pytest.raises(ContractError, match="candidate"):
        update_simple_state(run_dir, phase="paper_review")


def test_candidate_pdf_must_change_after_first_reviewable_milestone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """复制首版 PDF 不能冒充经过返修的候选版。"""
    run_dir = _run(tmp_path)
    pdf_bytes = b"%PDF-1.4\nsame-paper-content\n"
    (run_dir / "paper/draft-1.pdf").write_bytes(pdf_bytes)
    atomic_json(run_dir / "paper/reviewable-draft-receipt.json", {"fixture": True})
    monkeypatch.setattr(
        "shumozizi.paper.compiler.verify_reviewable_draft_receipt",
        lambda _run: {"valid": True, "errors": []},
    )
    freeze_pdf_milestone(run_dir, "first_reviewable")

    (run_dir / "paper/final.pdf").write_bytes(pdf_bytes)
    atomic_json(run_dir / "paper/compile-receipt.json", {"fixture": True})
    monkeypatch.setattr(
        "shumozizi.paper.compiler.verify_paper_compile_receipt",
        lambda _run: {"valid": True, "errors": []},
    )

    with pytest.raises(ContractError, match="实质内容增量"):
        freeze_pdf_milestone(run_dir, "candidate")


@pytest.mark.parametrize("required", [False, True])
def test_web_review_gate_follows_explicit_delivery_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, required: bool
) -> None:
    """网页新对话仅在初始化显式要求时阻断进入 verify。"""
    from shumozizi.simple.state import update_simple_state

    run_dir = _run(tmp_path, require_web_review=required)
    state_path = run_dir / "state/run.json"
    state = load_json(state_path)
    state["phase"] = "paper_review"
    atomic_json(state_path, state)
    monkeypatch.setattr(
        "shumozizi.simple.review.require_paper_blind_review_allowed", lambda _run_dir: None
    )

    if required:
        with pytest.raises(ContractError, match="网页"):
            update_simple_state(run_dir, phase="verify")
    else:
        assert update_simple_state(run_dir, phase="verify")["phase"] == "verify"


def test_protocol_overhead_forces_return_to_delivery_mainline(tmp_path: Path) -> None:
    """协议与执行器工时超过总工时 10% 后不得继续扩框架。"""
    run_dir = _run(tmp_path)
    started_at = load_json(run_dir / DELIVERY_CONTROL_PATH)["started_at"]
    record_work_session(
        run_dir,
        category="workflow_protocol",
        started_at=_at(started_at, 0),
        finished_at=_at(started_at, 11),
        summary="修复当前交付协议。",
    )
    record_work_session(
        run_dir,
        category="problem_analysis",
        started_at=_at(started_at, 11),
        finished_at=_at(started_at, 100),
        summary="完成题意与路线分析。",
    )

    action = next_required_action(run_dir, now=_at(started_at, 100))

    assert action["next_action"] == "return_to_competition_mainline"
    assert action["work_summary"]["protocol_overhead_ratio"] == pytest.approx(0.11)
    assert "expand_review_protocol" in action["forbidden_actions"]


def test_source_lock_detects_runtime_workflow_development(tmp_path: Path) -> None:
    """运行开始后修改工作流源码必须被统一推进器识别。"""
    source = tmp_path / "src" / "shumozizi" / "feature.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    run_dir = _run(tmp_path)
    source.write_text("VALUE = 2\n", encoding="utf-8")

    verification = verify_workflow_source_lock(run_dir)
    action = next_required_action(run_dir)

    assert verification["valid"] is False
    assert "src/shumozizi/feature.py" in verification["changed_files"]
    assert action["next_action"] == "restore_workflow_source_or_record_p0_patch"


def test_p0_patch_requires_unconsumed_blocking_repair_work(tmp_path: Path) -> None:
    """源码漂移只有绑定真实 P0 修补工时后才能更新源码锁基线。"""
    source = tmp_path / "src" / "shumozizi" / "feature.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    run_dir = _run(tmp_path)
    started_at = load_json(run_dir / DELIVERY_CONTROL_PATH)["started_at"]
    source.write_text("VALUE = 2\n", encoding="utf-8")
    record_work_session(
        run_dir,
        category="workflow_protocol",
        started_at=_at(started_at, 0),
        finished_at=_at(started_at, 5),
        summary="整理非阻断性协议说明。",
    )

    with pytest.raises(ContractError, match="blocking_delivery_repair=true"):
        approve_workflow_p0_patch(run_dir, reason="修复无法编译当前 PDF 的错误")

    record_work_session(
        run_dir,
        category="executor_debugging",
        started_at=_at(started_at, 5),
        finished_at=_at(started_at, 10),
        summary="修复阻断当前 PDF 编译的执行器错误。",
        blocking_delivery_repair=True,
    )
    patch = approve_workflow_p0_patch(run_dir, reason="修复无法编译当前 PDF 的错误")

    assert patch["work_log_entry_index"] == 1
    assert verify_workflow_source_lock(run_dir)["valid"] is True


def test_invalid_or_overlapping_work_sessions_are_rejected(tmp_path: Path) -> None:
    """工时账本拒绝未知分类和重叠区间，避免比例被伪造。"""
    run_dir = _run(tmp_path)
    started_at = load_json(run_dir / DELIVERY_CONTROL_PATH)["started_at"]
    record_work_session(
        run_dir,
        category="paper_writing",
        started_at=_at(started_at, 10),
        finished_at=_at(started_at, 20),
        summary="撰写逐问正文。",
    )

    with pytest.raises(ContractError, match="不受支持"):
        record_work_session(
            run_dir,
            category="misc",
            started_at=_at(started_at, 20),
            finished_at=_at(started_at, 21),
            summary="无法归类。",
        )
    with pytest.raises(ContractError, match="重叠"):
        record_work_session(
            run_dir,
            category="figure_generation",
            started_at=_at(started_at, 15),
            finished_at=_at(started_at, 25),
            summary="生成正文主图。",
        )


def test_start_stop_work_is_optional_detail_beside_phase_tracking(tmp_path: Path) -> None:
    """细粒度记录保持兼容，但状态页不再追查墙钟空档。"""
    run_dir = _run(tmp_path)
    started_at = load_json(run_dir / DELIVERY_CONTROL_PATH)["started_at"]

    session = start_work_session(
        run_dir, category="problem_analysis", started_at=_at(started_at, 0)
    )
    with pytest.raises(ContractError, match="active_session"):
        start_work_session(
            run_dir, category="paper_writing", started_at=_at(started_at, 1)
        )
    open_summary = work_log_summary(run_dir, now=_at(started_at, 121))
    assert session["category"] == "problem_analysis"
    assert open_summary["active_session_long_running"] is True
    assert open_summary["logged_time_coverage_ratio"] == pytest.approx(1.0)

    entry = stop_work_session(
        run_dir,
        summary="完成题意与候选目标分析。",
        finished_at=_at(started_at, 120),
    )
    assert entry["duration_minutes"] == pytest.approx(120)
    assert load_json(run_dir / WORK_LOG_PATH)["active_session"] is None

    start_work_session(
        run_dir, category="paper_writing", started_at=_at(started_at, 145)
    )
    stop_work_session(
        run_dir,
        summary="形成首版逐问正文。",
        finished_at=_at(started_at, 160),
    )
    summary = work_log_summary(run_dir, now=_at(started_at, 200))
    assert summary["coverage_warning"] is False
    assert summary["logged_time_coverage_ratio"] == pytest.approx(1.0)
    assert summary["unexplained_gaps"] == []
    assert summary["phase_sessions"][0]["phase"] == "analysis"


def test_required_figure_must_be_consumed_by_latex(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """必需图只有生成文件还不够，正文必须插入、标号、引用并解释。"""
    from shumozizi.core.io import atomic_json

    run_dir = _run(tmp_path)
    script = run_dir / "code/figures/q1.py"
    output = run_dir / "figures/current/q1-main.pdf"
    section = run_dir / "paper/sections/q1.tex"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("print('figure')\n", encoding="utf-8")
    output.write_bytes(b"%PDF-1.4\nfigure\n")
    plan_item = {
        "figure_id": "q1-main",
        "preferred": "skills/mathmodel-figure-templates",
        "fallback": "skills/3coding-visual",
        "selected_skill": "skills/mathmodel-figure-templates",
        "template_id": "cv-roc-ci",
        "selection_reason": "直接展示核心问题的决定性结果。",
        "question_id": "Q1",
        "role": "decisive_evidence",
        "claim": "主路线相对自然基线取得稳定改善。",
        "source_result_ids": ["q1-final"],
        "script": "code/figures/q1.py",
        "output": "figures/current/q1-main.pdf",
        "paper_section": "paper/sections/q1.tex",
        "caption": "主路线与自然基线的统一指标比较",
        "latex_label": "fig:q1-main",
        "explanation_anchor": "改善主要来自约束激活后的方案重排",
        "required": True,
    }
    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "schema_name": "figure_plan",
            "schema_version": "2.1",
            "run_id": run_dir.name,
            "visual_decisions": [
                {
                    "question_id": "Q1",
                    "status": "required",
                    "reason": "核心路线差异需要由统一指标比较图直接展示。",
                }
            ],
            "figures": [plan_item],
        },
    )
    atomic_json(
        run_dir / "figures/index.json",
        {
            "schema_version": "1.2",
            "run_id": run_dir.name,
            "figures": [
                {
                    "figure_id": "q1-main",
                    "status": "current",
                    "question_id": "Q1",
                    "role": "decisive_evidence",
                    "source_result_ids": ["q1-final"],
                    "renderer_script": {"path": "code/figures/q1.py"},
                    "outputs": [{"path": "figures/current/q1-main.pdf"}],
                }
            ],
        },
    )
    monkeypatch.setattr(
        "shumozizi.paper.readiness.verify_current_figure_files",
        lambda *_args, **_kwargs: {"success": True, "checked_figure_ids": ["q1-main"], "errors": []},
    )
    section.write_text("只有结果描述，没有插图。\n", encoding="utf-8")
    errors = validate_required_figure_consumption(run_dir)
    assert any("includegraphics" in error for error in errors)
    assert any("交叉引用" in error for error in errors)

    section.write_text(
        "\\begin{figure}\n"
        "\\includegraphics{../../figures/current/q1-main.pdf}\n"
        "\\caption{主路线与自然基线的统一指标比较}\n"
        "\\label{fig:q1-main}\n"
        "\\end{figure}\n"
        "由图~\\ref{fig:q1-main}可见，改善主要来自约束激活后的方案重排。\n",
        encoding="utf-8",
    )
    assert validate_required_figure_consumption(run_dir) == []


def test_core_question_requires_explicit_visual_decision(tmp_path: Path) -> None:
    """核心问题不能通过省略 2.1 计划或把所有图设为可选而静默零图。"""
    run_dir = _run(tmp_path)
    modeling = load_json(run_dir / "analysis/MODELING_UNITS.json")
    modeling["units"] = [{"unit_id": "U1", "question_id": "Q1", "core_question": True}]
    atomic_json(run_dir / "analysis/MODELING_UNITS.json", modeling)

    errors = validate_required_figure_consumption(run_dir)
    assert any("核心问题 Q1" in error and "视觉决策" in error for error in errors)

    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "schema_name": "figure_plan",
            "schema_version": "2.1",
            "run_id": run_dir.name,
            "visual_decisions": [
                {
                    "question_id": "Q1",
                    "status": "waived",
                    "reason": "核心关系由闭式公式与一张参数表完整表达，无额外空间或趋势结构需要图示。",
                }
            ],
            "figures": [],
        },
    )
    assert validate_required_figure_consumption(run_dir) == []

    plan = load_json(run_dir / "figures/FIGURE_PLAN.json")
    plan["visual_decisions"][0]["status"] = "required"
    atomic_json(run_dir / "figures/FIGURE_PLAN.json", plan)
    errors = validate_required_figure_consumption(run_dir)
    assert any("至少一张 required=true" in error for error in errors)
