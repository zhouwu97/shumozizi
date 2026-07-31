#!/usr/bin/env python3
"""生成不确定性扇形与阈值模板预览。"""

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(".mplconfig").resolve()))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def main() -> None:
    """用确定性分位带渲染三种预览格式。"""
    x = list(range(10))
    median = [0.15 + 0.07 * item for item in x]
    figure, axis = plt.subplots(figsize=(8.0, 5.8))
    axis.fill_between(x, [item - 0.18 for item in median], [item + 0.18 for item in median], color="#c9ddec", alpha=0.5, label="95% interval")
    axis.fill_between(x, [item - 0.10 for item in median], [item + 0.10 for item in median], color="#5d9bc3", alpha=0.5, label="80% interval")
    axis.plot(x, median, color="#1f5875", linewidth=2, label="Median")
    axis.axhline(0.62, color="#ad3f3f", linestyle="--", label="Safety threshold")
    axis.set(xlabel="Scenario", ylabel="Outcome", title="Uncertainty fan and decision threshold")
    axis.grid(alpha=0.2)
    axis.legend(fontsize=8)
    figure.tight_layout()
    stem = Path("outputs/uncertainty_fan_threshold_replica")
    stem.parent.mkdir(parents=True, exist_ok=True)
    for suffix in (".png", ".pdf", ".svg"):
        figure.savefig(stem.with_suffix(suffix), dpi=300, bbox_inches="tight")
    plt.close(figure)


if __name__ == "__main__":
    main()
