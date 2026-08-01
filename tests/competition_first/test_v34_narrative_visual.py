"""v3.4 论文叙事资产、视觉机会和分层就绪状态回归。"""

from __future__ import annotations

from pathlib import Path

from shumozizi.core.io import atomic_json, load_json
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.paper.evidence import review_evidence_functions
from shumozizi.paper.materials import (
    build_material_pool,
    validate_material_pool_freshness,
)
from shumozizi.paper.policy import current_policy_fingerprints, evaluate_staleness
from shumozizi.paper.readiness import classify_paper_readiness
from shumozizi.paper.storyboard import (
    build_research_storyboard,
    validate_storyboard_freshness,
)
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.visual_opportunities import (
    build_visual_opportunity_pool,
    read_visual_opportunity_pool,
    record_visual_critic,
)


def _run(tmp_path: Path, name: str = "v34") -> Path:
    """创建带三问故事板骨架的兼容生产运行。"""
    return initialize_simple_run(
        tmp_path,
        name,
        required_questions=["Q1", "Q2", "Q3"],
        workflow_version="3.2",
    )


def test_material_pool_and_storyboard_keep_writing_inputs_separate(tmp_path: Path) -> None:
    """素材池和故事板应保存作者内容，但不把控制字段渲染进 Markdown。"""
    run_dir = _run(tmp_path, "assets")
    pool = build_material_pool(
        run_dir,
        materials=[
            {
                "material_id": "q1-answer",
                "category": "Direct Answer",
                "title": "第一问直接答案",
                "content": "联合可行域中的最优点由容量约束决定。",
                "question_id": "Q1",
                "source_result_ids": ["r-q1"],
                "inclusion": "body",
            },
            {
                "material_id": "q1-mechanism",
                "category": "Mechanism",
                "title": "容量约束活跃",
                "content": "边际收益在容量约束活跃后递减。",
                "question_id": "Q1",
                "source_result_ids": ["r-q1"],
                "inclusion": "body",
            },
        ],
    )
    storyboard = build_research_storyboard(
        run_dir,
        cards=[
            {
                "question_id": "Q1",
                "reader_needs": "先找到容量边界下的直接答案。",
                "key_derivation": "由联合可行域的互补松弛条件得到判据。",
                "mechanism": "容量约束活跃导致边际收益递减。",
                "material_ids": ["q1-answer", "q1-mechanism"],
            }
        ],
    )

    assert pool["status"] == "current"
    assert storyboard["status"] == "current"
    assert validate_material_pool_freshness(run_dir)["current"]
    assert validate_storyboard_freshness(run_dir)["current"]
    markdown = (run_dir / "paper/PAPER_MATERIAL_POOL.md").read_text(encoding="utf-8")
    assert "第一问直接答案" in markdown
    assert "production_results_digest" not in markdown
    assert "result_id" not in markdown


def test_policy_and_result_changes_invalidate_only_downstream_assets(tmp_path: Path) -> None:
    """正式结果变化级联到论文资产，单独政策变化不伪造正式结果过期。"""
    run_dir = _run(tmp_path, "stale")
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
    build_visual_opportunity_pool(
        run_dir,
        opportunities=[
            {
                "opportunity_id": "q1-mechanism",
                "question_id": "Q1",
                "visual_question": "瓶颈在哪里？",
                "atomic_claim": "容量边界产生拐点。",
                "candidate_archetypes": ["feasible_region_active_constraints"],
            }
        ],
    )
    current = evaluate_staleness(run_dir)
    assert current["current"]["formal_results"] == "current"
    assert current["current"]["material_pool"] == "current"

    index_path = run_dir / "results/index.json"
    index = load_json(index_path)
    index["audit_marker"] = "new-formal-result"
    atomic_json(index_path, index)
    changed = evaluate_staleness(run_dir)
    assert changed["current"]["formal_results"] == "current"
    assert changed["current"]["material_pool"] == "stale"
    assert changed["current"]["research_storyboard"] == "stale"
    assert changed["current"]["visual_opportunities"] == "stale"

    # 模拟编辑重新接收正式结果后，才单独测试论文政策变化的最小失效范围。
    build_material_pool(
        run_dir,
        materials=[
            {
                "material_id": "q1-answer-v2",
                "category": "Direct Answer",
                "title": "更新答案",
                "content": "更新后的答案仍由联合判据决定。",
                "question_id": "Q1",
                "inclusion": "body",
            }
        ],
    )
    build_research_storyboard(run_dir, cards=[{"question_id": "Q1"}])
    build_visual_opportunity_pool(
        run_dir,
        opportunities=[
            {
                "opportunity_id": "q1-mechanism-v2",
                "question_id": "Q1",
                "visual_question": "更新后的瓶颈在哪里？",
                "atomic_claim": "容量边界仍产生拐点。",
                "candidate_archetypes": ["feasible_region_active_constraints"],
            }
        ],
    )
    policies = current_policy_fingerprints(resolve_repo_root(Path(__file__)))
    paper_changed = evaluate_staleness(
        run_dir,
        paper_policy="0" * 64,
        visual_policy=policies["visual"],
    )
    assert paper_changed["current"]["formal_results"] == "current"
    assert paper_changed["current"]["visual_opportunities"] == "current"
    assert paper_changed["current"]["material_pool"] == "stale"


def test_short_report_has_scientific_layer_but_not_competition_layer(tmp_path: Path) -> None:
    """答案、公式和图示可以形成科学首层，但缺机制/结构/边界不能放行竞赛稿。"""
    run_dir = _run(tmp_path, "layers")
    source = run_dir / "paper/sections/q1.tex"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "\\section{Q1}\n"
        "答案预览：最优值为 12。\n"
        "\\begin{equation}J(x)=12\\end{equation}\n"
        "\\begin{figure}\\includegraphics{figures/q1.png}\\end{figure}\n",
        encoding="utf-8",
    )
    status = classify_paper_readiness(run_dir)
    assert status["scientific_ready"] is True
    assert status["narrative_ready"] is False
    assert status["competition_paper_ready"] is False
    assert any(
        item["code"] == "PAPER_SECTION_UNDERDEVELOPED"
        for item in status["narrative_findings"]
    )


def test_visual_opportunity_critic_supports_four_editorial_actions(tmp_path: Path) -> None:
    """视觉批评必须绑定新鲜上下文，并把动作写回机会池。"""
    run_dir = _run(tmp_path, "critic")
    build_visual_opportunity_pool(
        run_dir,
        opportunities=[
            {
                "opportunity_id": "q2-bottleneck",
                "question_id": "Q2",
                "visual_question": "哪个约束制造瓶颈？",
                "atomic_claim": "容量约束活跃后边际收益递减。",
                "candidate_archetypes": ["multi_panel_evidence_chain"],
            }
        ],
    )
    record = record_visual_critic(
        run_dir,
        "q2-bottleneck",
        verdict="PROMOTE",
        reviewer_context_id="fresh-critic-q2",
        review={
            "candidate_version": "v1",
            "observed": "可行域边界和最优点同时可见。",
            "mechanism": "边界变窄对应容量约束活跃。",
            "boundary": "只解释当前参数区间，不外推到其他容量。",
            "action": "进入正文决定性证据位置。",
        },
    )
    payload = read_visual_opportunity_pool(run_dir)
    target = payload["opportunities"][0]
    assert record["verdict"] == "PROMOTE"
    assert target["status"] == "promote"
    assert (run_dir / "figures/reviews/q2-bottleneck/v1.md").is_file()


def test_evidence_is_deduplicated_by_function_not_by_conclusion() -> None:
    """不同信任功能可以并存，同功能重复才建议压缩。"""
    report = review_evidence_functions(
        [
            {
                "evidence_id": "lower-bound",
                "claim_id": "claim-q1",
                "function": "lower_bound",
                "description": "解析下界。",
            },
            {
                "evidence_id": "active-constraint",
                "claim_id": "claim-q1",
                "function": "active_constraint",
                "description": "移除约束后的反事实。",
            },
            {
                "evidence_id": "lower-bound-copy",
                "claim_id": "claim-q1",
                "function": "lower_bound",
                "description": "重复下界计算。",
            },
        ]
    )
    assert report["legal"] is True
    assert len(report["distinct_function_groups"][0]["functions"]) == 2
    assert report["duplicate_groups"][0]["function"] == "lower_bound"
