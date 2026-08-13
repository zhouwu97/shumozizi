"""验证 Repair Loop v1：路由从标签升级为命令。

核心断言：
- ``open_repair_directive`` 登记可执行修复动作 + 负责人阶段 + 验收测试；
- ``apply_repair_route`` 真正执行行为：experiment/analysis 沿合法迁移图切回
  顶层 phase，visual 创建视觉机会，author 标记外部 Author 返工，render 标记
  需要重渲染；
- ``close_repair_directive`` 必须提供验收证据，验收不过不能 close；
- 未关闭的修复指令阻断交接与交付（``require_no_open_repairs``）；
- 动作空间封闭：未知 route 直接拒绝。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, load_json
from shumozizi.paper.repair_loop import (
    apply_repair_route,
    close_repair_directive,
    open_repair_directive,
    open_repair_directives,
    require_no_open_repairs,
)
from shumozizi.simple.authoring import (
    mark_authoring_status,
    read_authoring,
    set_authoring_mode,
)
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.state import read_simple_state, write_simple_state


def _run(tmp_path: Path, name: str = "repair") -> Path:
    """创建最小 v3.2 运行并推进到 paper 阶段。"""
    run_dir = initialize_simple_run(
        tmp_path,
        name,
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    state = read_simple_state(run_dir)
    state["phase"] = "paper"
    write_simple_state(run_dir, state)
    return run_dir


def _directive(**overrides: object) -> dict[str, object]:
    """构造一条合法修复指令（可覆盖字段）。"""
    base: dict[str, object] = {
        "directive_id": "fix-1",
        "source": "reviewer finding F-12",
        "finding_class": "argument",
        "affected_questions": ["Q1"],
        "route": "experiment",
        "owner_stage": "experiment",
        "repair_action": "基于当前 production 结果补充机制解释。",
        "requires_new_evidence": True,
        "acceptance_test": "Q1 存在绑定 current production 的机制级 insight。",
        "waivable": False,
    }
    base.update(overrides)
    return base


def _phase_only_updater(monkeypatch: pytest.MonkeyPatch, run_dir: Path) -> None:
    """把 update_simple_state 换成只改 phase 的替身，隔离入口门禁。"""

    def fake_update(run_dir_: Path, **changes: object) -> dict[str, object]:
        state = read_simple_state(run_dir_)
        if "phase" in changes:
            state["phase"] = changes["phase"]
        state["revision"] += 1
        write_simple_state(run_dir_, state)
        return state

    import shumozizi.paper.repair_loop as repair_loop

    monkeypatch.setattr(repair_loop, "update_simple_state", fake_update)


def test_open_and_apply_experiment_route_changes_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """route=experiment 的 fulfill 必须真正把顶层 phase 切回 experiment。"""
    run_dir = _run(tmp_path, "exp-route")
    _phase_only_updater(monkeypatch, run_dir)
    open_repair_directive(run_dir, **_directive())
    result = apply_repair_route(run_dir, "fix-1")

    assert read_simple_state(run_dir)["phase"] == "experiment"
    assert result["status"] == "open"
    assert open_repair_directives(run_dir) == [result]


def test_phase_path_bfs_finds_legal_hops() -> None:
    """paper_review→experiment 与 paper→analysis 都能找到合法迁移路径。"""
    from shumozizi.paper.repair_loop import _phase_path

    assert _phase_path("paper_review", "experiment") == [
        "paper_review",
        "paper",
        "experiment",
    ]
    assert _phase_path("paper", "analysis") == ["paper", "experiment", "analysis"]
    assert _phase_path("paper", "paper") == ["paper"]


def test_apply_analysis_route_moves_through_experiment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """paper 阶段路由到 analysis 需要先经过 experiment（迁移图语义）。"""
    run_dir = _run(tmp_path, "analysis-route")
    hops: list[str] = []
    import shumozizi.paper.repair_loop as repair_loop

    def fake_update(run_dir_: Path, **changes: object) -> dict[str, object]:
        state = read_simple_state(run_dir_)
        if "phase" in changes:
            state["phase"] = changes["phase"]
            hops.append(str(changes["phase"]))
        state["revision"] += 1
        write_simple_state(run_dir_, state)
        return state

    monkeypatch.setattr(repair_loop, "update_simple_state", fake_update)
    open_repair_directive(run_dir, **_directive(route="analysis", owner_stage="analysis"))
    apply_repair_route(run_dir, "fix-1")

    assert read_simple_state(run_dir)["phase"] == "analysis"
    assert hops == ["experiment", "analysis"]


def test_close_requires_evidence_and_unblocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验收不过不能 close；close 后 require_no_open_repairs 放行。"""
    run_dir = _run(tmp_path, "close-evidence")
    open_repair_directive(run_dir, **_directive())
    with pytest.raises(ContractError, match="非空验收证据"):
        close_repair_directive(run_dir, "fix-1", acceptance_evidence="  ")
    with pytest.raises(ContractError, match="未关闭的修复指令"):
        require_no_open_repairs(run_dir)

    closed = close_repair_directive(
        run_dir, "fix-1", acceptance_evidence="Q1 已补齐机制级 insight 并绑定 current 结果。"
    )
    assert closed["status"] == "closed"
    assert closed["closure"]["verified"] is False
    require_no_open_repairs(run_dir)
    assert open_repair_directives(run_dir) == []


def test_unknown_route_rejected_closed_action_space(tmp_path: Path) -> None:
    """动作空间封闭：未知 route 不能被创建，哪怕 finding_class 是 unclassified。"""
    run_dir = _run(tmp_path, "closed-actions")
    with pytest.raises(ContractError, match="动作空间封闭"):
        open_repair_directive(
            run_dir, **_directive(route="run_forever", owner_stage="elsewhere")
        )


def test_duplicate_directive_rejected(tmp_path: Path) -> None:
    """同一指令 ID 不能重复登记。"""
    run_dir = _run(tmp_path, "dup-directive")
    open_repair_directive(run_dir, **_directive())
    with pytest.raises(ContractError, match="已存在"):
        open_repair_directive(run_dir, **_directive())


def test_visual_route_creates_visual_opportunity(tmp_path: Path) -> None:
    """route=visual 必须创建可被 Visual Sandbox 消费的机会。"""
    run_dir = _run(tmp_path, "visual-route")
    open_repair_directive(run_dir, **_directive(route="visual", owner_stage="visual"))
    apply_repair_route(run_dir, "fix-1")

    pool = load_json(run_dir / "figures/visual-opportunities.json")
    assert any(item.get("opportunity_id") == "repair-fix-1" for item in pool["opportunities"])


def test_author_route_marks_rework_in_external_mode(tmp_path: Path) -> None:
    """route=author 在外部交接模式下把草稿标为 rework_requested。"""
    run_dir = _run(tmp_path, "author-route")
    set_authoring_mode(run_dir, "external_handoff", reason="测试 author 返修路由")
    mark_authoring_status(run_dir, "handoff_ready")
    mark_authoring_status(run_dir, "waiting_external_author")
    mark_authoring_status(run_dir, "draft_imported")

    open_repair_directive(run_dir, **_directive(route="author", owner_stage="author"))
    apply_repair_route(run_dir, "fix-1")

    assert read_authoring(run_dir)["authoring_status"] == "rework_requested"


def test_render_route_marks_render_required(tmp_path: Path) -> None:
    """route=render 标记需要重新渲染，等待重新编译作为验收。"""
    run_dir = _run(tmp_path, "render-route")
    open_repair_directive(run_dir, **_directive(route="render", owner_stage="render"))
    result = apply_repair_route(run_dir, "fix-1")

    assert result["render_required"] is True
