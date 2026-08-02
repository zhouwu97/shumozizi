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
from shumozizi.paper.templates import (
    materialize_selected_template,
    require_materialized_template,
    select_paper_template,
)
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.review_focus import record_scientific_challenge_evidence
from shumozizi.simple.visual_sandbox import (
    graduate_visual_candidate,
    record_visual_competition,
    write_visual_ideas,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


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


def test_author_pass_exposes_two_default_inputs_and_separate_source(tmp_path: Path) -> None:
    """Author 默认只读两份材料，longform 源文件必须由 Author 另行产出。"""
    run_dir = _author_ready_run(tmp_path)
    manifest = prepare_longform_author(run_dir)

    assert manifest["research_package"]["path"] == "paper/author-pass/RESEARCH_PACKAGE.md"
    assert manifest["author_brief"]["path"] == "paper/author-pass/AUTHOR_BRIEF.md"
    assert not (run_dir / "paper/longform-source.tex").exists()
    assert (run_dir / "paper/AUTHOR_GAPS.md").is_file()
    brief = (run_dir / "paper/author-pass/AUTHOR_BRIEF.md").read_text(encoding="utf-8")
    assert "可以合并问题、重排章节" in brief
    assert "应提出返工请求" in brief


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


def test_visual_sandbox_competes_without_figure_contract(tmp_path: Path) -> None:
    """视觉想法可直接草绘、竞争并进入 work，不要求完整 Figure Contract。"""
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

    assert ideas["ideas"][0].keys() == {"id", "question", "sources", "idea", "status"}
    assert len(review["candidates"]) == 2
    assert promoted["formal_render_required"] is True
    assert promoted["selected_design_reference"].endswith("b.png")
    assert not (run_dir / "figures/work/q1-bottleneck/v1").exists()
    assert not (run_dir / "figures/FIGURE_PLAN.json").exists()


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
