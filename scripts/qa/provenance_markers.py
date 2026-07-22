"""解析不会渲染到最终论文中的 v3 结果与指标注释。"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

TEXT_SUFFIXES = {".typ", ".tex", ".md", ".txt"}
RESULT_REFERENCE = re.compile(
    r"(?:^\s*(?://|%)\s*@result\s+|<!--\s*@result\s+)([A-Za-z0-9._-]+)(?:\s*-->)?\s*$",
    re.MULTILINE,
)
METRIC_REFERENCE = re.compile(
    r"(?:^\s*(?://|%)\s*@metric\s+|<!--\s*@metric\s+)"
    r"([A-Za-z0-9._-]+)\.([A-Za-z0-9_-]+)\s+([-+]?\d+(?:\.\d+)?)(?:\s*-->)?\s*$",
    re.MULTILINE,
)
LEGACY_RENDERED_MARKER = re.compile(r"\[\[(?:result|metric):", re.IGNORECASE)


def paper_sources(run_dir: Path) -> Iterator[Path]:
    """遍历可包含论文追溯注释的源文件。

    Args:
        run_dir: v3 运行目录。

    Yields:
        论文目录中的文本源文件。
    """
    paper = run_dir / "paper"
    if paper.is_dir():
        yield from sorted(
            item for item in paper.rglob("*") if item.suffix.lower() in TEXT_SUFFIXES
        )
