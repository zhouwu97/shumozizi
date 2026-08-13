"""验证 SUBMISSION_CONTRACT：年度提交格式检查独立于求解、判定保守不误伤。"""

from __future__ import annotations

from pathlib import Path

from shumozizi.paper.submission_contract import audit_submission_contract
from shumozizi.simple.initialization import initialize_simple_run


def _run(tmp_path: Path, name: str) -> Path:
    """创建单问运行（格式检查只需 run 目录 + 一份 PDF）。"""
    return initialize_simple_run(
        tmp_path,
        name,
        required_questions=["Q1"],
        workflow_version="3.2",
    )


def _codes(report: dict) -> set[str]:
    """返回审计发现代码集合。"""
    return {item["code"] for item in report["findings"]}


def _write_pdf(
    run_dir: Path,
    text: str,
    *,
    total_pages: int,
    page2_text: str = "",
) -> Path:
    """构造一份最小的多页 PDF（首页含给定文本，可选第 2 页文本）。"""
    from reportlab.pdfgen import canvas

    pdf_path = run_dir / "document.pdf"
    c = canvas.Canvas(str(pdf_path))
    for page in range(total_pages):
        c.drawString(72, 720, f"page {page + 1}")
        body = text if page == 0 else (page2_text if page == 1 else "")
        y = 700
        for line in body.splitlines():
            c.drawString(72, y, line)
            y -= 14
        c.showPage()
    c.save()
    return pdf_path


def test_no_pdf_returns_clean(tmp_path: Path) -> None:
    """没有提交 PDF 时返回空发现而不是报错。"""
    run_dir = _run(tmp_path, "no-pdf")
    report = audit_submission_contract(run_dir)
    assert report["metrics"]["pdf_present"] is False
    assert report["findings"] == []


def test_abstract_on_first_page_and_no_toc_is_clean(tmp_path: Path) -> None:
    """首页含摘要、无目录、正文页数合格时应无格式告警。"""
    run_dir = _run(tmp_path, "clean-submission")
    _write_pdf(
        run_dir,
        "Title\nAbstract\nsummary text about NIPT reliability\nKeywords: NIPT",
        total_pages=25,
        page2_text="I. Introduction\nbody starts here",
    )
    report = audit_submission_contract(run_dir)
    assert "SUBMISSION_ABSTRACT_FIRST_PAGE" not in _codes(report)
    assert "SUBMISSION_BODY_OVER_LIMIT" not in _codes(report)


def test_abstract_overflow_flagged(tmp_path: Path) -> None:
    """摘要延伸到第 2 页开头时被判超页（2026 规范要求摘要不超过一页）。"""
    run_dir = _run(tmp_path, "abstract-overflow")
    # 第 2 页开头仍是摘要正文（不是章节标题）→ 应触发超页。
    _write_pdf(
        run_dir,
        "Title\nAbstract\nsummary text on page one",
        total_pages=3,
        page2_text="summary keeps continuing onto page two",
    )
    report = audit_submission_contract(run_dir)
    assert "SUBMISSION_ABSTRACT_OVERFLOW" in _codes(report)


def test_body_over_limit_flagged_but_code_appendix_not(tmp_path: Path) -> None:
    """正文超 30 页应告警；但含代码附录的总页数不算违规。"""
    run_dir = _run(tmp_path, "body-over-limit")
    _write_pdf(
        run_dir,
        "Title\nAbstract\nKeywords\nI. Introduction\nbody text very long",
        total_pages=45,
    )
    report = audit_submission_contract(run_dir)
    assert "SUBMISSION_BODY_OVER_LIMIT" in _codes(report)
    assert "SUBMISSION_CODE_APPENDIX_PAGES" not in _codes(report)


def test_toc_flagged(tmp_path: Path) -> None:
    """正文出现目录时应被标记（2026 规范不要目录）。"""
    run_dir = _run(tmp_path, "toc-present")
    _write_pdf(
        run_dir,
        "Title\nAbstract\nKeywords\nContents\nI. Introduction",
        total_pages=5,
    )
    report = audit_submission_contract(run_dir)
    assert "SUBMISSION_TOC_PRESENT" in _codes(report)


def test_code_appendix_missing_flagged(tmp_path: Path) -> None:
    """附录无代码块（只有文件清单）时告警。"""
    run_dir = _run(tmp_path, "code-appendix-missing")
    paper = run_dir / "paper"
    paper.mkdir(exist_ok=True)
    (paper / "main.tex").write_text(
        "\\section*{Appendix}\ncomplete code submitted as attachment\n",
        encoding="utf-8",
    )
    _write_pdf(run_dir, "Title\nAbstract\nKeywords", total_pages=5)
    report = audit_submission_contract(run_dir)
    assert "SUBMISSION_CODE_APPENDIX" in _codes(report)
