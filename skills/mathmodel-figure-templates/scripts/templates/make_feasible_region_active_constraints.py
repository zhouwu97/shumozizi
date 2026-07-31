#!/usr/bin/env python3
"""生成可行域与活跃约束模板预览。"""

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(".mplconfig").resolve()))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def main() -> None:
    """用确定性结构数据渲染三种预览格式。"""
    points = [(x, y) for x in range(6) for y in range(6)]
    feasible = [point for point in points if point[0] + point[1] <= 6 and point[1] <= 4]
    infeasible = [point for point in points if point not in feasible]
    figure, axis = plt.subplots(figsize=(7.6, 6.2))
    axis.scatter(*zip(*infeasible, strict=True), color="#c7c7c7", label="Infeasible")
    axis.scatter(*zip(*feasible, strict=True), color="#4d9b78", label="Feasible")
    axis.plot([0, 6], [6, 0], linewidth=2.3, label="C1 (active)")
    axis.plot([0, 6], [4, 4], "--", linewidth=1.1, label="C2")
    axis.scatter(3, 2, marker="D", s=52, color="#d08a36", label="Baseline")
    axis.scatter(4, 2, marker="*", s=190, color="#b73333", label="Selected")
    axis.set(xlabel="Decision x", ylabel="Decision y", title="Feasible region and active constraints")
    axis.grid(alpha=0.2)
    axis.legend(fontsize=8)
    figure.tight_layout()
    stem = Path("outputs/feasible_region_active_constraints_replica")
    stem.parent.mkdir(parents=True, exist_ok=True)
    for suffix in (".png", ".pdf", ".svg"):
        figure.savefig(stem.with_suffix(suffix), dpi=300, bbox_inches="tight")
    plt.close(figure)


if __name__ == "__main__":
    main()
