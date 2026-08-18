"""测试分组：默认验证生产 v3.1，旧 v3.0 生命周期保留为显式回归。"""

from __future__ import annotations

from pathlib import Path

import pytest

_LEGACY_V3_FILES = {
    "test_active_skill_installation.py",
    "test_capability_first_v3.py",
    "test_capability_knowledge_import.py",
    "test_capability_quality_protocol.py",
    "test_capability_routing_visualization.py",
    "test_cumcm_2025_a_recovery.py",
    "test_independent_review_workflow.py",
    "test_objective_semantics_review.py",
    "test_paper_final_qa.py",
    "test_paper_readiness_gate.py",
    "test_paper_reference_interface.py",
    "test_protocol_burden_audit.py",
    "test_red_team_skill.py",
    "test_simple_state_transitions.py",
    "test_verification_protocol.py",
}


def pytest_configure(config: pytest.Config) -> None:
    """受限 Windows 沙箱无法枚举 POSIX ``0o700`` 目录（pytest 临时目录默认模式）。

    WHY：在带文件沙箱的 Windows 环境里，``os.makedirs(mode=0o700)`` 创建的目录会被
    当作“其他用户私有”而拒绝 ``os.listdir``。pytest 的 basetemp 无论走 ``--basetemp``
    还是默认 temproot 都硬编码 ``mkdir(mode=0o700)``（``_pytest.tmpdir`` 内部），
    导致任何 pytest 会话在 session-finish 清理 basetemp 时 PermissionError。
    这里把 ``Path.mkdir`` 的 ``0o700`` 统一改为常规 ``0o755``，只影响临时测试目录
    的可见性，不改变任何业务语义。
    """
    import pathlib

    if getattr(pathlib.Path, "_shumozizi_mkdir_mode_patched", False):
        return

    _original_mkdir = pathlib.Path.mkdir

    def _listable_mkdir(self, mode: int = 0o777, parents: bool = False, exist_ok: bool = False):
        if mode == 0o700:
            mode = 0o755
        return _original_mkdir(self, mode=mode, parents=parents, exist_ok=exist_ok)

    pathlib.Path.mkdir = _listable_mkdir  # type: ignore[method-assign]
    pathlib.Path._shumozizi_mkdir_mode_patched = True  # type: ignore[attr-defined]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """把依赖已废止阶段的断言隔离到 legacy-v3 CI 分片。"""
    for item in items:
        if Path(str(item.fspath)).name in _LEGACY_V3_FILES:
            item.add_marker(pytest.mark.legacy_v3)
        elif "competition_first" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.competition_first)
