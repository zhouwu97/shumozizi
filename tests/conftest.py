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


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """把依赖已废止阶段的断言隔离到 legacy-v3 CI 分片。"""
    for item in items:
        if Path(str(item.fspath)).name in _LEGACY_V3_FILES:
            item.add_marker(pytest.mark.legacy_v3)
        elif "competition_first" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.competition_first)
