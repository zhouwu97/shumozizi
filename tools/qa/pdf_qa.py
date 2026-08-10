"""执行与竞赛论文无关的通用 PDF 机械检查。"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import pdfplumber
from pypdf import PdfReader

FIGURE_CAPTION_PATTERN = re.compile(
    r"^\s*(?:图|Figure)\s*(\d+)\s*(?::|：|\.|—|-|\s{2,})\S",
    re.IGNORECASE | re.MULTILINE,
)
TABLE_CAPTION_PATTERN = re.compile(
    r"^\s*(?:表|Table)\s*(\d+)\s*(?::|：|\.|—|-|\s{2,})\S",
    re.IGNORECASE | re.MULTILINE,
)
LEGACY_PROVENANCE_MARKER = re.compile(r"\[\[(?:result|metric):", re.IGNORECASE)
MIN_BODY_FONT_SAMPLE_CHARACTERS = 600
MAX_DOMINANT_BODY_FONT_SIZE = 14.0
MIN_SPARSE_PAGE_CHARACTERS = 120
FOOTER_AREA_RATIO = 0.14
FOOTER_NUMBER_PATTERN = re.compile(r"(?<!\d)(\d{1,5})(?!\d)")


def _render_with_pymupdf(path: Path, expected_pages: int) -> dict[str, Any]:
    """用 PyMuPDF 实际渲染所有页面，补足仅解析文本的盲区。

    Args:
        path: 待渲染 PDF。
        expected_pages: 由独立读取器得到的页数。

    Returns:
        渲染器可用性、通过状态及页面数。
    """
    try:
        import fitz
    except ImportError:
        return {
            "available": False,
            "passed": False,
            "details": "PyMuPDF 不可用，无法执行第二渲染器抽查",
        }
    try:
        document = fitz.open(path)
        rendered = 0
        for page in document:
            # 低 DPI 足以暴露缺页、损坏资源或页面裁切，避免机械 QA 消耗过多时间。
            pixmap = page.get_pixmap(matrix=fitz.Matrix(0.25, 0.25), alpha=False)
            if pixmap.width <= 0 or pixmap.height <= 0:
                raise ValueError(f"第 {rendered + 1} 页渲染尺寸非法")
            rendered += 1
        document.close()
    except Exception as exc:
        return {
            "available": True,
            "passed": False,
            "details": f"PyMuPDF 渲染失败: {exc}",
        }
    return {
        "available": True,
        "passed": rendered == expected_pages,
        "details": (
            f"PyMuPDF 已渲染 {rendered} 页"
            if rendered == expected_pages
            else f"PyMuPDF 页数 {rendered} 与读取器页数 {expected_pages} 不一致"
        ),
        "page_count": rendered,
    }


def _render_with_poppler(path: Path, expected_pages: int) -> dict[str, Any]:
    """通过 Poppler 的 ``pdftoppm`` 复验每页可由另一渲染器输出。

    Args:
        path: 待渲染 PDF。
        expected_pages: 由独立读取器得到的页数。

    Returns:
        渲染器可用性、通过状态及页面数。
    """
    # 优先使用直接可执行的 pdftocairo。某些 Windows 运行时会把 pdftoppm
    # 暴露为失效的 .cmd 转发器；两者同属 Poppler，输出都可逐页交叉复验。
    executable = shutil.which("pdftocairo") or shutil.which("pdftoppm")
    if executable is None:
        return {
            "available": False,
            "passed": False,
            "details": "未找到 pdftocairo/pdftoppm，无法执行 Poppler 渲染复验",
        }
    try:
        with tempfile.TemporaryDirectory(prefix="shumozizi-pdf-qa-") as temporary:
            prefix = Path(temporary) / "page"
            arguments = [executable, "-png", "-r", "72", str(path), str(prefix)]
            if os.name == "nt" and Path(executable).suffix.casefold() in {".cmd", ".bat"}:
                # Windows 的运行时包装器可能是 .cmd；直接 shell=False 无法启动它。
                # list2cmdline 保留每个已验证参数的边界，避免把路径拼成不受控命令。
                arguments = [
                    "cmd.exe",
                    "/d",
                    "/s",
                    "/c",
                    subprocess.list2cmdline(arguments),
                ]
            completed = subprocess.run(
                arguments,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                check=False,
            )
            if completed.returncode != 0:
                detail = completed.stderr.strip() or completed.stdout.strip()
                raise RuntimeError(detail or f"退出码 {completed.returncode}")
            rendered = len(list(Path(temporary).glob("page-*.png")))
    except Exception as exc:
        return {
            "available": True,
            "passed": False,
            "details": f"Poppler 渲染失败: {exc}",
        }
    return {
        "available": True,
        "passed": rendered == expected_pages,
        "details": (
            f"Poppler 已渲染 {rendered} 页"
            if rendered == expected_pages
            else f"Poppler 页数 {rendered} 与读取器页数 {expected_pages} 不一致"
        ),
        "page_count": rendered,
    }


def _footer_text(page: Any) -> str:
    """提取页面底部区域文字，用于发现页码缺位或截断。

    该检查只处理 PDF 可抽取的文本层，不能代替对字体栅格化异常的人工看图。
    """
    footer = page.crop(
        (0, float(page.height) * (1 - FOOTER_AREA_RATIO), float(page.width), float(page.height))
    )
    return re.sub(r"\s+", " ", footer.extract_text() or "").strip()


def _footer_numbering_report(footer_texts: list[str]) -> dict[str, Any]:
    """从页脚数值中推断连续页码，避免把页数一致误判为页码完整。"""
    numeric_tokens = [
        [int(value) for value in FOOTER_NUMBER_PATTERN.findall(text)] for text in footer_texts
    ]
    page_count = len(footer_texts)
    pages_with_numbers = [index + 1 for index, values in enumerate(numeric_tokens) if values]
    base = {
        "footer_texts": footer_texts,
        "page_number_candidates": numeric_tokens,
        "pages_with_numbers": pages_with_numbers,
    }
    if not pages_with_numbers:
        return {
            **base,
            "status": "not_detected",
            "passed": False,
            "blocking": False,
            "details": "未在页脚文字层检测到页码；需要人工关键页看图确认",
        }
    if len(pages_with_numbers) != page_count:
        missing = [index + 1 for index, values in enumerate(numeric_tokens) if not values]
        return {
            **base,
            "status": "incomplete",
            "passed": False,
            "blocking": False,
            "details": f"仅在页 {pages_with_numbers} 检到页脚数字，缺失页: {missing}；需要人工复核",
        }

    # 对 "Page 1 of 20" 等多数字页脚，寻找覆盖最多页面的 ``显示页码 - PDF 页序``
    # 偏移量。它允许前置封面或正文从非 1 页开始，同时能识别 15 被渲染为 5 这种断裂。
    offsets = Counter(
        value - page_number
        for page_number, values in enumerate(numeric_tokens, start=1)
        for value in values
    )
    offset, coverage = offsets.most_common(1)[0]
    expected = [page_number + offset for page_number in range(1, page_count + 1)]
    mismatches = [
        page_number
        for page_number, (values, expected_value) in enumerate(
            zip(numeric_tokens, expected, strict=True), start=1
        )
        if expected_value not in values
    ]
    one_number_per_page = all(len(values) == 1 for values in numeric_tokens)
    one_number_values = [values[0] for values in numeric_tokens] if one_number_per_page else []
    if one_number_per_page and len(set(one_number_values)) == 1:
        return {
            **base,
            "status": "ambiguous",
            "passed": False,
            "blocking": False,
            "details": "页脚数字在各页相同，无法确认其为连续页码；需要人工复核",
        }
    if not mismatches:
        return {
            **base,
            "status": "continuous",
            "passed": True,
            "blocking": False,
            "details": f"检测到连续页码，起始偏移量: {offset}",
            "offset": offset,
        }
    # 至少两页支持同一偏移时，序列可被可靠识别；此时缺页或前导数字丢失是硬异常。
    if coverage >= 2 or one_number_per_page:
        return {
            **base,
            "status": "discontinuous",
            "passed": False,
            "blocking": True,
            "details": f"页脚页码序列不连续，疑似异常页: {mismatches}",
            "offset": offset,
            "mismatched_pages": mismatches,
        }
    return {
        **base,
        "status": "ambiguous",
        "passed": False,
        "blocking": False,
        "details": "页脚含多个非连续数字，无法自动判定页码；需要人工复核",
    }


def _render_critical_pages(
    path: Path, *, pages: list[int], output_dir: Path | None
) -> dict[str, Any]:
    """可选导出关键页 PNG，供人眼检查字体、裁切和跨渲染器差异。"""
    if output_dir is None or not pages:
        return {"requested": bool(pages), "rendered_files": [], "details": "未请求关键页导出"}
    try:
        import fitz
    except ImportError:
        return {
            "requested": True,
            "rendered_files": [],
            "details": "PyMuPDF 不可用，无法导出关键页供人工复核",
        }
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered_files: list[str] = []
    try:
        document = fitz.open(path)
        for number in pages:
            pixmap = document[number - 1].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            target = output_dir / f"page-{number:03d}.png"
            pixmap.save(str(target))
            rendered_files.append(str(target))
        document.close()
    except Exception as exc:
        return {
            "requested": True,
            "rendered_files": rendered_files,
            "details": f"关键页导出失败: {exc}",
        }
    return {
        "requested": True,
        "rendered_files": rendered_files,
        "details": f"已导出 {len(rendered_files)} 个关键页 PNG，仍需人工看图确认",
    }


def _duplicates(values: list[str]) -> list[int]:
    """返回重复编号。

    Args:
        values: 匹配到的编号字符串。

    Returns:
        去重后的重复整数编号。
    """
    seen: set[int] = set()
    repeated: set[int] = set()
    for value in values:
        numeric = int(value)
        if numeric in seen:
            repeated.add(numeric)
        seen.add(numeric)
    return sorted(repeated)


def audit_pdf(
    path: Path,
    *,
    anonymous_required: bool = False,
    anonymous_terms: tuple[str, ...] = (),
    critical_pages: tuple[int, ...] = (),
    manual_critical_review_confirmed: bool = False,
    critical_page_output_dir: Path | None = None,
) -> dict[str, Any]:
    """检查 PDF 是否可打开、空白、裁切、重叠和重复编号。

    Args:
        path: 最终 PDF 路径。
        anonymous_required: 是否将身份信息视为硬错误。
        anonymous_terms: 需在 PDF 文本中禁止出现的姓名、学校或队伍标识。
        critical_pages: 需要人眼复核的物理页码；指定后必须显式确认已看图。
        manual_critical_review_confirmed: 已完成关键页人工看图时为真。
        critical_page_output_dir: 可选关键页 PNG 导出目录。

    Returns:
        机械检查明细；该函数不评价模型或结论质量。
    """
    checks: list[dict[str, Any]] = []

    def check(
        check_id: str, passed: bool, details: str, *, blocking: bool = True
    ) -> None:
        checks.append(
            {"id": check_id, "passed": passed, "details": details, "blocking": blocking}
        )

    if not path.is_file():
        check("pdf-exists", False, f"PDF 不存在: {path}")
        return {"pdf": str(path), "checks": checks, "text": "", "success": False}
    try:
        reader = PdfReader(str(path))
        check("pdf-open", True, "PDF 可打开")
    except Exception as exc:
        check("pdf-open", False, f"PDF 无法打开: {exc}")
        return {"pdf": str(path), "checks": checks, "text": "", "success": False}
    texts = [page.extract_text() or "" for page in reader.pages]
    check("page-count", bool(reader.pages), f"页数: {len(reader.pages)}")
    pymupdf_render = _render_with_pymupdf(path, len(reader.pages))
    poppler_render = _render_with_poppler(path, len(reader.pages))
    check(
        "renderer-pymupdf",
        bool(pymupdf_render["passed"]),
        str(pymupdf_render["details"]),
        blocking=bool(pymupdf_render["available"]),
    )
    check(
        "renderer-poppler",
        bool(poppler_render["passed"]),
        str(poppler_render["details"]),
        blocking=bool(poppler_render["available"]),
    )
    dual_available = bool(pymupdf_render["available"] and poppler_render["available"])
    check(
        "dual-renderer",
        bool(pymupdf_render["passed"] and poppler_render["passed"]),
        (
            "PyMuPDF 与 Poppler 均完成全页渲染"
            if dual_available
            else "缺少一套 PDF 渲染器；已保留为环境告警，不能替代人工抽查"
        ),
        # 环境缺工具时不把机械格式问题伪装成科学阻断；已安装却渲染失败则由
        # 对应 renderer 检查阻断。
        blocking=False,
    )
    blank_pages: list[int] = []
    clipping_pages: list[int] = []
    overlap_pages: list[int] = []
    sparse_pages: list[int] = []
    footer_texts: list[str] = []
    font_sizes: Counter[float] = Counter()
    with pdfplumber.open(str(path)) as document:
        for number, page in enumerate(document.pages, start=1):
            footer_texts.append(_footer_text(page))
            chars = page.chars or []
            images = page.images or []
            visible_chars = [
                char for char in chars if str(char.get("text", "")).strip()
            ]
            for char in visible_chars:
                size = round(float(char.get("size", 0.0)) * 2) / 2
                if size > 0:
                    font_sizes[size] += 1
            if not (page.extract_text() or "").strip() and not chars and not images:
                blank_pages.append(number)
            elif len(visible_chars) < MIN_SPARSE_PAGE_CHARACTERS and not images:
                sparse_pages.append(number)
            for char in chars:
                if (
                    float(char["x0"]) < -0.1
                    or float(char["x1"]) > float(page.width) + 0.1
                    or float(char["top"]) < -0.1
                    or float(char["bottom"]) > float(page.height) + 0.1
                ):
                    clipping_pages.append(number)
                    break
            words = page.extract_words() or []
            for index, first in enumerate(words):
                if any(
                    abs(float(first["top"]) - float(second["top"])) < 0.8
                    and min(float(first["x1"]), float(second["x1"]))
                    - max(float(first["x0"]), float(second["x0"]))
                    > 0.5
                    for second in words[index + 1 :]
                ):
                    overlap_pages.append(number)
                    break
    footer_numbering = _footer_numbering_report(footer_texts)
    check(
        "page-number-continuity",
        bool(footer_numbering["passed"]),
        str(footer_numbering["details"]),
        blocking=bool(footer_numbering["blocking"]),
    )
    requested_critical_pages = sorted(set(critical_pages))
    invalid_critical_pages = [
        number for number in requested_critical_pages if number < 1 or number > len(reader.pages)
    ]
    valid_critical_pages = [
        number for number in requested_critical_pages if number not in invalid_critical_pages
    ]
    critical_rendering = _render_critical_pages(
        path,
        pages=valid_critical_pages,
        output_dir=critical_page_output_dir,
    )
    if invalid_critical_pages:
        check(
            "manual-critical-page-review",
            False,
            f"关键页超出 PDF 页数: {invalid_critical_pages}",
        )
    elif valid_critical_pages:
        check(
            "manual-critical-page-review",
            manual_critical_review_confirmed,
            (
                f"已确认人工查看关键页: {valid_critical_pages}"
                if manual_critical_review_confirmed
                else f"关键页 {valid_critical_pages} 必须导出并人工看图后再确认"
            ),
        )
    else:
        check(
            "manual-critical-page-review",
            True,
            "未指定关键页；自动 QA 不能证明所有字形和布局在每个 renderer 中一致",
            blocking=False,
        )
    text = "\n".join(texts)
    figure_duplicates = _duplicates(FIGURE_CAPTION_PATTERN.findall(text))
    table_duplicates = _duplicates(TABLE_CAPTION_PATTERN.findall(text))
    author = str((reader.metadata or {}).get("/Author", "")).strip()
    identity_terms = [term for term in anonymous_terms if term and term in text]
    check("blank-pages", not blank_pages, "未发现空白页" if not blank_pages else f"空白页: {blank_pages}")
    check("clipping", not clipping_pages, "未发现文字裁切" if not clipping_pages else f"疑似裁切页: {clipping_pages}")
    check("text-overlap", not overlap_pages, "未发现文字重叠" if not overlap_pages else f"疑似重叠页: {overlap_pages}")
    dominant_font_size = None
    dominant_font_count = 0
    if font_sizes:
        dominant_font_size, dominant_font_count = font_sizes.most_common(1)[0]
    font_sample_sufficient = dominant_font_count >= MIN_BODY_FONT_SAMPLE_CHARACTERS
    font_size_passed = bool(
        not font_sample_sufficient
        or dominant_font_size is None
        or dominant_font_size <= MAX_DOMINANT_BODY_FONT_SIZE
    )
    if not font_sample_sufficient:
        font_details = "正文字符样本不足，主字号交由 PDF 盲审判断"
    elif font_size_passed:
        font_details = f"正文主字号约 {dominant_font_size:g} pt"
    else:
        font_details = (
            f"正文主字号约 {dominant_font_size:g} pt，超过 "
            f"{MAX_DOMINANT_BODY_FONT_SIZE:g} pt 可读性上限"
        )
    check("body-font-size", font_size_passed, font_details)
    check(
        "sparse-content-pages",
        not sparse_pages,
        "未发现稀疏内容页" if not sparse_pages else f"疑似稀疏内容页: {sparse_pages}",
        blocking=False,
    )
    check(
        "figure-numbering",
        not figure_duplicates,
        "图注编号无重复" if not figure_duplicates else f"疑似重复图注编号: {figure_duplicates}",
        blocking=False,
    )
    check(
        "table-numbering",
        not table_duplicates,
        "表题编号无重复" if not table_duplicates else f"疑似重复表题编号: {table_duplicates}",
        blocking=False,
    )
    anonymous_passed = not anonymous_required or (not author and not identity_terms)
    anonymous_details = "匿名检查未启用"
    if anonymous_required:
        anonymous_details = "匿名检查通过"
        if author:
            anonymous_details = f"PDF 元数据包含作者: {author}"
        elif identity_terms:
            anonymous_details = f"PDF 正文包含身份词: {', '.join(identity_terms)}"
    check("anonymous", anonymous_passed, anonymous_details, blocking=anonymous_required)
    check(
        "rendered-provenance-markers",
        not LEGACY_PROVENANCE_MARKER.search(text),
        "未发现可渲染追溯标记"
        if not LEGACY_PROVENANCE_MARKER.search(text)
        else "PDF 中发现 [[result: 或 [[metric: 标记",
    )
    return {
        "pdf": str(path),
        "checks": checks,
        "text": text,
        "success": all(item["passed"] or not item["blocking"] for item in checks),
        "warnings": [item for item in checks if not item["passed"] and not item["blocking"]],
        "renderers": {"pymupdf": pymupdf_render, "poppler": poppler_render},
        "footer_numbering": footer_numbering,
        "critical_page_rendering": critical_rendering,
        "mechanical_limits": [
            "双渲染器检查确认每页可由两个引擎栅格化，不进行逐像素等价证明。",
            "页脚检查只覆盖可抽取文本层；字体缺字、抗锯齿差异和复杂图形裁切仍须人工看图。",
            "对已知风险页应传入 critical_pages，导出 PNG 后再以 manual_critical_review_confirmed 明确记录人工复核。",
        ],
    }


def main() -> int:
    """提供 PDF QA 命令行入口。

    Returns:
        没有硬错误时为零。
    """
    parser = argparse.ArgumentParser(description="执行基础 PDF 机械 QA")
    parser.add_argument("pdf")
    parser.add_argument("--anonymous", action="store_true")
    parser.add_argument("--anonymous-term", action="append", default=[])
    parser.add_argument("--critical-page", type=int, action="append", default=[])
    parser.add_argument("--critical-page-output-dir", type=Path)
    parser.add_argument("--manual-critical-review-confirmed", action="store_true")
    args = parser.parse_args()
    payload = audit_pdf(
        Path(args.pdf),
        anonymous_required=args.anonymous,
        anonymous_terms=tuple(args.anonymous_term),
        critical_pages=tuple(args.critical_page),
        manual_critical_review_confirmed=args.manual_critical_review_confirmed,
        critical_page_output_dir=args.critical_page_output_dir,
    )

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
