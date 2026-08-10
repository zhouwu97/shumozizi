"""v3.4 论文叙事资产、视觉机会和分层就绪状态回归。"""

from __future__ import annotations

from pathlib import Path

from shumozizi.core.io import atomic_json, load_json
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.paper.editorial import (
    close_editorial_action,
    editorial_readiness,
    record_paper_cold_reader_actions,
)
from shumozizi.paper.evidence import review_evidence_functions
from shumozizi.paper.layout_optimizer import (
    build_layout_optimization,
    layout_optimization_freshness,
)
from shumozizi.paper.materials import (
    build_material_pool,
    validate_material_pool_freshness,
)
from shumozizi.paper.policy import current_policy_fingerprints, evaluate_staleness
from shumozizi.paper.readiness import classify_paper_readiness
from shumozizi.paper.storyboard import (
    build_research_storyboard,
    storyboard_progression_report,
    validate_storyboard_freshness,
)
from shumozizi.simple.figure_design import (
    build_figure_design_contract,
    read_figure_design_contract,
)
from shumozizi.simple.figure_templates_v34 import (
    select_v34_template,
    v34_template_registry_payload,
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


def test_material_pool_keeps_formal_metrics_as_intermediate_evidence(tmp_path: Path) -> None:
    """正式指标进入素材池，但不会被自动升级为直接答案或机制。"""
    run_dir = _run(tmp_path, "metrics")
    index = load_json(run_dir / "results/index.json")
    index["results"].append(
        {
            "result_id": "formal-q1",
            "question_id": "Q1",
            "status": "current",
            "execution_valid": True,
            "execution_mode": "production",
            "metrics": {"objective": 12.5, "feasible": True},
        }
    )
    atomic_json(run_dir / "results/index.json", index)
    pool = build_material_pool(run_dir)
    item = next(item for item in pool["items"] if item["material_id"] == "intermediate-formal-q1")
    assert item["category"] == "Intermediate Result"
    assert item["inclusion"] == "candidate"
    assert not any(
        item["category"] in {"Direct Answer", "Mechanism"} for item in pool["items"]
    )


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


def test_visual_opportunity_pool_checks_knowledge_without_auto_adoption(tmp_path: Path) -> None:
    """绘图阶段报告知识模式是否可用，但不替当前题自动选择模式。"""
    run_dir = _run(tmp_path, "knowledge-visual")
    atomic_json(
        run_dir / "knowledge/analysis-retrieval.json",
        {
            "matched_cards": [
                {
                    "visual_patterns": [
                        {
                            "pattern_id": "learned-mechanism-map",
                            "argument_roles": ["mechanism"],
                            "visual_archetype": "multi_panel_evidence_chain",
                            "required_data_fields": [],
                        }
                    ]
                }
            ],
            "accepted_patterns": [],
        },
    )
    atomic_json(
        run_dir / "analysis/MODELING_UNITS.json",
        {
            "schema_name": "modeling_units",
            "schema_version": "1.4",
            "units": [
                {
                    "unit_id": "u1",
                    "question_id": "Q1",
                    "core_question": True,
                    "visual_outputs": [
                        {"argument_unit_id": "a1", "output_path": "results/raw/q1.json"}
                    ],
                }
            ],
        },
    )
    pool = build_visual_opportunity_pool(run_dir, opportunities=[])
    check = pool["knowledge_check"]
    assert check["status"] == "ready"
    assert check["advisory_only"] is True
    assert check["recommendation_count"] == 1
    assert check["usable_pattern_ids"] == ["learned-mechanism-map"]
    assert pool["opportunities"] == []


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


def test_v34_template_registry_separates_design_assets_from_renderers() -> None:
    """五类高价值结构和比赛外壳都必须声明真实 renderer contract。"""
    registry = v34_template_registry_payload()
    assert len(registry["templates"]) >= 7
    assert select_v34_template("model_evolution_schematic")["status"] == "renderer_available"
    assert select_v34_template("model_evolution_schematic")["required_data"]
    assert select_v34_template("cumcm_semantic_v34")["status"] == "renderer_available"


def test_storyboard_progression_and_figure_design_contract_are_linked(tmp_path: Path) -> None:
    """故事板交接和图设计合同都绑定当前机会，而不是只记录图数量。"""
    run_dir = _run(tmp_path, "progression")
    build_material_pool(
        run_dir,
        materials=[
            {
                "material_id": "q1-structure",
                "category": "Visual Opportunity",
                "title": "Q1 结构机会",
                "content": "显示容量边界和最优点的关系。",
                "question_id": "Q1",
                "inclusion": "candidate",
            }
        ],
    )
    build_research_storyboard(
        run_dir,
        cards=[
            {
                "question_id": "Q1",
                "reader_needs": "先找到边界下的答案。",
                "why_math_object": "需要可行域表示共享容量。",
                "model_evolution": "从单约束扩展到共享约束。",
                "key_derivation": "由边界条件得到下界。",
                "handoff_to_next": "把活跃约束交给 Q2 的资源配置。",
            },
            {
                "question_id": "Q2",
                "reader_needs": "先看到资源配置答案。",
                "why_math_object": "需要状态转移表示资源。",
                "model_evolution": "继承 Q1 的容量边界。",
                "key_derivation": "由状态递推得到配置。",
            },
            {"question_id": "Q3"},
        ],
    )
    progression = storyboard_progression_report(run_dir)
    assert progression["valid"] is False
    assert any(item["question_id"] == "Q2" for item in progression["missing"])

    build_visual_opportunity_pool(
        run_dir,
        opportunities=[
            {
                "opportunity_id": "q1-structure",
                "question_id": "Q1",
                "visual_question": "边界在哪里？",
                "atomic_claim": "容量约束收紧时可行域变窄。",
                "candidate_archetypes": ["feasible_region_active_constraints"],
            }
        ],
    )
    contract = build_figure_design_contract(
        run_dir,
        "q1-structure",
        candidate_version="v1",
        selected_archetype="feasible_region_active_constraints",
        renderer="scripts/figures/render_q1.py",
        panels=[{"panel_id": "a", "takeaway": "可行域与活跃边界"}],
        mechanism_annotation="边界收紧对应容量约束活跃。",
    )
    assert contract["candidate"]["version"] == "v1"
    assert read_figure_design_contract(run_dir, "q1-structure", "v1")["run_id"] == run_dir.name


def test_layout_optimizer_preserves_narrative_order_without_hard_page_gate(tmp_path: Path) -> None:
    """高级版面优化只安排论证节拍，并绑定当前故事板与机会池。"""
    run_dir = _run(tmp_path, "layout")
    build_material_pool(
        run_dir,
        materials=[
            {
                "material_id": "q1-mechanism",
                "category": "Mechanism",
                "title": "Q1 机制",
                "content": "容量约束活跃后边际收益递减。",
                "question_id": "Q1",
                "inclusion": "body",
            }
        ],
    )
    build_research_storyboard(
        run_dir,
        cards=[
            {
                "question_id": "Q1",
                "reader_needs": "先看到答案。",
                "why_math_object": "用可行域表达共享约束。",
                "key_derivation": "由边界条件得到判据。",
                "mechanism": "容量约束活跃后边际收益递减。",
                "boundary": "只适用于当前容量区间。",
                "handoff_to_next": "将活跃约束交给 Q2。",
            }
        ],
    )
    build_visual_opportunity_pool(
        run_dir,
        opportunities=[
            {
                "opportunity_id": "q1-active",
                "question_id": "Q1",
                "visual_question": "哪个约束活跃？",
                "atomic_claim": "容量约束形成瓶颈。",
                "candidate_archetypes": ["feasible_region_active_constraints"],
            }
        ],
    )
    payload = build_layout_optimization(run_dir)
    roles = [item["role"] for item in payload["blocks"]]
    assert roles.index("answer_preview") < roles.index("math_object")
    assert roles.index("math_object") < roles.index("derivation")
    assert roles.index("derivation") < roles.index("mechanism")
    assert roles.index("mechanism") < roles.index("boundary")
    assert roles[-1] == "visual_opportunity"
    assert layout_optimization_freshness(run_dir)["current"] is True


def test_cold_reader_can_add_companion_figure_without_editing_science(tmp_path: Path) -> None:
    """冷读器的伴随图动作进入 living pool，并由作者关闭而非直接改正文。"""
    run_dir = _run(tmp_path, "editorial")
    build_visual_opportunity_pool(run_dir, opportunities=[])
    actions = record_paper_cold_reader_actions(
        run_dir,
        reviewer_context_id="fresh-paper-reader",
        actions=[
            {
                "action_id": "finding-17",
                "action": "ADD_COMPANION_FIGURE",
                "target_id": "q2-main",
                "reason": "主图没有显示哪一天决定下界。",
                "expected_benefit": "让读者看到活跃日期与下界机制。",
                "companion_figure": {
                    "opportunity_id": "q2-active-day",
                    "question_id": "Q2",
                    "visual_question": "哪一天真正决定下界？",
                    "atomic_claim": "第 12 日的覆盖余量最小。",
                    "candidate_archetypes": ["interval_event_timeline"],
                },
            }
        ],
    )
    assert actions["actions"][0]["status"] == "open"
    readiness = editorial_readiness(run_dir)
    assert readiness["ready"] is True
    assert readiness["advisory_actions"] == ["finding-17"]
    close_editorial_action(
        run_dir,
        "finding-17",
        closure_evidence="已生成候选图并在正文图后补充观察—机制—边界段落。",
    )
    assert editorial_readiness(run_dir)["ready"] is True
    assert read_visual_opportunity_pool(run_dir)["opportunities"][0]["origin"] == "paper_cold_reader"


def test_only_explicit_blocking_editorial_action_blocks_candidate(tmp_path: Path) -> None:
    """只有 Reviewer 明确标为阻断的高影响动作才拦截候选稿。"""
    run_dir = _run(tmp_path, "blocking-editorial")
    actions = record_paper_cold_reader_actions(
        run_dir,
        reviewer_context_id="fresh-blocking-reader",
        actions=[
            {
                "action_id": "finding-p1",
                "action": "ADD_DERIVATION",
                "target_id": "q3-core",
                "reason": "核心结论缺少可复核的中央推导。",
                "expected_benefit": "补齐决定正式答案可信度的论证。",
                "blocking": True,
            }
        ],
    )
    assert actions["actions"][0]["status"] == "open"
    readiness = editorial_readiness(run_dir)
    assert readiness["ready"] is False
    assert readiness["open_actions"] == ["finding-p1"]
