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


def _penalty(actions: list[Action]) -> float:
    """返回物理与同机时序违反罚值。"""

    errors = validate_drone_schedule(actions)
    invalid = sum(not item.feasible() for item in actions)
    late = sum(item.burst_time > missile_horizon(item.assigned_missile) for item in actions)
    return 1000.0 * (len(errors) + invalid + late)


def _proxy_score(actions: list[Action], missiles: tuple[str, ...]) -> float:
    """用代表点和较粗根括步长生成候选。"""

    penalty = _penalty(actions)
    if penalty:
        return -penalty
    return float(
        score_solution(actions, missiles, PROXY_TARGET, bracket_step=0.12)[
            "objective_missile_s"
        ]
    )


def _exact(actions: list[Action], missiles: tuple[str, ...], step: float = 0.04) -> dict[str, object]:
    """使用有限圆柱联合遮挡统一复算候选。"""

    errors = validate_drone_schedule(actions)
    if errors:
        raise ValueError("；".join(errors))
    scored = score_solution(actions, missiles, EXACT_TARGET, bracket_step=step)
    scored["actions"] = [action.as_dict() for action in actions]
    scored["target_semantics"] = "finite-cylinder-full-occlusion-by-spatial-union"
    scored["target_sample_count"] = int(len(EXACT_TARGET))
    scored["continuous_time_method"] = "event-partition-plus-brent-root-refinement"
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
    exact = _exact([action], ("M1",), step=0.01)
    bottom = score_solution([action], ("M1",), representative_point("bottom"), bracket_step=0.01)
    middle = score_solution([action], ("M1",), PROXY_TARGET, bracket_step=0.01)
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
    """优化 FY1 单弹并由有限圆柱 scorer 复算。"""

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
    initial_population = _mixed_initial_population(
        bounds,
        baseline_vector,
        seed=seed,
        size=64,
        local_fraction=0.8,
    )

    def decode(vector: np.ndarray) -> list[Action]:
        burst_time = float(vector[2])
        fuse_delay = float(vector[3] * min(max_delay, burst_time))
        release_time = burst_time - fuse_delay
        return [Action("FY1", vector[0], vector[1], release_time, fuse_delay, "M1")]

    result = differential_evolution(
        lambda vector: -_proxy_score(decode(vector), ("M1",)),
        bounds=bounds,
        seed=seed,
        init=initial_population,
        maxiter=120,
        polish=True,
        workers=1,
        updating="immediate",
        tol=1e-7,
    )
    actions = decode(result.x)
    exact = _exact(actions, ("M1",))
    baseline_proxy = _proxy_score([baseline_action], ("M1",))
    baseline_exact = _exact([baseline_action], ("M1",))["durations_s"]["M1"]
    if exact["durations_s"]["M1"] + 1e-9 < baseline_exact:
        raise RuntimeError("Q2 优化结果劣于已验证 Q1 可行基线")
    return {
        "schema_version": "1.0",
        "question": "Q2",
        "search": {
            "algorithm": "scipy-differential-evolution-on-point-proxy",
            "seed": seed,
            "evaluations": int(result.nfev),
            "proxy_best_s": float(-result.fun),
            "baseline_proxy_s": float(baseline_proxy),
            "baseline_exact_s": float(baseline_exact),
            "initial_population_size": int(len(initial_population)),
            "parameterization": "heading-speed-burst-time-delay-fraction",
            "success": bool(result.success),
            "message": str(result.message),
        },
        "result": exact,
        "metrics": {"duration_s": exact["durations_s"]["M1"]},
    }


def solve_q3(seed: int = 202503) -> dict[str, object]:
    """在 FY1 共享航迹下优化三弹时间并集。"""

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
    initial_population = _mixed_initial_population(
        bounds,
        baseline_vector,
        seed=seed,
        size=96,
        local_fraction=0.75,
        local_scale=np.array([0.005, 0.02, 0.003, 0.03, 0.03, 0.03, 0.05, 0.05]),
    )

    result = differential_evolution(
        lambda vector: -_proxy_score(decode(vector), ("M1",)),
        bounds=bounds,
        seed=seed,
        init=initial_population,
        maxiter=110,
        polish=True,
        workers=1,
        updating="immediate",
        tol=1e-6,
    )
    actions = decode(result.x)
    exact = _exact(actions, ("M1",))
    per_action = [
        _exact([action], ("M1",), step=0.05)["durations_s"]["M1"] for action in actions
    ]
    exact["individual_durations_s"] = per_action
    return {
        "schema_version": "1.0",
        "question": "Q3",
        "search": {
            "algorithm": "shared-path-differential-evolution",
            "seed": seed,
            "evaluations": int(result.nfev),
            "proxy_best_s": float(-result.fun),
            "initial_population_size": int(len(initial_population)),
            "baseline_proxy_s": float(_proxy_score(decode(baseline_vector), ("M1",))),
        },
        "result": exact,
        "metrics": {"duration_s": exact["durations_s"]["M1"]},
    }


def solve_q4(seed: int = 202504) -> dict[str, object]:
    """优化 FY1-FY3 各一弹对 M1 的联合遮挡。"""

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
    initial_population = _mixed_initial_population(
        bounds,
        baseline_vector,
        seed=seed,
        size=96,
        local_fraction=0.8,
        local_scale=np.array([0.004, 0.015, 0.003, 0.02] * 3),
    )
    result = differential_evolution(
        lambda vector: -_proxy_score(decode(vector), ("M1",)),
        bounds=bounds,
        seed=seed,
        init=initial_population,
        maxiter=110,
        polish=True,
        workers=1,
        updating="immediate",
        tol=1e-6,
    )
    actions = decode(result.x)
    exact = _exact(actions, ("M1",))
    exact["individual_durations_s"] = [
        _exact([action], ("M1",), step=0.05)["durations_s"]["M1"] for action in actions
    ]
    return {
        "schema_version": "1.0",
        "question": "Q4",
        "search": {
            "algorithm": "multi-drone-differential-evolution",
            "seed": seed,
            "evaluations": int(result.nfev),
            "proxy_best_s": float(-result.fun),
            "initial_population_size": int(len(initial_population)),
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


def _q5_blueprint(seed: int) -> list[tuple[str, Action]]:
    """为一个 seed 构造十五个可行的无人机-导弹动作槽位。"""

    path_families = {
        202505: {
            "FY2": (230.0, 140.0),
            "FY3": (128.0, 125.0),
            "FY4": (250.0, 140.0),
            "FY5": (122.0, 140.0),
        },
        202506: {
            "FY2": (233.0, 135.0),
            "FY3": (115.0, 120.0),
            "FY4": (251.0, 135.0),
            "FY5": (121.0, 135.0),
        },
    }
    if seed not in path_families:
        raise ValueError(f"未定义 Q5 seed: {seed}")
    q3_actions = json.loads((RAW / "q3.json").read_text(encoding="utf-8"))["result"][
        "actions"
    ]
    blueprint: list[tuple[str, Action]] = []
    for missile, item in zip(MISSILES, q3_actions):
        action = Action(
            "FY1",
            item["heading_deg"],
            item["speed_mps"],
            item["release_time_s"],
            item["fuse_delay_s"],
            missile,
        )
        blueprint.append((f"FY1-{missile}", action))
    for drone, (heading, speed) in path_families[seed].items():
        for missile in MISSILES:
            action = _line_intersection_action(drone, missile, heading, speed)
            blueprint.append((f"{drone}-{missile}", action))
    errors = validate_drone_schedule([item[1] for item in blueprint])
    if len(blueprint) != 15 or errors:
        raise RuntimeError("Q5 十五动作蓝图未通过容量、共享航迹或投放间隔校验")
    return blueprint


def _greedy_activation(seed: int, exact_budget: int = 16) -> list[dict[str, object]]:
    """以固定 exact 预算执行 1 至 15 动作的逐槽位插入挑战。"""

    rng = np.random.default_rng(seed)
    blueprint = _q5_blueprint(seed)
    current: list[Action] = []
    unused = {slot: action for slot, action in blueprint}
    empty = _exact([], MISSILES, step=0.08)
    records: list[dict[str, object]] = [
        {
            "action_count": 0,
            "exact_evaluations": 1,
            "selected_slot": None,
            "marginal_gain_missile_s": 0.0,
            "exact": empty,
        }
    ]
    previous_value = 0.0
    for action_count in range(1, 16):
        slots = list(unused)
        proposals: list[tuple[str, Action]] = [(slot, unused[slot]) for slot in slots]
        while len(proposals) < exact_budget:
            slot = str(rng.choice(slots))
            base = unused[slot]
            max_delay = np.sqrt(2.0 * DRONE_INITIAL[base.drone][2] / GRAVITY)
            delay = float(np.clip(base.fuse_delay + rng.normal(0.0, 0.18), 0.0, max_delay))
            proposals.append(
                (
                    slot,
                    Action(
                        base.drone,
                        base.heading_deg,
                        base.speed,
                        base.release_time,
                        delay,
                        base.assigned_missile,
                    ),
                )
            )
        candidates: list[tuple[float, float, str, Action, dict[str, object]]] = []
        for slot, proposal in proposals[:exact_budget]:
            trial = [*current, proposal]
            errors = validate_drone_schedule(trial)
            if errors:
                raise RuntimeError(f"Q5 候选 {slot} 违反无人机时序: {'；'.join(errors)}")
            exact = _exact(trial, MISSILES, step=0.08)
            candidates.append(
                (
                    float(exact["objective_missile_s"]),
                    float(exact["min_duration_s"]),
                    slot,
                    proposal,
                    exact,
                )
            )
        best_value, _, best_slot, best_action, best_exact = max(
            candidates, key=lambda item: (item[0], item[1])
        )
        current.append(best_action)
        del unused[best_slot]
        records.append(
            {
                "action_count": action_count,
                "exact_evaluations": exact_budget,
                "selected_slot": best_slot,
                "marginal_gain_missile_s": float(best_value - previous_value),
                "candidate_objective_range_missile_s": [
                    float(min(item[0] for item in candidates)),
                    float(max(item[0] for item in candidates)),
                ],
                "exact": best_exact,
            }
        )
        previous_value = best_value
    return records


def solve_q5() -> dict[str, object]:
    """完成两个 seed、全动作数覆盖和统一 scorer 激活挑战。"""

    seeds = (202505, 202506)
    exact_budget = 16
    runs = [{"seed": seed, "records": _greedy_activation(seed, exact_budget)} for seed in seeds]
    all_candidates = [
        (run["seed"], record)
        for run in runs
        for record in run["records"]
        if record["action_count"] > 0
    ]
    best_seed, best_record = max(
        all_candidates,
        key=lambda item: (
            round(float(item[1]["exact"]["objective_missile_s"]), 8),
            round(float(item[1]["exact"]["min_duration_s"]), 8),
            -int(item[1]["action_count"]),
        ),
    )
    result = best_record["exact"]
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
        per_action.append(_exact([action], (missile,), step=0.08)["durations_s"][missile])
    result["individual_assigned_duration_s"] = per_action
    coverage = {
        str(run["seed"]): [
            {
                "action_count": record["action_count"],
                "objective_missile_s": record["exact"]["objective_missile_s"],
                "durations_s": record["exact"]["durations_s"],
                "min_duration_s": record["exact"]["min_duration_s"],
                "selected_slot": record["selected_slot"],
                "marginal_gain_missile_s": record["marginal_gain_missile_s"],
                "exact_evaluations": record["exact_evaluations"],
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
            "exact_evaluation_budget_per_activation": exact_budget,
            "exact_scorer": "finite-cylinder-full-occlusion-by-spatial-union",
            "challenge_design": "greedy insertion over unused drone-missile slots with exact local-delay variants",
            "selection": "sum-duration then max-min; within 1e-8 s prefer fewer actions",
        },
        "action_count_coverage": coverage,
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
