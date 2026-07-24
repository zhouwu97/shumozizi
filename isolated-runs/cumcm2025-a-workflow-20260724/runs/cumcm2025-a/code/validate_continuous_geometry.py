"""为有限圆柱离散表面构造可证明的时长上下界。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import model_core as core
from model_core import Action

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "results" / "raw"


def _actions(filename: str) -> list[Action]:
    """读取已登记问题结果中的动作。"""

    payload = json.loads((RAW / filename).read_text(encoding="utf-8"))
    return [
        Action(
            item["drone"],
            item["heading_deg"],
            item["speed_mps"],
            item["release_time_s"],
            item["fuse_delay_s"],
            item["assigned_missile"],
        )
        for item in payload["result"]["actions"]
    ]


def _cover_radius(n_theta: int, n_z: int, n_radial: int) -> float:
    """返回圆柱侧面和端面采样网格的欧氏覆盖半径上界。"""

    half_chord = 2.0 * core.TARGET_RADIUS * np.sin(np.pi / (2.0 * n_theta))
    half_height = core.TARGET_HEIGHT / (2.0 * (n_z - 1))
    half_radial = core.TARGET_RADIUS / (2.0 * (n_radial - 1))
    side_bound = np.hypot(half_chord, half_height)
    disk_bound = np.hypot(half_chord, half_radial)
    return float(max(side_bound, disk_bound))


def _score_with_radius(
    actions: list[Action],
    missiles: tuple[str, ...],
    targets: np.ndarray,
    radius: float,
    temporal_tolerance: float,
) -> dict[str, object]:
    """在不修改生产源码的前提下用指定有效半径复算。"""

    original = core.CLOUD_RADIUS
    try:
        core.CLOUD_RADIUS = radius
        return core.score_solution(
            actions,
            missiles,
            targets,
            temporal_tolerance=temporal_tolerance,
        )
    finally:
        core.CLOUD_RADIUS = original


def main() -> int:
    """生成连续圆柱时长证书和时间网格收敛记录。"""

    configurations = {
        "Q1": ("q1.json", ("M1",)),
        "Q2": ("q2.json", ("M1",)),
        "Q3": ("q3.json", ("M1",)),
        "Q4": ("q4.json", ("M1",)),
        "Q5": ("q5.json", ("M1", "M2", "M3")),
    }
    n_theta, n_z, n_radial = 180, 21, 13
    dense_targets = core.cylinder_surface_samples(n_theta, n_z, n_radial)
    production_targets = core.cylinder_surface_samples(72, 9, 5)
    cover_radius = _cover_radius(n_theta, n_z, n_radial)
    conservative_radius = core.CLOUD_RADIUS - cover_radius
    questions: dict[str, object] = {}
    maximum_interval_width = 0.0
    maximum_time_difference = 0.0

    for question, (filename, missiles) in configurations.items():
        actions = _actions(filename)
        upper = _score_with_radius(
            actions,
            missiles,
            dense_targets,
            core.CLOUD_RADIUS,
            0.00005,
        )
        lower = _score_with_radius(
            actions,
            missiles,
            dense_targets,
            conservative_radius,
            0.00005,
        )
        time_scores = {
            str(step): _score_with_radius(
                actions, missiles, production_targets, core.CLOUD_RADIUS, step
            )["objective_missile_s"]
            for step in (0.0002, 0.0001, 0.00005)
        }
        interval_width = float(
            upper["objective_upper_bound_missile_s"]
            - lower["objective_lower_bound_missile_s"]
        )
        time_difference = float(
            max(time_scores.values()) - min(time_scores.values())
        )
        maximum_interval_width = max(maximum_interval_width, interval_width)
        maximum_time_difference = max(maximum_time_difference, time_difference)
        questions[question] = {
            "continuous_duration_lower_bound_missile_s": lower[
                "objective_lower_bound_missile_s"
            ],
            "continuous_duration_upper_bound_missile_s": upper[
                "objective_upper_bound_missile_s"
            ],
            "sampled_duration_upper_bound_missile_s": upper[
                "objective_upper_bound_missile_s"
            ],
            "spatial_bound_width_missile_s": interval_width,
            "lower_durations_s": lower["durations_s"],
            "upper_durations_s": upper["durations_s"],
            "lower_temporal_uncertainty_missile_s": lower[
                "temporal_uncertainty_missile_s"
            ],
            "upper_temporal_uncertainty_missile_s": upper[
                "temporal_uncertainty_missile_s"
            ],
            "time_refinement_objective_missile_s": time_scores,
            "time_refinement_range_missile_s": time_difference,
        }

    payload = {
        "schema_version": "1.0",
        "method": {
            "surface_grid": {
                "n_theta": n_theta,
                "n_z": n_z,
                "n_radial": n_radial,
                "sample_count": int(len(dense_targets)),
            },
            "surface_cover_radius_upper_bound_m": cover_radius,
            "certified_cloud_radius_m": conservative_radius,
            "proof": (
                "任意连续圆柱表面点距最近网格点不超过 rho；固定观察点时，"
                "线段集合的 Hausdorff 距离不超过端点位移，点到线段距离、"
                "对烟幕取 min、对目标取 max 均保持 1-Lipschitz。故以 10-rho "
                "为半径得到连续覆盖下界，以 10 为半径的网格结果给出时长上界。"
            ),
            "temporal_method": "adaptive Lipschitz interval classification with 303 m/s bound",
            "temporal_tolerances_s": [0.0002, 0.0001, 0.00005],
        },
        "questions": questions,
        "metrics": {
            "surface_cover_radius_upper_bound_m": cover_radius,
            "maximum_spatial_bound_width_missile_s": maximum_interval_width,
            "maximum_time_refinement_range_missile_s": maximum_time_difference,
        },
    }
    output = RAW / "continuous_geometry_certificate.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["metrics"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
