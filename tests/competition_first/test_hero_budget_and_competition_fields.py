"""验证 v3.4 Hero 预算与 9.2 评审字段（9.1/9.2）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from shumozizi.core.io import ContractError
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.paper_image_prompts import HERO_BUDGET, _candidate_score, _selected_hero_ids
from shumozizi.simple.visual_sandbox import (
    record_visual_competition,
    write_visual_ideas,
)


def _requirement(
    *,
    question_id: str,
    purpose: str,
    mathematical_object: str = "",
    tier: str = "supporting_figure",
    claim: str | None = None,
    figure_tier: str | None = None,
) -> dict:
    """构造带角色与对象的视觉需求。"""
    return {
        "question_id": question_id,
        "purpose": purpose,
        "mathematical_object": mathematical_object,
        "figure_tier": figure_tier or (
            "hero_figure" if purpose == "decisive_evidence" else tier
        ),
        "claim": claim
        or f"{question_id} 的{purpose}论证需要一张能直接显示对象与结论的图。",
        "visual_question": f"如何让评委直接看到 {question_id} 的{purpose}对象？",
        "requirement_id": f"VR-{question_id}-{purpose}-test0001",
        "source_span": "paper/longform-source.tex:1-2",
        "status": "open",
        "covered_by_figure_ids": [],
        "preferred_structures": ["mathematical-object schematic"],
    }


def test_decisive_evidence_can_be_selected_as_hero() -> None:
    """决定性证据不再被排除在 Hero 竞争之外（根因 4 修复）。"""
    unit = {
        "visual_outputs": [
            {
                "required_data": [
                    "lattice_points", "feasible_mask", "costs", "selected_point"
                ]
            }
        ]
    }
    requirement = _requirement(
        question_id="Q4",
        purpose="decisive_evidence",
        mathematical_object="integer_feasible_region",
    )
    score, reasons = _candidate_score(requirement, unit)
    assert score > 0
    assert "decisive_evidence_hero" in reasons
    assert "object_aware=integer_feasible_region" in reasons


def test_mechanism_and_boundary_can_compete_for_hero() -> None:
    """机制与边界论证同样可以成为 Hero 候选。"""
    for purpose in ("mechanism", "boundary"):
        score, _ = _candidate_score(
            _requirement(question_id="Q1", purpose=purpose), {}
        )
        assert score >= 12, purpose


def test_global_hero_budget_caps_planned_candidates() -> None:
    """全篇 Hero 预算限制正式结构竞争数量，不机械按问分配。"""
    requirements = [
        _requirement(
            question_id=f"Q{index}",
            purpose="decisive_evidence" if index % 2 else "mechanism",
            mathematical_object="integer_feasible_region",
            figure_tier="hero_figure",
        )
        for index in range(1, 7)
    ]
    units = {str(item["question_id"]): {} for item in requirements}
    selected, _ = _selected_hero_ids(requirements, units)
    assert len(selected) <= HERO_BUDGET
    assert len(selected) == HERO_BUDGET


def test_hero_competition_requires_92_review_fields(tmp_path: Path) -> None:
    """hero_figure 评审必须填写对象可见性、领域特异性与边界等字段（9.2）。"""
    run_dir = initialize_simple_run(tmp_path, "hero-review-fields", required_questions=["Q1"])
    write_visual_ideas(
        run_dir,
        [
            {
                "id": "q1-hero-fields",
                "question": "哪些对象必须可见？",
                "sources": ["Q1"],
                "idea": "对象、机制与边界在同一主图中分层。",
                "figure_tier": "hero_figure",
            }
        ],
    )
    sandbox = run_dir / "figures/sandbox/q1-hero-fields"
    sandbox.mkdir(parents=True)
    (sandbox / "a.png").write_bytes(b"candidate-a")
    (sandbox / "b.png").write_bytes(b"candidate-b")
    structures = {
        "figures/sandbox/q1-hero-fields/a.png": "spatial_scene",
        "figures/sandbox/q1-hero-fields/b.png": "network_backbone",
    }

    with pytest.raises(ContractError, match="9.2 字段"):
        record_visual_competition(
            run_dir,
            "q1-hero-fields",
            selected_candidate="figures/sandbox/q1-hero-fields/b.png",
            reviewer_context_id="fresh-visual-reader",
            fastest_mechanism="B 最快显示骨架。",
            full_width_value="主图需要整栏。",
            table_redundancy="表格无法显示对象。",
            rationale="需要真实结构竞争。",
            candidate_structures=structures,
        )

    review = record_visual_competition(
        run_dir,
        "q1-hero-fields",
        selected_candidate="figures/sandbox/q1-hero-fields/b.png",
        reviewer_context_id="fresh-visual-reader",
        fastest_mechanism="B 最快显示骨架。",
        full_width_value="主图需要整栏。",
        table_redundancy="表格无法显示对象。",
        rationale="需要真实结构竞争。",
        candidate_structures=structures,
        model_object_visibility="粒子与接触边在 B 中可见。",
        domain_specificity="换题后周期身份语义失效。",
        mechanism_or_path_visibility="贯通路径直接标出。",
        constraint_or_boundary_visibility="周期边界可见。",
        uncertainty_visibility="区间仅用于辅助。",
        paper_size_legibility="整栏下文字可读。",
        information_density="每面板一个对象。",
        reading_order="A 到 B 按对象到骨架。",
        known_risks="3D 面板可能遮挡。",
    )
    assert review["schema_version"] == "1.1"
    assert review["model_object_visibility"]
    assert review["known_risks"] == "3D 面板可能遮挡。"


def test_supporting_competition_does_not_require_92_fields(tmp_path: Path) -> None:
    """supporting 图允许旧版五项判断，9.2 字段可后续补充。"""
    run_dir = initialize_simple_run(
        tmp_path, "supporting-review", required_questions=["Q1"]
    )
    write_visual_ideas(
        run_dir,
        [
            {
                "id": "q1-supporting",
                "question": "哪个候选更清楚？",
                "sources": ["Q1"],
                "idea": "支撑图单候选即可。",
            }
        ],
    )
    sandbox = run_dir / "figures/sandbox/q1-supporting"
    sandbox.mkdir(parents=True)
    (sandbox / "a.png").write_bytes(b"candidate-a")

    review = record_visual_competition(
        run_dir,
        "q1-supporting",
        selected_candidate="figures/sandbox/q1-supporting/a.png",
        reviewer_context_id="fresh-visual-reader",
        fastest_mechanism="A 显示边界。",
        full_width_value="无需整栏。",
        table_redundancy="不替代表格。",
        rationale="支撑图按需补充。",
    )
    assert "model_object_visibility" not in review
