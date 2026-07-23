"""数学建模空间场景的可复用三维图元与统一导出。"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any


def plot_finite_segment(ax: Any, start: Sequence[float], end: Sequence[float], **kwargs: Any) -> Any:
    """绘制有限三维线段。"""
    return ax.plot(*zip(start, end, strict=True), **kwargs)


def plot_trajectory3d(ax: Any, points: Sequence[Sequence[float]], **kwargs: Any) -> Any:
    """绘制按时间排序的三维轨迹。"""
    if not points:
        raise ValueError("轨迹至少需要一个点")
    x, y, z = zip(*points, strict=True)
    return ax.plot(x, y, z, **kwargs)


def plot_sphere_cloud(
    ax: Any, center: Sequence[float], radius: float, *, resolution: int = 36, **kwargs: Any
) -> Any:
    """绘制球形烟幕或球形作用区域。"""
    import numpy as np

    if radius < 0 or resolution < 8:
        raise ValueError("radius 必须非负且 resolution 至少为 8")
    u = np.linspace(0.0, 2.0 * np.pi, resolution)
    v = np.linspace(0.0, np.pi, resolution // 2)
    x = center[0] + radius * np.outer(np.cos(u), np.sin(v))
    y = center[1] + radius * np.outer(np.sin(u), np.sin(v))
    z = center[2] + radius * np.outer(np.ones_like(u), np.cos(v))
    return ax.plot_surface(x, y, z, **kwargs)


def plot_cylinder_target(
    ax: Any,
    center_xy: Sequence[float],
    radius: float,
    z_min: float,
    z_max: float,
    *,
    resolution: int = 48,
    **kwargs: Any,
) -> Any:
    """绘制竖直圆柱目标的侧表面。"""
    import numpy as np

    if radius < 0 or z_max < z_min or resolution < 8:
        raise ValueError("圆柱半径、高度区间或 resolution 不合法")
    theta = np.linspace(0.0, 2.0 * np.pi, resolution)
    z = np.array([z_min, z_max])
    theta_grid, z_grid = np.meshgrid(theta, z)
    x = center_xy[0] + radius * np.cos(theta_grid)
    y = center_xy[1] + radius * np.sin(theta_grid)
    return ax.plot_surface(x, y, z_grid, **kwargs)


def plot_event_point(ax: Any, point: Sequence[float], *, marker: str, label: str, **kwargs: Any) -> Any:
    """绘制带稳定语义的投放或起爆事件点。"""
    return ax.scatter([point[0]], [point[1]], [point[2]], marker=marker, label=label, **kwargs)


def plot_drop_point(ax: Any, point: Sequence[float], **kwargs: Any) -> Any:
    """绘制投放点。"""
    return plot_event_point(ax, point, marker="v", label="drop", **kwargs)


def plot_explosion_point(ax: Any, point: Sequence[float], **kwargs: Any) -> Any:
    """绘制起爆点。"""
    return plot_event_point(ax, point, marker="*", label="explosion", **kwargs)


def set_equal_3d_axes(ax: Any) -> None:
    """设置三轴等比例，避免空间距离被视觉拉伸。"""
    limits = (ax.get_xlim3d(), ax.get_ylim3d(), ax.get_zlim3d())
    centers = [sum(limit) / 2.0 for limit in limits]
    radius = max(limit[1] - limit[0] for limit in limits) / 2.0
    ax.set_xlim3d(centers[0] - radius, centers[0] + radius)
    ax.set_ylim3d(centers[1] - radius, centers[1] + radius)
    ax.set_zlim3d(centers[2] - radius, centers[2] + radius)


def export_publication_figure(fig: Any, output_base: Path, *, dpi: int = 600) -> list[Path]:
    """统一导出可编辑 PDF/SVG 与高分辨率 PNG。"""
    if dpi < 300:
        raise ValueError("论文栅格图 dpi 不得低于 300")
    output_base.parent.mkdir(parents=True, exist_ok=True)
    outputs = [output_base.with_suffix(suffix) for suffix in (".pdf", ".svg", ".png")]
    fig.savefig(outputs[0], bbox_inches="tight")
    fig.savefig(outputs[1], bbox_inches="tight")
    fig.savefig(outputs[2], dpi=dpi, bbox_inches="tight")
    return outputs
