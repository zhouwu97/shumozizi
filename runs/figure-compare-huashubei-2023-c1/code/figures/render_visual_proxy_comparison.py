"""生成旧论文图表的视觉代理对比，不将代理数据伪装为原始赛题结果。"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "shumozizi-mpl"))
os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OKABE_ITO = ("#0072B2", "#D55E00", "#009E73", "#CC79A7")


def _configure() -> None:
    """配置适合论文与灰度阅读的统一版式。"""
    matplotlib.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"],
            "font.size": 8,
            "axes.labelsize": 9,
            "axes.titlesize": 9,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
        }
    )


def _proxy_data() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """生成只反映旧图可见结构的确定性代理数据。

    Returns:
        EPDS 横坐标、睡眠时长纵坐标和近似类别计数。
    """
    generator = np.random.default_rng(20260722)
    epds = np.clip(generator.gamma(shape=2.2, scale=4.8, size=390), 0, 32)
    sleep_hours = np.clip(10.25 - 0.047 * epds + generator.normal(0, 1.35, size=390), 4.5, 12.2)
    category_counts = np.array([220, 118, 45])
    return epds, sleep_hours, category_counts


def _draw_proxy_figure() -> Path:
    """生成两面板代理图，并导出可印刷格式。

    Returns:
        PNG 输出文件路径。
    """
    _configure()
    epds, sleep_hours, category_counts = _proxy_data()
    figure = plt.figure(figsize=(7.1, 6.15), constrained_layout=True)
    grid = figure.add_gridspec(2, 1, height_ratios=(1.14, 1.0), hspace=0.17)

    scatter_axis = figure.add_subplot(grid[0])
    scatter_axis.scatter(
        epds,
        sleep_hours,
        s=11,
        color=OKABE_ITO[0],
        alpha=0.48,
        edgecolors="none",
        rasterized=True,
        label="Visual proxy points (n=390)",
    )
    slope, intercept = np.polyfit(epds, sleep_hours, deg=1)
    line_x = np.linspace(0, 32, 120)
    scatter_axis.plot(
        line_x,
        slope * line_x + intercept,
        color=OKABE_ITO[1],
        linewidth=1.7,
        label="Illustrative linear trend",
    )
    scatter_axis.set(
        xlim=(-1, 33),
        ylim=(4.2, 12.7),
        xlabel="Maternal EPDS score",
        ylabel="Infant sleep duration (hours)",
        title="Maternal EPDS and infant sleep duration",
    )
    scatter_axis.grid(axis="y", linewidth=0.5, color="#d7d7d7")
    scatter_axis.legend(loc="lower left", frameon=False, fontsize=7)
    scatter_axis.text(
        -0.10,
        1.04,
        "A",
        transform=scatter_axis.transAxes,
        fontweight="bold",
        fontsize=11,
        va="top",
    )
    scatter_axis.text(
        0.985,
        0.97,
        "VISUAL PROXY — original records unavailable",
        transform=scatter_axis.transAxes,
        ha="right",
        va="top",
        fontsize=6.5,
        color="#6a6a6a",
        style="italic",
    )

    bar_axis = figure.add_subplot(grid[1])
    labels = ("Category A", "Category B", "Category C")
    bars = bar_axis.bar(
        labels,
        category_counts,
        color=(OKABE_ITO[2], OKABE_ITO[0], OKABE_ITO[3]),
        edgecolor="#3d3d3d",
        linewidth=0.55,
    )
    for bar, hatch in zip(bars, ("", "//", "xx"), strict=True):
        bar.set_hatch(hatch)
    for bar, count in zip(bars, category_counts, strict=True):
        bar_axis.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 5,
            f"≈{count}",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    bar_axis.set(
        ylim=(0, 250),
        ylabel="Count (visual estimate)",
        title="Infant behavior categories after cleaning",
    )
    bar_axis.grid(axis="y", linewidth=0.5, color="#d7d7d7")
    bar_axis.set_axisbelow(True)
    bar_axis.text(
        -0.10,
        1.04,
        "B",
        transform=bar_axis.transAxes,
        fontweight="bold",
        fontsize=11,
        va="top",
    )
    bar_axis.text(
        0.985,
        0.95,
        "Counts are approximate visual estimates",
        transform=bar_axis.transAxes,
        ha="right",
        va="top",
        fontsize=6.5,
        color="#6a6a6a",
        style="italic",
    )

    for axis in (scatter_axis, bar_axis):
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
    output_stem = ROOT / "figures" / "v3_visual_proxy_replot"
    output_stem.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_stem.with_suffix(".png"), dpi=360, bbox_inches="tight", facecolor="white")
    figure.savefig(output_stem.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    figure.savefig(output_stem.with_suffix(".svg"), bbox_inches="tight", facecolor="white")
    plt.close(figure)
    return output_stem.with_suffix(".png")


def _make_side_by_side(new_plot: Path) -> Path:
    """把旧论文第二页与新图置于同一画布，便于只比较视觉表达。

    Args:
        new_plot: 新生成的代理图 PNG。

    Returns:
        对比图 PNG 路径。
    """
    contact = Image.open(ROOT / "qa" / "old-paper-contact-sheet.png").convert("RGB")
    page_height = contact.height // 3
    old_page = contact.crop((0, page_height, contact.width, page_height * 2))
    new_image = Image.open(new_plot).convert("RGB")
    target_height = 1200
    old_page.thumbnail((850, target_height))
    new_image.thumbnail((850, target_height))
    canvas = Image.new("RGB", (old_page.width + new_image.width + 72, target_height + 80), "white")
    canvas.paste(old_page, (18, 56))
    canvas.paste(new_image, (old_page.width + 54, 56))
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 18), "OLD PAPER — page 2", fill="#202020")
    draw.text((old_page.width + 54, 18), "V3 VISUAL PROXY — not empirical data", fill="#202020")
    output = ROOT / "figures" / "old-vs-v3-visual-proxy.png"
    canvas.save(output, format="PNG")
    return output


def main() -> None:
    """写入代理输入说明、渲染图表并输出机器可读摘要。"""
    epds, sleep_hours, category_counts = _proxy_data()
    new_plot = _draw_proxy_figure()
    comparison = _make_side_by_side(new_plot)
    payload = {
        "metrics": {
            "proxy_point_count": int(epds.size),
            "proxy_category_total": int(category_counts.sum()),
        },
        "source_type": "visual_proxy_not_empirical_result",
        "source_limit": "原始 390 条记录缺失；趋势与类别数量只依据旧 PDF 的可见结构生成。",
        "outputs": {
            "new_plot": new_plot.relative_to(ROOT).as_posix(),
            "side_by_side": comparison.relative_to(ROOT).as_posix(),
        },
        "proxy_summary": {
            "epds_range": [float(epds.min()), float(epds.max())],
            "sleep_hours_range": [float(sleep_hours.min()), float(sleep_hours.max())],
            "approximate_category_counts": category_counts.tolist(),
        },
    }
    output = ROOT / "results" / "raw" / "visual_proxy_comparison.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
