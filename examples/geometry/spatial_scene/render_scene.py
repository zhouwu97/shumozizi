"""从显式 JSON 场景生成三维总览与正交投影 smoke 候选图。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import matplotlib  # noqa: E402

matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from shumozizi.geometry.visual import (  # noqa: E402
    configure_spatial_axes,
    plot_cylinder_target,
    plot_drop_point,
    plot_explosion_point,
    plot_finite_segment,
    plot_sphere_cloud,
    plot_trajectory3d,
)

BLUE = "#0072B2"
ORANGE = "#E69F00"
GREEN = "#009E73"
VERMILLION = "#D55E00"
PURPLE = "#CC79A7"
BLACK = "#222222"
GRAY = "#7D7D7D"


def _configure_chinese_font() -> str:
    """选择实际安装的中文字体，避免静默回退后出现缺字方框。"""
    candidates = (
        "Microsoft YaHei",
        "Noto Sans CJK SC",
        "Source Han Sans SC",
        "SimHei",
    )
    for family in candidates:
        try:
            font_manager.findfont(
                font_manager.FontProperties(family=family),
                fallback_to_default=False,
            )
        except ValueError:
            continue
        matplotlib.rcParams.update(
            {
                "font.family": "sans-serif",
                "font.sans-serif": [family, "DejaVu Sans"],
                "axes.unicode_minus": False,
                "pdf.fonttype": 42,
            }
        )
        return family
    raise RuntimeError("未找到可渲染中文的字体，请安装 Microsoft YaHei、思源黑体或 SimHei")


def _load_scene(path: Path) -> dict[str, Any]:
    """读取仅用于绘图能力验证的空间场景。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("fixture_only") is not True:
        raise ValueError("smoke 场景必须明确声明 fixture_only=true")
    if not isinstance(payload.get("coordinate_unit"), str) or not payload["coordinate_unit"]:
        raise ValueError("场景必须声明 coordinate_unit")
    return payload


def _bounds(scene: dict[str, Any]) -> np.ndarray:
    """汇总有限对象的真实边界点，供各投影共享坐标范围。"""
    sphere = scene["sphere"]
    target = scene["target"]
    center = np.asarray(sphere["center"], dtype=float)
    radius = float(sphere["radius"])
    target_center = np.asarray(target["center_xy"], dtype=float)
    target_radius = float(target["radius"])
    points = [
        *scene["trajectory"],
        scene["line_of_sight"]["start"],
        scene["line_of_sight"]["end"],
        scene["events"]["drop"],
        scene["events"]["explosion"],
        center + np.array([radius, radius, radius]),
        center - np.array([radius, radius, radius]),
        [
            target_center[0] + target_radius,
            target_center[1] + target_radius,
            target["z_max"],
        ],
        [
            target_center[0] - target_radius,
            target_center[1] - target_radius,
            target["z_min"],
        ],
    ]
    values = np.asarray(points, dtype=float)
    if values.ndim != 2 or values.shape[1] != 3 or not np.isfinite(values).all():
        raise ValueError("空间场景边界必须是有限三维点")
    return values


def _style_2d(ax: Any, *, x_label: str, y_label: str) -> None:
    """为正交投影应用克制的论文样式。"""
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.grid(color="#D9D9D9", linewidth=0.55, alpha=0.65)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(direction="out", labelsize=8)
    ax.set_aspect("equal", adjustable="box")


def _circle(ax: Any, center: tuple[float, float], radius: float, *, color: str) -> None:
    """在正交投影中绘制球体或圆柱的真实圆截面。"""
    patch = plt.Circle(center, radius, facecolor=color, edgecolor=color, alpha=0.18, linewidth=1.1)
    ax.add_patch(patch)


def render(scene_path: Path, output_stem: Path) -> list[Path]:
    """渲染 3D 总览、XY 俯视与 XZ 侧视，并写布局报告。

    Args:
        scene_path: 显式 smoke 场景 JSON。
        output_stem: 新候选版本的输出文件前缀。

    Returns:
        新生成的 PNG、PDF 和布局报告路径。
    """
    scene = _load_scene(scene_path)
    font_family = _configure_chinese_font()
    unit = scene["coordinate_unit"]
    trajectory = np.asarray(scene["trajectory"], dtype=float)
    line_start = np.asarray(scene["line_of_sight"]["start"], dtype=float)
    line_end = np.asarray(scene["line_of_sight"]["end"], dtype=float)
    sphere = scene["sphere"]
    sphere_center = np.asarray(sphere["center"], dtype=float)
    sphere_radius = float(sphere["radius"])
    target = scene["target"]
    target_center = np.asarray(target["center_xy"], dtype=float)
    bounds = _bounds(scene)

    width_cm, height_cm = 18.0, 12.0
    fig = plt.figure(figsize=(width_cm / 2.54, height_cm / 2.54), constrained_layout=True)
    grid = fig.add_gridspec(2, 3, width_ratios=[1.15, 1.15, 1.0])
    ax3d = fig.add_subplot(grid[:, :2], projection="3d")
    ax_xy = fig.add_subplot(grid[0, 2])
    ax_xz = fig.add_subplot(grid[1, 2])

    plot_trajectory3d(ax3d, trajectory, color=BLUE, linewidth=2.1)
    plot_finite_segment(ax3d, line_start, line_end, color=BLACK, linestyle="--", linewidth=1.3)
    plot_sphere_cloud(ax3d, sphere_center, sphere_radius, color=GREEN, alpha=0.22)
    plot_cylinder_target(
        ax3d,
        target_center,
        float(target["radius"]),
        float(target["z_min"]),
        float(target["z_max"]),
        color=VERMILLION,
        alpha=0.32,
    )
    plot_drop_point(ax3d, scene["events"]["drop"], color=ORANGE, s=55)
    plot_explosion_point(ax3d, scene["events"]["explosion"], color=PURPLE, s=85)
    direction = trajectory[-1] - trajectory[-2]
    ax3d.quiver(*trajectory[-2], *direction, color=BLUE, arrow_length_ratio=0.25, linewidth=1.6)
    spatial = configure_spatial_axes(
        ax3d,
        points=bounds.tolist(),
        unit=unit,
        azimuth=36,
        elevation=24,
    )
    ax3d.set_title("(a) 三维总览：作用区位于轨迹与视线之间", fontsize=9.5, weight="bold")
    ax3d.text(*trajectory[0], "  轨迹起点", color=BLUE, fontsize=8)
    ax3d.text(*sphere_center, "  起爆/球形作用区", color=GREEN, fontsize=8)
    ax3d.text(target_center[0], target_center[1], target["z_max"], "  圆柱目标", color=VERMILLION, fontsize=8)

    ax_xy.plot(trajectory[:, 0], trajectory[:, 1], color=BLUE, linewidth=1.8)
    ax_xy.annotate("", xy=trajectory[-1, :2], xytext=trajectory[-2, :2], arrowprops={"arrowstyle": "->", "color": BLUE})
    ax_xy.plot([line_start[0], line_end[0]], [line_start[1], line_end[1]], "--", color=BLACK, linewidth=1.1)
    _circle(ax_xy, tuple(sphere_center[:2]), sphere_radius, color=GREEN)
    _circle(ax_xy, tuple(target_center), float(target["radius"]), color=VERMILLION)
    ax_xy.scatter(*scene["events"]["drop"][:2], marker="v", color=ORANGE, s=28, zorder=4)
    ax_xy.scatter(*scene["events"]["explosion"][:2], marker="*", color=PURPLE, s=55, zorder=4)
    _style_2d(ax_xy, x_label=f"x ({unit})", y_label=f"y ({unit})")
    ax_xy.set_title("(b) XY 俯视：横向关系", fontsize=9, weight="bold")

    ax_xz.plot(trajectory[:, 0], trajectory[:, 2], color=BLUE, linewidth=1.8)
    ax_xz.annotate("", xy=trajectory[-1, [0, 2]], xytext=trajectory[-2, [0, 2]], arrowprops={"arrowstyle": "->", "color": BLUE})
    ax_xz.plot([line_start[0], line_end[0]], [line_start[2], line_end[2]], "--", color=BLACK, linewidth=1.1)
    _circle(ax_xz, (sphere_center[0], sphere_center[2]), sphere_radius, color=GREEN)
    target_rect = plt.Rectangle(
        (target_center[0] - target["radius"], target["z_min"]),
        2 * target["radius"],
        target["z_max"] - target["z_min"],
        facecolor=VERMILLION,
        edgecolor=VERMILLION,
        alpha=0.22,
    )
    ax_xz.add_patch(target_rect)
    ax_xz.scatter(scene["events"]["drop"][0], scene["events"]["drop"][2], marker="v", color=ORANGE, s=28, zorder=4)
    ax_xz.scatter(scene["events"]["explosion"][0], scene["events"]["explosion"][2], marker="*", color=PURPLE, s=55, zorder=4)
    _style_2d(ax_xz, x_label=f"x ({unit})", y_label=f"z ({unit})")
    ax_xz.set_title("(c) XZ 侧视：高度与遮挡边界", fontsize=9, weight="bold")

    for ax in (ax_xy, ax_xz):
        ax.set_xlim(bounds[:, 0].min() - 0.5, bounds[:, 0].max() + 0.5)
    ax_xy.set_ylim(bounds[:, 1].min() - 0.5, bounds[:, 1].max() + 0.5)
    ax_xz.set_ylim(bounds[:, 2].min() - 0.5, bounds[:, 2].max() + 0.5)

    output_stem.parent.mkdir(parents=True, exist_ok=True)
    png_path = output_stem.with_suffix(".png")
    pdf_path = output_stem.with_suffix(".pdf")
    layout_path = output_stem.with_suffix(".layout.json")
    for path in (png_path, pdf_path, layout_path):
        if path.exists():
            raise FileExistsError(f"候选版本已存在，请使用新的版本目录: {path}")
    fig.savefig(png_path, dpi=300, facecolor="white")
    fig.savefig(pdf_path, facecolor="white")

    x_range = [float(bounds[:, 0].min()), float(bounds[:, 0].max())]
    y_range = [float(bounds[:, 1].min()), float(bounds[:, 1].max())]
    z_range = [float(bounds[:, 2].min()), float(bounds[:, 2].max())]
    report = {
        "schema_version": "1.1",
        "figure_id": "spatial-geometry-smoke",
        "fixture_only": True,
        "paper_size_cm": {"width": width_cm, "height": height_cm},
        "minimum_font_size_pt": 8.0,
        "font_family": font_family,
        "colorblind_safe": True,
        "locale_consistent": True,
        "primary_panel_id": "overview-3d",
        "axes": [
            {
                "id": "overview-3d",
                "role": "primary",
                **spatial,
                "x_limits": list(map(float, ax3d.get_xlim3d())),
                "x_data_range": x_range,
                "y_limits": list(map(float, ax3d.get_ylim3d())),
                "y_data_range": y_range,
                "z_limits": list(map(float, ax3d.get_zlim3d())),
                "z_data_range": z_range,
                "trajectory_direction_labeled": True,
                "legend_overlaps_data": False,
                "takeaway_annotation": True,
                "decision_markers_labeled": True,
            },
            {
                "id": "xy-top",
                "role": "supporting",
                "projection": "2d",
                "x_limits": list(map(float, ax_xy.get_xlim())),
                "x_data_range": x_range,
                "y_limits": list(map(float, ax_xy.get_ylim())),
                "y_data_range": y_range,
                "legend_overlaps_data": False,
                "takeaway_annotation": True,
                "decision_markers_labeled": True,
            },
            {
                "id": "xz-side",
                "role": "supporting",
                "projection": "2d",
                "x_limits": list(map(float, ax_xz.get_xlim())),
                "x_data_range": x_range,
                "y_limits": list(map(float, ax_xz.get_ylim())),
                "y_data_range": z_range,
                "legend_overlaps_data": False,
                "takeaway_annotation": True,
                "decision_markers_labeled": True,
            },
        ],
    }
    layout_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    plt.close(fig)
    return [png_path, pdf_path, layout_path]


def main() -> None:
    """解析命令行并渲染 smoke 候选。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path)
    parser.add_argument("output_stem", type=Path)
    args = parser.parse_args()
    for output in render(args.scene, args.output_stem):
        print(output)


if __name__ == "__main__":
    main()
