"""P0d 确定性优化夹具：容量约束下的贪心与穷举最优解。"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path


def score(items: list[dict[str, float]], indices: tuple[int, ...]) -> tuple[float, float]:
    """计算方案总重量和总价值。"""
    return (
        sum(items[index]["weight"] for index in indices),
        sum(items[index]["value"] for index in indices),
    )


def greedy(items: list[dict[str, float]], capacity: float) -> tuple[int, ...]:
    """按单位重量价值选择可行物品。"""
    chosen: list[int] = []
    remaining = capacity
    for index in sorted(
        range(len(items)),
        key=lambda item: items[item]["value"] / items[item]["weight"],
        reverse=True,
    ):
        if items[index]["weight"] <= remaining:
            chosen.append(index)
            remaining -= items[index]["weight"]
    return tuple(chosen)


def exact(items: list[dict[str, float]], capacity: float) -> tuple[int, ...]:
    """枚举全部子集，返回价值最大且满足容量的方案。"""
    feasible = (
        candidate
        for size in range(len(items) + 1)
        for candidate in itertools.combinations(range(len(items)), size)
        if score(items, candidate)[0] <= capacity
    )
    return max(feasible, key=lambda candidate: score(items, candidate)[1])


def main() -> None:
    """执行一个确定性容量优化循环并输出结构化结果。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("problem")
    parser.add_argument("output")
    parser.add_argument("mode", choices=("baseline", "primary"))
    args = parser.parse_args()
    problem = json.loads(Path(args.problem).read_text(encoding="utf-8"))
    items = problem["items"]
    capacity = problem["capacity"]
    selected = greedy(items, capacity) if args.mode == "baseline" else exact(items, capacity)
    weight, value = score(items, selected)
    payload = {
        "objective": value,
        "selected_indices": list(selected),
        "total_weight": weight,
        "capacity": capacity,
        "feasible": weight <= capacity,
        "item_count": len(items),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
