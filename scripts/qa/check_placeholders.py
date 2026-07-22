"""检查论文源文件和 PDF 文本中残留的占位符。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

PLACEHOLDER = re.compile(r"\b(?:TODO|TBD|PLACEHOLDER)\b|\{\{[^{}]+\}\}|<<[^<>]+>>", re.IGNORECASE)
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
            found = sorted(set(PLACEHOLDER.findall(path.read_text(encoding="utf-8", errors="replace"))))
            if found:
                matches[path.relative_to(paper_dir).as_posix()] = found
    return {"success": not matches, "matches": matches}
