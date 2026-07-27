"""验证 Competition-First v3.2 的交付节奏和范围控制。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.paper.readiness import validate_required_figure_consumption
from shumozizi.simple.delivery import (
    DELIVERY_CONTROL_PATH,
    WORK_LOG_PATH,
    advance_delivery_phase,
    approve_workflow_p0_patch,
    next_required_action,
    record_work_session,
    verify_workflow_source_lock,
)
from shumozizi.simple.initialization import initialize_simple_run


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


def _at(started_at: str, minutes: float) -> str:
    """返回相对运行开始时间的 RFC 3339 时间。"""
    start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    return (start + timedelta(minutes=minutes)).astimezone(UTC).isoformat().replace(
        "+00:00", "Z"
    )


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


def test_first_pdf_deadline_overrides_normal_experiment_work(tmp_path: Path) -> None:
    """到第一版截止点后，唯一 P0 动作必须切换为产出可审阅 PDF。"""
    run_dir = _run(tmp_path)
    started_at = load_json(run_dir / DELIVERY_CONTROL_PATH)["started_at"]

    action = next_required_action(run_dir, now=_at(started_at, 481))

    assert action["next_action"] == "generate_first_reviewable_pdf"
    assert action["priority"] == "P0_DELIVERY"
    assert "add_new_route" in action["forbidden_actions"]
    assert "modify_workflow_schema" in action["forbidden_actions"]


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
