"""执行与竞赛论文无关的通用 PDF 机械检查。"""

from __future__ import annotations

import argparse
import json
import re
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
) -> dict[str, Any]:
    """检查 PDF 是否可打开、空白、裁切、重叠和重复编号。

    Args:
        path: 最终 PDF 路径。
        anonymous_required: 是否将身份信息视为硬错误。
        anonymous_terms: 需在 PDF 文本中禁止出现的姓名、学校或队伍标识。

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
    blank_pages: list[int] = []
    clipping_pages: list[int] = []
    overlap_pages: list[int] = []
    with pdfplumber.open(str(path)) as document:
        for number, page in enumerate(document.pages, start=1):
            chars = page.chars or []
            images = page.images or []
            if not (page.extract_text() or "").strip() and not chars and not images:
                blank_pages.append(number)
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
    text = "\n".join(texts)
    figure_duplicates = _duplicates(FIGURE_CAPTION_PATTERN.findall(text))
    table_duplicates = _duplicates(TABLE_CAPTION_PATTERN.findall(text))
    author = str((reader.metadata or {}).get("/Author", "")).strip()
    identity_terms = [term for term in anonymous_terms if term and term in text]
    check("blank-pages", not blank_pages, "未发现空白页" if not blank_pages else f"空白页: {blank_pages}")
    check("clipping", not clipping_pages, "未发现文字裁切" if not clipping_pages else f"疑似裁切页: {clipping_pages}")
    check("text-overlap", not overlap_pages, "未发现文字重叠" if not overlap_pages else f"疑似重叠页: {overlap_pages}")
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
    args = parser.parse_args()
    payload = audit_pdf(
        Path(args.pdf),
        anonymous_required=args.anonymous,
        anonymous_terms=tuple(args.anonymous_term),
    )

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
