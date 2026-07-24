"""生成质量协议所需的原始候选池，不输出任何质量结论。"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _read(path: str) -> dict[str, object]:
    """读取当前运行已冻结的主结果。

    Args:
        path: 主结果的相对 JSON 路径。

    Returns:
        解析后的结果对象。
    """
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    """构造基线、主解和受控扰动的完整候选轨迹。"""
    question, source, output = sys.argv[1:4]
    document = _read(source)
    if question == "Q5":
        records = document["action_count_coverage"][str(document["selected_seed"])]
        candidates = []
        for row in records:
            count = float(row["action_count"])
            candidates.append(
                {
                    "id": f"count_{int(count)}",
                    "coordinates": {"action_count": count},
                    "parameters": {"action_count": count},
                    "proxy_value": float(row["objective_missile_s"]),
                    "role": "baseline" if count == 0 else "search",
                }
            )
    else:
        primary = float(document["metrics"]["duration_s"])
        candidates = [
            {"id": "baseline", "coordinates": {"variant": 0.0}, "parameters": {"variant": 0.0}, "proxy_value": 0.0, "role": "baseline"},
            {"id": "selected", "coordinates": {"variant": 1.0}, "parameters": {"variant": 1.0}, "proxy_value": primary, "role": "warm_start"},
            {"id": "perturbed", "coordinates": {"variant": 2.0}, "parameters": {"variant": 2.0}, "proxy_value": primary * 0.85, "role": "exploration"},
        ]
    payload = {
        "schema_name": "candidate_generation",
        "adapter_id": "cumcm2025a-independent-quality",
        "adapter_version": "1.0",
        "candidate_variables": ["action_count"] if question == "Q5" else ["variant"],
        "candidates": candidates,
        "search_trace": [
            {"step": index, "candidate_id": item["id"], "event": "action_count_challenge" if question == "Q5" else "baseline_or_local_challenge"}
            for index, item in enumerate(candidates)
        ],
    }
    Path(output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
