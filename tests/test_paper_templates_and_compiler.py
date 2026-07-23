"""回归模板路由、动态题目结构和受控论文编译。"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

import shumozizi.paper.compiler as paper_compiler
import shumozizi.paper.templates as paper_templates
from scripts.qa.check_placeholders import check_placeholders
from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.paper.compiler import compile_paper, verify_paper_compile_receipt
from shumozizi.paper.templates import (
    materialize_selected_template,
    require_materialized_template,
    select_paper_template,
)
from shumozizi.simple.initialization import initialize_simple_run

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
    entrypoint = run_dir / "paper" / manifest["question_layout"]["entrypoint_path"]
    assert entrypoint.read_text(encoding="utf-8").count(
        '#include("sections/questions.typ")'
        if engine == "typst"
        else "\\input{sections/questions}"
    ) == 1


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
