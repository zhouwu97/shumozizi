#!/usr/bin/env python3
"""生成区间事件时间线模板预览。"""

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(".mplconfig").resolve()))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def main() -> None:
    """用确定性区间数据渲染三种预览格式。"""
    intervals = [("Resource 1", "Window A", 0, 4.5), ("Resource 2", "Window B", 2, 7), ("Resource 3", "Window C", 5, 9)]
    figure, axis = plt.subplots(figsize=(9.2, 4.8))
    for index, (group, label, start, end) in enumerate(intervals):
        y = 3 - index
        axis.broken_barh([(start, end - start)], (y - 0.28, 0.56), alpha=0.72)
        axis.text((start + end) / 2, y, label, ha="center", va="center", fontsize=8)
    axis.axvspan(2, 4.5, color="#75b798", alpha=0.16)
    for time, label in ((2, "Switch"), (7, "Deadline")):
        axis.axvline(time, color="#8c3f3f", linestyle="--", linewidth=1)
        axis.text(time, 3.65, label, rotation=90, ha="right", va="top", fontsize=8)
    axis.set_yticks([3, 2, 1], [item[0] for item in intervals])
    axis.set(xlabel="Time (s)", title="Intervals, events, and effective windows")
    axis.grid(axis="x", alpha=0.2)
    figure.tight_layout()
    stem = Path("outputs/interval_event_timeline_replica")
    stem.parent.mkdir(parents=True, exist_ok=True)
    for suffix in (".png", ".pdf", ".svg"):
        figure.savefig(stem.with_suffix(suffix), dpi=300, bbox_inches="tight")
    plt.close(figure)


if __name__ == "__main__":
    main()
