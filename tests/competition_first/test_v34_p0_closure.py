"""v3.4 beta P0 闭环：素材、视觉批评、冷读和页数硬门。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfWriter

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.paper.editorial import editorial_readiness
from shumozizi.paper.materials import build_material_pool
from shumozizi.paper.page_budget import audit_page_budget, verify_page_budget
from shumozizi.paper.storyboard import (
    build_research_storyboard,
    require_research_storyboard,
)
from shumozizi.simple.figure_design import build_figure_design_contract
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.state import utc_now
from shumozizi.simple.visual_opportunities import (
    build_visual_opportunity_pool,
    record_visual_critic,
    validate_visual_critic_record,
    visual_opportunity_pool_freshness,
)


def _run(tmp_path: Path, name: str, *, questions: list[str] | None = None) -> Path:
    """创建使用 v3.2 兼容状态、但执行 v3.4 论文资产门的运行。"""
    return initialize_simple_run(
        tmp_path,
        name,
        required_questions=questions or ["Q1"],
        workflow_version="3.2",
    )


def _write_pdf(path: Path, pages: int) -> None:
    """写入指定页数的最小有效 PDF，测试页数审计而不伪造论文内容。"""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        writer.write(stream)


def _full_card(question_id: str) -> dict[str, object]:
    """返回一问完整研究故事板卡片。"""
    return {
        "question_id": question_id,
        "reader_needs": "先看到共享容量下的直接答案。",
        "phenomenon": "容量收紧后可行域出现明显边界。",
        "why_math_object": "用可行域表达共享资源与边界。",
        "model_evolution": "本问继承共享容量并加入时间约束。",
        "key_derivation": "由边界条件推出最小余量判据。",
        "structural_finding": "最优点贴近一个活跃约束面。",
        "decision_determinant": "最小余量决定最终配置。",
        "mechanism": "活跃约束使继续增加资源的边际收益递减。",
        "contrast": "与自然 baseline 的边界位置进行对照。",
        "boundary": "结论只在当前容量和采样范围内成立。",
        "best_media": ["feasible_region_active_constraints"],
        "handoff_to_next": "把活跃约束和边界余量交给下一问。",
    }


def test_material_auto_pool_collects_science_and_local_figure_binding(tmp_path: Path) -> None:
    """自动素材池应吸收分析合同、正式结果、主张和当前图，而非整表反向绑定。"""
    run_dir = _run(tmp_path, "material-expansion")
    modeling = load_json(run_dir / "analysis/MODELING_UNITS.json")
    modeling["units"] = [
        {
            "unit_id": "unit-q1",
            "question_id": "Q1",
            "mathematical_object": "联合可行域",
            "objective": "最大化有效覆盖",
            "constraints": ["共享容量约束"],
            "question_delta": {"added_resources": ["时间窗口"]},
        }
    ]
    atomic_json(run_dir / "analysis/MODELING_UNITS.json", modeling)
    atomic_json(
        run_dir / "analysis/critical_claims.json",
        {
            "claims": [
                {
                    "claim_id": "claim-q1",
                    "claim_type": "mechanism_explanation",
                    "question_id": "Q1",
                    "statement": "容量边界决定有效覆盖的拐点。",
                    "evidence_needed": ["边界对照"],
                    "importance": "primary",
                }
            ]
        },
    )
    results = load_json(run_dir / "results/index.json")
    results["results"].append(
        {
            "result_id": "formal-q1",
            "question_id": "Q1",
            "status": "current",
            "execution_valid": True,
            "execution_mode": "production",
            "metrics": {"objective": 12.5},
            "conclusion": "Q1 的直接答案由联合可行域判据决定。",
            "derivation": "边界条件给出最小余量判据。",
            "mechanism": "容量约束活跃后边际收益递减。",
            "boundary": "只在当前容量区间内外推。",
        }
    )
    atomic_json(run_dir / "results/index.json", results)
    current_figure = run_dir / "figures/current/q1.png"
    current_figure.parent.mkdir(parents=True, exist_ok=True)
    current_figure.write_bytes(b"current-figure")
    figure_index = load_json(run_dir / "figures/index.json")
    figure_index["figures"].append(
        {
            "figure_id": "q1-hero",
            "status": "current",
            "paper_allowed": True,
            "question_id": "Q1",
            "takeaway": "最优点贴近活跃容量边界。",
            "outputs": [{"path": "figures/current/q1.png"}],
        }
    )
    atomic_json(run_dir / "figures/index.json", figure_index)

    pool = build_material_pool(run_dir)
    categories = {item["category"] for item in pool["items"]}
    assert {"Direct Answer", "Mathematical Derivation", "Mechanism", "Visual Opportunity"} <= categories
    figure_item = next(item for item in pool["items"] if item["material_id"] == "figure-q1-hero")
    assert figure_item["source_figure_bindings"]["q1-hero"]["outputs"][0]["path"] == "figures/current/q1.png"
    assert "figure_index_digest" not in pool["source_bindings"]


def test_longform_storyboard_gate_rejects_placeholder_cards(tmp_path: Path) -> None:
    """长篇编译使用的严格故事板门不能把空模板当作论文论证。"""
    run_dir = _run(tmp_path, "storyboard-gate")
    build_material_pool(
        run_dir,
        materials=[
            {
                "material_id": "q1-answer",
                "category": "Direct Answer",
                "title": "答案",
                "content": "答案由联合判据决定。",
                "question_id": "Q1",
                "inclusion": "body",
            }
        ],
    )
    build_research_storyboard(run_dir, cards=[{"question_id": "Q1"}])
    with pytest.raises(ContractError, match="占位|实质内容"):
        require_research_storyboard(run_dir, substantive=True)


def test_visual_opportunity_becomes_stale_when_storyboard_changes(tmp_path: Path) -> None:
    """故事板变更必须沿素材—故事板—机会 DAG 使视觉机会失效。"""
    run_dir = _run(tmp_path, "visual-dag")
    build_material_pool(
        run_dir,
        materials=[
            {
                "material_id": "q1-structure",
                "category": "Structural Observation",
                "title": "边界观察",
                "content": "活跃约束形成可见边界。",
                "question_id": "Q1",
                "inclusion": "body",
            }
        ],
    )
    build_research_storyboard(run_dir, cards=[_full_card("Q1")])
    build_visual_opportunity_pool(
        run_dir,
        opportunities=[
            {
                "opportunity_id": "q1-boundary",
                "question_id": "Q1",
                "visual_question": "边界在哪里？",
                "atomic_claim": "活跃约束形成边界。",
                "candidate_archetypes": ["feasible_region_active_constraints"],
            }
        ],
    )
    storyboard_path = run_dir / "paper/generated/research_storyboard.json"
    storyboard = load_json(storyboard_path)
    storyboard["generated_at"] = utc_now()
    atomic_json(storyboard_path, storyboard)
    freshness = visual_opportunity_pool_freshness(run_dir)
    assert freshness["current"] is False
    assert "storyboard_digest" in freshness["stale_fields"]


def test_visual_critic_hard_gate_rejects_unbound_promote(tmp_path: Path) -> None:
    """PROMOTE 文字不能绕过候选 PNG/PDF/设计合同的实际绑定。"""
    run_dir = _run(tmp_path, "critic-gate")
    build_material_pool(
        run_dir,
        materials=[
            {
                "material_id": "q1-visual",
                "category": "Visual Opportunity",
                "title": "Q1 图机会",
                "content": "让评委看到边界和最优点。",
                "question_id": "Q1",
                "inclusion": "candidate",
            }
        ],
    )
    build_research_storyboard(run_dir, cards=[_full_card("Q1")])
    build_visual_opportunity_pool(
        run_dir,
        opportunities=[
            {
                "opportunity_id": "q1-visual",
                "question_id": "Q1",
                "visual_question": "边界和最优点如何同时可见？",
                "atomic_claim": "最优点贴近活跃边界。",
                "candidate_archetypes": ["undecided"],
            }
        ],
    )
    candidate_dir = run_dir / "figures/work/q1-visual/v1"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    png = candidate_dir / "q1-visual.png"
    pdf = candidate_dir / "q1-visual.pdf"
    png.write_bytes(b"candidate-png")
    _write_pdf(pdf, 1)
    build_figure_design_contract(
        run_dir,
        "q1-visual",
        candidate_version="v1",
        selected_archetype="undecided",
        renderer="tests",
        panels=[{"panel_id": "main", "takeaway": "边界与最优点"}],
    )
    review = {
        "observed": "图中可看到边界和最优点。",
        "mechanism": "活跃约束解释最优点位置。",
        "boundary": "当前图不能外推参数范围。",
        "action": "保留并在图后补充机制说明。",
        "candidate_version": "v1",
    }
    record_visual_critic(
        run_dir,
        "q1-visual",
        verdict="PROMOTE",
        review=review,
        reviewer_context_id="fresh-critic",
    )
    with pytest.raises(ContractError, match="绑定完整|artifact|产物"):
        validate_visual_critic_record(
            run_dir,
            "q1-visual",
            "v1",
            require_artifact_binding=True,
        )
    record_visual_critic(
        run_dir,
        "q1-visual",
        verdict="PROMOTE",
        review=review,
        reviewer_context_id="fresh-critic",
        candidate_png="figures/work/q1-visual/v1/q1-visual.png",
        candidate_pdf="figures/work/q1-visual/v1/q1-visual.pdf",
        design_contract_path="figures/work/q1-visual/v1/design-contract.json",
    )
    assert validate_visual_critic_record(
        run_dir, "q1-visual", "v1", require_artifact_binding=True
    )["artifact_binding_complete"] is True


def test_strict_cold_reader_requires_current_source_or_explicit_waiver(tmp_path: Path) -> None:
    """候选稿缺少冷读时阻断，只有带原因的 emergency/fallback 才能显式放宽。"""
    run_dir = _run(tmp_path, "cold-reader-gate")
    assert editorial_readiness(run_dir, require_record=True)["ready"] is False
    atomic_json(
        run_dir / "review/PAPER_COLD_READER_WAIVER.json",
        {
            "schema_name": "paper_cold_reader_waiver",
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "mode": "fallback",
            "reason": "本次仅用于紧急回退演示，外部冷读上下文暂时不可用。",
            "recorded_at": utc_now(),
        },
    )
    assert editorial_readiness(run_dir, require_record=True)["ready"] is True


def test_page_budget_writes_report_before_blocking_short_pdf(tmp_path: Path) -> None:
    """少于 18 页必须留下页数证据并阻断严格候选编译。"""
    run_dir = _run(tmp_path, "page-budget")
    pdf = run_dir / "paper/short.pdf"
    _write_pdf(pdf, 10)
    with pytest.raises(ContractError, match="页数门阻断"):
        audit_page_budget(run_dir, pdf, enforce_minimum=True)
    report = load_json(run_dir / "qa/paper-page-budget.json")
    assert report["page_count"] == 10
    assert report["status"] == "under_18_review_required"
    assert verify_page_budget(run_dir, pdf_path=pdf)["valid"] is True
