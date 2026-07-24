"""烟幕干扰题的动力学、连续遮挡评分与区间运算。"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Iterable

import numpy as np
from scipy.optimize import brentq

GRAVITY = 9.8
CLOUD_RADIUS = 10.0
CLOUD_LIFETIME = 20.0
CLOUD_SINK_SPEED = 3.0
TARGET_CENTER_XY = np.array([0.0, 200.0])
TARGET_RADIUS = 7.0
TARGET_HEIGHT = 10.0

MISSILE_INITIAL = {
    "M1": np.array([20000.0, 0.0, 2000.0]),
    "M2": np.array([19000.0, 600.0, 2100.0]),
    "M3": np.array([18000.0, -600.0, 1900.0]),
}
DRONE_INITIAL = {
    "FY1": np.array([17800.0, 0.0, 1800.0]),
    "FY2": np.array([12000.0, 1400.0, 1400.0]),
    "FY3": np.array([6000.0, -3000.0, 700.0]),
    "FY4": np.array([11000.0, 2000.0, 1800.0]),
    "FY5": np.array([13000.0, -2000.0, 1300.0]),
}


@dataclass(frozen=True)
class Action:
    """一枚烟幕弹的完整可执行动作。"""

    drone: str
    heading_deg: float
    speed: float
    release_time: float
    fuse_delay: float
    assigned_missile: str

    @property
    def burst_time(self) -> float:
        """返回起爆时刻。"""

        return self.release_time + self.fuse_delay

    @property
    def direction(self) -> np.ndarray:
        """返回无人机水平单位航向。"""

        angle = np.deg2rad(self.heading_deg)
        return np.array([np.cos(angle), np.sin(angle), 0.0])

    def release_point(self) -> np.ndarray:
        """计算投放点。"""

        return DRONE_INITIAL[self.drone] + self.speed * self.release_time * self.direction

    def burst_point(self) -> np.ndarray:
        """计算起爆点。"""

        point = DRONE_INITIAL[self.drone] + self.speed * self.burst_time * self.direction
        return point - np.array([0.0, 0.0, 0.5 * GRAVITY * self.fuse_delay**2])

    def feasible(self) -> bool:
        """检查单动作物理可行性。"""

        return (
            self.drone in DRONE_INITIAL
            and self.assigned_missile in MISSILE_INITIAL
            and 70.0 <= self.speed <= 140.0
            and self.release_time >= 0.0
            and self.fuse_delay >= 0.0
            and self.burst_point()[2] >= -1e-9
        )

    def as_dict(self) -> dict[str, object]:
        """转换为可序列化结果。"""

        return {
            "drone": self.drone,
            "heading_deg": float(self.heading_deg % 360.0),
            "speed_mps": float(self.speed),
            "release_time_s": float(self.release_time),
            "fuse_delay_s": float(self.fuse_delay),
            "burst_time_s": float(self.burst_time),
            "release_point_m": self.release_point().tolist(),
            "burst_point_m": self.burst_point().tolist(),
            "assigned_missile": self.assigned_missile,
        }


def missile_horizon(missile: str) -> float:
    """返回导弹到达假目标原点的时刻。"""

    return float(np.linalg.norm(MISSILE_INITIAL[missile]) / 300.0)


def missile_position(missile: str, time_s: float) -> np.ndarray:
    """计算导弹位置。"""

    initial = MISSILE_INITIAL[missile]
    return initial * (1.0 - 300.0 * time_s / np.linalg.norm(initial))


def cloud_center(action: Action, time_s: float) -> np.ndarray:
    """计算有效期内的烟幕中心。"""

    return action.burst_point() - np.array(
        [0.0, 0.0, CLOUD_SINK_SPEED * (time_s - action.burst_time)]
    )


@lru_cache(maxsize=16)
def cylinder_surface_samples(n_theta: int = 72, n_z: int = 9, n_radial: int = 5) -> np.ndarray:
    """生成有限圆柱侧面及上下底面的确定性验证点。"""

    theta = np.linspace(0.0, 2.0 * np.pi, n_theta, endpoint=False)
    z = np.linspace(0.0, TARGET_HEIGHT, n_z)
    tt, zz = np.meshgrid(theta, z, indexing="ij")
    side = np.column_stack(
        [
            TARGET_RADIUS * np.cos(tt.ravel()),
            TARGET_CENTER_XY[1] + TARGET_RADIUS * np.sin(tt.ravel()),
            zz.ravel(),
        ]
    )
    disks = []
    for height in (0.0, TARGET_HEIGHT):
        for radius in np.linspace(0.0, TARGET_RADIUS, n_radial):
            disks.append(
                np.column_stack(
                    [
                        radius * np.cos(theta),
                        TARGET_CENTER_XY[1] + radius * np.sin(theta),
                        np.full_like(theta, height),
                    ]
                )
            )
    return np.unique(np.vstack([side, *disks]), axis=0)


def representative_point(kind: str = "mid") -> np.ndarray:
    """返回仅用于搜索代理或敏感性分析的目标代表点。"""

    z = 5.0 if kind == "mid" else 0.0
    return np.array([[0.0, 200.0, z]])


def segment_distances(center: np.ndarray, observer: np.ndarray, targets: np.ndarray) -> np.ndarray:
    """用投影裁剪公式计算球心到多条有限视线段的距离。"""

    vectors = targets - observer
    denominator = np.einsum("ij,ij->i", vectors, vectors)
    if np.any(denominator <= 1e-18):
        # 导弹到达目标后不再评价；此保护只避免退化输入产生 NaN。
        denominator = np.maximum(denominator, 1e-18)
    numerators = vectors @ (center - observer)
    parameters = np.clip(numerators / denominator, 0.0, 1.0)
    closest = observer + parameters[:, None] * vectors
    return np.linalg.norm(center - closest, axis=1)


def occlusion_margin(
    time_s: float,
    missile: str,
    actions: Iterable[Action],
    targets: np.ndarray,
) -> float:
    """计算联合烟幕对有限目标的最坏视线裕量。

    返回值不大于零表示每条离散验证视线至少被一个有效烟幕球截断。
    """

    active = [
        action
        for action in actions
        if action.feasible()
        and action.burst_time - 1e-12 <= time_s <= action.burst_time + CLOUD_LIFETIME + 1e-12
    ]
    if not active or time_s < 0.0 or time_s > missile_horizon(missile):
        return 1e6
    return _occlusion_margin_with_active(time_s, missile, active, targets)


def _occlusion_margin_with_active(
    time_s: float,
    missile: str,
    active: list[Action],
    targets: np.ndarray,
) -> float:
    """在有效烟幕集合固定时计算最坏视线裕量。"""

    if not active or time_s < 0.0 or time_s > missile_horizon(missile):
        return 1e6
    observer = missile_position(missile, time_s)
    all_distances = np.vstack(
        [segment_distances(cloud_center(action, time_s), observer, targets) for action in active]
    )
    # 每条视线选择最先能遮住它的任一烟幕，再取最难遮的目标视线。
    return float(np.max(np.min(all_distances, axis=0) - CLOUD_RADIUS))


def _merge_intervals(intervals: list[tuple[float, float]], tol: float = 1e-8) -> list[tuple[float, float]]:
    """合并闭区间并消除数值重叠。"""

    if not intervals:
        return []
    ordered = sorted(intervals)
    merged = [ordered[0]]
    for left, right in ordered[1:]:
        old_left, old_right = merged[-1]
        if left <= old_right + tol:
            merged[-1] = (old_left, max(old_right, right))
        else:
            merged.append((left, right))
    return merged


def _fast_occlusion_intervals(
    missile: str,
    actions: list[Action],
    targets: np.ndarray,
    *,
    bracket_step: float = 0.05,
) -> tuple[list[tuple[float, float]], dict[str, float | int | str]]:
    """用网格、单元极小值和 Brent 根生成搜索代理区间。"""

    horizon = missile_horizon(missile)
    events = {0.0, horizon}
    for action in actions:
        if action.feasible():
            events.add(float(np.clip(action.burst_time, 0.0, horizon)))
            events.add(float(np.clip(action.burst_time + CLOUD_LIFETIME, 0.0, horizon)))
    sorted_events = sorted(events)
    intervals: list[tuple[float, float]] = []
    roots: list[float] = []
    evaluations = 0

    def value(time_s: float) -> float:
        nonlocal evaluations
        evaluations += 1
        return occlusion_margin(time_s, missile, actions, targets)

    for event_left, event_right in zip(sorted_events[:-1], sorted_events[1:]):
        if event_right - event_left <= 1e-10:
            continue
        count = max(2, int(np.ceil((event_right - event_left) / bracket_step)) + 1)
        grid = np.linspace(event_left, event_right, count)
        values = np.array([value(float(time_s)) for time_s in grid])
        local_roots: list[float] = []
        for index in range(count - 1):
            left, right = float(grid[index]), float(grid[index + 1])
            f_left, f_right = float(values[index]), float(values[index + 1])
            if f_left == 0.0:
                local_roots.append(left)
            if f_left * f_right < 0.0:
                local_roots.append(brentq(value, left, right, xtol=1e-10, rtol=1e-12))
            elif f_left > 0.0 and f_right > 0.0:
                # 搜索代理也检查单元内部极小值，避免偶数个根被端点同号掩盖。
                center = 0.5 * (left + right)
                center_value = value(center)
                if center_value < 0.0:
                    local_roots.append(brentq(value, left, center, xtol=1e-10, rtol=1e-12))
                    local_roots.append(brentq(value, center, right, xtol=1e-10, rtol=1e-12))
        if values[-1] == 0.0:
            local_roots.append(float(grid[-1]))
        cuts = sorted({event_left, event_right, *local_roots})
        roots.extend(local_roots)
        for left, right in zip(cuts[:-1], cuts[1:]):
            midpoint = 0.5 * (left + right)
            if value(midpoint) <= 0.0:
                intervals.append((left, right))
    merged = _merge_intervals(intervals)
    duration = float(sum(right - left for left, right in merged))
    diagnostics: dict[str, float | int | str] = {
        "duration_s": duration,
        "duration_lower_bound_s": duration,
        "duration_upper_bound_s": duration,
        "temporal_uncertainty_s": 0.0,
        "root_count": len(roots),
        "function_evaluations": evaluations,
        "bracket_step_s": bracket_step,
        "temporal_method": "grid-cell-minimization-plus-brent-proxy",
    }
    return merged, diagnostics


def _certified_event_intervals(
    value: Callable[[float], float],
    left: float,
    right: float,
    *,
    lipschitz: float,
    tolerance: float,
) -> tuple[
    list[tuple[float, float]],
    list[tuple[float, float]],
    list[tuple[float, float]],
]:
    """用 Lipschitz 包络分类一个固定活跃集事件段。"""

    confirmed: list[tuple[float, float]] = []
    estimated: list[tuple[float, float]] = []
    uncertain: list[tuple[float, float]] = []
    stack = [(left, right)]
    while stack:
        cell_left, cell_right = stack.pop()
        midpoint = 0.5 * (cell_left + cell_right)
        half_width = 0.5 * (cell_right - cell_left)
        midpoint_value = float(value(midpoint))
        lower_envelope = midpoint_value - lipschitz * half_width
        upper_envelope = midpoint_value + lipschitz * half_width
        if upper_envelope <= 0.0:
            confirmed.append((cell_left, cell_right))
            estimated.append((cell_left, cell_right))
        elif lower_envelope > 0.0:
            continue
        elif cell_right - cell_left <= tolerance:
            uncertain.append((cell_left, cell_right))
            if midpoint_value <= 0.0:
                estimated.append((cell_left, cell_right))
        else:
            stack.append((midpoint, cell_right))
            stack.append((cell_left, midpoint))
    return confirmed, estimated, uncertain


def _certified_occlusion_intervals(
    missile: str,
    actions: list[Action],
    targets: np.ndarray,
    *,
    temporal_tolerance: float,
) -> tuple[list[tuple[float, float]], dict[str, float | int | str]]:
    """以显式时间 Lipschitz 界生成遮挡时长包络。"""

    horizon = missile_horizon(missile)
    events = {0.0, horizon}
    feasible_actions = [action for action in actions if action.feasible()]
    for action in feasible_actions:
        events.add(float(np.clip(action.burst_time, 0.0, horizon)))
        events.add(float(np.clip(action.burst_time + CLOUD_LIFETIME, 0.0, horizon)))

    # 固定活跃集内，烟幕中心速度为 3 m/s，导弹速度为 300 m/s；
    # 点到线段距离以及 min/max 运算保持 Lipschitz，故 303 是可靠上界。
    lipschitz = CLOUD_SINK_SPEED + 300.0
    confirmed_cells: list[tuple[float, float]] = []
    estimated_cells: list[tuple[float, float]] = []
    uncertain_cells: list[tuple[float, float]] = []
    evaluations = 0

    for event_left, event_right in zip(sorted(events)[:-1], sorted(events)[1:]):
        if event_right - event_left <= 1e-12:
            continue
        midpoint = 0.5 * (event_left + event_right)
        active = [
            action
            for action in feasible_actions
            if action.burst_time <= midpoint <= action.burst_time + CLOUD_LIFETIME
        ]
        if not active:
            continue

        def value(time_s: float) -> float:
            nonlocal evaluations
            evaluations += 1
            return _occlusion_margin_with_active(time_s, missile, active, targets)

        confirmed, estimated, uncertain = _certified_event_intervals(
            value,
            event_left,
            event_right,
            lipschitz=lipschitz,
            tolerance=temporal_tolerance,
        )
        confirmed_cells.extend(confirmed)
        estimated_cells.extend(estimated)
        uncertain_cells.extend(uncertain)

    confirmed = _merge_intervals(confirmed_cells, tol=temporal_tolerance)
    estimated = _merge_intervals(estimated_cells, tol=temporal_tolerance)
    possible = _merge_intervals([*confirmed_cells, *uncertain_cells], tol=temporal_tolerance)
    lower_duration = float(sum(right - left for left, right in confirmed))
    estimated_duration = float(sum(right - left for left, right in estimated))
    upper_duration = float(sum(right - left for left, right in possible))
    diagnostics: dict[str, float | int | str] = {
        "duration_s": estimated_duration,
        "duration_lower_bound_s": lower_duration,
        "duration_upper_bound_s": upper_duration,
        "temporal_uncertainty_s": upper_duration - lower_duration,
        "uncertain_cell_count": len(uncertain_cells),
        "function_evaluations": evaluations,
        "temporal_tolerance_s": temporal_tolerance,
        "temporal_lipschitz_mps": lipschitz,
        "temporal_method": "adaptive-lipschitz-interval-classification",
    }
    return estimated, diagnostics


def occlusion_intervals(
    missile: str,
    actions: list[Action],
    targets: np.ndarray,
    *,
    bracket_step: float = 0.05,
    temporal_tolerance: float | None = None,
) -> tuple[list[tuple[float, float]], dict[str, float | int | str]]:
    """计算遮挡区间；正式评分可启用时间方向的严格包络。"""

    if temporal_tolerance is not None:
        return _certified_occlusion_intervals(
            missile,
            actions,
            targets,
            temporal_tolerance=temporal_tolerance,
        )
    return _fast_occlusion_intervals(
        missile,
        actions,
        targets,
        bracket_step=bracket_step,
    )


def score_solution(
    actions: list[Action],
    missiles: Iterable[str],
    targets: np.ndarray,
    *,
    bracket_step: float = 0.05,
    temporal_tolerance: float | None = None,
) -> dict[str, object]:
    """用统一 scorer 计算逐导弹时长、总和及公平指标。"""

    durations: dict[str, float] = {}
    intervals: dict[str, list[list[float]]] = {}
    diagnostics: dict[str, dict[str, float | int | str]] = {}
    for missile in missiles:
        missile_intervals, info = occlusion_intervals(
            missile,
            actions,
            targets,
            bracket_step=bracket_step,
            temporal_tolerance=temporal_tolerance,
        )
        durations[missile] = float(info["duration_s"])
        intervals[missile] = [[float(left), float(right)] for left, right in missile_intervals]
        diagnostics[missile] = info
    values = list(durations.values())
    lower_bound = float(sum(float(item["duration_lower_bound_s"]) for item in diagnostics.values()))
    upper_bound = float(sum(float(item["duration_upper_bound_s"]) for item in diagnostics.values()))
    return {
        "durations_s": durations,
        "intervals_s": intervals,
        "objective_missile_s": float(sum(values)),
        "objective_lower_bound_missile_s": lower_bound,
        "objective_upper_bound_missile_s": upper_bound,
        "temporal_uncertainty_missile_s": upper_bound - lower_bound,
        "min_duration_s": float(min(values)) if values else 0.0,
        "diagnostics": diagnostics,
    }


def validate_drone_schedule(actions: list[Action]) -> list[str]:
    """检查同机共享航迹与至少 1 s 投放间隔。"""

    errors: list[str] = []
    for drone in DRONE_INITIAL:
        group = sorted((item for item in actions if item.drone == drone), key=lambda item: item.release_time)
        if len(group) > 3:
            errors.append(f"{drone} 超过三枚")
        if group:
            heading = group[0].heading_deg % 360.0
            speed = group[0].speed
            for action in group:
                if not action.feasible():
                    errors.append(f"{drone} 存在不可行动作")
                if abs((action.heading_deg % 360.0) - heading) > 1e-7 or abs(action.speed - speed) > 1e-7:
                    errors.append(f"{drone} 航向或速度不共享")
            for first, second in zip(group[:-1], group[1:]):
                if second.release_time - first.release_time < 1.0 - 1e-9:
                    errors.append(f"{drone} 投放间隔不足 1 s")
    return errors
