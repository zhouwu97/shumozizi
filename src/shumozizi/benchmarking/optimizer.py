"""使用统一精确评分器、预算和随机种子比较优化算法。"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

Candidate = Sequence[float]


@dataclass(frozen=True)
class ExactEvaluation:
    """一次统一精确评分结果。"""

    objective: float
    feasible: bool
    constraint_violation: float = 0.0


class BudgetedExactScorer:
    """为单个算法和种子强制执行同一精确评价预算。"""

    def __init__(self, scorer: Callable[[Candidate], ExactEvaluation], budget: int) -> None:
        """初始化带预算评分器。

        Args:
            scorer: 所有算法共享的精确评分函数。
            budget: 本轮允许的最大评分次数。
        """
        if budget < 1:
            raise ValueError("evaluation_budget 必须至少为 1")
        self._scorer = scorer
        self._budget = budget
        self.evaluations: list[tuple[tuple[float, ...], ExactEvaluation]] = []

    @property
    def remaining(self) -> int:
        """返回尚可使用的精确评分次数。"""
        return self._budget - len(self.evaluations)

    def __call__(self, candidate: Candidate) -> ExactEvaluation:
        """评分一个候选，并在超预算前阻断算法。"""
        if self.remaining <= 0:
            raise RuntimeError("算法超过统一 exact scorer 评价预算")
        frozen = tuple(float(value) for value in candidate)
        evaluation = self._scorer(frozen)
        if evaluation.constraint_violation < 0:
            raise ValueError("constraint_violation 不得为负")
        self.evaluations.append((frozen, evaluation))
        return evaluation


Optimizer = Callable[[int, BudgetedExactScorer], None]


def run_optimizer_benchmark(
    algorithms: Mapping[str, Optimizer],
    exact_scorer: Callable[[Candidate], ExactEvaluation],
    *,
    evaluation_budget: int,
    seeds: Sequence[int],
    direction: str = "minimize",
) -> dict[str, Any]:
    """在统一 exact scorer、预算和种子下运行多个优化器。

    Args:
        algorithms: 算法名到执行函数的映射。函数只能通过收到的计数评分器评价候选。
        exact_scorer: 所有算法共享的精确目标与约束评分器。
        evaluation_budget: 每个算法、每个种子的最大精确评价次数。
        seeds: 所有算法共同使用的随机种子。
        direction: ``minimize`` 或 ``maximize``。

    Returns:
        包含逐轮轨迹、可行率、首次可行位置与最佳精确目标的机器收据。

    Raises:
        ValueError: 算法、预算、种子或目标方向不合法。
    """
    if not algorithms or not seeds:
        raise ValueError("至少需要一个算法和一个随机种子")
    if len(set(algorithms)) != len(algorithms) or any(not name.strip() for name in algorithms):
        raise ValueError("算法名称必须非空且唯一")
    if direction not in {"minimize", "maximize"}:
        raise ValueError("direction 必须为 minimize 或 maximize")
    if evaluation_budget < 1:
        raise ValueError("evaluation_budget 必须至少为 1")

    runs: list[dict[str, Any]] = []
    for algorithm_name, algorithm in algorithms.items():
        for seed in seeds:
            scorer = BudgetedExactScorer(exact_scorer, evaluation_budget)
            started = time.perf_counter()
            algorithm(int(seed), scorer)
            elapsed = time.perf_counter() - started
            feasible = [item for item in scorer.evaluations if item[1].feasible]
            def objective_value(
                item: tuple[tuple[float, ...], ExactEvaluation],
            ) -> float:
                """返回轨迹项的精确目标值。"""
                return item[1].objective

            best = (
                min(feasible, key=objective_value)
                if direction == "minimize"
                else max(feasible, key=objective_value)
            ) if feasible else None
            first_feasible = next(
                (index for index, (_, item) in enumerate(scorer.evaluations, start=1) if item.feasible),
                None,
            )
            runs.append(
                {
                    "algorithm": algorithm_name,
                    "seed": int(seed),
                    "evaluation_budget": evaluation_budget,
                    "evaluations_used": len(scorer.evaluations),
                    "first_feasible_evaluation": first_feasible,
                    "feasible_rate": len(feasible) / len(scorer.evaluations) if scorer.evaluations else 0.0,
                    "best_candidate": list(best[0]) if best else None,
                    "best_exact": asdict(best[1]) if best else None,
                    "elapsed_seconds": elapsed,
                    "trace": [
                        {"candidate": list(candidate), **asdict(evaluation)}
                        for candidate, evaluation in scorer.evaluations
                    ],
                }
            )
    return {
        "schema_name": "optimizer_benchmark",
        "schema_version": "1.0",
        "direction": direction,
        "evaluation_budget": evaluation_budget,
        "seeds": [int(seed) for seed in seeds],
        "algorithms": list(algorithms),
        "runs": runs,
    }
