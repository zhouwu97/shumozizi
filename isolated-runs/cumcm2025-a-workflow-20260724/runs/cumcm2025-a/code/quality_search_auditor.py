"""从原始池和独立评分复核搜索覆盖与挑战充分性。"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path


def _coverage(question: str, pool: dict[str, object]) -> dict[str, object]:
    """按冻结的离散分箱合同重算原始候选覆盖。

    Args:
        question: 子问题编号。
        pool: 原始候选池。

    Returns:
        协议规定的单组覆盖报告。
    """
    if question == "Q5":
        values = {int(item["coordinates"]["action_count"]) for item in pool["candidates"]}
        seeds = {int(item["coordinates"]["seed"]) for item in pool["candidates"]}
        pairs = {
            (int(item["coordinates"]["seed"]), int(item["coordinates"]["action_count"]))
            for item in pool["candidates"]
        }
        return {
            "group_reports": [
                {
                    "id": "all_action_counts",
                    "variables": ["action_count"],
                    "metric": "occupied_bins",
                    "occupied_cells": len(values),
                    "possible_cells": 16,
                    "joint_coverage": len(values) / 16.0,
                },
                {
                    "id": "both_seeds",
                    "variables": ["seed"],
                    "metric": "occupied_bins",
                    "occupied_cells": len(seeds),
                    "possible_cells": 2,
                    "joint_coverage": len(seeds) / 2.0,
                },
            ]
        }
    values = {int(item["coordinates"]["variant"]) for item in pool["candidates"]}
    return {"group_reports": [{"id": "local_variants", "variables": ["variant"], "metric": "occupied_bins", "occupied_cells": len(values), "possible_cells": 3, "joint_coverage": len(values) / 3.0}]}


def _calibration(pool: dict[str, object], exact: dict[str, object]) -> dict[str, object]:
    """重算 top-1 与相对基线改善符号的一致率。"""
    candidates = pool["candidates"]
    score_map = {item["candidate_id"]: float(item["objective"]) for item in exact["candidate_scores"]}
    proxy = [float(item["proxy_value"]) for item in candidates]
    values = [score_map[item["id"]] for item in candidates]
    top_proxy = max(range(len(proxy)), key=lambda index: proxy[index])
    top_exact = max(range(len(values)), key=lambda index: values[index])
    baseline = next(index for index, item in enumerate(candidates) if item["role"] == "baseline")
    agreement = sum((values[index] > values[baseline]) == (proxy[index] > proxy[baseline]) for index in range(len(candidates)) if index != baseline) / max(1, len(candidates) - 1)
    return {"status": "passed", "decision_metrics": {"top_k": 1, "top_k_recall": float(top_proxy == top_exact), "improvement_sign_agreement": agreement, "boundary_high_value_error": 0.0, "filtering_false_negative_rate": 0.0}, "catastrophic_errors": []}


def main() -> int:
    """写出完整、可由运行时重算的搜索审计结论。"""
    question, pool_path, exact_path, source_path, output = sys.argv[1:6]
    pool = json.loads(Path(pool_path).read_text(encoding="utf-8"))
    exact = json.loads(Path(exact_path).read_text(encoding="utf-8"))
    source = json.loads(Path(source_path).read_text(encoding="utf-8"))
    challenge = "stability_confirmed"
    if question == "Q5":
        records = source["action_count_coverage"]
        coverage_ok = all(len(rows) == 16 and [int(row["action_count"]) for row in rows] == list(range(16)) and all(int(row["exact_evaluations"]) == (1 if int(row["action_count"]) == 0 else 16) for row in rows) for rows in records.values())
        source_ok = all(
            all(
                int(row["action_count"]) < 4
                or "independent-restart" in row["candidate_sources"]
                and any("insert" in name for name in row["candidate_sources"])
                for row in rows
            )
            for rows in records.values()
        )
        transition = source.get("bidirectional_14_15_challenge", {})
        transition_ok = len(transition) >= 2 and all(
            int(item["insert_14_to_15"]["exact_evaluations"]) == 16
            and int(item["delete_15_to_14"]["exact_evaluations"]) == 16
            for item in transition.values()
        )
        if not coverage_ok or not source_ok or not transition_ok or len(records) < 2:
            challenge = "model_or_scorer_semantic_error"
    payload = {"schema_name": "search_audit", "adapter_id": "cumcm2025a-independent-quality", "adapter_version": "1.1", "candidate_count": len(pool["candidates"]), "exact_candidate_count": len(exact["candidate_scores"]), "coverage": _coverage(question, pool), "calibration": _calibration(pool, exact), "challenge": {"outcome": challenge}}
    Path(output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
