"""Q1-Q5 候选搜索、统一精确复算与动作数挑战入口。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.optimize import brentq, differential_evolution

from model_core import (
    DRONE_INITIAL,
    GRAVITY,
    MISSILE_INITIAL,
    Action,
    cylinder_surface_samples,
    missile_horizon,
    occlusion_margin,
    representative_point,
    score_solution,
    validate_drone_schedule,
)

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "results" / "raw"
DRONES = tuple(DRONE_INITIAL)
MISSILES = tuple(MISSILE_INITIAL)
PROXY_TARGET = representative_point("mid")
EXACT_TARGET = cylinder_surface_samples(72, 9, 5)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    """原子写入 JSON 结果。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _frozen_pre_revision_actions(question: str) -> list[Action]:
    """读取本轮科学红队冻结包中的修订前可行基线。"""

    candidates = sorted(
        ROOT.glob(f"review/packet/scientific/*/candidate_results/{question.lower()}.json")
    )
    if not candidates:
        return []
    payload = json.loads(candidates[0].read_text(encoding="utf-8"))
    return [_action_from_dict(item) for item in payload["result"]["actions"]]


def _penalty(actions: list[Action]) -> float:
    """返回物理与同机时序违反罚值。"""

    errors = validate_drone_schedule(actions)
    invalid = sum(not item.feasible() for item in actions)
    late = sum(item.burst_time > missile_horizon(item.assigned_missile) for item in actions)
    return 1000.0 * (len(errors) + invalid + late)


def _proxy_score(actions: list[Action], missiles: tuple[str, ...]) -> float:
    """用代表点和 0.25 s 中点占用近似生成候选排序。"""

    penalty = _penalty(actions)
    if penalty:
        return -penalty
    step = 0.25
    total = 0.0
    for missile in missiles:
        horizon = missile_horizon(missile)
        count = int(np.ceil(horizon / step))
        edges = np.linspace(0.0, horizon, count + 1)
        midpoints = 0.5 * (edges[:-1] + edges[1:])
        widths = edges[1:] - edges[:-1]
        covered = np.array(
            [
                occlusion_margin(float(time_s), missile, actions, PROXY_TARGET) <= 0.0
                for time_s in midpoints
            ]
        )
        total += float(np.sum(widths[covered]))
    return total


def _exact(
    actions: list[Action],
    missiles: tuple[str, ...],
    *,
    temporal_tolerance: float = 0.001,
) -> dict[str, object]:
    """使用有限圆柱与时间 Lipschitz 包络统一复算候选。"""

    errors = validate_drone_schedule(actions)
    if errors:
        raise ValueError("；".join(errors))
    scored = score_solution(
        actions,
        missiles,
        EXACT_TARGET,
        temporal_tolerance=temporal_tolerance,
    )
    scored["actions"] = [action.as_dict() for action in actions]
    scored["target_semantics"] = "finite-cylinder-full-occlusion-by-spatial-union"
    scored["target_sample_count"] = int(len(EXACT_TARGET))
    scored["continuous_time_method"] = "adaptive-lipschitz-interval-classification"
    return scored


def _mixed_initial_population(
    bounds: list[tuple[float, float]],
    baseline: np.ndarray,
    *,
    seed: int,
    size: int,
    local_fraction: float = 0.7,
    local_scale: np.ndarray | None = None,
) -> np.ndarray:
    """生成含可行基线的局部与全局混合初始种群。"""

    rng = np.random.default_rng(seed)
    lower = np.array([item[0] for item in bounds], dtype=float)
    upper = np.array([item[1] for item in bounds], dtype=float)
    span = upper - lower
    population = np.empty((size, len(bounds)), dtype=float)
    population[0] = np.clip(baseline, lower, upper)
    local_count = max(1, min(size - 1, int(round(size * local_fraction))))
    scale = (
        np.full(len(bounds), 0.035, dtype=float)
        if local_scale is None
        else np.asarray(local_scale, dtype=float)
    )
    if scale.shape != (len(bounds),):
        raise ValueError("局部扰动尺度必须与参数维数一致")
    population[1 : local_count + 1] = np.clip(
        baseline + rng.normal(0.0, 1.0, size=(local_count, len(bounds))) * scale * span,
        lower,
        upper,
    )
    population[local_count + 1 :] = rng.uniform(
        lower,
        upper,
        size=(size - local_count - 1, len(bounds)),
    )
    return population


def solve_q1() -> dict[str, object]:
    """计算 Q1 固定策略并保留代表点敏感性。"""

    action = Action("FY1", 180.0, 120.0, 1.5, 3.6, "M1")
    exact = _exact([action], ("M1",), temporal_tolerance=0.00005)
    bottom = score_solution(
        [action],
        ("M1",),
        representative_point("bottom"),
        temporal_tolerance=0.00005,
    )
    middle = score_solution(
        [action],
        ("M1",),
        PROXY_TARGET,
        temporal_tolerance=0.00005,
    )
    return {
        "schema_version": "1.0",
        "question": "Q1",
        "result": exact,
        "sensitivity": {
            "bottom_center_duration_s": bottom["durations_s"]["M1"],
            "mid_center_duration_s": middle["durations_s"]["M1"],
        },
        "metrics": {
            "duration_s": exact["durations_s"]["M1"],
            "left_endpoint_s": exact["intervals_s"]["M1"][0][0],
            "right_endpoint_s": exact["intervals_s"]["M1"][0][1],
        },
    }


def solve_q2(seed: int = 202501) -> dict[str, object]:
    """用两个同分布 seed 优化 FY1 单弹并执行 exact 复排。"""

    max_delay = np.sqrt(2.0 * DRONE_INITIAL["FY1"][2] / GRAVITY)
    horizon = missile_horizon("M1")
    baseline_action = Action("FY1", 180.0, 120.0, 1.5, 3.6, "M1")
    baseline_burst = baseline_action.burst_time

    bounds = [(0.0, 360.0), (70.0, 140.0), (0.0, horizon), (0.0, 1.0)]
    baseline_vector = np.array(
        [
            baseline_action.heading_deg,
            baseline_action.speed,
            baseline_burst,
            baseline_action.fuse_delay / min(max_delay, baseline_burst),
        ]
    )
    def decode(vector: np.ndarray) -> list[Action]:
        burst_time = float(vector[2])
        fuse_delay = float(vector[3] * min(max_delay, burst_time))
        release_time = burst_time - fuse_delay
        return [Action("FY1", vector[0], vector[1], release_time, fuse_delay, "M1")]

    seed_values = (seed, seed + 10)
    trials: list[dict[str, object]] = []
    for seed_value in seed_values:
        initial_population = _mixed_initial_population(
            bounds,
            baseline_vector,
            seed=seed_value,
            size=48,
            local_fraction=0.8,
        )
        optimization = differential_evolution(
            lambda vector: -_proxy_score(decode(vector), ("M1",)),
            bounds=bounds,
            seed=seed_value,
            init=initial_population,
            maxiter=60,
            polish=True,
            workers=1,
            updating="immediate",
            tol=1e-7,
        )
        actions = decode(optimization.x)
        exact_candidate = _exact(actions, ("M1",), temporal_tolerance=0.0002)
        trials.append(
            {
                "seed": seed_value,
                "evaluations": int(optimization.nfev),
                "proxy_best_s": float(-optimization.fun),
                "success": bool(optimization.success),
                "message": str(optimization.message),
                "exact": exact_candidate,
            }
        )
    frozen_actions = _frozen_pre_revision_actions("Q2")
    if frozen_actions:
        trials.append(
            {
                "seed": "pre-revision-feasible-baseline",
                "evaluations": 1,
                "proxy_best_s": _proxy_score(frozen_actions, ("M1",)),
                "success": True,
                "message": "红队冻结包可行基线参与同一 exact 复排",
                "exact": _exact(
                    frozen_actions,
                    ("M1",),
                    temporal_tolerance=0.0002,
                ),
            }
        )
    selected = max(
        trials,
        key=lambda item: (
            float(item["exact"]["objective_lower_bound_missile_s"]),
            float(item["exact"]["objective_missile_s"]),
        ),
    )
    exact = selected["exact"]
    baseline_proxy = _proxy_score([baseline_action], ("M1",))
    baseline_exact = _exact(
        [baseline_action],
        ("M1",),
        temporal_tolerance=0.0002,
    )["durations_s"]["M1"]
    if exact["durations_s"]["M1"] + 1e-9 < baseline_exact:
        raise RuntimeError("Q2 优化结果劣于已验证 Q1 可行基线")
    return {
        "schema_version": "1.0",
        "question": "Q2",
        "search": {
            "algorithm": "scipy-differential-evolution-on-point-proxy",
            "seeds": list(seed_values),
            "selected_seed": selected["seed"],
            "trials": [
                {
                    key: value
                    for key, value in trial.items()
                    if key != "exact"
                }
                | {
                    "exact_objective_s": trial["exact"]["objective_missile_s"],
                    "exact_lower_bound_s": trial["exact"]["objective_lower_bound_missile_s"],
                }
                for trial in trials
            ],
            "baseline_proxy_s": float(baseline_proxy),
            "baseline_exact_s": float(baseline_exact),
            "initial_population_size": 48,
            "parameterization": "heading-speed-burst-time-delay-fraction",
        },
        "result": exact,
        "metrics": {"duration_s": exact["durations_s"]["M1"]},
    }


def solve_q3(seed: int = 202503) -> dict[str, object]:
    """以两个 seed 优化 FY1 共享航迹下的三弹时间并集。"""

    max_delay = np.sqrt(2.0 * DRONE_INITIAL["FY1"][2] / GRAVITY)

    def decode(vector: np.ndarray) -> list[Action]:
        release = [vector[2], vector[2] + vector[3], vector[2] + vector[3] + vector[4]]
        return [
            Action("FY1", vector[0], vector[1], release[index], vector[5 + index], "M1")
            for index in range(3)
        ]

    q2_action = json.loads((RAW / "q2.json").read_text(encoding="utf-8"))["result"][
        "actions"
    ][0]
    bounds = [
        (0.0, 360.0),
        (70.0, 140.0),
        (0.0, 45.0),
        (1.0, 15.0),
        (1.0, 15.0),
        (0.0, max_delay),
        (0.0, max_delay),
        (0.0, max_delay),
    ]
    baseline_vector = np.array(
        [
            q2_action["heading_deg"],
            q2_action["speed_mps"],
            q2_action["release_time_s"],
            1.0,
            1.0,
            q2_action["fuse_delay_s"],
            q2_action["fuse_delay_s"],
            q2_action["fuse_delay_s"],
        ]
    )
    seed_values = (seed, seed + 10)
    trials: list[dict[str, object]] = []
    for seed_value in seed_values:
        initial_population = _mixed_initial_population(
            bounds,
            baseline_vector,
            seed=seed_value,
            size=48,
            local_fraction=0.75,
            local_scale=np.array([0.005, 0.02, 0.003, 0.03, 0.03, 0.03, 0.05, 0.05]),
        )
        optimization = differential_evolution(
            lambda vector: -_proxy_score(decode(vector), ("M1",)),
            bounds=bounds,
            seed=seed_value,
            init=initial_population,
            maxiter=45,
            polish=True,
            workers=1,
            updating="immediate",
            tol=1e-6,
        )
        actions = decode(optimization.x)
        exact_candidate = _exact(actions, ("M1",), temporal_tolerance=0.0002)
        trials.append(
            {
                "seed": seed_value,
                "evaluations": int(optimization.nfev),
                "proxy_best_s": float(-optimization.fun),
                "exact": exact_candidate,
            }
        )
    frozen_actions = _frozen_pre_revision_actions("Q3")
    if frozen_actions:
        trials.append(
            {
                "seed": "pre-revision-feasible-baseline",
                "evaluations": 1,
                "proxy_best_s": _proxy_score(frozen_actions, ("M1",)),
                "exact": _exact(
                    frozen_actions,
                    ("M1",),
                    temporal_tolerance=0.0002,
                ),
            }
        )
    selected = max(
        trials,
        key=lambda item: (
            float(item["exact"]["objective_lower_bound_missile_s"]),
            float(item["exact"]["objective_missile_s"]),
        ),
    )
    exact = selected["exact"]
    actions = [
        Action(
            item["drone"],
            item["heading_deg"],
            item["speed_mps"],
            item["release_time_s"],
            item["fuse_delay_s"],
            item["assigned_missile"],
        )
        for item in exact["actions"]
    ]
    per_action = [
        _exact([action], ("M1",), temporal_tolerance=0.0005)["durations_s"]["M1"]
        for action in actions
    ]
    exact["individual_durations_s"] = per_action
    return {
        "schema_version": "1.0",
        "question": "Q3",
        "search": {
            "algorithm": "shared-path-differential-evolution",
            "seeds": list(seed_values),
            "selected_seed": selected["seed"],
            "trials": [
                {
                    "seed": trial["seed"],
                    "evaluations": trial["evaluations"],
                    "proxy_best_s": trial["proxy_best_s"],
                    "exact_objective_s": trial["exact"]["objective_missile_s"],
                    "exact_lower_bound_s": trial["exact"]["objective_lower_bound_missile_s"],
                }
                for trial in trials
            ],
            "initial_population_size": 48,
            "baseline_proxy_s": float(_proxy_score(decode(baseline_vector), ("M1",))),
        },
        "result": exact,
        "metrics": {"duration_s": exact["durations_s"]["M1"]},
    }


def solve_q4(seed: int = 202504) -> dict[str, object]:
    """用两个 seed 优化 FY1-FY3 各一弹对 M1 的联合遮挡。"""

    drones = ("FY1", "FY2", "FY3")
    max_delays = [np.sqrt(2.0 * DRONE_INITIAL[drone][2] / GRAVITY) for drone in drones]

    def decode(vector: np.ndarray) -> list[Action]:
        return [
            Action(drone, *vector[4 * index : 4 * index + 4], "M1")
            for index, drone in enumerate(drones)
        ]

    bounds = []
    for max_delay in max_delays:
        bounds.extend([(0.0, 360.0), (70.0, 140.0), (0.0, 55.0), (0.0, max_delay)])
    q2_action = json.loads((RAW / "q2.json").read_text(encoding="utf-8"))["result"][
        "actions"
    ][0]
    # FY2/FY3 基线由各自初始点与 M1-目标中点视线的连续交点方程求得。
    baseline_vector = np.array(
        [
            q2_action["heading_deg"],
            q2_action["speed_mps"],
            q2_action["release_time_s"],
            q2_action["fuse_delay_s"],
            270.0,
            140.0,
            3.206667864330899,
            6.364762806350186,
            90.0,
            140.0,
            17.761110957286753,
            4.454855574700245,
        ]
    )
    seed_values = (seed, seed + 10)
    trials: list[dict[str, object]] = []
    for seed_value in seed_values:
        initial_population = _mixed_initial_population(
            bounds,
            baseline_vector,
            seed=seed_value,
            size=64,
            local_fraction=0.8,
            local_scale=np.array([0.004, 0.015, 0.003, 0.02] * 3),
        )
        optimization = differential_evolution(
            lambda vector: -_proxy_score(decode(vector), ("M1",)),
            bounds=bounds,
            seed=seed_value,
            init=initial_population,
            maxiter=45,
            polish=True,
            workers=1,
            updating="immediate",
            tol=1e-6,
        )
        actions = decode(optimization.x)
        exact_candidate = _exact(actions, ("M1",), temporal_tolerance=0.0002)
        trials.append(
            {
                "seed": seed_value,
                "evaluations": int(optimization.nfev),
                "proxy_best_s": float(-optimization.fun),
                "exact": exact_candidate,
            }
        )
    frozen_actions = _frozen_pre_revision_actions("Q4")
    if frozen_actions:
        trials.append(
            {
                "seed": "pre-revision-feasible-baseline",
                "evaluations": 1,
                "proxy_best_s": _proxy_score(frozen_actions, ("M1",)),
                "exact": _exact(
                    frozen_actions,
                    ("M1",),
                    temporal_tolerance=0.0002,
                ),
            }
        )
    selected = max(
        trials,
        key=lambda item: (
            float(item["exact"]["objective_lower_bound_missile_s"]),
            float(item["exact"]["objective_missile_s"]),
        ),
    )
    exact = selected["exact"]
    actions = [
        Action(
            item["drone"],
            item["heading_deg"],
            item["speed_mps"],
            item["release_time_s"],
            item["fuse_delay_s"],
            item["assigned_missile"],
        )
        for item in exact["actions"]
    ]
    exact["individual_durations_s"] = [
        _exact([action], ("M1",), temporal_tolerance=0.0005)["durations_s"]["M1"]
        for action in actions
    ]
    return {
        "schema_version": "1.0",
        "question": "Q4",
        "search": {
            "algorithm": "multi-drone-differential-evolution",
            "seeds": list(seed_values),
            "selected_seed": selected["seed"],
            "trials": [
                {
                    "seed": trial["seed"],
                    "evaluations": trial["evaluations"],
                    "proxy_best_s": trial["proxy_best_s"],
                    "exact_objective_s": trial["exact"]["objective_missile_s"],
                    "exact_lower_bound_s": trial["exact"]["objective_lower_bound_missile_s"],
                }
                for trial in trials
            ],
            "initial_population_size": 64,
            "baseline_proxy_s": float(_proxy_score(decode(baseline_vector), ("M1",))),
        },
        "result": exact,
        "metrics": {"duration_s": exact["durations_s"]["M1"]},
    }


def _line_intersection_action(
    drone: str,
    missile: str,
    heading_deg: float,
    speed: float,
) -> Action:
    """求共享航迹与导弹至目标中点视线的连续交点动作。"""

    target = PROXY_TARGET[0]
    initial = DRONE_INITIAL[drone]
    angle = np.deg2rad(heading_deg)
    direction = np.array([np.cos(angle), np.sin(angle)])
    horizon = missile_horizon(missile)

    def geometry(time_s: float) -> tuple[float, float, float]:
        observer = MISSILE_INITIAL[missile] * (
            1.0 - 300.0 * time_s / np.linalg.norm(MISSILE_INITIAL[missile])
        )
        drone_xy = initial[:2] + speed * time_s * direction
        sight_xy = target[:2] - observer[:2]
        offset = drone_xy - observer[:2]
        cross = sight_xy[0] * offset[1] - sight_xy[1] * offset[0]
        parameter = float(np.dot(offset, sight_xy) / np.dot(sight_xy, sight_xy))
        height = float(observer[2] + parameter * (target[2] - observer[2]))
        return float(cross), parameter, height

    grid = np.linspace(0.0, horizon - 1e-6, 241)
    roots: list[float] = []
    for left, right in zip(grid[:-1], grid[1:]):
        f_left = geometry(float(left))[0]
        f_right = geometry(float(right))[0]
        if f_left == 0.0:
            roots.append(float(left))
        elif f_left * f_right < 0.0:
            roots.append(brentq(lambda value: geometry(value)[0], float(left), float(right)))
    for burst_time in roots:
        _, parameter, height = geometry(burst_time)
        if not (0.0 <= parameter <= 1.0 and 0.0 <= height <= initial[2]):
            continue
        fuse_delay = float(np.sqrt(2.0 * (initial[2] - height) / GRAVITY))
        if fuse_delay <= burst_time:
            return Action(
                drone,
                heading_deg,
                speed,
                burst_time - fuse_delay,
                fuse_delay,
                missile,
            )
    raise RuntimeError(f"{drone}-{missile} 在指定共享航迹上没有可行视线交点")


ROUTE_CENTERS = {
    "FY1": 180.0,
    "FY2": 232.0,
    "FY3": 122.0,
    "FY4": 251.0,
    "FY5": 122.0,
}


def _action_from_dict(item: dict[str, object]) -> Action:
    """从结果 JSON 恢复动作。"""

    return Action(
        str(item["drone"]),
        float(item["heading_deg"]),
        float(item["speed_mps"]),
        float(item["release_time_s"]),
        float(item["fuse_delay_s"]),
        str(item["assigned_missile"]),
    )


def _q5_incumbent() -> list[Action]:
    """读取修订前可行解作为暖启动，不把它当作搜索边界。"""

    frozen = _frozen_pre_revision_actions("Q5")
    if frozen:
        return frozen
    path = RAW / "q5.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [_action_from_dict(item) for item in payload["result"]["actions"]]


def _resize_without_joint_mutation(
    base: list[Action],
    action_count: int,
    rng: np.random.Generator,
) -> list[Action] | None:
    """仅执行随机删除或插入，保留其余动作作为可行基线。"""

    actions = list(base)
    while len(actions) > action_count:
        actions.pop(int(rng.integers(0, len(actions))))
    while len(actions) < action_count:
        inserted = _propose_insert(actions, rng)
        if inserted is None:
            return None
        actions = inserted
    return _normalize_schedule(actions)


def _normalize_schedule(actions: list[Action]) -> list[Action] | None:
    """恢复共享航迹、投放间隔和导弹到达时刻约束。"""

    normalized: list[Action] = []
    for drone in DRONES:
        group = [action for action in actions if action.drone == drone]
        if not group:
            continue
        if len(group) > 3:
            return None
        heading = float(group[0].heading_deg % 360.0)
        speed = float(np.clip(group[0].speed, 70.0, 140.0))
        previous_release = -1.0
        for action in sorted(group, key=lambda item: item.release_time):
            max_delay = float(np.sqrt(2.0 * DRONE_INITIAL[drone][2] / GRAVITY))
            fuse_delay = float(np.clip(action.fuse_delay, 0.0, max_delay))
            latest_release = missile_horizon(action.assigned_missile) - fuse_delay - 1e-6
            release_time = float(np.clip(action.release_time, 0.0, latest_release))
            release_time = max(release_time, previous_release + 1.0)
            if release_time > latest_release:
                return None
            normalized.append(
                Action(
                    drone,
                    heading,
                    speed,
                    release_time,
                    fuse_delay,
                    action.assigned_missile,
                )
            )
            previous_release = release_time
    if len(normalized) != len(actions) or validate_drone_schedule(normalized):
        return None
    return normalized


def _propose_insert(actions: list[Action], rng: np.random.Generator) -> list[Action] | None:
    """在完整连续决策空间中插入一枚烟幕并恢复共享约束。"""

    counts = {drone: sum(action.drone == drone for action in actions) for drone in DRONES}
    available = [drone for drone, count in counts.items() if count < 3]
    if not available:
        return None
    drone = str(rng.choice(available))
    group = [action for action in actions if action.drone == drone]
    if group:
        heading = group[0].heading_deg
        speed = group[0].speed
    else:
        heading = float((ROUTE_CENTERS[drone] + rng.normal(0.0, 24.0)) % 360.0)
        speed = float(rng.uniform(80.0, 140.0))
    missile = str(rng.choice(MISSILES))
    try:
        proposal = _line_intersection_action(drone, missile, heading, speed)
        proposal = Action(
            drone,
            heading,
            speed,
            max(0.0, proposal.release_time + float(rng.normal(0.0, 1.2))),
            max(0.0, proposal.fuse_delay + float(rng.normal(0.0, 0.35))),
            missile,
        )
    except RuntimeError:
        max_delay = float(np.sqrt(2.0 * DRONE_INITIAL[drone][2] / GRAVITY))
        proposal = Action(
            drone,
            heading,
            speed,
            float(rng.uniform(0.0, 38.0)),
            float(rng.uniform(0.0, max_delay)),
            missile,
        )
    return _normalize_schedule([*actions, proposal])


def _mutate_schedule(
    base: list[Action],
    action_count: int,
    rng: np.random.Generator,
    *,
    broad: bool,
) -> tuple[list[Action] | None, list[str]]:
    """联合改变基数、共享航迹、时序、引信和服务导弹。"""

    actions = list(base)
    operations: list[str] = []
    while len(actions) > action_count:
        actions.pop(int(rng.integers(0, len(actions))))
        operations.append("delete")
    while len(actions) < action_count:
        inserted = _propose_insert(actions, rng)
        if inserted is None:
            return None, operations
        actions = inserted
        operations.append("insert")

    mutated: list[Action] = []
    heading_scale = 18.0 if broad else 3.0
    speed_scale = 12.0 if broad else 3.0
    time_scale = 4.0 if broad else 0.8
    delay_scale = 1.0 if broad else 0.22
    for drone in DRONES:
        group = [action for action in actions if action.drone == drone]
        if not group:
            continue
        heading = float((group[0].heading_deg + rng.normal(0.0, heading_scale)) % 360.0)
        speed = float(np.clip(group[0].speed + rng.normal(0.0, speed_scale), 70.0, 140.0))
        for action in group:
            assigned = (
                str(rng.choice(MISSILES))
                if rng.random() < (0.28 if broad else 0.08)
                else action.assigned_missile
            )
            mutated.append(
                Action(
                    drone,
                    heading,
                    speed,
                    max(0.0, action.release_time + float(rng.normal(0.0, time_scale))),
                    max(0.0, action.fuse_delay + float(rng.normal(0.0, delay_scale))),
                    assigned,
                )
            )
    operations.extend(["joint-path", "joint-timing", "assignment"])
    return _normalize_schedule(mutated), operations


def _candidate_key(actions: list[Action]) -> tuple[object, ...]:
    """为候选去重生成稳定键。"""

    return tuple(
        (
            action.drone,
            round(action.heading_deg % 360.0, 4),
            round(action.speed, 4),
            round(action.release_time, 4),
            round(action.fuse_delay, 4),
            action.assigned_missile,
        )
        for action in sorted(actions, key=lambda item: (item.drone, item.release_time))
    )


def _random_restart(action_count: int, rng: np.random.Generator) -> list[Action] | None:
    """从空计划随机插入并广域联合扰动，形成独立重启。"""

    actions: list[Action] = []
    for _ in range(action_count):
        inserted = _propose_insert(actions, rng)
        if inserted is None:
            return None
        actions = inserted
    mutated, _ = _mutate_schedule(actions, action_count, rng, broad=True)
    return mutated


def _run_cardinality_search(
    seed: int,
    incumbent: list[Action],
    *,
    proxy_budget: int,
    exact_budget: int,
) -> list[dict[str, object]]:
    """对 0--15 每个基数独立生成候选并以统一 exact 复排。"""

    rng = np.random.default_rng(seed)
    empty = _exact([], MISSILES, temporal_tolerance=0.001)
    records: list[dict[str, object]] = [
        {
            "action_count": 0,
            "proxy_evaluations": 0,
            "exact_evaluations": 1,
            "candidate_sources": {"empty": 1},
            "exact": empty,
        }
    ]
    previous_best: list[Action] = []
    for action_count in range(1, 16):
        candidates: dict[tuple[object, ...], tuple[list[Action], str]] = {}
        if len(incumbent) == action_count:
            normalized_incumbent = _normalize_schedule(incumbent)
            if normalized_incumbent is not None:
                candidates[_candidate_key(normalized_incumbent)] = (
                    normalized_incumbent,
                    "unchanged-pre-revision-baseline",
                )
        for _ in range(4):
            resized = _resize_without_joint_mutation(incumbent, action_count, rng)
            if resized is not None:
                candidates[_candidate_key(resized)] = (
                    resized,
                    "baseline-delete-or-insert-without-forced-drift",
                )
        if previous_best:
            adjacent = _resize_without_joint_mutation(previous_best, action_count, rng)
            if adjacent is not None:
                candidates[_candidate_key(adjacent)] = (
                    adjacent,
                    "adjacent-count-direct-insert",
                )
        attempts = 0
        while len(candidates) < proxy_budget and attempts < proxy_budget * 30:
            attempts += 1
            selector = rng.random()
            if selector < 0.25:
                candidate = _random_restart(action_count, rng)
                source = "independent-restart"
            elif selector < 0.60 and previous_best:
                candidate, _ = _mutate_schedule(
                    previous_best,
                    action_count,
                    rng,
                    broad=selector < 0.42,
                )
                source = "adjacent-count-insert-and-joint-reopt"
            else:
                candidate, _ = _mutate_schedule(
                    incumbent,
                    action_count,
                    rng,
                    broad=selector < 0.80,
                )
                source = "incumbent-delete-insert-replace-and-joint-reopt"
            if candidate is None or len(candidate) != action_count:
                continue
            candidates[_candidate_key(candidate)] = (candidate, source)
        if len(candidates) < exact_budget:
            raise RuntimeError(f"Q5 seed={seed} 基数 {action_count} 的可行候选不足")

        proxy_ranked = sorted(
            (
                (_proxy_score(candidate, MISSILES), candidate, source)
                for candidate, source in candidates.values()
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        exact_ranked: list[tuple[dict[str, object], list[Action], str, float]] = []
        for proxy_value, candidate, source in proxy_ranked[:exact_budget]:
            exact = _exact(candidate, MISSILES, temporal_tolerance=0.001)
            exact_ranked.append((exact, candidate, source, float(proxy_value)))
        best_exact, best_actions, best_source, best_proxy = max(
            exact_ranked,
            key=lambda item: (
                float(item[0]["objective_lower_bound_missile_s"]),
                float(item[0]["objective_missile_s"]),
                float(item[0]["min_duration_s"]),
            ),
        )
        previous_best = best_actions
        source_counts: dict[str, int] = {}
        for _, source in candidates.values():
            source_counts[source] = source_counts.get(source, 0) + 1
        records.append(
            {
                "action_count": action_count,
                "proxy_evaluations": len(candidates),
                "exact_evaluations": exact_budget,
                "candidate_sources": source_counts,
                "selected_source": best_source,
                "selected_proxy_missile_s": best_proxy,
                "exact_objective_range_missile_s": [
                    min(float(item[0]["objective_missile_s"]) for item in exact_ranked),
                    max(float(item[0]["objective_missile_s"]) for item in exact_ranked),
                ],
                "exact": best_exact,
            }
        )
    return records


def _bidirectional_transition_challenge(
    source: list[Action],
    target_count: int,
    seed: int,
    *,
    exact_budget: int,
) -> dict[str, object]:
    """对 14/15 相邻基数执行插入或删除后联合重优化。"""

    rng = np.random.default_rng(seed)
    candidates: dict[tuple[object, ...], list[Action]] = {}
    if len(source) == target_count + 1:
        # 15→14 必须逐一删除每枚动作，才能真实识别最弱动作。
        for index in range(len(source)):
            direct = _normalize_schedule(source[:index] + source[index + 1 :])
            if direct is not None:
                candidates[_candidate_key(direct)] = direct
    else:
        # 14→15 保留一半预算给无漂移直接插入，另一半用于联合重优化。
        while len(candidates) < exact_budget // 2:
            direct = _resize_without_joint_mutation(source, target_count, rng)
            if direct is not None:
                candidates[_candidate_key(direct)] = direct
    while len(candidates) < exact_budget:
        candidate, _ = _mutate_schedule(source, target_count, rng, broad=len(candidates) % 3 == 0)
        if candidate is not None:
            candidates[_candidate_key(candidate)] = candidate
    evaluated = [
        _exact(candidate, MISSILES, temporal_tolerance=0.001)
        for candidate in candidates.values()
    ]
    best = max(
        evaluated,
        key=lambda item: (
            float(item["objective_lower_bound_missile_s"]),
            float(item["objective_missile_s"]),
        ),
    )
    return {
        "source_action_count": len(source),
        "target_action_count": target_count,
        "exact_evaluations": exact_budget,
        "best_objective_missile_s": best["objective_missile_s"],
        "best_lower_bound_missile_s": best["objective_lower_bound_missile_s"],
        "best_upper_bound_missile_s": best["objective_upper_bound_missile_s"],
        "best_actions": best["actions"],
    }


def solve_q5() -> dict[str, object]:
    """完成双 seed、全基数联合搜索与 14/15 双向挑战。"""

    seeds = (202505, 202506)
    exact_budget = 16
    proxy_budget = 32
    incumbent = _q5_incumbent()
    runs = [
        {
            "seed": seed,
            "records": _run_cardinality_search(
                seed,
                incumbent,
                proxy_budget=proxy_budget,
                exact_budget=exact_budget,
            ),
        }
        for seed in seeds
    ]
    bidirectional = {}
    for run in runs:
        seed = int(run["seed"])
        record_14 = run["records"][14]
        record_15 = run["records"][15]
        actions_14 = [_action_from_dict(item) for item in record_14["exact"]["actions"]]
        actions_15 = [_action_from_dict(item) for item in record_15["exact"]["actions"]]
        bidirectional[str(seed)] = {
            "insert_14_to_15": _bidirectional_transition_challenge(
                actions_14,
                15,
                seed + 1400,
                exact_budget=exact_budget,
            ),
            "delete_15_to_14": _bidirectional_transition_challenge(
                actions_15,
                14,
                seed + 1500,
                exact_budget=exact_budget,
            ),
        }
    all_candidates = [
        (run["seed"], record)
        for run in runs
        for record in run["records"]
        if record["action_count"] > 0
    ]
    coarse_best = max(
        all_candidates,
        key=lambda item: float(item[1]["exact"]["objective_missile_s"]),
    )
    finalist_counts = {
        max(1, int(coarse_best[1]["action_count"]) - 2),
        max(1, int(coarse_best[1]["action_count"]) - 1),
        int(coarse_best[1]["action_count"]),
    }
    high_precision_finalists: list[tuple[int, dict[str, object], dict[str, object]]] = []
    for seed, record in all_candidates:
        if int(record["action_count"]) not in finalist_counts:
            continue
        actions = [_action_from_dict(item) for item in record["exact"]["actions"]]
        precise = _exact(actions, MISSILES, temporal_tolerance=0.00005)
        high_precision_finalists.append((int(seed), record, precise))
    best_lower = max(
        float(item[2]["objective_lower_bound_missile_s"])
        for item in high_precision_finalists
    )
    statistically_tied = [
        item
        for item in high_precision_finalists
        if float(item[2]["objective_upper_bound_missile_s"]) >= best_lower
    ]
    best_seed, best_record, result = max(
        statistically_tied,
        key=lambda item: (
            -int(item[1]["action_count"]),
            float(item[2]["objective_lower_bound_missile_s"]),
            float(item[2]["objective_missile_s"]),
            float(item[2]["min_duration_s"]),
        ),
    )
    per_action = []
    for action_dict in result["actions"]:
        action = Action(
            action_dict["drone"],
            action_dict["heading_deg"],
            action_dict["speed_mps"],
            action_dict["release_time_s"],
            action_dict["fuse_delay_s"],
            action_dict["assigned_missile"],
        )
        missile = action.assigned_missile
        per_action.append(
            _exact([action], (missile,), temporal_tolerance=0.0005)["durations_s"][missile]
        )
    result["individual_assigned_duration_s"] = per_action
    coverage = {
        str(run["seed"]): [
            {
                "action_count": record["action_count"],
                "objective_missile_s": record["exact"]["objective_missile_s"],
                "durations_s": record["exact"]["durations_s"],
                "objective_lower_bound_missile_s": record["exact"][
                    "objective_lower_bound_missile_s"
                ],
                "objective_upper_bound_missile_s": record["exact"][
                    "objective_upper_bound_missile_s"
                ],
                "min_duration_s": record["exact"]["min_duration_s"],
                "proxy_evaluations": record["proxy_evaluations"],
                "exact_evaluations": record["exact_evaluations"],
                "candidate_sources": record["candidate_sources"],
                "selected_source": record.get("selected_source"),
                "actions": record["exact"]["actions"],
            }
            for record in run["records"]
        ]
        for run in runs
    }
    return {
        "schema_version": "1.0",
        "question": "Q5",
        "search_contract": {
            "allowed_action_count": 15,
            "covered_action_counts": list(range(16)),
            "seeds": list(seeds),
            "proxy_evaluation_budget_per_seed_and_count": proxy_budget,
            "exact_evaluation_budget_per_seed_and_count": exact_budget,
            "exact_scorer": "finite-cylinder-spatial-union-with-adaptive-time-envelope",
            "challenge_design": (
                "independent restart plus insertion/deletion/replacement and joint reoptimization "
                "of shared path, release, fuse and missile assignment"
            ),
            "selection": "certified lower bound, estimated sum-duration, max-min, then fewer actions",
        },
        "action_count_coverage": coverage,
        "bidirectional_14_15_challenge": bidirectional,
        "high_precision_finalists": [
            {
                "seed": seed,
                "action_count": record["action_count"],
                "objective_missile_s": precise["objective_missile_s"],
                "objective_lower_bound_missile_s": precise[
                    "objective_lower_bound_missile_s"
                ],
                "objective_upper_bound_missile_s": precise[
                    "objective_upper_bound_missile_s"
                ],
            }
            for seed, record, precise in high_precision_finalists
        ],
        "selected_seed": best_seed,
        "selected_action_count": best_record["action_count"],
        "result": result,
        "metrics": {
            "objective_missile_s": result["objective_missile_s"],
            "min_duration_s": result["min_duration_s"],
            "action_count": best_record["action_count"],
            "duration_M1_s": result["durations_s"]["M1"],
            "duration_M2_s": result["durations_s"]["M2"],
            "duration_M3_s": result["durations_s"]["M3"],
        },
    }


SOLVERS = {"Q1": solve_q1, "Q2": solve_q2, "Q3": solve_q3, "Q4": solve_q4, "Q5": solve_q5}


def main() -> int:
    """解析问题编号、执行并保存 JSON。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--question", choices=SOLVERS, required=True)
    args = parser.parse_args()
    payload = SOLVERS[args.question]()
    output = RAW / f"{args.question.lower()}.json"
    _write_json(output, payload)
    print(json.dumps(payload["metrics"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
