"""检查论文显式结果引用是否指向仍可使用的 v3 结果。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.qa.provenance_markers import RESULT_REFERENCE, paper_sources
from shumozizi.simple.quality import quality_allows_paper
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import read_simple_state


def check_result_references(run_dir: Path) -> dict[str, Any]:
    """验证结果注释只引用 current 且执行事实有效的结果。

    Args:
        run_dir: v3 运行目录。

    Returns:
        引用列表、失效引用和通过状态。
    """
    state = read_simple_state(run_dir)
    index = read_result_index(run_dir)
    results = {item["result_id"]: item for item in index["results"]}
    references: list[dict[str, str]] = []
    for path in paper_sources(run_dir):
        for result_id in RESULT_REFERENCE.findall(path.read_text(encoding="utf-8", errors="replace")):
            references.append({"file": path.relative_to(run_dir).as_posix(), "result_id": result_id})
    invalid: list[dict[str, str]] = []
    for reference in references:
        result = results.get(reference["result_id"])
        reason = None
        if state["phase"] == "blocked":
            reason = "运行处于 blocked 状态"
        elif result is None:
            reason = "结果不存在"
        elif result["status"] != "current" or not result["execution_valid"]:
            reason = "结果不是 current 且 execution_valid=true"
        elif not quality_allows_paper(run_dir, reference["result_id"]):
            reason = "结果未通过质量层放行"
        if reason is not None:
            invalid.append({**reference, "reason": reason})
    return {"success": not invalid, "references": references, "invalid": invalid}
