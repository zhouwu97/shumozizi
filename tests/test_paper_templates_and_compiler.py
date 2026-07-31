"""回归模板路由、动态题目结构和受控论文编译。"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

import shumozizi.paper.compiler as paper_compiler
import shumozizi.paper.readiness as paper_readiness
import shumozizi.paper.templates as paper_templates
import shumozizi.simple.review as simple_review
from scripts.qa.check_placeholders import check_placeholders
from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.knowledge.retrieval import (
    write_analysis_knowledge_retrieval,
    write_paper_knowledge_application,
)
from shumozizi.paper.compiler import (
    compile_paper,
    compile_reviewable_draft,
    verify_paper_compile_receipt,
    verify_reviewable_draft_receipt,
)
from shumozizi.paper.templates import (
    materialize_selected_template,
    require_materialized_template,
    select_paper_template,
)
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.state import (
    paper_revision_status,
    read_simple_state,
    record_layout_audit,
    record_paper_compilation,
    record_paper_review,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = REPO_ROOT / "skills/5writing/templates"
QUESTION_COUNTS = (1, 3, 5)

# 这些模板的正文由安全的 sections include 接管，可以替换为当前运行的动态问题
# 章节。其余 Typst 模板仍保留未受控的示例正文依赖，必须明确阻断而不能静默保留。
SUPPORTED_TYPST_TEMPLATES = {
    ("zh", "apmcm"),
    ("zh", "changsanjiao"),
    ("zh", "cumcm"),
    ("zh", "diangongbei"),
    ("zh", "dongsansheng"),
    ("zh", "huaweibei"),
    ("zh", "huazhongbei"),
    ("zh", "mathorcup"),
    ("zh", "mcm"),
    ("zh", "stats"),
    ("en", "mcm"),
}
UNSUPPORTED_TYPST_TEMPLATES = {
    ("en", "apmcm"),
    ("zh", "huashubei"),
    ("zh", "shuweibei"),
    ("zh", "wuyibei"),
}


def _template_cases(engine: str) -> set[tuple[str, str]]:
    """返回仓内声明的非 default 模板键，用于防止矩阵遗漏新增模板。"""
    suffix = "" if engine == "typst" else "-latex"
    return {
        (language_dir.name, base)
        for language_dir in (TEMPLATE_ROOT / "zh", TEMPLATE_ROOT / "en")
        for directory in language_dir.iterdir()
        if directory.is_dir()
        and (not suffix or directory.name.endswith(suffix))
        and (suffix or not directory.name.endswith("-latex"))
        if (base := directory.name[: -len(suffix)] if suffix else directory.name) != "default"
    }


def _question_heading(language: str, engine: str) -> str:
    """返回动态章节中每个问题标题的稳定前缀。"""
    title = "问题" if language == "zh" else "Problem"
    return f"= {title} Q" if engine == "typst" else f"\\section{{{title} Q"


def _supported_template_layout_cases() -> list[tuple[str, str, str, int]]:
    """生成紧凑模板矩阵，兼顾全覆盖与默认 PR 运行时间。"""
    cases = [
        (engine, language, competition, 5)
        for engine, templates in (
            ("latex", _template_cases("latex")),
            ("typst", SUPPORTED_TYPST_TEMPLATES),
        )
        for language, competition in sorted(templates)
    ]
    # 所有模板都测五问以防赛事模板遗漏；每种引擎再测一问和三问边界，验证动态
    # 章节没有隐含“恰好三问”的假设，而无需把同一文件复制 78 次。
    cases.extend(
        (engine, "zh", "cumcm", question_count)
        for engine in ("latex", "typst")
        for question_count in QUESTION_COUNTS[:2]
    )
    return cases


def _new_run(
    tmp_path: Path,
    run_id: str,
    *,
    competition: str = "cumcm",
    questions: list[str] | None = None,
) -> Path:
    """创建带完整比赛信息的最小论文运行。"""
    return initialize_simple_run(
        tmp_path,
        run_id,
        competition=competition,
        required_questions=questions or ["Q1"],
    )


def _set_engines(monkeypatch: pytest.MonkeyPatch, latex: bool, typst: bool) -> None:
    """隔离模板选择测试，不依赖开发机实际安装的 LaTeX。"""
    monkeypatch.setattr(
        paper_templates,
        "_available_paper_engines",
        lambda: (
            {"xelatex": "fake-xelatex"} if latex else {},
            "fake-typst" if typst else None,
        ),
    )


def _isolate_compiler_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离编译回执测试，工作流门由独立审核 E2E 单独覆盖。

    同时用内存存根替换 pandoc docx 转换，避免测试环境依赖 pandoc 安装。
    """
    monkeypatch.setattr(simple_review, "require_paper_generation_allowed", lambda _run: None)
    monkeypatch.setattr(paper_readiness, "require_paper_readiness", lambda _run: None)

    def _fake_compile_docx(paper_dir: Path, *, engine: str, timeout_seconds: int = 120) -> Path:
        """写入最小 docx 存根，确保 sha256 计算和后续文件检查不失败。"""
        out = paper_dir / "final.docx"
        out.write_bytes(b"PK\x03\x04fake-docx-stub")
        return out

    monkeypatch.setattr(paper_compiler, "compile_docx", _fake_compile_docx)

    def _fake_audit_docx(run_dir: Path, _docx: Path, *, timeout_seconds: int = 120) -> dict[str, object]:
        """模拟已独立覆盖的 DOCX 结构 QA，避免编译回执测试依赖 Word XML。"""
        report = {"schema_version": "1.0", "success": True, "errors": []}
        atomic_json(run_dir / "qa" / "docx-structure.json", report)
        return report

    monkeypatch.setattr(paper_compiler, "audit_docx", _fake_audit_docx)


def test_auto_template_selection_prefers_latex_and_records_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """自动选择必须以 LaTeX 为主路径，Typst 回退必须可见。"""
    _set_engines(monkeypatch, latex=True, typst=True)
    latex_run = _new_run(tmp_path, "latex-auto")
    latex_manifest = select_paper_template(
        latex_run,
        language="zh",
        engine="auto",
        selection_reason="全国赛中文稿使用仓内模板，自动路径优先 LaTeX。",
    )
    assert latex_manifest["engine"] == "latex"
    assert latex_manifest["requested_engine"] == "auto"
    assert latex_manifest["fallback_used"] is False
    assert latex_manifest["template_id"] == "zh/cumcm-latex"

    _set_engines(monkeypatch, latex=False, typst=True)
    typst_run = _new_run(tmp_path, "typst-fallback")
    typst_manifest = select_paper_template(
        typst_run,
        language="zh",
        engine="auto",
        selection_reason="LaTeX 环境不可用时，允许受控回退到仓内 Typst 模板。",
    )
    assert typst_manifest["engine"] == "typst"
    assert typst_manifest["fallback_used"] is True
    assert isinstance(typst_manifest["fallback_reason"], str)


def test_explicit_unavailable_engine_and_unknown_competition_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """显式用户选择不能被静默替换，未知赛事也不能默认化。"""
    _set_engines(monkeypatch, latex=False, typst=True)
    run_dir = _new_run(tmp_path, "explicit-latex")
    with pytest.raises(ContractError, match="显式选择 LaTeX"):
        select_paper_template(
            run_dir,
            language="zh",
            engine="latex",
            selection_reason="用户显式要求 LaTeX，环境不可用必须明确阻断。",
        )

    _set_engines(monkeypatch, latex=True, typst=False)
    for competition in ("unlisted-contest", "default"):
        unknown = _new_run(tmp_path, f"unknown-{competition}", competition=competition)
        with pytest.raises(ContractError, match="未识别比赛类型"):
            select_paper_template(
                unknown,
                language="en",
                engine="auto",
                selection_reason="未知赛事不允许静默使用默认模板，必须先补充映射。",
            )


def test_typst_template_support_inventory_is_explicit() -> None:
    """新增 Typst 模板必须先明确分类，不能绕过动态正文安全边界。"""
    assert _template_cases("typst") == SUPPORTED_TYPST_TEMPLATES | UNSUPPORTED_TYPST_TEMPLATES


@pytest.mark.parametrize(
    ("engine", "language", "competition", "question_count"),
    _supported_template_layout_cases(),
    ids=lambda case: str(case),
)
@pytest.mark.template_matrix
def test_supported_templates_materialize_all_question_layouts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    engine: str,
    language: str,
    competition: str,
    question_count: int,
) -> None:
    """每个可用模板均须支持 1/3/5 问，不得固化为示例题目结构。"""
    _set_engines(monkeypatch, latex=True, typst=True)
    questions = [f"Q{index}" for index in range(1, question_count + 1)]
    run_dir = _new_run(
        tmp_path,
        f"{engine}-{language}-{competition}-{question_count}",
        competition=competition,
        questions=questions,
    )
    select_paper_template(
        run_dir,
        language=language,
        engine=engine,
        selection_reason="模板矩阵回归验证动态章节、目录入口与实际题目数量同步。",
    )
    manifest = materialize_selected_template(run_dir)
    require_materialized_template(run_dir)

    questions_file = run_dir / "paper" / manifest["question_layout"]["section_path"]
    content = questions_file.read_text(encoding="utf-8")
    assert content.count(_question_heading(language, engine)) == question_count
    answer_heading = "本问结论" if language == "zh" else "Answer First"
    assert content.count(answer_heading) == question_count
    for question_index in range(1, question_count + 1):
        heading = f"问题 Q{question_index}" if language == "zh" else f"Problem Q{question_index}"
        start = content.index(heading)
        next_heading = "模型选择与关键关系" if language == "zh" else "Model and Key Relations"
        assert content.index(answer_heading, start) < content.index(next_heading, start)
    entrypoint = run_dir / "paper" / manifest["question_layout"]["entrypoint_path"]
    assert entrypoint.read_text(encoding="utf-8").count(
        '#include("sections/questions.typ")'
        if engine == "typst"
        else "\\input{sections/questions}"
    ) == 1


def test_cumcm_typography_contract_is_explicit() -> None:
    """CUMCM 模板明确宋体小四正文和 Times 系数学斜体。"""
    latex = (TEMPLATE_ROOT / "zh/cumcm-latex/main.tex").read_text(encoding="utf-8")
    typst = (TEMPLATE_ROOT / "zh/cumcm/main.typ").read_text(encoding="utf-8")
    assert "\\fontsize{12pt}{18pt}\\selectfont" in latex
    assert "newtxmath.sty" in latex and "mathptmx" in latex
    assert "#set text(font: song-font, size: 12pt" in typst
    assert "#show math.equation: set text(font:" in typst


@pytest.mark.parametrize(
    ("language", "competition"),
    sorted(UNSUPPORTED_TYPST_TEMPLATES),
)
def test_unsupported_typst_templates_reject_instead_of_retaining_examples(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    language: str,
    competition: str,
) -> None:
    """没有安全插入锚点的 Typst 模板必须明确阻断。"""
    _set_engines(monkeypatch, latex=True, typst=True)
    run_dir = _new_run(tmp_path, f"unsupported-{language}-{competition}", competition=competition)
    with pytest.raises(ContractError, match="缺少安全的动态问题章节插入点"):
        select_paper_template(
            run_dir,
            language=language,
            engine="typst",
            selection_reason="模板缺少动态问题锚点时，不能通过保留示例正文继续写作。",
        )


def test_materialization_clears_sample_references_and_placeholder_scan_finds_residue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """赛事模板不能因示例参考文献或标题占位符而污染最终稿。"""
    _set_engines(monkeypatch, latex=True, typst=True)
    run_dir = _new_run(tmp_path, "clear-template-residue")
    select_paper_template(
        run_dir,
        language="zh",
        engine="latex",
        selection_reason="模板样例内容必须在实例化时清空，避免误入当前竞赛论文。",
    )
    materialize_selected_template(run_dir)
    references = (run_dir / "paper/references.tex").read_text(encoding="utf-8")
    assert "正式参考文献" in references
    assert "\\bibitem" not in references

    (run_dir / "paper/sections/questions.tex").write_text(
        "\\section{论文标题}\n中文摘要内容\n关键词1\n[Paper Title]\n",
        encoding="utf-8",
    )
    report = check_placeholders(run_dir / "paper")
    found = report["matches"]["sections/questions.tex"]
    assert {"论文标题", "中文摘要内容", "关键词1", "[Paper Title]"} <= set(found)


@pytest.mark.paper_e2e
@pytest.mark.skipif(shutil.which("typst") is None, reason="当前环境未安装 typst")
def test_typst_compile_receipt_rejects_tampering_and_ignores_bibliography_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实 Typst 编译、回执复验和生成副产物排除必须同时工作。"""
    _set_engines(monkeypatch, latex=False, typst=True)
    _isolate_compiler_receipt(monkeypatch)
    run_dir = _new_run(tmp_path, "typst-compile", questions=["Q1", "Q2"])
    select_paper_template(
        run_dir,
        language="zh",
        engine="typst",
        selection_reason="真实 Typst 烟雾测试只验证受控编译与回执，不使用题目样例内容。",
    )
    materialize_selected_template(run_dir)
    # 将复杂模板缩成动态问题入口，保证测试只覆盖编译器边界而非模板排版风格。
    (run_dir / "paper/main.typ").write_text(
        '#include("sections/questions.typ")\n', encoding="utf-8", newline="\n"
    )
    receipt = compile_paper(run_dir)
    assert receipt["engine"] == "typst"
    assert verify_paper_compile_receipt(run_dir)["valid"] is True

    for filename in ("main.bbl", "main.blg", "main.bcf", "main.run.xml", "main.xdv"):
        (run_dir / "paper" / filename).write_text("compiler byproduct\n", encoding="utf-8")
    assert verify_paper_compile_receipt(run_dir)["valid"] is True

    (run_dir / "paper/sections/questions.typ").write_text("= changed\n", encoding="utf-8")
    assert verify_paper_compile_receipt(run_dir)["valid"] is False


def test_latex_compile_receipt_uses_selected_latex_entrypoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LaTeX 主路径必须实际执行 main.tex 并冻结与 Typst 不同的 PDF 回执。"""
    _set_engines(monkeypatch, latex=True, typst=True)
    _isolate_compiler_receipt(monkeypatch)
    run_dir = _new_run(tmp_path, "latex-compile", questions=["Q1", "Q2"])
    select_paper_template(
        run_dir,
        language="zh",
        engine="auto",
        selection_reason="LaTeX 可用时，受控编译必须沿用自动选择的主路径。",
    )
    materialize_selected_template(run_dir)
    # 用最小受控编译器代替开发机 TeX 环境，覆盖 subprocess、main.pdf -> final.pdf
    # 和回执绑定，而不是依赖某套本机字体或宏包。
    fake_compiler = tmp_path / "fake_xelatex.py"
    fake_compiler.write_text(
        "from pathlib import Path\n"
        "Path('sections/questions.aux').write_text('generated aux', encoding='utf-8')\n"
        "Path('main.log').write_text('generated log', encoding='utf-8')\n"
        "Path('main.pdf').write_bytes(b'%PDF-1.4\\nminimal latex output')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        paper_compiler,
        "_compiler_steps",
        lambda engine: (
            "xelatex",
            [[sys.executable, str(fake_compiler), "main.tex"]] if engine == "latex" else [],
        ),
    )

    receipt = compile_paper(run_dir)

    assert receipt["engine"] == "latex"
    assert receipt["requested_engine"] == "auto"
    assert receipt["compiler"] == "xelatex"
    assert receipt["entrypoint_path"] == "paper/main.tex"
    assert receipt["final_pdf_path"] == "paper/final.pdf"
    assert (run_dir / "paper/final.pdf").is_file()
    assert verify_paper_compile_receipt(run_dir)["valid"] is True


def test_v32_compile_increments_render_revision_and_invalidates_old_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """每次正式渲染只递增一次修订号，未重审时状态必须可见。"""
    _set_engines(monkeypatch, latex=True, typst=True)
    _isolate_compiler_receipt(monkeypatch)
    run_dir = initialize_simple_run(
        tmp_path,
        "v32-render-revision",
        competition="mcm",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    select_paper_template(
        run_dir,
        language="zh",
        engine="latex",
        selection_reason="验证正式编译修订号与盲评新鲜度，不涉及竞赛模板内容。",
    )
    materialize_selected_template(run_dir)
    fake_compiler = tmp_path / "fake_revision_xelatex.py"
    fake_compiler.write_text(
        "from pathlib import Path\n"
        "Path('main.log').write_text('generated log', encoding='utf-8')\n"
        "Path('main.pdf').write_bytes(b'%PDF-1.4\\nrevision test')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        paper_compiler,
        "_compiler_steps",
        lambda engine: (
            "xelatex",
            [[sys.executable, str(fake_compiler), "main.tex"]] if engine == "latex" else [],
        ),
    )

    first = compile_paper(run_dir)
    first_state = read_simple_state(run_dir)
    assert first["paper_render_revision"] == 1
    assert first_state["paper_render_revision"] == 1
    assert paper_revision_status(first_state)["status"] == "UNREVIEWED_DRAFT"

    second = compile_paper(run_dir)
    second_state = read_simple_state(run_dir)
    assert second["paper_render_revision"] == 2
    assert second_state["paper_render_revision"] == 2
    assert second_state["paper_reviewed_revision"] == 0
    assert paper_revision_status(second_state)["status"] == "UNREVIEWED_DRAFT"
    assert verify_paper_compile_receipt(run_dir)["valid"] is True


def test_reviewable_draft_compiles_before_answer_qualification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未完成答案可生成显式披露的草稿，但不能绕过正式编译门禁。"""
    _set_engines(monkeypatch, latex=True, typst=True)
    run_dir = initialize_simple_run(
        tmp_path,
        "reviewable-draft",
        competition="cumcm",
        required_questions=["Q1", "Q2"],
        workflow_version="3.2",
        total_hours=12,
    )
    write_analysis_knowledge_retrieval(
        run_dir,
        None,
        {
            "problem_type": "测试用论文编译",
            "data_structure": "测试构造数据",
            "task_types": ["草稿编译"],
        },
        unavailable_reason="该编译测试不装载真实论文卡索引，仅验证草稿论证入口。",
    )
    write_paper_knowledge_application(run_dir)
    select_paper_template(
        run_dir,
        language="zh",
        engine="latex",
        selection_reason="测试首个可审阅 PDF 与正式候选门禁相互隔离。",
    )
    materialize_selected_template(run_dir)
    (run_dir / "paper/PAPER_BLUEPRINT.md").write_text(
        "# 论文结构蓝图\n\n"
        "## 总体判断\n\n"
        "本文先统一问题对象与评价口径，再用当前真实结果判断路线是否值得进入后续问题。"
        "这一判断连接基线、候选路线、验证证据与适用边界，避免正文退化为结果清单。\n\n"
        "## Q1 完整性卡\n\n"
        "题面要求明确比较可执行方案。数学对象是当前样本上的统一目标。"
        "关键推导连接约束与评价量，算法执行自然基线和主路线。"
        "结果由真实实验支持，边界是不外推到题面范围之外，结论给出当前直接答案。\n\n"
        "## 跨问题论证链\n\n"
        "题面事实导出共享数学对象，再由解析关系确定数值求解任务；"
        "当前实验支持 Q1 判断，后续 Q2 将继承同一评价口径并补足尚未完成的验证。"
        "竞争解释通过自然基线排除，结论只在当前题面参数和数据范围内成立。\n",
        encoding="utf-8",
    )
    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "schema_name": "figure_plan",
            "schema_version": "2.3",
            "run_id": run_dir.name,
            "visual_decisions": [
                {
                    "scope": question_id,
                    "evidence_need": "waived",
                    "presentation_need": "waived",
                    "reason": "当前草稿只验证论证入口，暂不需要展示图且已在首稿前决定。",
                }
                for question_id in ("Q1", "Q2")
            ],
            "figures": [],
        },
    )
    monkeypatch.setattr(
        paper_readiness,
        "require_paper_readiness",
        lambda _run: (_ for _ in ()).throw(ContractError("Q2 尚未形成答案资格")),
    )
    monkeypatch.setattr(
        simple_review,
        "require_paper_generation_allowed",
        lambda _run: None,
    )
    fake_compiler = tmp_path / "fake_draft_xelatex.py"
    fake_compiler.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "entry = Path(sys.argv[-1])\n"
        "entry.with_suffix('.pdf').write_bytes(b'%PDF-1.4\\nreviewable draft')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        paper_compiler,
        "_compiler_steps",
        lambda engine: (
            "xelatex",
            [[sys.executable, str(fake_compiler), "main.tex"]] if engine == "latex" else [],
        ),
    )

    with pytest.raises(ContractError, match="Q2 尚未形成答案资格"):
        compile_paper(run_dir)

    receipt = compile_reviewable_draft(
        run_dir,
        completed_content=["Q1 已完成自然基线与主路线比较。"],
        unfinished_questions=["Q2"],
        remaining_experiments=["完成 Q2 fallback 的统一 exact scorer 复算。"],
        provisional_conclusions=[],
    )

    disclosure = (run_dir / "paper/generated/reviewable-draft-status.tex").read_text(
        encoding="utf-8"
    )
    assert receipt["artifact_path"] == "paper/draft-1.pdf"
    assert receipt["not_for_final_submission"] is True
    assert "当前已完成内容" in disclosure
    assert "暂未完成的问题" in disclosure
    assert "仍需补的实验" in disclosure
    assert "当前候选结论" in disclosure
    assert "不可作为最终提交" in disclosure
    assert verify_reviewable_draft_receipt(run_dir)["valid"] is True


def test_reviewable_draft_requires_paper_blueprint(tmp_path: Path) -> None:
    """能编译的空壳不能冒充可审阅论文首版。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "reviewable-draft-without-argument",
        competition="cumcm",
        required_questions=["Q1"],
        workflow_version="3.2",
    )

    with pytest.raises(ContractError, match="PAPER_BLUEPRINT.md"):
        compile_reviewable_draft(
            run_dir,
            completed_content=["Q1 已完成。"],
            unfinished_questions=[],
            remaining_experiments=[],
            provisional_conclusions=[],
        )


def test_argument_and_render_revisions_invalidate_different_checks(tmp_path: Path) -> None:
    """纯排版只失效版式 QA，正文论证变化才失效独立盲评。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "split-paper-revisions",
        competition="cumcm",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    record_paper_compilation(
        run_dir, previous_render_revision=0, argument_changed=False
    )
    record_paper_review(run_dir, argument_revision=1)
    record_layout_audit(run_dir, render_revision=1)
    assert paper_revision_status(read_simple_state(run_dir))["status"] == "REVIEWED"

    record_paper_compilation(
        run_dir, previous_render_revision=1, argument_changed=False
    )
    render_only = read_simple_state(run_dir)
    assert render_only["argument_revision"] == 1
    assert render_only["reviewed_argument_revision"] == 1
    assert paper_revision_status(render_only)["status"] == "REVIEWED_LAYOUT_PENDING"

    record_paper_compilation(
        run_dir, previous_render_revision=2, argument_changed=True
    )
    argument_change = read_simple_state(run_dir)
    assert argument_change["argument_revision"] == 2
    assert paper_revision_status(argument_change)["status"] == "UNREVIEWED_DRAFT"


@pytest.mark.paper_e2e
@pytest.mark.skipif(
    not any(shutil.which(command) for command in ("latexmk", "xelatex", "tectonic")),
    reason="当前环境未安装可用的 XeLaTeX 工具链",
)
def test_real_latex_cumcm_template_compiles_and_verifies_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实 LaTeX 工具链必须能编译 CUMCM 动态问题模板并复验回执。"""
    _set_engines(monkeypatch, latex=True, typst=False)
    _isolate_compiler_receipt(monkeypatch)
    run_dir = _new_run(tmp_path, "real-latex-cumcm", questions=["Q1", "Q2"])
    select_paper_template(
        run_dir,
        language="zh",
        engine="latex",
        selection_reason="阻断 CI 使用真实 XeLaTeX 编译 CUMCM 最小论文。",
    )
    materialize_selected_template(run_dir)
    entrypoint = run_dir / "paper/main.tex"
    source = entrypoint.read_text(encoding="utf-8")
    # CI 使用 TeX Live 自带的 Fandol 字体，保留完整 CUMCM 模板结构和动态正文入口。
    entrypoint.write_text(
        source.replace("fontset=mac", "fontset=fandol"),
        encoding="utf-8",
        newline="\n",
    )

    receipt = compile_paper(run_dir)

    assert receipt["engine"] == "latex"
    assert receipt["compiler"] in {"latexmk", "xelatex", "tectonic"}
    assert receipt["executions"]
    assert (run_dir / "paper/final.pdf").stat().st_size > 1_000
    assert verify_paper_compile_receipt(run_dir)["valid"] is True


@pytest.mark.paper_e2e
@pytest.mark.skipif(shutil.which("typst") is None, reason="当前环境未安装 typst")
@pytest.mark.parametrize("tamper_target", ["manifest", "pdf"])
def test_compile_receipt_binds_manifest_and_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper_target: str,
) -> None:
    """模板清单和最终 PDF 任何一个变化都必须撤销编译回执。"""
    _set_engines(monkeypatch, latex=False, typst=True)
    _isolate_compiler_receipt(monkeypatch)
    run_dir = _new_run(tmp_path, f"compile-{tamper_target}")
    select_paper_template(
        run_dir,
        language="zh",
        engine="typst",
        selection_reason="测试编译回执必须绑定模板清单、源文件和最终 PDF。",
    )
    materialize_selected_template(run_dir)
    (run_dir / "paper/main.typ").write_text(
        '#include("sections/questions.typ")\n', encoding="utf-8", newline="\n"
    )
    compile_paper(run_dir)
    if tamper_target == "manifest":
        manifest_path = run_dir / "paper/template_manifest.json"
        manifest = load_json(manifest_path)
        manifest["selection_reason"] = "模板清单在编译后被篡改，回执必须立即失效。"
        atomic_json(manifest_path, manifest)
    else:
        (run_dir / "paper/final.pdf").write_bytes(b"%PDF-1.4\nchanged")

    assert verify_paper_compile_receipt(run_dir)["valid"] is False


def test_compile_skips_docx_and_records_reason_when_pandoc_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pandoc 缺失时编译不应整体失败；回执记录跳过原因，不记录 docx 路径。"""
    _set_engines(monkeypatch, latex=True, typst=True)
    monkeypatch.setattr(simple_review, "require_paper_generation_allowed", lambda _run: None)
    monkeypatch.setattr(paper_readiness, "require_paper_readiness", lambda _run: None)

    def _no_pandoc(paper_dir: Path, *, engine: str, timeout_seconds: int = 120) -> Path:
        raise ContractError(
            "论文编译要求同时生成 Word（.docx）版本，但当前环境未检测到 pandoc。"
            "请安装 pandoc（https://pandoc.org/installing.html）后重试。"
        )

    monkeypatch.setattr(paper_compiler, "compile_docx", _no_pandoc)

    run_dir = _new_run(tmp_path, "no-pandoc", questions=["Q1"])
    select_paper_template(
        run_dir,
        language="zh",
        engine="auto",
        selection_reason="测试 pandoc 缺失时 PDF 仍可冻结回执。",
    )
    materialize_selected_template(run_dir)

    fake_compiler = tmp_path / "fake_xelatex_nopandoc.py"
    fake_compiler.write_text(
        "from pathlib import Path\n"
        "Path('main.log').write_text('generated log', encoding='utf-8')\n"
        "Path('main.pdf').write_bytes(b'%PDF-1.4\\nno-pandoc test')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        paper_compiler,
        "_compiler_steps",
        lambda engine: (
            "xelatex",
            [[sys.executable, str(fake_compiler), "main.tex"]] if engine == "latex" else [],
        ),
    )

    receipt = compile_paper(run_dir)

    assert receipt["engine"] == "latex"
    assert receipt["final_pdf_path"] == "paper/final.pdf"
    assert "final_docx_path" not in receipt
    assert "final_docx_sha256" not in receipt
    assert "docx_skipped_reason" in receipt
    assert "pandoc" in receipt["docx_skipped_reason"]
    assert verify_paper_compile_receipt(run_dir)["valid"] is True


def test_latex_compile_failure_surfaces_log_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LaTeX 编译失败时，ContractError 应包含 main.log 中的 '! Error' 行。"""
    _set_engines(monkeypatch, latex=True, typst=True)
    monkeypatch.setattr(simple_review, "require_paper_generation_allowed", lambda _run: None)
    monkeypatch.setattr(paper_readiness, "require_paper_readiness", lambda _run: None)

    run_dir = _new_run(tmp_path, "latex-fail", questions=["Q1"])
    select_paper_template(
        run_dir,
        language="zh",
        engine="auto",
        selection_reason="测试 LaTeX 编译失败时从 main.log 提取错误行。",
    )
    materialize_selected_template(run_dir)

    fake_compiler = tmp_path / "fake_bad_xelatex.py"
    fake_compiler.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "Path('main.log').write_text(\n"
        "    'This is XeTeX\\n! Undefined control sequence.\\nl.42 \\\\\\\\badcommand\\n',\n"
        "    encoding='utf-8',\n"
        ")\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        paper_compiler,
        "_compiler_steps",
        lambda engine: (
            "xelatex",
            [[sys.executable, str(fake_compiler), "main.tex"]] if engine == "latex" else [],
        ),
    )

    with pytest.raises(ContractError, match="Undefined control sequence"):
        compile_paper(run_dir)
