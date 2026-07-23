"""用球面二次方程和端点内含独立判定线段与闭球体相交。"""

from __future__ import annotations

import math
from collections.abc import Sequence


def segment_intersects_closed_ball_quadratic(
    start: Sequence[float],
    end: Sequence[float],
    center: Sequence[float],
    radius: float,
    *,
    tolerance: float = 1e-10,
) -> bool:
    """按二次方程求根判定有限线段是否进入闭球体。

    端点位于球内时即判相交，因此该函数判断的是实心闭球体，而不只是球面。
    实现不依赖投影裁剪模块，可作为不同公式的 oracle 基础。

    Args:
        start: 线段起点。
        end: 线段终点。
        center: 球心。
        radius: 球半径。
        tolerance: 二次式与参数区间的数值容差。

    Returns:
        线段进入、位于或接触闭球体时为 ``True``。

    Raises:
        ValueError: 输入维数、坐标、半径或容差不合法。
    """
    if len(start) != 3 or len(end) != 3 or len(center) != 3:
        raise ValueError("start、end 和 center 必须恰好包含三个坐标")
    a = tuple(float(value) for value in start)
    b = tuple(float(value) for value in end)
    c = tuple(float(value) for value in center)
    values = (*a, *b, *c, float(radius), float(tolerance))
    if not all(math.isfinite(value) for value in values):
        raise ValueError("坐标、半径和容差必须是有限数")
    if radius < 0 or tolerance < 0:
        raise ValueError("radius 和 tolerance 必须非负")

    direction = tuple(b[index] - a[index] for index in range(3))
    offset = tuple(a[index] - c[index] for index in range(3))
    coefficient_a = sum(value * value for value in direction)
    coefficient_b = 2.0 * sum(offset[index] * direction[index] for index in range(3))
    coefficient_c = sum(value * value for value in offset) - radius * radius
    endpoint_c = sum((b[index] - c[index]) ** 2 for index in range(3)) - radius * radius

    if coefficient_c <= tolerance or endpoint_c <= tolerance:
        return True
    if coefficient_a <= tolerance * tolerance:
        return False
    discriminant = coefficient_b * coefficient_b - 4.0 * coefficient_a * coefficient_c
    if discriminant < -tolerance:
        return False
    root = math.sqrt(max(0.0, discriminant))
    denominator = 2.0 * coefficient_a
    roots = ((-coefficient_b - root) / denominator, (-coefficient_b + root) / denominator)
    return any(-tolerance <= parameter <= 1.0 + tolerance for parameter in roots)
