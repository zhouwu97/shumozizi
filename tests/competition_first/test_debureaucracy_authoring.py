"""v3.4 创作减负：事实保持严格，表达探索不再前置重合同。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfWriter

from evaluation.debureaucracy_replay import replay_authoring
from evaluation.pairwise_paper_review import build_blinded_pair
from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.core.schema import require_valid
from shumozizi.knowledge.inspiration import build_inspiration_context
from shumozizi.paper.author_pass import prepare_longform_author
from shumozizi.paper.compiler import compile_longform_draft
from shumozizi.paper.narrative_competition import (
    narrative_competition_freshness,
    select_narrative_candidate,
    write_narrative_candidates,
)
from shumozizi.paper.page_budget import audit_page_budget
from shumozizi.paper.readiness import (
    check_paper_readiness,
    validate_candidate_visual_assessment,
)
from shumozizi.paper.templates import (
    materialize_selected_template,
    require_materialized_template,
    select_paper_template,
)
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.review_focus import record_scientific_challenge_evidence
from shumozizi.simple.visual_sandbox import (
    graduate_visual_candidate,
    read_visual_ideas,
    record_visual_competition,
    write_visual_ideas,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _stable_latex_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    """固定模板选择能力，避免单元测试依赖开发机的 TeX 安装。"""
    monkeypatch.setattr(
        "shumozizi.paper.templates._available_paper_engines",
        lambda: (True, False),
    )


def _author_ready_run(tmp_path: Path, name: str = "author-pass") -> Path:
    """构造有唯一正式答案、LaTeX 模板和 current production 结果的运行。"""
    run_dir = initialize_simple_run(
        tmp_path,
        name,
        required_questions=["Q1"],
        workflow_version="3.2",
        competition="cumcm",
    )
    index = load_json(run_dir / "results/index.json")
    index["results"].append(
        {
            "result_id": "r-q1",
            "question_id": "Q1",
            "kind": "test",
            "source_script": None,
            "command": "test",
            "input_files": [],
            "input_hashes": {},
            "output_files": [],
            "output_hashes": {},
            "metric_sources": {},
            "method_facts": {},
            "status": "current",
            "execution_mode": "production",
            "execution_valid": True,
            "exit_code": 0,
            "stdout_path": "results/test.stdout.log",
            "stderr_path": "results/test.stderr.log",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:01Z",
            "duration_seconds": 1.0,
            "error": None,
            "created_at": "2026-01-01T00:00:01Z",
            "objective_semantics_sha256": "0" * 64,
            "dependency_scope": "question",
            "affected_question_ids": ["Q1"],
            "metrics": {"objective": 12.0, "feasible": True},
        }
    )
    atomic_json(run_dir / "results/index.json", index)
    atomic_json(
        run_dir / "paper/answer-map.json",
        {
            "answers": {
                "Q1": {
                    "primary_result_id": "r-q1",
                    "result_ids": ["r-q1"],
                    "direct_answer_location": "问题一结尾",
                    "objective_answer": {"result_id": "r-q1", "answer": "Q1 的正式目标值为 12。"},
                }
            }
        },
    )
    select_paper_template(
        run_dir,
        language="zh",
        engine="latex",
        selection_reason="减负 Author Pass 回归测试使用无回退 LaTeX 模板。",
    )
    materialize_selected_template(run_dir)
    record_scientific_challenge_evidence(
        run_dir,
        result_ids=["r-q1"],
        attack_description="独立复核 Q1 正式结果与可行性边界。",
        findings=[],
    )
    return run_dir


def _blank_pdf(path: Path, page_count: int) -> None:
    """生成指定页数的有效 PDF，供页数政策回归。"""
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=595, height=842)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        writer.write(stream)


def _reviewed_nonrequired_figure_plan(
    run_dir: Path, *, questions: list[str], figure_count: int
) -> None:
    """写入已完成 waived 决策的轻量图表计划，供数量反例复用。"""
    figures = [
        {
            "figure_id": f"reviewed-{index}",
            "preferred": "skills/mathmodel-figure-templates",
            "fallback": "skills/3coding-visual",
            "selected_skill": "skills/mathmodel-figure-templates",
            "template_id": "feasible-region-active-constraints",
            "selection_reason": "夹具只验证视觉评估和图数量不是同一件事。",
            "question_id": questions[(index - 1) % len(questions)],
            "role": "insight",
            "claim": "该图作为已评估的辅助视觉材料，不承担新的强制证明义务。",
            "source_result_ids": ["r-q1"],
            "script": f"code/figures/reviewed-{index}.py",
            "output": f"figures/current/reviewed-{index}.pdf",
            "paper_section": "paper/sections/questions.tex",
            "caption": f"已评估图 {index}",
            "latex_label": f"fig:reviewed-{index}",
            "explanation_anchor": "辅助视觉材料",
            "required": False,
        }
        for index in range(1, figure_count + 1)
    ]
    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "schema_name": "figure_plan",
            "schema_version": "2.1",
            "run_id": run_dir.name,
            "visual_decisions": [
                {
                    "question_id": question_id,
                    "status": "waived",
                    "reason": "评阅确认现有推导和结果已完整表达该问题，不需要额外必需图。",
                }
                for question_id in questions
            ],
            "figures": figures,
        },
    )


def test_author_pass_exposes_two_default_inputs_and_separate_source(tmp_path: Path) -> None:
    """Author 默认只读两份材料，longform 源文件必须由 Author 另行产出。"""
    run_dir = _author_ready_run(tmp_path)
    manifest = prepare_longform_author(run_dir)

    assert manifest["research_package"]["path"] == "paper/author-pass/RESEARCH_PACKAGE.md"
    assert manifest["author_brief"]["path"] == "paper/author-pass/AUTHOR_BRIEF.md"
    assert not (run_dir / "paper/longform-source.tex").exists()
    assert (run_dir / "paper/AUTHOR_GAPS.md").is_file()
    brief = (run_dir / "paper/author-pass/AUTHOR_BRIEF.md").read_text(encoding="utf-8")
    assert "国奖级完整竞赛论文" in brief
    assert "应提出返工请求" in brief


def test_author_can_start_without_figure_plan(tmp_path: Path) -> None:
    """视觉候选门只能约束最终 Candidate，不能重新阻断 Author 开稿。"""
    run_dir = _author_ready_run(tmp_path, "author-without-figure-plan")

    assert not (run_dir / "figures/FIGURE_PLAN.json").exists()
    manifest = prepare_longform_author(run_dir)

    assert manifest["research_package"]["path"] == "paper/author-pass/RESEARCH_PACKAGE.md"


def test_missing_figure_plan_does_not_bypass_candidate_gate(tmp_path: Path) -> None:
    """没有 Figure Plan 或替代评估时，Candidate 必须给出明确阻断原因。"""
    run_dir = _author_ready_run(tmp_path, "candidate-without-visual-assessment")

    errors = validate_candidate_visual_assessment(run_dir)

    assert any(error.startswith("VISUAL_NOT_ASSESSED") for error in errors)


def test_legacy_runs_do_not_inherit_competition_quality_figure_quota(tmp_path: Path) -> None:
    """非 competition-quality-v1 的历史/普通运行不继承新质量合同的全篇硬配额。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "legacy-figure-plan",
        required_questions=["Q1", "Q2", "Q3"],
        workflow_version="3.2",
    )
    atomic_json(
        run_dir / "analysis/MODELING_UNITS.json",
        {
            "schema_version": "1.4",
            "units": [
                {"question_id": "Q1", "core_question": True},
                {"question_id": "Q2", "core_question": True},
                {"question_id": "Q3", "core_question": True},
            ],
        },
    )
    _reviewed_nonrequired_figure_plan(
        run_dir, questions=["Q1", "Q2", "Q3"], figure_count=4
    )

    assert validate_candidate_visual_assessment(run_dir) == []


def test_pending_visual_blocks_candidate_until_current(tmp_path: Path) -> None:
    """已选中新图但尚未 promotion 时，Candidate 不能继续消费旧 current。"""
    run_dir = _author_ready_run(tmp_path, "candidate-with-pending-visual")
    _reviewed_nonrequired_figure_plan(run_dir, questions=["Q1"], figure_count=8)
    write_visual_ideas(
        run_dir,
        [
            {
                "id": "q1-boundary",
                "question": "哪个边界决定 Q1 的最终答案？",
                "sources": ["Q1"],
                "idea": "用边界与最优点的关系解释结果。",
            }
        ],
    )
    sandbox = run_dir / "figures/sandbox/q1-boundary"
    sandbox.mkdir(parents=True)
    (sandbox / "winner.png").write_bytes(b"winner")
    record_visual_competition(
        run_dir,
        "q1-boundary",
        selected_candidate="figures/sandbox/q1-boundary/winner.png",
        reviewer_context_id="fresh-boundary-reviewer",
        fastest_mechanism="候选图直接显示活动边界和最终决策点。",
        full_width_value="边界与决策点需要并列显示才能承担正文解释任务。",
        table_redundancy="数值表无法直观看到活动边界的几何关系。",
        rationale="胜出设计能同时表达正式答案、约束机制和适用边界。",
    )
    graduate_visual_candidate(run_dir, "q1-boundary", candidate_version="v2")

    status = check_paper_readiness(run_dir)

    assert any(
        "PENDING_VISUAL_PROMOTION" in error and "q1-boundary" in error and "v2" in error
        for error in status["errors"]
    ), status["errors"]


def test_longform_rejects_formal_entrypoint_disguised_as_author_pass(tmp_path: Path) -> None:
    """把正式入口原样复制为 longform-source 不算真实 Author Pass。"""
    run_dir = _author_ready_run(tmp_path, "same-source")
    prepare_longform_author(run_dir)
    template = require_materialized_template(run_dir)
    main = run_dir / "paper" / template["question_layout"]["entrypoint_path"]
    (run_dir / "paper/longform-source.tex").write_text(
        main.read_text(encoding="utf-8"), encoding="utf-8"
    )

    with pytest.raises(ContractError, match="完全相同"):
        compile_longform_draft(run_dir)


def test_longform_receipt_binds_independent_author_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """长篇首稿回执绑定独立 Author 源文件和两份 Author Pass 输入。"""
    run_dir = _author_ready_run(tmp_path, "receipt")
    manifest = prepare_longform_author(run_dir)
    source = run_dir / "paper/longform-source.tex"
    source.write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "由共享约束推导正式答案，并解释其适用边界。\n\\end{document}\n",
        encoding="utf-8",
    )

    import shumozizi.paper.compiler as compiler

    monkeypatch.setattr(
        compiler,
        "_draft_steps",
        lambda engine, entrypoint, output_name: ("fake", [["fake"]]),
    )

    def fake_compile(paper_dir: Path, steps: object, *, timeout_seconds: int) -> list[dict]:
        _blank_pdf(paper_dir / "longform-draft.pdf", 2)
        return [{"command": ["fake"], "returncode": 0}]

    monkeypatch.setattr(compiler, "_run_compiler_steps", fake_compile)
    receipt = compile_longform_draft(run_dir)

    assert receipt["author_source_path"] == "paper/longform-source.tex"
    assert receipt["research_package_sha256"] == manifest["research_package"]["sha256"]
    assert receipt["author_brief_sha256"] == manifest["author_brief"]["sha256"]


def test_author_pass_and_compile_block_open_scientific_p1(tmp_path: Path) -> None:
    """未关闭 scientific P0/P1 时，准备和编译两处都必须阻断。"""
    run_dir = _author_ready_run(tmp_path, "open-science")
    prepare_longform_author(run_dir)
    challenge_path = run_dir / "review/scientific-challenge-evidence.json"
    challenge = load_json(challenge_path)
    challenge["findings"] = [
        {
            "finding_id": "SCI-OPEN-P1",
            "question_id": "Q1",
            "severity": "P1",
            "finding": "正式答案的边界仍需科学修复。",
            "action_type": "WRITING_FIX",
            "rollback_target": "paper",
            "invalidates": ["Q1 正式结论表述"],
            "required_action": "关闭该科学边界后重新准备 Author Pass。",
            "status": "open",
            "closure_evidence_result_ids": [],
        }
    ]
    atomic_json(challenge_path, challenge)

    with pytest.raises(ContractError, match="SCI-OPEN-P1"):
        prepare_longform_author(run_dir)

    (run_dir / "paper/longform-source.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n正文\n\\end{document}\n",
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="SCI-OPEN-P1"):
        compile_longform_draft(run_dir)


def test_visual_sandbox_winner_marks_pending_promotion(tmp_path: Path) -> None:
    """Sandbox 胜出设计应显式等待正式渲染和 promotion，而非伪装成 current。"""
    run_dir = initialize_simple_run(tmp_path, "visual", required_questions=["Q1"])
    ideas = write_visual_ideas(
        run_dir,
        [
            {
                "id": "q1-bottleneck",
                "question": "哪个约束决定答案？",
                "sources": ["Q1"],
                "idea": "对比活跃边界与松弛区间。",
                "status": "sketch",
            }
        ],
    )
    sandbox = run_dir / "figures/sandbox/q1-bottleneck"
    sandbox.mkdir(parents=True)
    (sandbox / "a.png").write_bytes(b"candidate-a")
    (sandbox / "b.png").write_bytes(b"candidate-b")

    review = record_visual_competition(
        run_dir,
        "q1-bottleneck",
        selected_candidate="figures/sandbox/q1-bottleneck/b.png",
        reviewer_context_id="fresh-visual-reader",
        fastest_mechanism="B 最快显示活跃约束。",
        full_width_value="B 值得正文整栏。",
        table_redundancy="A 更接近表格复述。",
        rationale="B 把答案、机制和边界放在同一视觉路径中。",
    )
    promoted = graduate_visual_candidate(run_dir, "q1-bottleneck")

    assert ideas["ideas"][0].keys() == {
        "id", "question", "sources", "idea", "figure_tier", "status"
    }
    assert len(review["candidates"]) == 2
    assert promoted["formal_render_required"] is True
    assert promoted["selected_design_reference"].endswith("b.png")
    assert promoted["status"] == "selected_pending_promotion"
    recorded = read_visual_ideas(run_dir)["ideas"][0]
    assert recorded["status"] == "selected_pending_promotion"
    assert recorded["pending_promotion"]["figure_id"] == "q1-bottleneck"
    assert recorded["pending_promotion"]["candidate_version"] == "v1"
    assert not (run_dir / "figures/work/q1-bottleneck/v1").exists()
    assert not (run_dir / "figures/FIGURE_PLAN.json").exists()


def test_hero_visual_competition_requires_distinct_structures(tmp_path: Path) -> None:
    """主图不得以单候选或同构换色冒充视觉竞争。"""
    run_dir = initialize_simple_run(tmp_path, "hero-competition", required_questions=["Q1"])
    write_visual_ideas(
        run_dir,
        [
            {
                "id": "q1-hero",
                "question": "哪个结构最快解释核心结论？",
                "sources": ["Q1"],
                "idea": "比较可行域与时间机制两种主图结构。",
                "figure_tier": "hero_figure",
            }
        ],
    )
    sandbox = run_dir / "figures/sandbox/q1-hero"
    sandbox.mkdir(parents=True)
    (sandbox / "a.png").write_bytes(b"candidate-a")
    with pytest.raises(ContractError, match="至少需要两个候选"):
        record_visual_competition(
            run_dir,
            "q1-hero",
            selected_candidate="figures/sandbox/q1-hero/a.png",
            reviewer_context_id="fresh-visual-reader",
            fastest_mechanism="A 最快显示核心结论。",
            full_width_value="主图需要完整宽度。",
            table_redundancy="表格无法显示机制。",
            rationale="候选需要比较。",
        )

    (sandbox / "b.png").write_bytes(b"candidate-b")
    paths = {
        "figures/sandbox/q1-hero/a.png": "feasible_region",
        "figures/sandbox/q1-hero/b.png": "constraint_timeline",
    }
    review = record_visual_competition(
        run_dir,
        "q1-hero",
        selected_candidate="figures/sandbox/q1-hero/b.png",
        reviewer_context_id="fresh-visual-reader",
        fastest_mechanism="B 最快显示约束激活时段。",
        full_width_value="时间机制需要完整宽度。",
        table_redundancy="表格无法显示激活顺序。",
        rationale="两种数学结构完成了真实竞争。",
        candidate_structures=paths,
        model_object_visibility="可行域与时间机制的对象均可见。",
        domain_specificity="换题后约束时序含义完全改变。",
        mechanism_or_path_visibility="激活时段与边界变化路径可见。",
        constraint_or_boundary_visibility="约束边界直接标出。",
        uncertainty_visibility="区间在候选 B 中以带显示。",
        paper_size_legibility="正文整栏下最小字可读。",
        information_density="两面板各承担一个对象。",
        reading_order="A 到 B 按对象到结论顺序阅读。",
        known_risks="三维面板可能遮挡关键路径。",
    )

    assert review["figure_tier"] == "hero_figure"
    assert {item["visual_structure"] for item in review["candidates"]} == {
        "feasible_region", "constraint_timeline"
    }


def test_narrative_competition_is_advisory_and_research_package_bound(tmp_path: Path) -> None:
    """叙事候选允许竞争，但科学材料变化后旧选择自动失效。"""
    run_dir = _author_ready_run(tmp_path, "narrative")
    prepare_longform_author(run_dir)
    write_narrative_candidates(
        run_dir,
        [
            {
                "candidate_id": "question-chain",
                "title": "问题递进型",
                "central_thread": "共享约束逐问收紧。",
                "section_flow": ["数据直觉", "统一模型", "逐问扩展"],
                "memorable_takeaway": "答案由同一活跃约束链解释。",
                "risks": ["可能弱化方法结构"],
            },
            {
                "candidate_id": "mechanism",
                "title": "机制型",
                "central_thread": "从瓶颈现象追到活跃约束。",
                "section_flow": ["瓶颈", "判据", "构造"],
                "memorable_takeaway": "看见瓶颈就能理解答案。",
                "risks": ["需要更强主图"],
            },
        ],
    )
    selected = select_narrative_candidate(
        run_dir,
        "mechanism",
        reviewer_context_id="fresh-narrative-reader",
        selection_reason="机制主线更容易被记住。",
        revision_advice="保留逐问直接答案索引。",
    )
    assert selected["selected_candidate_id"] == "mechanism"
    brief = (run_dir / "paper/author-pass/AUTHOR_BRIEF.md").read_text(encoding="utf-8")
    assert "本轮选中的叙事方向" in brief
    assert "机制型" not in brief  # brief consumes the selected thread, not a fixed title
    assert "从瓶颈现象追到活跃约束" in brief
    assert narrative_competition_freshness(run_dir) == {
        "current": True,
        "status": "reviewed",
        "advisory_only": True,
    }

    package = run_dir / "paper/author-pass/RESEARCH_PACKAGE.md"
    package.write_text(package.read_text(encoding="utf-8") + "\n事实更新\n", encoding="utf-8")
    assert narrative_competition_freshness(run_dir)["current"] is False


def test_inspiration_context_has_no_current_result_binding(tmp_path: Path) -> None:
    """表达启发不绑定当前结果，schema 直接拒绝事实迁移字段。"""
    run_dir = initialize_simple_run(tmp_path, "inspiration", required_questions=["Q1"])
    context = build_inspiration_context(run_dir)
    assert context["advisory_only"] is True
    assert "result_ids" not in context
    assert "evidence_result_ids" not in context

    invalid_library = {
        "schema_name": "inspiration_library",
        "schema_version": "1.0",
        "library_id": "invalid",
        "cards": [
            {
                "card_id": "leaky-card",
                "title": "错误示例",
                "observations": [{"kind": "page_rhythm", "lesson": "先图后公式"}],
                "transfer_boundary": "expression_only_no_facts_formulas_data_or_conclusions",
                "result_ids": ["r-q1"],
            }
        ],
    }
    with pytest.raises(ContractError):
        require_valid(invalid_library, "inspiration_library")


@pytest.mark.parametrize(
    ("page_count", "expected_status"),
    [
        (17, "under_18_editorial_signal"),
        (18, "under_24_editorial_review"),
        (24, "normal_planning_range"),
        (31, "over_30_compression_review"),
    ],
)
def test_page_budget_four_ranges_are_advisory(
    tmp_path: Path, page_count: int, expected_status: str
) -> None:
    """即使旧调用传 enforce_minimum，四档页数也只返回编辑信号。"""
    run_dir = initialize_simple_run(
        tmp_path,
        f"pages-{page_count}",
        required_questions=["Q1"],
    )
    pdf = run_dir / f"paper/pages-{page_count}.pdf"
    _blank_pdf(pdf, page_count)
    report = audit_page_budget(run_dir, pdf, enforce_minimum=True)
    assert report["status"] == expected_status
    assert report["page_count"] == page_count


def test_historical_replay_keeps_facts_and_competes_on_expression() -> None:
    """真实旧 run 回放必须保持事实摘要，并把 Author 输入减少至少一半。"""
    source = REPO_ROOT / "runs/liaoning-b-2026-20260801-002"
    if not source.is_dir():
        pytest.skip("仓内历史回放样本不可用")
    report = replay_authoring(source)
    assert report["baseline_pdf_pages"] == 20
    assert report["science_facts_stable"] is True
    assert report["control_file_reduction_at_least_half"] is True
    assert report["author_facing_count"] == 2
    assert report["narrative_candidate_count"] >= 2
    assert report["distinct_narrative_flows"] is True
    assert report["author_context_not_increased"] is True
    assert report["research_package_has_question_contracts"] is True
    assert report["research_package_has_formal_answer_text"] is True
    assert report["research_package_has_citations"] is True
    assert report["selected_narrative_in_author_brief"] is True


def test_pairwise_package_requires_three_blind_reviewers(tmp_path: Path) -> None:
    """A/B 包固定三名独立 reviewer 和本轮减负质量问题。"""
    baseline = tmp_path / "baseline.pdf"
    candidate = tmp_path / "candidate.pdf"
    _blank_pdf(baseline, 1)
    _blank_pdf(candidate, 1)
    manifest = build_blinded_pair(baseline, candidate, tmp_path / "blind", seed=34)

    assert manifest["required_independent_reviewers"] == 3
    assert len(manifest["pairwise_questions"]) == 6
    assert any("工作报告" in item for item in manifest["pairwise_questions"])
    assert any("模板化" in item for item in manifest["pairwise_questions"])


def test_selected_materials_preserves_all_distinct_categories_without_count_cutoff(
    tmp_path: Path,
) -> None:
    """素材池去重按语义功能进行，不得有 del items[4:] 等机械数量截断。"""
    from shumozizi.paper.author_pass import _selected_materials, prepare_longform_author

    run_dir = _author_ready_run(tmp_path, name="materials-no-cutoff")
    # 创建 7 个不同类别的素材项目，全部应该被保留
    material_items = [
        {"item_id": "m1", "question_id": "Q1", "category": "Mathematical Derivation", "title": "表面距离公式推导", "content": "公式推导内容 1", "status": "current"},
        {"item_id": "m2", "question_id": "Q1", "category": "Mathematical Derivation", "title": "连通性并查集定理", "content": "公式推导内容 2", "status": "current"},
        {"item_id": "m3", "question_id": "Q1", "category": "Mechanism", "title": "活跃约束机制", "content": "机制分析内容 A", "status": "current"},
        {"item_id": "m4", "question_id": "Q1", "category": "Mechanism", "title": "渗流相变临界点", "content": "机制分析内容 B", "status": "current"},
        {"item_id": "m5", "question_id": "Q1", "category": "Baseline/Contrast", "title": "基准模型对比", "content": "Baseline 对比内容", "status": "current"},
        {"item_id": "m6", "question_id": "Q1", "category": "Illustrative Case", "title": "反例与临界形态", "content": "反例案例内容", "status": "current"},
        {"item_id": "m7", "question_id": "Q1", "category": "Boundary/Robustness", "title": "适用边界与敏感性", "content": "边界条件内容", "status": "current"},
    ]
    atomic_json(
        run_dir / "paper/generated/material_pool.json",
        {"schema_version": "1.0", "items": material_items},
    )
    selected = _selected_materials(run_dir)
    assert len(selected["Q1"]) == 7, "所有 7 项差异化科学素材必须全部保留，不得截断"

    from shumozizi.simple.review_focus import record_scientific_challenge_evidence

    record_scientific_challenge_evidence(
        run_dir,
        result_ids=["r-q1"],
        attack_description="复核 Q1 科学事实",
        findings=[],
    )
    manifest = prepare_longform_author(run_dir, require_template=False)
    package = (run_dir / manifest["research_package"]["path"]).read_text(encoding="utf-8")
    assert "表面距离公式推导" in package
    assert "连通性并查集定理" in package
    assert "活跃约束机制" in package
    assert "渗流相变临界点" in package
    assert "基准模型对比" in package
    assert "反例与临界形态" in package
    assert "适用边界与敏感性" in package


def test_author_brief_has_natural_academic_tone_and_modeling_focus(tmp_path: Path) -> None:
    """AUTHOR_BRIEF 强调 50-60% 建模重心与连续学术段落，不再强制被动语态。"""
    from shumozizi.paper.author_pass import _render_author_brief

    state = {"run_id": "test-tone", "required_questions": ["Q1"]}
    brief = _render_author_brief(state, {"cards": []}, None)
    assert "50–60%" in brief
    assert "连续学术段落" in brief
    assert "本文建立" in brief
    assert "观察 → 机制 → 结论" in brief
    assert "全文用被动语态" not in brief
