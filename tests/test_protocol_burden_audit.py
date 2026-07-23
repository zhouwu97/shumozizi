"""验证主动 Skill 已把协议细节下沉到可执行收据。"""

from __future__ import annotations

from pathlib import Path

from scripts.qa.audit_protocol_burden import audit_protocol_burden
from shumozizi.simple.capabilities import (
    record_knowledge_consumption,
    require_capability_route,
    write_capability_route,
    write_local_tooling,
)
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.state import update_simple_state

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_protocol_burden_audit_keeps_math_focus_ahead_of_protocol() -> None:
    """主对话只保留少量决策，数学重点不得被协议说明挤占。"""
    report = audit_protocol_burden(REPO_ROOT)
    summary = report["summary"]

    assert report["missing_skill_files"] == []
    assert report["main_dialogue_decisions"] == [
        "problem_families",
        "capabilities",
        "verification_capability",
        "toolchain",
        "knowledge_assets",
    ]
    assert report["conditional_dialogue_decision"] == "visual_evidence"
    assert summary["main_dialogue_required_field_count"] == 5
    assert summary["main_dialogue_protocol_field_count"] == 0
    assert summary["math_focus_at_least_protocol"] is True
    assert summary["protocol_explanation_lines"] > 0
    assert summary["math_focus_at_least_protocol_explanation"] is True
    assert summary["cognitive_burden_reduced"] is True
    assert all(guard["available"] for guard in report["runtime_guards"])
    assert "不是安全或科学正确性的证明" in report["limitations"]


def test_route_decisions_generate_protocol_receipts_without_manual_fields(tmp_path: Path) -> None:
    """五项路由决策应由运行时补齐工具与知识收据，而不是要求人工填写。"""
    run_dir = initialize_simple_run(tmp_path, "lean-route")
    update_simple_state(run_dir, phase="capability_route")
    write_local_tooling(run_dir)
    route = write_capability_route(
        run_dir,
        {
            "schema_version": "1.2",
            "problem_families": ["other"],
            "capabilities": [
                {
                    "id": "general-modeling",
                    "reason": "最小运行只需要通用建模能力来验证路由边界。",
                }
            ],
            "verification_capability": None,
            "toolchain": {"production_engine": "python"},
            "knowledge_assets": ["knowledge/cards/structural-preflight.json"],
        },
    )

    assert route["status"] == "ready"
    assert route["run_id"] == "lean-route"
    assert isinstance(route["tooling_sha256"], str)
    assert route["toolchain"]["requirement_receipts"] == []
    assert isinstance(route["knowledge_assets"][0]["sha256"], str)

    receipt = record_knowledge_consumption(run_dir)
    assert receipt["reader"]["operation"] == "controlled_binary_read"
    assert require_capability_route(run_dir)["run_id"] == "lean-route"


def test_active_skills_keep_latex_first_and_runtime_receipts() -> None:
    """精简不能回退成手工模板、联网搜索或无收据的声明。"""
    router = (REPO_ROOT / ".agents/skills/mathmodel-capability-router/SKILL.md").read_text(
        encoding="utf-8"
    )
    workflow = (REPO_ROOT / ".agents/skills/mathmodel-workflow/SKILL.md").read_text(
        encoding="utf-8"
    )
    paper = (REPO_ROOT / ".agents/skills/mathmodel-paper/SKILL.md").read_text(encoding="utf-8")
    writing = (REPO_ROOT / "skills/5writing/SKILL.md").read_text(encoding="utf-8")

    assert "record_knowledge_consumption.py" in router
    assert "--engine auto" in workflow
    assert "--engine auto" in paper
    assert "--engine auto" in writing
    assert "WebSearch" not in writing
    assert "WebFetch" not in writing
    assert "不要假设固定三问" in writing
    assert "动态决定" in writing
    assert "不能静默替代或手工搭建入口" in writing
