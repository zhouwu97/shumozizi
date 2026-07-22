"""检查论文显式结果引用是否指向仍可使用的 v3 结果。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.qa.provenance_markers import RESULT_REFERENCE, paper_sources
from shumozizi.simple.results import read_result_index


def check_result_references(run_dir: Path) -> dict[str, Any]:
    """验证结果注释只引用 current 且执行事实有效的结果。

    Args:
        run_dir: v3 运行目录。

    Returns:
        引用列表、失效引用和通过状态。
    """
    index = read_result_index(run_dir)
    results = {item["result_id"]: item for item in index["results"]}
    references: list[dict[str, str]] = []
    for path in paper_sources(run_dir):
        for result_id in RESULT_REFERENCE.findall(path.read_text(encoding="utf-8", errors="replace")):
            references.append({"file": path.relative_to(run_dir).as_posix(), "result_id": result_id})
    invalid = [
        reference
        for reference in references
        if reference["result_id"] not in results
        or results[reference["result_id"]]["status"] != "current"
        or not results[reference["result_id"]]["execution_valid"]
    ]
    return {"success": not invalid, "references": references, "invalid": invalid}
