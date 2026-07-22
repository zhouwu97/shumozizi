"""检查论文显式结果引用是否指向仍可使用的 v3 结果。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from shumozizi.simple.results import read_result_index

RESULT_REFERENCE = re.compile(r"\[\[result:([A-Za-z0-9._-]+)\]\]")


def check_result_references(run_dir: Path) -> dict[str, Any]:
    """验证 ``[[result:<id>]]`` 仅引用 current 且可用于论文的结果。

    Args:
        run_dir: v3 运行目录。

    Returns:
        引用列表、失效引用和通过状态。
    """
    index = read_result_index(run_dir)
    results = {item["result_id"]: item for item in index["results"]}
    references: list[dict[str, str]] = []
    paper = run_dir / "paper"
    for path in sorted(item for item in paper.rglob("*") if item.suffix.lower() in {".typ", ".tex", ".md", ".txt"}):
        for result_id in RESULT_REFERENCE.findall(path.read_text(encoding="utf-8", errors="replace")):
            references.append({"file": path.relative_to(run_dir).as_posix(), "result_id": result_id})
    invalid = [
        reference
        for reference in references
        if reference["result_id"] not in results
        or results[reference["result_id"]]["status"] != "current"
        or not results[reference["result_id"]]["paper_allowed"]
    ]
    return {"success": not invalid, "references": references, "invalid": invalid}
