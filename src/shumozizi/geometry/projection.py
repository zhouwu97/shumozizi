"""用投影裁剪计算有限线段到点的距离。"""

from __future__ import annotations

import math
from collections.abc import Sequence

Point3 = tuple[float, float, float]


def _point3(value: Sequence[float], name: str) -> Point3:
    """验证并冻结一个三维点。"""
    if len(value) != 3:
        raise ValueError(f"{name} 必须恰好包含三个坐标")
    point = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in point):
        raise ValueError(f"{name} 坐标必须是有限数")
    return point[0], point[1], point[2]


def closest_point_on_segment(
    start: Sequence[float],
    end: Sequence[float],
    point: Sequence[float],
    *,
    degenerate_tolerance: float = 1e-12,
) -> tuple[float, Point3, float]:
    """返回有限线段上距给定点最近的位置。

    Args:
        start: 线段起点。
        end: 线段终点。
        point: 被测点。
        degenerate_tolerance: 退化线段长度阈值。

    Returns:
        裁剪参数、最近点和欧氏距离。

    Raises:
        ValueError: 坐标、容差或维数不合法。
    """
    if not math.isfinite(degenerate_tolerance) or degenerate_tolerance < 0:
        raise ValueError("degenerate_tolerance 必须是非负有限数")
    a = _point3(start, "start")
    b = _point3(end, "end")
    c = _point3(point, "point")
    direction = tuple(b[index] - a[index] for index in range(3))
    length_squared = sum(component * component for component in direction)
    if length_squared <= degenerate_tolerance * degenerate_tolerance:
        parameter = 0.0
    else:
        projection = sum((c[index] - a[index]) * direction[index] for index in range(3))
        parameter = min(1.0, max(0.0, projection / length_squared))
    closest = tuple(a[index] + parameter * direction[index] for index in range(3))
    distance = math.sqrt(sum((c[index] - closest[index]) ** 2 for index in range(3)))
    return parameter, (closest[0], closest[1], closest[2]), distance


def segment_intersects_closed_ball(
    start: Sequence[float],
    end: Sequence[float],
    center: Sequence[float],
    radius: float,
    *,
    tolerance: float = 1e-10,
) -> bool:
    """按最小距离判定有限线段是否与闭球体相交。

    Args:
        start: 线段起点。
        end: 线段终点。
        center: 球心。
        radius: 球半径。
        tolerance: 距离边界的绝对容差。

    Returns:
        相交或相切时为 ``True``。

    Raises:
        ValueError: 半径或容差不合法。
    """
    if not math.isfinite(radius) or radius < 0:
        raise ValueError("radius 必须是非负有限数")
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("tolerance 必须是非负有限数")
    _, _, distance = closest_point_on_segment(start, end, center)
    return distance <= radius + tolerance
