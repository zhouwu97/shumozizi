"""用有限圆柱连续评分器独立复算质量候选。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from model_core import Action, cylinder_surface_samples, score_solution, validate_drone_schedule


def _actions(document: dict[str, object]) -> list[Action]:
    """由主结果中的物理参数重建动作，避免读取其已算出的时长。

    Args:
        document: 含 ``result.actions`` 的主结果。

    Returns:
        可交给统一 scorer 的动作列表。
    """
    return [
        Action(
            str(item["drone"]), float(item["heading_deg"]), float(item["speed_mps"]),
            float(item["release_time_s"]), float(item["fuse_delay_s"]), str(item["assigned_missile"]),
        )
        for item in document["result"]["actions"]
    ]


def _actions_from_q5(source: dict[str, object], parameters: dict[str, object]) -> list[Action]:
    """按 seed 和动作数从 Q5 原始覆盖记录恢复动作，不读取其目标值。"""

    seed = str(int(float(parameters["seed"])))
    count = int(float(parameters["action_count"]))
    row = next(
        item
        for item in source["action_count_coverage"][seed]
        if int(item["action_count"]) == count
    )
    return [
        Action(
            str(item["drone"]),
            float(item["heading_deg"]),
            float(item["speed_mps"]),
            float(item["release_time_s"]),
            float(item["fuse_delay_s"]),
            str(item["assigned_missile"]),
        )
        for item in row["actions"]
    ]


def _value(question: str, identifier: str, document: dict[str, object]) -> tuple[float, bool, list[str]]:
    """对一个候选执行可行性检查和连续精确评分。

    Args:
        question: 子问题编号。
        identifier: 原始候选编号。
        document: 对应主结果。

    Returns:
        目标值、可行性和约束违反列表。
    """
    if identifier == "baseline":
        return 0.0, True, []
    actions = _actions(document)
    if identifier == "perturbed":
        actions = actions[:-1] if len(actions) > 1 else [Action("FY1", 165.0, 120.0, 1.5, 3.6, "M1")]
    errors = validate_drone_schedule(actions)
    missiles = ("M1",)
    result = score_solution(
        actions,
        missiles,
        cylinder_surface_samples(72, 9, 5),
        temporal_tolerance=0.0002,
    )
    return float(result["objective_missile_s"]), not errors, errors


def main() -> int:
    """读取原始候选池并输出全部候选的独立 exact 评分。"""
    question, pool_path, source_path, output = sys.argv[1:5]
    pool = json.loads(Path(pool_path).read_text(encoding="utf-8"))
    source = json.loads(Path(source_path).read_text(encoding="utf-8"))
    scores = []
    for item in pool["candidates"]:
        if question == "Q5":
            actions = _actions_from_q5(source, item["parameters"])
            errors = validate_drone_schedule(actions)
            result = score_solution(
                actions,
                ("M1", "M2", "M3"),
                cylinder_surface_samples(72, 9, 5),
                temporal_tolerance=0.001,
            )
            value, feasible = float(result["objective_missile_s"]), not errors
        else:
            value, feasible, errors = _value(question, str(item["id"]), source)
        scores.append({"candidate_id": item["id"], "feasible": feasible, "objective": value, "constraint_violations": errors})
    selected_id = (
        f"seed_{source['selected_seed']}_count_{int(source['selected_action_count'])}"
        if question == "Q5"
        else "selected"
    )
    selected = next(item for item in scores if item["candidate_id"] == selected_id)
    metric = "objective_missile_s" if question == "Q5" else "duration_s"
    payload = {
        "schema_name": "exact_scores",
        "adapter_id": "cumcm2025a-independent-quality",
        "adapter_version": "1.1",
        "candidate_scores": scores,
        "selected_candidate_id": selected_id,
        "metrics": {metric: selected["objective"]},
    }
    Path(output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
