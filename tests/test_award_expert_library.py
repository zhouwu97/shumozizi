"""CUMCM A/B 获奖论文结构专家库的隔离与路由测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError
from shumozizi.knowledge.award_experts import (
    AWARD_EXPERT_AUDIT_PATH,
    audit_award_expert_route,
    load_award_expert_library,
    write_award_expert_route,
    write_baseline_freeze,
)
from shumozizi.simple.initialization import initialize_simple_run


def _run(tmp_path: Path, identifier: str) -> Path:
    """创建带当前题面的最小 v3.2 运行。"""
    run_dir = initialize_simple_run(
        tmp_path,
        identifier,
        competition="cumcm",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    (run_dir / "problem" / "statement.md").write_text("在约束下最小化总成本。", encoding="utf-8")
    return run_dir


def _freeze(run_dir: Path) -> None:
    """冻结一个仅基于题面的简单 baseline。"""
    write_baseline_freeze(
        run_dir,
        {
            "question_id": "Q1",
            "baseline": {
                "mathematical_structure": "可解释的约束规则模型",
                "objective": "统一 exact 总成本",
                "rationale": "先建立可行性和目标口径，再比较竞争路线。",
            },
            "independent_analysis": {
                "allowed_inputs": ["problem/"],
                "award_expert_library_used": False,
                "external_discussion_used": False,
                "web_answer_search_used": False,
            },
        },
    )


def test_award_expert_route_is_advisory_before_baseline_freeze(tmp_path: Path) -> None:
    """未冻结时仍可获得建议，但收据必须显式限制其用途。"""
    run_dir = _run(tmp_path, "award-route-no-freeze")

    route = write_award_expert_route(run_dir, award_question="A", phase="analysis")
    audit = audit_award_expert_route(run_dir, route)

    assert route["baseline_status"] == "not_frozen"
    assert route["baseline_freeze_sha256"] is None
    assert route["baseline_question_id"] is None
    assert route["advisory_only"] is True
    assert route["requires_independent_verification"] is True
    assert route["external_discussion_policy"]["online_answer_search"] == "prohibited"
    assert audit["status"] == "pass", audit


def test_award_expert_routes_are_small_prompt_safe_and_cover_a_b_specialists(tmp_path: Path) -> None:
    """A/B 路由各保留少量结构卡，且不会返回来源资料。"""
    run_dir = _run(tmp_path, "award-route-safe")
    _freeze(run_dir)

    route_a = write_award_expert_route(
        run_dir,
        award_question="A",
        phase="analysis",
        topic_key="route_design",
    )
    route_b = write_award_expert_route(
        run_dir,
        award_question="B",
        phase="experiment",
        topic_key="comparison",
    )
    audit = audit_award_expert_route(run_dir, route_b)
    rendered = json.dumps(route_b, ensure_ascii=False)

    assert 3 <= len(route_a["selected_cards"]) <= 6
    assert 3 <= len(route_b["selected_cards"]) <= 6
    assert "a-state-predicate-optimizer" in {item["card_id"] for item in route_a["selected_cards"]}
    assert "b-baseline-uncertainty" in {item["card_id"] for item in route_b["selected_cards"]}
    assert route_a["baseline_status"] == "frozen"
    assert route_a["baseline_freeze_sha256"] == route_b["baseline_freeze_sha256"]
    assert audit["status"] == "pass", audit
    assert audit["raw_sources_returned"] == 0
    assert audit["access_monitoring"]["enabled"] is False
    for prohibited in ("http://", "https://", "paper_id", "evidence_refs", "pages", "C:\\"):
        assert prohibited not in rendered


def test_baseline_snapshot_can_be_revised_after_advice_and_invalidates_old_route(tmp_path: Path) -> None:
    """发现问题后允许修订快照，旧路由不能伪装成仍绑定当前基线。"""
    run_dir = _run(tmp_path, "award-route-revision")
    _freeze(run_dir)
    route = write_award_expert_route(run_dir, award_question="A", phase="analysis")

    revised = write_baseline_freeze(
        run_dir,
        {
            "question_id": "Q1",
            "baseline": {
                "mathematical_structure": "可解释的约束规则模型",
                "objective": "统一 exact 总成本",
                "rationale": "讨论提出反例后，补入边界条件并重建可行性基线。",
            },
            "independent_analysis": {
                "allowed_inputs": ["problem/"],
                "award_expert_library_used": True,
                "external_discussion_used": True,
                "web_answer_search_used": False,
            },
        },
    )

    stale_audit = audit_award_expert_route(run_dir, route)
    fresh_route = write_award_expert_route(run_dir, award_question="A", phase="analysis")
    fresh_audit = audit_award_expert_route(run_dir, fresh_route)

    assert revised["revision"] == 2
    assert revised["independent_analysis"]["external_discussion_used"] is True
    assert stale_audit["status"] == "fail"
    assert fresh_route["baseline_freeze_sha256"] != route["baseline_freeze_sha256"]
    assert fresh_audit["status"] == "pass", fresh_audit


def test_baseline_rejects_web_answer_search_claim(tmp_path: Path) -> None:
    """建议来源记录不得把网页答案检索包装成题意讨论。"""
    run_dir = _run(tmp_path, "award-route-web-search")

    with pytest.raises(ContractError, match="禁止联网检索"):
        write_baseline_freeze(
            run_dir,
            {
                "question_id": "Q1",
                "baseline": {
                    "mathematical_structure": "约束模型",
                    "objective": "总成本",
                    "rationale": "记录讨论后的初始方案。",
                },
                "independent_analysis": {
                    "allowed_inputs": ["problem/"],
                    "award_expert_library_used": False,
                    "external_discussion_used": True,
                    "web_answer_search_used": True,
                },
            },
        )


def test_legacy_baseline_remains_readable_for_audit(tmp_path: Path) -> None:
    """旧版仅记录专家库字段的 baseline 不应阻断已有运行。"""
    run_dir = _run(tmp_path, "award-route-legacy-baseline")
    _freeze(run_dir)
    path = run_dir / "analysis" / "BASELINE_FREEZE.json"
    legacy = json.loads(path.read_text(encoding="utf-8"))
    legacy.pop("revision")
    legacy["independent_analysis"].pop("external_discussion_used")
    legacy["independent_analysis"].pop("web_answer_search_used")
    path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

    route = write_award_expert_route(run_dir, award_question="B", phase="analysis")
    audit = audit_award_expert_route(run_dir, route)

    assert route["baseline_status"] == "frozen"
    assert audit["status"] == "pass", audit


def test_award_expert_audit_rejects_a_tampered_route(tmp_path: Path) -> None:
    """修改卡片、阶段或 baseline 哈希都会使审计不可通过。"""
    run_dir = _run(tmp_path, "award-route-tampered")
    _freeze(run_dir)
    route = write_award_expert_route(run_dir, award_question="B", phase="analysis")
    route["selected_cards"][0]["instruction_zh"] = "伪造指令"

    audit = audit_award_expert_route(run_dir, route)

    assert audit["status"] == "fail"
    persisted = json.loads((run_dir / AWARD_EXPERT_AUDIT_PATH).read_text(encoding="utf-8"))
    assert persisted["status"] == "fail"
    assert any("不一致" in error for error in persisted["errors"])


def test_runtime_library_excludes_provenance_and_uses_latex_layout_role() -> None:
    """运行时库不得携带论文定位资料，也不得保留 Word 默认角色。"""
    library = load_award_expert_library()
    rendered = json.dumps(library, ensure_ascii=False)

    assert len(library["cards"]) == 21
    assert len(library["experts"]) == 15
    assert "latex-layout-editor" in {item["id"] for item in library["experts"]}
    assert "word-layout-editor" not in rendered
    assert "writing-round-" not in rendered
    for prohibited in ("http://", "https://", "evidence_refs", "paper_id", "source_url", "\"pages\""):
        assert prohibited not in rendered
