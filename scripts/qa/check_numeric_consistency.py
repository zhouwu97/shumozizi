"""检查论文中显式声明的关键指标是否与结果索引一致。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.qa.check_result_references import check_result_references
from scripts.qa.provenance_markers import METRIC_REFERENCE, paper_sources
from shumozizi.simple.quality import quality_allows_paper
from shumozizi.simple.results import read_result_index


def check_numeric_consistency(run_dir: Path) -> dict[str, Any]:
    """比较论文指标注释与真实执行输出中的指标。

    Args:
        run_dir: v3 运行目录。

    Returns:
        可复核的指标引用和不一致项。
    """
    results = {item["result_id"]: item for item in read_result_index(run_dir)["results"]}
    references: list[dict[str, Any]] = []
    inconsistent: list[dict[str, Any]] = []
    for path in paper_sources(run_dir):
        for result_id, metric, stated in METRIC_REFERENCE.findall(path.read_text(encoding="utf-8", errors="replace")):
            item = {"file": path.relative_to(run_dir).as_posix(), "result_id": result_id, "metric": metric, "stated": float(stated)}
            references.append(item)
            result = results.get(result_id)
            expected = result.get("metrics", {}).get(metric) if result else None
            if (
                result is None
                or result["status"] != "current"
                or not result["execution_valid"]
                or not quality_allows_paper(run_dir, result_id)
            ):
                inconsistent.append(
                    {
                        **item,
                        "expected": expected,
                        "reason": "指标引用的结果不是 current 且 execution_valid=true",
                    }
                )
                continue
            if not isinstance(expected, (int, float)) or abs(float(expected) - item["stated"]) > 1e-9:
                inconsistent.append({**item, "expected": expected})
    result_reference_report = check_result_references(run_dir)
    metric_result_ids = {item["result_id"] for item in references}
    missing_question_metrics: list[str] = []
    for question_id, evidence_ids in result_reference_report[
        "question_evidence_requirements"
    ].items():
        numeric_evidence = any(
            isinstance(result, dict)
            and any(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in result.get("metrics", {}).values()
            )
            for result_id in evidence_ids
            for result in [results.get(result_id)]
        )
        if numeric_evidence and not (metric_result_ids & set(evidence_ids)):
            missing_question_metrics.append(question_id)
    return {
        "success": not inconsistent and not missing_question_metrics,
        "references": references,
        "inconsistent": inconsistent,
        "missing_question_metrics": sorted(missing_question_metrics),
    }
