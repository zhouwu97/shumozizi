"""汇总 Competition-First 评测的过程指标，不把过程数据解释为竞赛成绩。"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """按工作流汇总可审计的过程指标。

    Args:
        records: 每条记录至少含 workflow 和任意数值指标的数组。

    Returns:
        各工作流的计数、数值均值和缺失指标说明。
    """
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        workflow = record.get("workflow")
        if isinstance(workflow, str) and workflow:
            groups[workflow].append(record)
    summary: dict[str, Any] = {}
    for workflow, items in groups.items():
        numeric: dict[str, list[float]] = defaultdict(list)
        for item in items:
            for key, value in item.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    numeric[key].append(float(value))
        summary[workflow] = {
            "run_count": len(items),
            "means": {key: sum(values) / len(values) for key, values in sorted(numeric.items())},
        }
    return {"schema_version": "1.0", "workflows": summary}


def main() -> int:
    """读取 JSON 记录并输出过程指标摘要。"""
    parser = argparse.ArgumentParser(description="汇总 Competition-First 过程指标")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    records = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise SystemExit("input 必须是 JSON 数组")
    payload = summarize(records)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8", newline="\n")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
