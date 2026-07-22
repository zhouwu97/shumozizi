"""检查论文源文件和 PDF 文本中残留的占位符。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from scripts.qa.provenance_markers import LEGACY_RENDERED_MARKER

PLACEHOLDER = re.compile(
    r"\b(?:TODO|TBD|PLACEHOLDER)\b|\{\{[^{}]+\}\}|<<[^<>]+>>",
    re.IGNORECASE,
)
TEXT_SUFFIXES = {".typ", ".tex", ".md", ".txt", ".csv"}


def check_placeholders(paper_dir: Path) -> dict[str, Any]:
    """扫描论文源文件中的通用占位符。

    Args:
        paper_dir: 论文目录。

    Returns:
        文件到占位符列表的映射和通过状态。
    """
    matches: dict[str, list[str]] = {}
    if paper_dir.is_dir():
        for path in sorted(item for item in paper_dir.rglob("*") if item.suffix.lower() in TEXT_SUFFIXES):
            content = path.read_text(encoding="utf-8", errors="replace")
            found = sorted(set(PLACEHOLDER.findall(content)))
            if LEGACY_RENDERED_MARKER.search(content):
                found.append("遗留可渲染追溯标记")
            if found:
                matches[path.relative_to(paper_dir).as_posix()] = found
    return {"success": not matches, "matches": matches}
