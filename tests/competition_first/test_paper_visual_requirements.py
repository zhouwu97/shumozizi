"""验证论文论证能够自动产生视觉需求，并向新质量合同暴露高级图规格。"""

from __future__ import annotations

from pathlib import Path

from shumozizi.core.io import atomic_json, load_json
from shumozizi.core.schema import require_valid
from shumozizi.paper.editorial import record_paper_cold_reader_actions
from shumozizi.paper.external_author import decide_author_request
from shumozizi.paper.visual_requirements import (
    build_visual_requirements_from_paper,
    derive_visual_requirements_from_paper,
    validate_paper_visual_requirement_closure,
)
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.visual_opportunities import (
    build_visual_opportunity_pool,
    record_visual_critic,
)


def _visual_run(
    tmp_path: Path,
    *,
    quality_policy: str = "legacy",
    question_count: int = 1,
) -> Path:
    """构造具有五个独立视觉论证义务的最小运行。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "paper-visual-loop",
        required_questions=[f"Q{index}" for index in range(1, question_count + 1)],
        workflow_version="3.2",
        quality_policy=quality_policy,
    )
    atomic_json(
        run_dir / "analysis/MODELING_UNITS.json",
        {
            "schema_name": "modeling_units",
            "schema_version": "1.4",
            "run_id": run_dir.name,
            "units": [
                {
                    "unit_id": "u1",
                    "question_id": "Q1",
                    "unit_kind": "evaluation",
                    "core_question": False,
                    "visual_outputs": [
                        {
                            "argument_unit_id": f"argument-{index}",
                            "visual_question": f"论证关系 {index} 如何成立？",
                            "takeaway": f"关系 {index} 支撑不同的正文论证。",
                            "visual_archetype": "active-constraint plot",
                        }
                        for index in range(1, 6)
                    ],
                }
            ],
        },
    )
    atomic_json(
        run_dir / "paper/answer-map.json",
        {
            "answers": {
                "Q1": {
                    "primary_result_id": "result-q1",
                    "result_ids": ["result-q1"],
                    "objective_answer": {"result_id": "result-q1", "answer": "正式答案。"},
                }
            }
        },
    )
    return run_dir


def test_argument_driven_requirements_have_no_three_figure_cap(tmp_path: Path) -> None:
    """五个独立论证需求必须全部保留，不能隐式截断为三项。"""
    run_dir = _visual_run(tmp_path)

    payload = build_visual_requirements_from_paper(run_dir)

    assert payload["generation_policy"] == "argument_driven_no_figure_count_target"
    assert payload["summary"] == {"total": 5, "covered": 0, "open": 5}
    assert len(load_json(run_dir / "figures/visual-opportunities.json")["opportunities"]) == 5
    assert all(
        item["figure_tier"] == "supporting_figure"
        for item in payload["requirements"]
    )


def test_competition_quality_visual_requirements_expose_adaptive_figure_quota(
    tmp_path: Path,
) -> None:
    """少题质量合同把图总量降为论证角色目标，而非只在最终失败时提示。"""
    run_dir = _visual_run(tmp_path, quality_policy="competition-quality-v1")

    payload = build_visual_requirements_from_paper(run_dir)

    assert payload["schema_version"] == "1.4"
    assert payload["generation_policy"] == "argument_driven_with_adaptive_figure_quota"
    quota = payload["advanced_figure_quota"]
    assert quota["per_required_question"] == {"minimum": 2, "maximum": 3}
    assert quota["overall_enforcement"] == "coverage_driven_editorial_target"
    assert quota["minimum_formal_current_figures"] is None
    assert quota["minimum_visual_archetypes"] is None
    assert "正式发布入口" in quota["count_scope"]
    assert "论证角色" in payload["figure_tiers"]["supporting_figure"]


def test_four_question_visual_contract_keeps_global_quality_minima(tmp_path: Path) -> None:
    """四问及以上仍把全篇图量和图型多样性作为候选稿硬规格。"""
    run_dir = _visual_run(
        tmp_path,
        quality_policy="competition-quality-v1",
        question_count=4,
    )

    payload = build_visual_requirements_from_paper(run_dir)
    quota = payload["advanced_figure_quota"]

    assert quota["overall_enforcement"] == "hard_minimum"
    assert quota["minimum_formal_current_figures"] == 13
    assert quota["maximum_formal_current_figures"] == 18
    assert quota["minimum_visual_archetypes"] == 3


def test_legacy_v13_figure_quota_remains_schema_compatible(tmp_path: Path) -> None:
    """新增自适应条件不能让缺少新字段的 v1.3 合同互相矛盾。"""
    run_dir = _visual_run(
        tmp_path,
        quality_policy="competition-quality-v1",
        question_count=4,
    )
    legacy = derive_visual_requirements_from_paper(run_dir)
    legacy["schema_version"] = "1.3"
    legacy["generation_policy"] = "argument_driven_with_advanced_figure_quota"
    quota = legacy["advanced_figure_quota"]
    assert isinstance(quota, dict)
    quota.pop("required_question_count")
    quota.pop("overall_enforcement")
    quota.pop("editorial_target")

    require_valid(legacy, "paper_visual_requirements")


def test_current_figure_covers_matching_argument_requirement(tmp_path: Path) -> None:
    """绑定同一论证单元的 current 图应关闭对应需求，而不是继续重复补图。"""
    run_dir = _visual_run(tmp_path)
    initial = derive_visual_requirements_from_paper(run_dir)
    requirement = initial["requirements"][0]
    figure_path = run_dir / "figures/current/current-argument-1.png"
    figure_path.parent.mkdir(parents=True, exist_ok=True)
    figure_path.write_bytes(b"figure")
    (run_dir / "paper/longform-source.tex").write_text(
        r"\includegraphics{figures/current/current-argument-1.png}",
        encoding="utf-8",
    )
    index = load_json(run_dir / "figures/index.json")
    index["figures"].append(
        {
            "figure_id": "current-argument-1",
            "question_id": "Q1",
            "role": "model_understanding",
            "covered_requirement_ids": [requirement["requirement_id"]],
            "covered_requirement_digests": [requirement["requirement_digest"]],
            "focal_claim": requirement["claim"],
            "outputs": [{"path": "figures/current/current-argument-1.png"}],
            "placement": "body",
            "status": "current",
            "paper_allowed": True,
        }
    )
    atomic_json(run_dir / "figures/index.json", index)

    payload = derive_visual_requirements_from_paper(run_dir)

    covered = [item for item in payload["requirements"] if item["status"] == "covered"]
    assert [item["requirement_id"] for item in covered] == [requirement["requirement_id"]]
    assert covered[0]["covered_by_figure_ids"] == ["current-argument-1"]
    assert payload["summary"] == {"total": 5, "covered": 1, "open": 4}


def test_longform_only_figure_cannot_close_publication_requirement(tmp_path: Path) -> None:
    """作者长稿插图不能替正式入口关闭候选稿的视觉义务。"""
    run_dir = _visual_run(tmp_path)
    (run_dir / "paper/main.tex").write_text(
        "\\section{问题 Q1}\n正式候选稿没有插图。\n", encoding="utf-8"
    )
    requirement = derive_visual_requirements_from_paper(
        run_dir, source_role="publication"
    )["requirements"][0]
    figure_path = run_dir / "figures/current/longform-only.png"
    figure_path.parent.mkdir(parents=True, exist_ok=True)
    figure_path.write_bytes(b"figure")
    (run_dir / "paper/longform-source.tex").write_text(
        "\\includegraphics{figures/current/longform-only.png}\n", encoding="utf-8"
    )
    index = load_json(run_dir / "figures/index.json")
    index["figures"].append(
        {
            "figure_id": "longform-only",
            "question_id": "Q1",
            "role": "model_understanding",
            "covered_requirement_ids": [requirement["requirement_id"]],
            "covered_requirement_digests": [requirement["requirement_digest"]],
            "focal_claim": requirement["claim"],
            "outputs": [{"path": "figures/current/longform-only.png"}],
            "placement": "body",
            "status": "current",
            "paper_allowed": True,
        }
    )
    atomic_json(run_dir / "figures/index.json", index)

    payload = build_visual_requirements_from_paper(run_dir, source_role="publication")

    assert payload["requirements"][0]["status"] == "open"
    assert any(
        requirement["requirement_id"] in error
        for error in validate_paper_visual_requirement_closure(run_dir)
    )


def test_drop_requires_current_publication_evidence_anchor(tmp_path: Path) -> None:
    """散文 DROP 不能关闭候选稿；当前正式稿中的替代推导可以。"""
    run_dir = _visual_run(tmp_path)
    (run_dir / "paper/main.tex").write_text(
        "\\section{问题 Q1}\n"
        "\\begin{equation}\n"
        "p=1-q\n"
        "\\end{equation}\n"
        "该推导直接给出正式答案的单调边界。\n",
        encoding="utf-8",
    )
    first = build_visual_requirements_from_paper(run_dir, source_role="publication")
    requirement = first["requirements"][0]
    generic_review = {
        "observed": "作者认为文字已经足够。",
        "mechanism": "没有给出可定位的替代证据。",
        "boundary": "该判断不绑定正式入口。",
        "action": "DROP",
    }
    record_visual_critic(
        run_dir,
        requirement["requirement_id"],
        verdict="DROP",
        reviewer_context_id="fresh-generic-drop",
        review=generic_review,
    )
    assert any(
        requirement["requirement_id"] in error and "DROP 无效" in error
        for error in validate_paper_visual_requirement_closure(run_dir)
    )

    record_visual_critic(
        run_dir,
        requirement["requirement_id"],
        verdict="DROP",
        reviewer_context_id="fresh-anchored-drop",
        review={
            **generic_review,
            "evidence_anchor": {
                "kind": "derivation",
                "source_path": "paper/main.tex",
                "source_span": "paper/main.tex:2-5",
                "statement": "该推导直接给出正式答案的单调边界。",
            },
        },
    )
    assert not any(
        requirement["requirement_id"] in error
        for error in validate_paper_visual_requirement_closure(run_dir)
    )


def test_longform_mechanism_paragraph_creates_argument_and_requirement(tmp_path: Path) -> None:
    """正文中新出现的机制论点必须反向生成视觉需求。"""
    run_dir = _visual_run(tmp_path)
    (run_dir / "paper/longform-source.tex").write_text(
        "\\section{问题一}\n\n"
        "方案 A 与方案 B 的总目标接近，但方案 A 的优势主要来自第 17--19 日"
        "资源约束激活，其他日期方案 B 并不差。\n",
        encoding="utf-8",
    )

    payload = build_visual_requirements_from_paper(run_dir)
    arguments = load_json(run_dir / "paper/generated/PAPER_ARGUMENT_UNITS.json")

    mechanism = next(item for item in arguments["arguments"] if item["role"] == "mechanism")
    requirement = next(
        item
        for item in payload["requirements"]
        if mechanism["argument_id"] in item["argument_unit_ids"]
    )
    assert "17--19" in mechanism["claim"]
    assert requirement["purpose"] == "mechanism"
    assert requirement["source_span"].startswith("paper/longform-source.tex:")
    assert requirement["requirement_id"].endswith(requirement["requirement_digest"][:10])


def test_one_generic_figure_cannot_close_distinct_claims(tmp_path: Path) -> None:
    """同问 insight 图只能关闭显式绑定的一个 claim。"""
    run_dir = _visual_run(tmp_path)
    initial = derive_visual_requirements_from_paper(run_dir)
    first = initial["requirements"][0]
    path = run_dir / "figures/current/q1-generic.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"figure")
    (run_dir / "paper/longform-source.tex").write_text(
        r"\includegraphics{figures/current/q1-generic.png}", encoding="utf-8"
    )
    index = load_json(run_dir / "figures/index.json")
    index["figures"].append(
        {
            "figure_id": "q1-generic",
            "question_id": "Q1",
            "role": "insight",
            "status": "current",
            "paper_allowed": True,
            "placement": "body",
            "outputs": [{"path": "figures/current/q1-generic.png"}],
            "covered_requirement_ids": [first["requirement_id"]],
            "covered_requirement_digests": [first["requirement_digest"]],
            "focal_claim": first["claim"],
        }
    )
    atomic_json(run_dir / "figures/index.json", index)

    payload = derive_visual_requirements_from_paper(run_dir)

    assert payload["summary"] == {"total": 5, "covered": 1, "open": 4}


def test_appendix_stability_and_unconsumed_figures_do_not_cover_body_requirement(
    tmp_path: Path,
) -> None:
    """附录稳定性图及未被正文引用的图都不能关闭正文需求。"""
    run_dir = _visual_run(tmp_path)
    requirement = derive_visual_requirements_from_paper(run_dir)["requirements"][0]
    index = load_json(run_dir / "figures/index.json")
    common = {
        "question_id": "Q1",
        "status": "current",
        "paper_allowed": True,
        "covered_requirement_ids": [requirement["requirement_id"]],
        "covered_requirement_digests": [requirement["requirement_digest"]],
        "focal_claim": requirement["claim"],
    }
    index["figures"].extend(
        [
            {
                **common,
                "figure_id": "appendix-stability",
                "role": "stability",
                "placement": "appendix",
            },
            {
                **common,
                "figure_id": "not-in-paper",
                "role": "insight",
                "placement": "body",
            },
        ]
    )
    atomic_json(run_dir / "figures/index.json", index)
    (run_dir / "paper/longform-source.tex").write_text(
        "正文不引用上述两张图。", encoding="utf-8"
    )

    payload = derive_visual_requirements_from_paper(run_dir)

    assert payload["summary"]["covered"] == 0


def test_refresh_preserves_existing_visual_review_state(tmp_path: Path) -> None:
    """论文需求刷新不能抹掉已经完成的视觉批评或选择。"""
    run_dir = _visual_run(tmp_path)
    build_visual_requirements_from_paper(run_dir)
    path = run_dir / "figures/visual-opportunities.json"
    pool = load_json(path)
    pool["opportunities"][0].update(
        {
            "status": "drop",
            "critic_verdict": "DROP",
            "critic_path": "figures/reviews/kept.md",
        }
    )
    atomic_json(path, pool)

    build_visual_requirements_from_paper(run_dir)
    refreshed = load_json(path)

    assert len(refreshed["opportunities"]) == 5
    assert refreshed["opportunities"][0]["status"] == "drop"
    assert refreshed["opportunities"][0]["critic_verdict"] == "DROP"


def test_changed_paper_claim_invalidates_old_drop_review(tmp_path: Path) -> None:
    """正文 claim 改变后，旧 requirement digest 的 DROP 不能继续闭合新需求。"""
    run_dir = _visual_run(tmp_path)
    source = run_dir / "paper/longform-source.tex"
    source.write_text(
        "\\section{问题一}\n\n方案 A 的优势主要来自第 17--19 日资源约束激活。\n",
        encoding="utf-8",
    )
    first = build_visual_requirements_from_paper(run_dir)
    requirement = next(item for item in first["requirements"] if item["purpose"] == "mechanism")
    record_visual_critic(
        run_dir,
        requirement["requirement_id"],
        verdict="DROP",
        reviewer_context_id="fresh-critic",
        review={
            "observed": "该机制在正文中已经由一个简单表格直接显示。",
            "mechanism": "旧 claim 不需要额外视觉编码即可理解。",
            "boundary": "此判断仅绑定当前正文中的旧机制主张。",
            "action": "DROP",
        },
    )
    assert requirement["requirement_id"] not in {
        error.split("：", 1)[-1].split()[0]
        for error in validate_paper_visual_requirement_closure(run_dir)
    }

    source.write_text(
        "\\section{问题一}\n\n方案 A 的优势主要来自第 21--23 日安全阈值约束激活。\n",
        encoding="utf-8",
    )
    changed = build_visual_requirements_from_paper(run_dir)
    replacement = next(item for item in changed["requirements"] if item["purpose"] == "mechanism")
    pool = load_json(run_dir / "figures/visual-opportunities.json")

    assert replacement["requirement_digest"] != requirement["requirement_digest"]
    assert replacement["requirement_id"] != requirement["requirement_id"]
    opportunity = next(
        item for item in pool["opportunities"] if item["requirement_id"] == replacement["requirement_id"]
    )
    assert opportunity["status"] == "candidate"
    # 长稿仍是 Author Pass 产物；没有正式入口时，候选稿闭环不能借它来判断。
    assert any("缺少正式论文入口" in error for error in validate_paper_visual_requirement_closure(run_dir))


def test_open_paper_requirement_blocks_candidate_closure(tmp_path: Path) -> None:
    """已启用新闭环后，未评阅的论文视觉需求不能被旧 Figure Plan 绕过。"""
    run_dir = _visual_run(tmp_path)
    build_visual_requirements_from_paper(run_dir)

    errors = validate_paper_visual_requirement_closure(run_dir)

    assert errors == [
        "VISUAL_REQUIREMENT_OPEN：视觉需求或机会池无法复验："
        "缺少正式论文入口 paper/main.tex、paper/main.typ 或已接受的外部稿"
    ]


def test_cold_reader_add_figure_routes_to_living_opportunity_pool(tmp_path: Path) -> None:
    """普通 ADD_FIGURE 与伴随图一样必须进入视觉生产入口。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "cold-reader-figure",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    build_visual_opportunity_pool(run_dir, opportunities=[])
    pdf = run_dir / "paper/longform-draft.pdf"
    pdf.write_bytes(b"paper")

    record_paper_cold_reader_actions(
        run_dir,
        reviewer_context_id="fresh-cold-reader",
        actions=[
            {
                "action_id": "add-q1-mechanism",
                "action": "ADD_FIGURE",
                "target_id": "Q1-mechanism",
                "reason": "核心机制仅靠文字无法快速理解。",
                "expected_benefit": "直接显示活跃约束如何决定答案。",
                "figure": {
                    "question_id": "Q1",
                    "visual_question": "哪个活跃约束决定正式答案？",
                    "atomic_claim": "活跃约束而非平均水平决定最优值。",
                    "candidate_archetypes": ["active-constraint plot"],
                },
            }
        ],
    )
    pool = load_json(run_dir / "figures/visual-opportunities.json")

    assert pool["opportunities"][0]["opportunity_id"] == "add-q1-mechanism"
    assert pool["opportunities"][0]["origin"] == "paper_cold_reader"


def test_fulfilled_author_visual_request_routes_to_opportunity_pool(tmp_path: Path) -> None:
    """Author 的视觉缺口被接受后必须形成可执行视觉机会。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "author-visual-request",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    atomic_json(
        run_dir / "paper/AUTHOR_REQUESTS.json",
        {
            "schema_name": "author_request",
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "requests": [
                {
                    "gap_id": "gap-q1-boundary",
                    "kind": "visual",
                    "affected_argument": "阈值变化决定方案切换。",
                    "request": "需要展示阈值两侧的决策变化。",
                    "why_needed": "文字难以表达切换边界。",
                    "can_continue_without_it": True,
                    "fallback": "使用正文解释边界。",
                    "recommended_route": "visual",
                    "expected_benefit": "让边界条件可见。",
                    "estimated_cost": "low",
                }
            ],
        },
    )

    decide_author_request(
        run_dir,
        [
            {
                "gap_id": "gap-q1-boundary",
                "decision": "fulfill",
                "route": "visual",
                "reason": "该图能直接补齐核心边界论证。",
            }
        ],
    )
    pool = load_json(run_dir / "figures/visual-opportunities.json")

    assert pool["opportunities"][0]["opportunity_id"] == "author-gap-q1-boundary"
    assert pool["opportunities"][0]["origin"] == "author_request"
