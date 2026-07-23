"""验证题型无关几何双实现与统一优化比较器。"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from shumozizi.benchmarking.optimizer import (
    BudgetedExactScorer,
    ExactEvaluation,
    run_optimizer_benchmark,
)
from shumozizi.geometry.projection import (
    closest_point_on_segment,
    segment_intersects_closed_ball,
)
from shumozizi.geometry.quadratic import segment_intersects_closed_ball_quadratic
from shumozizi.geometry.visual import (
    export_publication_figure,
    plot_cylinder_target,
    plot_explosion_point,
    plot_finite_segment,
    plot_sphere_cloud,
    plot_trajectory3d,
    set_equal_3d_axes,
)


@pytest.mark.parametrize(
    ("start", "end", "center", "radius", "expected"),
    [
        ((0, 0, 0), (2, 0, 0), (1, 1, 0), 1.0, True),
        ((0, 0, 0), (1, 0, 0), (2, 0, 0), 1.0, True),
        ((0, 0, 0), (1, 0, 0), (3, 0, 0), 1.0, False),
        ((0, 0, 0), (0, 0, 0), (0, 0, 0), 0.0, True),
        ((0, 0, 0), (0, 0, 0), (1, 0, 0), 0.5, False),
        ((0, 0, 0), (0.5, 0, 0), (0, 0, 0), 2.0, True),
    ],
)
def test_projection_and_quadratic_oracles_agree_on_boundary_cases(
    start: tuple[float, ...],
    end: tuple[float, ...],
    center: tuple[float, ...],
    radius: float,
    expected: bool,
) -> None:
    """端点、切线、退化和全内含情形必须命中闭球体语义。"""
    assert segment_intersects_closed_ball(start, end, center, radius) is expected
    assert segment_intersects_closed_ball_quadratic(start, end, center, radius) is expected


def test_geometry_oracles_preserve_translation_and_rotation() -> None:
    """平移与刚体旋转不得改变有限线段和闭球体的相交结论。"""
    start = (-2.0, 0.25, 0.0)
    end = (3.0, 0.25, 0.0)
    center = (0.5, 1.0, 0.0)
    radius = 0.75
    translation = (10.0, -4.0, 2.0)
    translated = [
        tuple(point[index] + translation[index] for index in range(3))
        for point in (start, end, center)
    ]
    rotated = [(-point[1], point[0], point[2]) for point in (start, end, center)]
    for transformed in (translated, rotated):
        assert segment_intersects_closed_ball(*transformed, radius)
        assert segment_intersects_closed_ball_quadratic(*transformed, radius)


def test_projection_clips_to_finite_segment_endpoint() -> None:
    """无限直线投影落在线段外时必须裁剪到端点。"""
    parameter, closest, distance = closest_point_on_segment((0, 0, 0), (1, 0, 0), (2, 1, 0))
    assert parameter == 1.0
    assert closest == (1.0, 0.0, 0.0)
    assert distance == pytest.approx(2**0.5)


def test_geometry_visual_primitives_render_and_export(tmp_path: Path) -> None:
    """空间图元必须真实渲染有限对象并导出矢量与栅格格式。"""
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(5, 4))
    ax = fig.add_subplot(111, projection="3d")
    plot_finite_segment(ax, (0, 0, 0), (2, 0, 0), color="black")
    plot_trajectory3d(ax, [(0, 0, 1), (1, 0.5, 1.2), (2, 1, 1.5)], color="tab:blue")
    plot_sphere_cloud(ax, (1, 0, 0), 0.4, alpha=0.2, color="tab:cyan")
    plot_cylinder_target(ax, (2, 1), 0.25, 0, 1.0, alpha=0.25, color="tab:red")
    plot_explosion_point(ax, (1, 0, 0), color="tab:orange")
    set_equal_3d_axes(ax)

    outputs = export_publication_figure(fig, tmp_path / "geometry-scene", dpi=300)
    plt.close(fig)

    assert {path.suffix for path in outputs} == {".pdf", ".svg", ".png"}
    assert all(path.stat().st_size > 100 for path in outputs)


def test_optimizer_benchmark_uses_same_budget_seeds_and_exact_scorer() -> None:
    """所有算法必须共享 exact scorer、预算和种子，并留下完整精确轨迹。"""
    def exact_scorer(candidate: tuple[float, ...]) -> ExactEvaluation:
        x = candidate[0]
        return ExactEvaluation(objective=(x - 1.0) ** 2, feasible=x >= 0, constraint_violation=max(0.0, -x))

    def random_search(seed: int, scorer: BudgetedExactScorer) -> None:
        rng = random.Random(seed)
        for _ in range(4):
            scorer((rng.uniform(-1.0, 2.0),))

    def grid_search(seed: int, scorer: BudgetedExactScorer) -> None:
        del seed
        for value in (-1.0, 0.0, 1.0, 2.0):
            scorer((value,))

    receipt = run_optimizer_benchmark(
        {"random": random_search, "grid": grid_search},
        exact_scorer,
        evaluation_budget=4,
        seeds=[7, 11],
    )

    assert receipt["evaluation_budget"] == 4
    assert receipt["seeds"] == [7, 11]
    assert len(receipt["runs"]) == 4
    assert all(run["evaluations_used"] == 4 for run in receipt["runs"])
    grid_runs = [run for run in receipt["runs"] if run["algorithm"] == "grid"]
    assert all(run["best_exact"]["objective"] == 0.0 for run in grid_runs)


def test_optimizer_benchmark_blocks_budget_overrun() -> None:
    """算法不能超过统一 exact scorer 预算。"""
    def scorer(candidate: tuple[float, ...]) -> ExactEvaluation:
        return ExactEvaluation(objective=candidate[0], feasible=True)

    def overrun(seed: int, budgeted: BudgetedExactScorer) -> None:
        del seed
        budgeted((0.0,))
        budgeted((1.0,))

    with pytest.raises(RuntimeError, match="超过统一"):
        run_optimizer_benchmark({"overrun": overrun}, scorer, evaluation_budget=1, seeds=[1])
