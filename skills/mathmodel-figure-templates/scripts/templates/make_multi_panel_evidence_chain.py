#!/usr/bin/env python3
"""生成联合证据链模板预览。"""

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(".mplconfig").resolve()))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def main() -> None:
    """用四个相互关联面板渲染三种预览格式。"""
    figure, axes = plt.subplots(2, 2, figsize=(11, 8))
    axes[0, 0].scatter([1, 2, 3, 4], [1.2, 2.1, 2.8, 4.2], color="#2b7297")
    axes[0, 0].set_title("A  Observed structure", loc="left")
    axes[0, 1].plot([1, 2, 3, 4], [4.0, 3.1, 2.4, 2.0], marker="o", color="#2b7297")
    axes[0, 1].set_title("B  Constraint effect", loc="left")
    axes[1, 0].bar(["Baseline", "Selected"], [0.72, 0.88], color="#5b9a78")
    axes[1, 0].set_title("C  Route comparison", loc="left")
    axes[1, 1].broken_barh([(1, 3)], (-0.3, 0.6))
    axes[1, 1].broken_barh([(2, 3)], (0.7, 0.6))
    axes[1, 1].set_yticks([])
    axes[1, 1].set_title("D  Decision window", loc="left")
    takeaways = ("Samples concentrate near the boundary.", "The active constraint limits improvement.", "The challenger improves the objective.", "The action is valid in the central window.")
    for axis, takeaway in zip(axes.ravel(), takeaways, strict=True):
        axis.text(0.01, -0.18, takeaway, transform=axis.transAxes, fontsize=8)
        axis.grid(alpha=0.18)
    figure.suptitle("Evidence chain")
    figure.tight_layout()
    stem = Path("outputs/multi_panel_evidence_chain_replica")
    stem.parent.mkdir(parents=True, exist_ok=True)
    for suffix in (".png", ".pdf", ".svg"):
        figure.savefig(stem.with_suffix(suffix), dpi=300, bbox_inches="tight")
    plt.close(figure)


if __name__ == "__main__":
    main()
