"""验证论文机械 QA 会实际调用两套可用 PDF 渲染器。"""

from __future__ import annotations

from pathlib import Path

from reportlab.pdfgen import canvas

from tools.qa.pdf_qa import audit_pdf


def test_pdf_qa_renders_every_page_with_available_engines(tmp_path: Path) -> None:
    """双渲染器检查应报告页数一致性，而不只依赖文本抽取。"""
    pdf = tmp_path / "two-pages.pdf"
    writer = canvas.Canvas(str(pdf))
    writer.drawString(72, 720, "Page one: renderer verification")
    writer.showPage()
    writer.drawString(72, 720, "Page two: renderer verification")
    writer.save()

    report = audit_pdf(pdf)
    checks = {item["id"]: item for item in report["checks"]}

    assert "renderer-pymupdf" in checks
    assert "renderer-poppler" in checks
    assert "dual-renderer" in checks
    for renderer in report["renderers"].values():
        if renderer["available"]:
            assert renderer["passed"], renderer["details"]


def test_pdf_qa_detects_discontinuous_footer_page_numbers(tmp_path: Path) -> None:
    """可栅格化不等于页码完整；页脚序列缺页必须被单独报告。"""
    pdf = tmp_path / "broken-footer-numbering.pdf"
    writer = canvas.Canvas(str(pdf))
    for number in (1, 3):
        writer.drawString(72, 720, "Body text")
        writer.drawCentredString(300, 24, f"Page {number}")
        writer.showPage()
    writer.save()

    report = audit_pdf(pdf)
    checks = {item["id"]: item for item in report["checks"]}

    assert "page-number-continuity" in checks
    assert not checks["page-number-continuity"]["passed"]
    assert checks["page-number-continuity"]["blocking"]
    assert report["footer_numbering"]["status"] == "discontinuous"


def test_pdf_qa_requires_explicit_human_confirmation_for_critical_pages(tmp_path: Path) -> None:
    """已知风险页必须导出后经人工确认，不能由 renderer 页数替代。"""
    pdf = tmp_path / "critical-page.pdf"
    rendered = tmp_path / "critical-rendered"
    writer = canvas.Canvas(str(pdf))
    writer.drawString(72, 720, "Body text")
    writer.drawCentredString(300, 24, "Page 1")
    writer.save()

    pending = audit_pdf(
        pdf,
        critical_pages=(1,),
        critical_page_output_dir=rendered,
    )
    pending_checks = {item["id"]: item for item in pending["checks"]}
    assert not pending_checks["manual-critical-page-review"]["passed"]
    assert pending_checks["manual-critical-page-review"]["blocking"]
    assert (rendered / "page-001.png").is_file()

    confirmed = audit_pdf(
        pdf,
        critical_pages=(1,),
        manual_critical_review_confirmed=True,
        critical_page_output_dir=rendered,
    )
    confirmed_checks = {item["id"]: item for item in confirmed["checks"]}
    assert confirmed_checks["manual-critical-page-review"]["passed"]
