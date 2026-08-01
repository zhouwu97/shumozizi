"""验证 v3.4 External Author Handoff 的 authoring 状态机。"""

from __future__ import annotations

from pathlib import Path

import pytest

from shumozizi.core.io import ContractError
from shumozizi.simple.authoring import (
    mark_authoring_status,
    read_authoring,
    record_handoff_revision,
    set_authoring_mode,
)
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.state import read_simple_state, write_simple_state


def _run(tmp_path: Path, name: str = "authoring", version: str = "3.2") -> Path:
    """创建最小 v3.2 运行，并把阶段推进到 paper。"""
    run_dir = initialize_simple_run(
        tmp_path,
        name,
        required_questions=["Q1"],
        workflow_version=version,
    )
    state = read_simple_state(run_dir)
    state["phase"] = "paper"
    write_simple_state(run_dir, state)
    return run_dir


def test_old_runs_default_to_internal_authoring(tmp_path: Path) -> None:
    """未启用交接的运行默认 internal，不出现外部交接语义。"""
    run_dir = _run(tmp_path, "default")
    authoring = read_authoring(run_dir)
    assert authoring["authoring_mode"] == "internal"
    assert authoring["authoring_status"] == "preparing_handoff"
    assert authoring["handoff_revision"] == 0


def test_switch_to_external_handoff_records_reason(tmp_path: Path) -> None:
    """切换到 external_handoff 必须记录原因，且切换后默认 preparing_handoff。"""
    run_dir = _run(tmp_path, "external")
    set_authoring_mode(run_dir, "external_handoff", reason="交给外部写作模型")
    authoring = read_authoring(run_dir)
    assert authoring["authoring_mode"] == "external_handoff"
    assert authoring["authoring_status"] == "preparing_handoff"


def test_switch_to_external_handoff_requires_reason(tmp_path: Path) -> None:
    """缺少切换原因必须被拒绝。"""
    run_dir = _run(tmp_path, "noreason")
    with pytest.raises(ContractError, match="原因"):
        set_authoring_mode(run_dir, "external_handoff", reason="")


def test_authoring_status_follows_allowed_transitions(tmp_path: Path) -> None:
    """合法迁移链：preparing → handoff_ready → waiting_external_author。"""
    run_dir = _run(tmp_path, "flow")
    set_authoring_mode(run_dir, "external_handoff", reason="测试")
    mark_authoring_status(run_dir, "handoff_ready")
    mark_authoring_status(run_dir, "waiting_external_author")
    authoring = read_authoring(run_dir)
    assert authoring["authoring_status"] == "waiting_external_author"


def test_waiting_external_author_is_not_blocked_phase(tmp_path: Path) -> None:
    """waiting_external_author 是正常暂停，阶段保持 paper 而非 blocked。"""
    run_dir = _run(tmp_path, "pause")
    set_authoring_mode(run_dir, "external_handoff", reason="测试")
    mark_authoring_status(run_dir, "handoff_ready")
    mark_authoring_status(run_dir, "waiting_external_author")
    state = read_simple_state(run_dir)
    assert state["phase"] == "paper"
    assert read_authoring(run_dir)["authoring_status"] == "waiting_external_author"


def test_illegal_authoring_transition_is_rejected(tmp_path: Path) -> None:
    """不能从 preparing_handoff 直接跳到 waiting_external_author。"""
    run_dir = _run(tmp_path, "illegal")
    set_authoring_mode(run_dir, "external_handoff", reason="测试")
    with pytest.raises(ContractError, match="不允许从 preparing_handoff"):
        mark_authoring_status(run_dir, "waiting_external_author")


def test_handoff_revision_is_monotonic(tmp_path: Path) -> None:
    """handoff_revision 只能递增，不能回退。"""
    run_dir = _run(tmp_path, "revision")
    record_handoff_revision(run_dir, 2)
    assert read_authoring(run_dir)["handoff_revision"] == 2
    with pytest.raises(ContractError, match="不能回退"):
        record_handoff_revision(run_dir, 1)


def test_authoring_mutation_rejects_non_v32_runs(tmp_path: Path) -> None:
    """外部交接只允许 v3.2+ 运行；v3.1 运行应被拒绝。"""
    run_dir = _run(tmp_path, "v31", version="3.1")
    with pytest.raises(ContractError, match="3.2"):
        set_authoring_mode(run_dir, "external_handoff", reason="测试")


def test_switching_back_to_internal_keeps_draft_files(tmp_path: Path) -> None:
    """回到 internal 不删除已存在的外部草稿文件。"""
    run_dir = _run(tmp_path, "back")
    set_authoring_mode(run_dir, "external_handoff", reason="测试")
    draft = run_dir / "paper/external-author/draft.tex"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text("\\section{草稿}\n", encoding="utf-8")
    set_authoring_mode(run_dir, "internal", reason="回到内部写作")
    assert draft.is_file()
    assert read_authoring(run_dir)["authoring_mode"] == "internal"
