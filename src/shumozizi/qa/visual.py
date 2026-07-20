"""PDF 确定性视觉前置检查与结构化格式审计。"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from shumozizi.core.io import atomic_json, load_json, sha256_file
from shumozizi.core.schema import require_valid

try:
    import pdfplumber
except ImportError:  # pragma: no cover - 依赖由项目运行环境提供
    pdfplumber = None


_FIGURE_RE = re.compile(r"(?:图|Figure)\s*([0-9]+)", re.IGNORECASE)
_TABLE_RE = re.compile(r"(?:表|Table)\s*([0-9]+)", re.IGNORECASE)
_ANONYMOUS_TERMS = ("学校名称", "学生姓名", "指导教师", "学号")


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


def _deref(value: Any) -> Any:
    """安全解引用 pypdf 间接对象。"""
    return value.get_object() if hasattr(value, "get_object") else value


def _font_descriptor(font: Any) -> Any:
    """查找普通字体和 Type0/CIDFont 的字体描述符。"""
    font = _deref(font)
    descriptor = font.get("/FontDescriptor")
    if descriptor is not None:
        return _deref(descriptor)
    descendants = _deref(font.get("/DescendantFonts")) or []
    for descendant in descendants:
        descriptor = _deref(_deref(descendant).get("/FontDescriptor"))
        if descriptor is not None:
            return descriptor
    return None


def _font_resources(reader: PdfReader) -> tuple[list[dict[str, Any]], bool]:
    """记录所有 PDF 字体资源，并检查 FontFile/FontFile2/FontFile3。"""
    resources: list[dict[str, Any]] = []
    embedded_all = True
    seen: set[tuple[int, str]] = set()
    for page_number, page in enumerate(reader.pages, start=1):
        page_resources = _deref(page.get("/Resources")) or {}
        fonts = _deref(page_resources.get("/Font")) or {}
        for name, raw_font in fonts.items():
            font = _deref(raw_font)
            key = (id(font), str(name))
            if key in seen:
                continue
            seen.add(key)
            descriptor = _font_descriptor(font)
            files = [key for key in ("/FontFile", "/FontFile2", "/FontFile3") if descriptor and descriptor.get(key) is not None]
            embedded = bool(files)
            embedded_all = embedded_all and embedded
            resources.append(
                {
                    "page": page_number,
                    "name": str(name),
                    "subtype": str(font.get("/Subtype", "")),
                    "base_font": str(font.get("/BaseFont", "")),
                    "embedded": embedded,
                    "embedded_resources": files,
                }
            )
    return resources, bool(resources) and embedded_all


def _numbering_complete(text: str, pattern: re.Pattern[str]) -> bool:
    """检查图/表编号是否从 1 连续出现；没有该类对象时视为通过。"""
    numbers = sorted({int(value) for value in pattern.findall(text)})
    return not numbers or numbers == list(range(1, max(numbers) + 1))


def _margin_and_text_metrics(pdf: Path) -> dict[str, Any]:
    """用 pdfplumber 的字符框测量正文边界和字号分布。"""
    if pdfplumber is None:
        raise RuntimeError("缺少 pdfplumber，无法执行 PDF 实际测量")
    page_metrics: list[dict[str, Any]] = []
    body_sizes: Counter[str] = Counter()
    caption_sizes: Counter[str] = Counter()
    all_text: list[str] = []
    image_dpi: list[dict[str, Any]] = []
    clipping = False
    overlap = False
    with pdfplumber.open(str(pdf)) as document:
        for page_number, page in enumerate(document.pages, start=1):
            chars = page.chars or []
            text = page.extract_text() or ""
            all_text.append(text)
            if chars:
                left = min(float(item["x0"]) for item in chars)
                right = max(float(item["x1"]) for item in chars)
                top = min(float(item["top"]) for item in chars)
                bottom = max(float(item["bottom"]) for item in chars)
                for item in chars:
                    size = round(float(item.get("size", 0.0)), 2)
                    body_sizes[f"{size:g}"] += 1
                    if re.search(r"(?:图|表|Figure|Table)", str(item.get("text", "")), re.IGNORECASE):
                        caption_sizes[f"{size:g}"] += 1
                    clipping = clipping or float(item["x0"]) < 0 or float(item["x1"]) > page.width
                    clipping = clipping or float(item["top"]) < 0 or float(item["bottom"]) > page.height
                words = page.extract_words() or []
                for index, first in enumerate(words):
                    for second in words[index + 1 :]:
                        same_line = abs(float(first["top"]) - float(second["top"])) < 0.8
                        if same_line and min(float(first["x1"]), float(second["x1"])) - max(float(first["x0"]), float(second["x0"])) > 0.5:
                            overlap = True
                            break
                    if overlap:
                        break
                page_metrics.append(
                    {
                        "page": page_number,
                        "left_cm": round(left / 72 * 2.54, 3),
                        "right_cm": round((page.width - right) / 72 * 2.54, 3),
                        "top_cm": round(top / 72 * 2.54, 3),
                        "bottom_cm": round((page.height - bottom) / 72 * 2.54, 3),
                    }
                )
            else:
                page_metrics.append({"page": page_number, "left_cm": None, "right_cm": None, "top_cm": None, "bottom_cm": None})
            for image in page.images or []:
                source_size = image.get("srcsize") or (None, None)
                source_width, source_height = source_size
                display_width = float(image.get("width", 0.0)) / 72
                display_height = float(image.get("height", 0.0)) / 72
                image_dpi.append(
                    {
                        "page": page_number,
                        "width_px": source_width,
                        "height_px": source_height,
                        "dpi_x": round(source_width / display_width, 2) if source_width and display_width else None,
                        "dpi_y": round(source_height / display_height, 2) if source_height and display_height else None,
                    }
                )
    minimum = {
        key: min((item[key] for item in page_metrics if item[key] is not None), default=None)
        for key in ("left_cm", "right_cm", "top_cm", "bottom_cm")
    }
    return {
        "page_metrics": page_metrics,
        "minimum": minimum,
        "body_sizes": dict(body_sizes),
        "caption_sizes": dict(caption_sizes),
        "text": "\n".join(all_text),
        "page_texts": all_text,
        "image_dpi": image_dpi,
        "clipping": clipping,
        "overlap": overlap,
    }


def audit_pdf_format(
    run_dir: Path, pdf: Path, *, write: bool = True
) -> dict[str, Any]:
    """执行并写入 ``review/FORMAT_AUDIT.json``，Profile 硬规则不能由审核意见覆盖。"""
    run_dir = run_dir.resolve()
    pdf = pdf.resolve()
    lock = load_json(run_dir / "config" / "RUN_CONFIG_LOCK.json")
    repo_root = run_dir.parent.parent
    profile = load_json(repo_root / lock["competition_profile"]["profile_path"])
    format_rules = profile.get(
        "format_audit",
        {
            "fonts_embedded_required": True,
            "keywords_required": False,
            "references_required": False,
            "citation_links_required": False,
            "min_image_dpi": 150,
        },
    )
    checks: list[dict[str, Any]] = []
    hard_failures: list[str] = []
    warnings: list[str] = list(profile.get("warnings", []))

    def add(check_id: str, passed: bool, details: str, *, hard: bool = True) -> None:
        checks.append({"check_id": check_id, "passed": passed, "hard": hard, "details": details})
        if hard and not passed:
            hard_failures.append(check_id)

    if not pdf.is_file():
        add("pdf-exists", False, f"PDF 不存在: {pdf}")
        page_count = 0
        page_sizes: list[dict[str, Any]] = []
        metrics = {"page_metrics": [], "minimum": {}, "body_sizes": {}, "caption_sizes": {}, "text": "", "page_texts": [], "image_dpi": [], "clipping": False, "overlap": False}
        font_resources: list[dict[str, Any]] = []
        fonts_embedded = False
        reader = None
    else:
        try:
            reader = PdfReader(str(pdf))
            page_count = len(reader.pages)
            page_sizes = []
            for page_number, page in enumerate(reader.pages, start=1):
                width = float(page.mediabox.width)
                height = float(page.mediabox.height)
                a4 = (abs(width - 595.276) <= 2 and abs(height - 841.89) <= 2) or (abs(width - 841.89) <= 2 and abs(height - 595.276) <= 2)
                page_sizes.append({"page": page_number, "width_pt": round(width, 3), "height_pt": round(height, 3), "a4": a4})
            add("pdf-open", True, "PDF 可打开")
            add("page-count", page_count > 0, f"页数: {page_count}")
            add("a4", all(item["a4"] for item in page_sizes), "所有页面为 A4" if page_sizes else "无页面", hard=bool(profile.get("a4_required", False)))
            metrics = _margin_and_text_metrics(pdf)
            font_resources, fonts_embedded = _font_resources(reader)
        except Exception as exc:
            add("pdf-open", False, f"PDF 审计失败: {exc}")
            page_count = 0
            page_sizes = []
            metrics = {"page_metrics": [], "minimum": {}, "body_sizes": {}, "caption_sizes": {}, "text": "", "page_texts": [], "image_dpi": [], "clipping": False, "overlap": False}
            font_resources = []
            fonts_embedded = False
            reader = None

    text = metrics["text"]
    first_page_text = metrics["page_texts"][0] if metrics["page_texts"] else ""
    summary = bool(re.search(r"摘要|abstract", first_page_text, re.IGNORECASE))
    keywords = bool(re.search(r"关键词|keywords", text, re.IGNORECASE))
    references = bool(re.search(r"参考文献|references", text, re.IGNORECASE))
    linked = False
    if reader is not None:
        for page in reader.pages:
            annotations = _deref(page.get("/Annots")) or []
            if any(_deref(item).get("/Subtype") == "/Link" for item in annotations):
                linked = True
                break
    anonymous = not any(term in text for term in _ANONYMOUS_TERMS)
    if reader is not None:
        metadata = reader.metadata or {}
        anonymous = anonymous and not str(metadata.get("/Author", "")).strip()
    required_margin = float(profile.get("page_margin_cm", 0.0))
    margin_tolerance = 0.1
    minimum = metrics["minimum"]
    margins_pass = bool(minimum) and all(value is not None and value >= required_margin - margin_tolerance for value in minimum.values())
    add("page-margins", margins_pass, f"测量最小页边距: {minimum}; 要求: {required_margin} cm; 测量容差: {margin_tolerance} cm", hard=required_margin > 0)
    add("summary-first-page", summary, "第一页检测到摘要/Abstract", hard=bool(profile.get("summary_first_page", False)))
    add("fonts-embedded", fonts_embedded, f"字体资源 {len(font_resources)} 个，嵌入={fonts_embedded}", hard=format_rules["fonts_embedded_required"])
    add("anonymous", anonymous, "未发现身份字段" if anonymous else "发现身份字段", hard=bool(profile.get("anonymous_required", False)))
    add("references", references, "检测到参考文献标题" if references else "未检测到参考文献标题", hard=format_rules["references_required"])
    add("citation-links", linked, "检测到 PDF 链接注释" if linked else "未检测到 PDF 链接注释", hard=format_rules["citation_links_required"])
    add("clipping", not metrics["clipping"], "未发现文字超出页面边界", hard=True)
    add("overlap", not metrics["overlap"], "未发现同一行文字框重叠", hard=True)
    min_dpi = float(format_rules["min_image_dpi"])
    low_dpi = [item for item in metrics["image_dpi"] if (item.get("dpi_x") or 0) < min_dpi or (item.get("dpi_y") or 0) < min_dpi]
    add("image-dpi", not low_dpi, f"图片 {len(metrics['image_dpi'])} 个，低于 {min_dpi} DPI: {len(low_dpi)}", hard=False)
    for required in profile.get("required_submission_files", []):
        add(f"submission-{required}", (run_dir / required).is_file(), f"提交文件: {required}")
    if format_rules["keywords_required"]:
        add("keywords", keywords, "检测到关键词", hard=True)
    else:
        add("keywords", keywords, "检测到关键词" if keywords else "未检测到关键词", hard=False)
    payload = {
        "schema_name": "format_audit",
        "schema_version": "2.0",
        "run_id": run_dir.name,
        "profile_id": profile["profile_id"],
        "final_pdf_path": pdf.relative_to(run_dir).as_posix() if pdf.is_relative_to(run_dir) else str(pdf),
        "final_pdf_sha256": sha256_file(pdf) if pdf.is_file() else "0" * 64,
        "page_count": page_count,
        "page_sizes": page_sizes,
        "file_size_bytes": pdf.stat().st_size if pdf.is_file() else 0,
        "measured_margins_cm": {"required_cm": required_margin, "tolerance_cm": margin_tolerance, "pages": metrics["page_metrics"], "minimum": minimum},
        "summary_on_first_page": summary,
        "keywords_present": keywords,
        "font_resources": font_resources,
        "fonts_embedded": fonts_embedded,
        "body_font_size_distribution": metrics["body_sizes"],
        "caption_font_size_distribution": metrics["caption_sizes"],
        "figure_numbering_complete": _numbering_complete(text, _FIGURE_RE),
        "table_numbering_complete": _numbering_complete(text, _TABLE_RE),
        "references_present": references,
        "citations_linked": linked,
        "image_dpi": metrics["image_dpi"],
        "clipping_detected": metrics["clipping"],
        "overlap_detected": metrics["overlap"],
        "anonymous_check": anonymous,
        "checks": checks,
        "hard_failures": sorted(set(hard_failures)),
        "warnings": warnings,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    require_valid(payload, "format_audit")
    if write:
        output = run_dir / "review" / "FORMAT_AUDIT.json"
        atomic_json(output, payload)
    return payload
