"""PDF 确定性视觉前置检查；复杂遮挡仍需桌面逐页复核。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pypdf import PdfReader


def inspect_pdf_visual(
    pdf: Path, *, max_bytes: int | None = None, enforce_a4: bool = False
) -> dict[str, Any]:
    """检查 A4 页面、文件大小、字体资源和基本绘制内容。"""
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    if not pdf.is_file():
        return {"status": "blocked", "checks": [], "errors": [f"PDF 不存在: {pdf}"], "warnings": []}
    if max_bytes is not None:
        passed = pdf.stat().st_size <= max_bytes
        checks.append({"check_id": "file-size", "passed": passed, "details": str(pdf.stat().st_size)})
        if not passed:
            errors.append(f"PDF 文件大小超过限制: {pdf.stat().st_size} > {max_bytes}")
    try:
        reader = PdfReader(str(pdf))
        a4_width, a4_height = 595.276, 841.89
        for index, page in enumerate(reader.pages, start=1):
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
            a4 = (abs(width - a4_width) <= 2 and abs(height - a4_height) <= 2) or (
                abs(width - a4_height) <= 2 and abs(height - a4_width) <= 2
            )
            checks.append({"check_id": f"page-{index}-a4", "passed": a4, "details": f"{width:.2f}x{height:.2f}pt"})
            if enforce_a4 and not a4:
                errors.append(f"第 {index} 页不是 A4 尺寸: {width:.2f}x{height:.2f}pt")
            elif not a4:
                warnings.append(f"第 {index} 页不是 A4 尺寸: {width:.2f}x{height:.2f}pt")
            resources = page.get("/Resources")
            fonts = resources.get("/Font") if resources else None
            if not fonts:
                warnings.append(f"第 {index} 页未发现字体资源，需人工确认图形页可读性")
            contents = page.get_contents()
            if contents is None:
                errors.append(f"第 {index} 页没有绘制内容")
        return {"status": "pass" if not errors else "blocked", "checks": checks, "errors": errors, "warnings": warnings}
    except Exception as exc:
        return {"status": "blocked", "checks": checks, "errors": [f"PDF 视觉检查失败: {exc}"], "warnings": warnings}
