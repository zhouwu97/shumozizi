"""检查论文中显式声明的关键指标是否与结果索引一致。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from shumozizi.simple.results import read_result_index

METRIC_REFERENCE = re.compile(r"\[\[metric:([A-Za-z0-9._-]+)\.([A-Za-z0-9._-]+)=([-+]?\d+(?:\.\d+)?)\]\]")


def check_numeric_consistency(run_dir: Path) -> dict[str, Any]:
    """比较 ``[[metric:result_id.metric=value]]`` 与真实执行指标。

    Args:
        run_dir: v3 运行目录。

    Returns:
        可复核的指标引用和不一致项。
    """
    results = {item["result_id"]: item for item in read_result_index(run_dir)["results"]}
    references: list[dict[str, Any]] = []
    inconsistent: list[dict[str, Any]] = []
    paper = run_dir / "paper"
    for path in sorted(item for item in paper.rglob("*") if item.suffix.lower() in {".typ", ".tex", ".md", ".txt"}):
        for result_id, metric, stated in METRIC_REFERENCE.findall(path.read_text(encoding="utf-8", errors="replace")):
            item = {"file": path.relative_to(run_dir).as_posix(), "result_id": result_id, "metric": metric, "stated": float(stated)}
            references.append(item)
            expected = results.get(result_id, {}).get("metrics", {}).get(metric)
            if not isinstance(expected, (int, float)) or abs(float(expected) - item["stated"]) > 1e-9:
                inconsistent.append({**item, "expected": expected})
    return {"success": not inconsistent, "references": references, "inconsistent": inconsistent}
