"""管理 v3.4 External Author Handoff 的 authoring 状态机。

该层只负责 ``authoring_mode``、``authoring_status`` 与 ``handoff_revision``
的读写与合法迁移，不判断科学材料是否充分。``waiting_external_author`` 是
正常暂停，不是 blocked；迁移守卫只防止状态机跳跃，不替代任何科学门禁。

外部写作模型的草稿永远保留在 ``paper/external-author/``，即使上游结果变化
也只把状态标成 ``needs_rebase``，绝不删除用户已写好的稿件。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError
from shumozizi.simple.state import (
    is_competition_first_v32_state,
    read_simple_state,
    utc_now,
    write_simple_state,
)

AUTHORING_MODES = ("internal", "external_handoff")
AUTHORING_STATUSES = (
    "preparing_handoff",
    "handoff_ready",
    "waiting_external_author",
    "draft_imported",
    "rework_requested",
    "author_pass_accepted",
    "needs_rebase",
)
ALLOWED_AUTHORING_TRANSITIONS = {
    "preparing_handoff": {"handoff_ready"},
    "handoff_ready": {"waiting_external_author", "preparing_handoff"},
    "waiting_external_author": {"draft_imported", "preparing_handoff", "needs_rebase"},
    "draft_imported": {"rework_requested", "author_pass_accepted", "needs_rebase"},
    # 返修后可重新导入修订稿，或重建交接包继续等待外部 Author。
    "rework_requested": {
        "draft_imported",
        "waiting_external_author",
        "preparing_handoff",
        "needs_rebase",
    },
    "author_pass_accepted": {"handoff_ready", "preparing_handoff", "needs_rebase"},
    "needs_rebase": {"handoff_ready", "preparing_handoff"},
}

EXTERNAL_DRAFT_PATH = Path("paper/external-author/draft.tex")


def read_authoring(run_dir: Path) -> dict[str, Any]:
    """读取并返回当前 authoring 状态（旧运行自动补默认值）。"""
    state = read_simple_state(run_dir)
    return {
        "authoring_mode": state.get("authoring_mode", "internal"),
        "authoring_status": state.get("authoring_status", "preparing_handoff"),
        "handoff_revision": int(state.get("handoff_revision", 0)),
        "phase": state["phase"],
        "external_draft_present": (run_dir / EXTERNAL_DRAFT_PATH).is_file(),
    }


def _require_v32(run_dir: Path) -> dict[str, Any]:
    """只允许在 Competition-First v3.2+ 状态上写 authoring 字段。"""
    state = read_simple_state(run_dir)
    if not is_competition_first_v32_state(state):
        raise ContractError("External Author Handoff 仅支持 Competition-First v3.2+ 运行")
    return state


def set_authoring_mode(run_dir: Path, mode: str, *, reason: str) -> dict[str, Any]:
    """在 ``internal`` 与 ``external_handoff`` 之间切换写作交接模式。

    Args:
        run_dir: 当前运行目录。
        mode: 目标模式，必须是 ``internal`` 或 ``external_handoff``。
        reason: 切换原因；回 internal 时必须记录，避免把外部交接静默废弃。

    Returns:
        写入后的完整 v3 状态。

    Raises:
        ContractError: 模式未知、缺少原因，或运行不属于 v3.2+。
    """
    if mode not in AUTHORING_MODES:
        raise ContractError(f"未知 authoring mode: {mode}")
    if not isinstance(reason, str) or not reason.strip():
        raise ContractError("切换 authoring mode 必须记录具体原因")
    state = _require_v32(run_dir)
    state["authoring_mode"] = mode
    if mode == "internal":
        # 回到内部写作：已存在的外部草稿文件保留，但不参与状态迁移。
        state["authoring_status"] = "preparing_handoff"
    else:
        state.setdefault("authoring_status", "preparing_handoff")
    state["revision"] += 1
    state["updated_at"] = utc_now()
    write_simple_state(run_dir, state)
    return state


def mark_authoring_status(run_dir: Path, status: str) -> dict[str, Any]:
    """按合法迁移表推进 authoring_status。

    Args:
        run_dir: 当前运行目录。
        status: 目标状态，必须是 ``AUTHORING_STATUSES`` 之一。

    Returns:
        写入后的完整 v3 状态。

    Raises:
        ContractError: 状态未知、迁移非法，或运行不属于 v3.2+。
    """
    if status not in AUTHORING_STATUSES:
        raise ContractError(f"未知 authoring_status: {status}")
    state = _require_v32(run_dir)
    current = state.get("authoring_status", "preparing_handoff")
    if status not in ALLOWED_AUTHORING_TRANSITIONS[current]:
        raise ContractError(f"authoring_status 不允许从 {current} 直接进入 {status}")
    state["authoring_status"] = status
    state["revision"] += 1
    state["updated_at"] = utc_now()
    write_simple_state(run_dir, state)
    return state


def require_internal_authoring(run_dir: Path) -> None:
    """外部交接模式下禁止自动撰写正式正文。

    ``waiting_external_author`` 等状态表示正文写作任务已交给外部 Author；
    此时自动编译正式正文会把外部稿件之外的内容悄悄写进论文。只有
    ``draft_imported``（外部稿已导入并通过 audit）或 ``author_pass_accepted``
    之后才允许编译。

    Args:
        run_dir: 当前运行目录。

    Raises:
        ContractError: external 模式下 authoring_status 尚未推进到可编译状态。
    """
    state = read_simple_state(run_dir)
    if state.get("authoring_mode") != "external_handoff":
        return
    status = state.get("authoring_status", "preparing_handoff")
    if status in {"draft_imported", "author_pass_accepted"}:
        return
    raise ContractError(
        f"external_handoff 模式下 authoring_status={status}，"
        "禁止自动撰写正式正文；请先导入外部草稿或完成裁决后再编译"
    )


def record_handoff_revision(run_dir: Path, revision: int) -> dict[str, Any]:
    """单调递增 Writer Handoff 修订号。

    Args:
        run_dir: 当前运行目录。
        revision: 新修订号，必须不小于当前值。

    Returns:
        写入后的完整 v3 状态。

    Raises:
        ContractError: 修订号非法、回退，或运行不属于 v3.2+。
    """
    if not isinstance(revision, int) or revision < 0:
        raise ContractError("handoff_revision 必须是非负整数")
    state = _require_v32(run_dir)
    current = int(state.get("handoff_revision", 0))
    if revision < current:
        raise ContractError("handoff_revision 不能回退")
    if revision == current:
        return state
    state["handoff_revision"] = revision
    state["revision"] += 1
    state["updated_at"] = utc_now()
    write_simple_state(run_dir, state)
    return state
