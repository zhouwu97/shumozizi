"""数学建模空间场景的可复用三维图元与统一导出。"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any


def _point3(value: Sequence[float], *, label: str) -> tuple[float, float, float]:
    """把空间点规范化为三个有限浮点数。"""
    from math import isfinite

    if len(value) != 3:
        raise ValueError(f"{label} 必须包含三个坐标")
    point = tuple(float(item) for item in value)
    if not all(isfinite(item) for item in point):
        raise ValueError(f"{label} 坐标必须为有限数")
    return point


def plot_finite_segment(ax: Any, start: Sequence[float], end: Sequence[float], **kwargs: Any) -> Any:
    """绘制有限三维线段。"""
    normalized_start = _point3(start, label="线段起点")
    normalized_end = _point3(end, label="线段终点")
    return ax.plot(*zip(normalized_start, normalized_end, strict=True), **kwargs)


def plot_trajectory3d(ax: Any, points: Sequence[Sequence[float]], **kwargs: Any) -> Any:
    """绘制按时间排序的三维轨迹。"""
    if len(points) == 0:
        raise ValueError("轨迹至少需要一个点")
    normalized = [_point3(point, label="轨迹点") for point in points]
    x, y, z = zip(*normalized, strict=True)
    return ax.plot(x, y, z, **kwargs)


def plot_sphere_cloud(
    ax: Any, center: Sequence[float], radius: float, *, resolution: int = 36, **kwargs: Any
) -> Any:
    """绘制球形烟幕或球形作用区域。"""
    import numpy as np

    normalized_center = _point3(center, label="球心")
    if radius < 0 or resolution < 8:
        raise ValueError("radius 必须非负且 resolution 至少为 8")
    u = np.linspace(0.0, 2.0 * np.pi, resolution)
    v = np.linspace(0.0, np.pi, resolution // 2)
    x = normalized_center[0] + radius * np.outer(np.cos(u), np.sin(v))
    y = normalized_center[1] + radius * np.outer(np.sin(u), np.sin(v))
    z = normalized_center[2] + radius * np.outer(np.ones_like(u), np.cos(v))
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

    if len(center_xy) != 2:
        raise ValueError("圆柱平面中心必须包含两个坐标")
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
    normalized = _point3(point, label="事件点")
    return ax.scatter(
        [normalized[0]],
        [normalized[1]],
        [normalized[2]],
        marker=marker,
        label=label,
        **kwargs,
    )


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
    ax.set_box_aspect((1, 1, 1))


def configure_spatial_axes(
    ax: Any,
    *,
    points: Sequence[Sequence[float]] | None = None,
    unit: str,
    azimuth: float = 35.0,
    elevation: float = 25.0,
    padding_ratio: float = 0.08,
) -> dict[str, Any]:
    """配置可核验的等比例正交三维坐标轴。

    Args:
        ax: Matplotlib 三维坐标轴。
        points: 决定显示范围的真实空间点；省略时使用轴内已有范围。
        unit: 三轴共同使用的物理单位。
        azimuth: 相机方位角，单位为度。
        elevation: 相机仰角，单位为度。
        padding_ratio: 数据包围盒外的相对留白。

    Returns:
        可写入候选图布局报告的空间元数据。

    Raises:
        ValueError: 坐标轴、单位、视角或留白参数不合法。
    """
    from math import isfinite

    if getattr(ax, "name", None) != "3d":
        raise ValueError("configure_spatial_axes 需要三维坐标轴")
    if not isinstance(unit, str) or not unit.strip():
        raise ValueError("三维坐标必须声明非空物理单位")
    if not all(isfinite(float(value)) for value in (azimuth, elevation)):
        raise ValueError("相机视角必须为有限数")
    if not -90 <= float(elevation) <= 90:
        raise ValueError("相机仰角必须位于 -90 至 90 度")
    if not 0 <= padding_ratio <= 0.4:
        raise ValueError("padding_ratio 必须位于 0 至 0.4")

    if points:
        normalized = [_point3(point, label="范围点") for point in points]
        dimensions = list(zip(*normalized, strict=True))
        minima = [min(values) for values in dimensions]
        maxima = [max(values) for values in dimensions]
        span = max(maximum - minimum for minimum, maximum in zip(minima, maxima, strict=True))
        if span <= 0:
            span = max(1.0, max(abs(value) for point in normalized for value in point) * 0.1)
        radius = span * (0.5 + padding_ratio)
        centers = [(minimum + maximum) / 2 for minimum, maximum in zip(minima, maxima, strict=True)]
        ax.set_xlim3d(centers[0] - radius, centers[0] + radius)
        ax.set_ylim3d(centers[1] - radius, centers[1] + radius)
        ax.set_zlim3d(centers[2] - radius, centers[2] + radius)
    else:
        set_equal_3d_axes(ax)
    ax.set_box_aspect((1, 1, 1))
    ax.set_proj_type("ortho")
    ax.view_init(elev=float(elevation), azim=float(azimuth))
    normalized_unit = unit.strip()
    ax.set_xlabel(f"x ({normalized_unit})")
    ax.set_ylabel(f"y ({normalized_unit})")
    ax.set_zlabel(f"z ({normalized_unit})")
    return {
        "projection": "3d",
        "camera_projection": "orthographic",
        "camera_view": {"azimuth": float(azimuth), "elevation": float(elevation)},
        "coordinate_unit": normalized_unit,
        "data_aspect_ratio": [1.0, 1.0, 1.0],
    }


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
