"""管理 Competition-First v3.2 的轻量建模单元合同。

该模块只冻结会改变建模决策的事实：题意双重独立重建、比较或 oracle-only
单元、首解后的异构深化、条件验证，以及事前预期与实际结果的对照。它不复制
旧工作区的大型模型组合 JSON，也不替代现有的 result、review 或论文协议。

v3.2 另外约束两件直接决定建模上限的事：
1. 核心问题必须显式标记，并且其搜索预算不得被验证与复算预算压过；
2. 核心问题必须产出结构化规律（机制、边际收益、活跃约束或权衡），
   否则结果只是"被证明没撒谎"，而没有被真正理解。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_tree
from shumozizi.knowledge.external_discussion import validate_external_discussion_protocol_if_present
from shumozizi.simple.results import read_result_index
from shumozizi.simple.review_tasks import validate_review_task_receipt
from shumozizi.simple.state import is_competition_first_v32_state, read_simple_state, utc_now

MODELING_UNITS_PATH = Path("analysis/MODELING_UNITS.json")
STOP_REASON_WHITELIST = frozenset(
    {
        "exact_certificate",
        "frozen_target_reached",
        "budget_exhausted",
        "verified_stagnation",
    }
)
_OBJECTIVE_DIRECTIONS = frozenset({"minimize", "maximize"})
_EXPECTATION_STATUSES = frozenset({"confirmed", "revised", "contradicted"})
_INSIGHT_KINDS = frozenset(
    {
        "mechanism",
        "marginal_gain",
        "active_constraint",
        "threshold",
        "tradeoff",
        "counterintuitive",
        "decision_rule",
    }
)
# 核心问题的搜索预算下限：占全部生产执行耗时的比例。低于它说明算力主要
# 花在确认当前候选没撒谎，而不是继续寻找更强候选。
CORE_SEARCH_BUDGET_SHARE = 0.4


def semantic_reconstruction_input_bindings(run_dir: Path) -> dict[str, Any]:
    """构造题意独立重建唯一允许使用的题面绑定。

    Args:
        run_dir: 当前 v3.2 运行目录。

    Returns:
        仅含 problem/ 树摘要的任务输入绑定。
    """
    problem_dir = run_dir / "problem"
    if not problem_dir.is_dir():
        raise ContractError("v3.2 题意重建缺少 problem/ 输入目录")
    return {
        "input_scope": ["problem"],
        "problem_tree_sha256": sha256_tree(problem_dir),
    }


def _require_text(value: object, label: str) -> str:
    """读取非空文本，避免用空占位符伪造已完成决策。"""
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} 必须是非空文本")
    return value.strip()


def _require_text_list(value: object, label: str, *, minimum: int = 1) -> list[str]:
    """读取去重后的非空文本列表。"""
    if not isinstance(value, list) or len(value) < minimum:
        raise ContractError(f"{label} 至少需要 {minimum} 项")
    values = [_require_text(item, f"{label}[]") for item in value]
    if len(set(values)) != len(values):
        raise ContractError(f"{label} 不得重复")
    return values


def _require_mapping(value: object, label: str) -> dict[str, Any]:
    """验证对象字段，便于错误定位到具体建模单元。"""
    if not isinstance(value, dict):
        raise ContractError(f"{label} 必须是对象")
    return value


def _require_flagged_validation(value: object, label: str) -> bool:
    """验证条件门禁配置，避免把所有题型硬塞进同一固定清单。"""
    item = _require_mapping(value, label)
    required = item.get("required")
    if not isinstance(required, bool):
        raise ContractError(f"{label}.required 必须是布尔值")
    if required:
        _require_text(item.get("trigger"), f"{label}.trigger")
        _require_text(item.get("pass_criterion"), f"{label}.pass_criterion")
    return required


def _semantic_reconstructions(run_dir: Path, value: object) -> None:
    """验证两轮题意重建均为真实 create_thread 的 problem-only 审核。"""
    reconstructions = value
    if not isinstance(reconstructions, list) or len(reconstructions) < 2:
        raise ContractError("semantic_reconstructions 至少需要两轮真实 fresh-thread 重建")
    bindings = semantic_reconstruction_input_bindings(run_dir)
    thread_ids: set[str] = set()
    reports: set[str] = set()
    for index, raw in enumerate(reconstructions):
        item = _require_mapping(raw, f"semantic_reconstructions[{index}]")
        receipt_file = _require_text(item.get("task_receipt"), f"semantic_reconstructions[{index}].task_receipt")
        report_file = _require_text(item.get("report_file"), f"semantic_reconstructions[{index}].report_file")
        receipt = validate_review_task_receipt(
            run_dir,
            receipt_file,
            expected_type="semantic_reconstruction",
            expected_report=report_file,
            expected_input_bindings=bindings,
            require_fresh_thread=True,
        )
        report = run_dir / report_file
        if not report.is_file() or not report.read_text(encoding="utf-8").strip():
            raise ContractError(f"semantic_reconstructions[{index}] 的报告为空")
        if receipt["thread_id"] in thread_ids:
            raise ContractError("两轮题意重建必须来自不同 fresh thread")
        if report_file in reports:
            raise ContractError("两轮题意重建必须各自绑定独立报告")
        thread_ids.add(receipt["thread_id"])
        reports.add(report_file)


def _route_definition(
    value: object, label: str, *, require_potential: bool
) -> tuple[str, str, float | None]:
    """读取路线 ID、数学结构和可检验的预期上限。

    核心问题额外要求声明结构利用方式和量化预期上限：只按假设、成本和风险
    选路线会系统性偏向保守路线，压低建模上限；而纯文字的"预期上限"事后无法
    与实测对照，等于没有声明。
    """
    item = _require_mapping(value, label)
    upside: float | None = None
    if require_potential:
        _require_text(item.get("structure_exploited"), f"{label}.structure_exploited")
        _require_text(item.get("expected_upside"), f"{label}.expected_upside")
        ratio = item.get("expected_improvement_ratio")
        if (
            not isinstance(ratio, (int, float))
            or isinstance(ratio, bool)
            or not math.isfinite(float(ratio))
        ):
            raise ContractError(
                f"{label}.expected_improvement_ratio 必须是有限数："
                "核心问题的预期上限要能在实验后与实测改善对照"
            )
        upside = float(ratio)
    return (
        _require_text(item.get("route_id"), f"{label}.route_id"),
        _require_text(item.get("mathematical_structure"), f"{label}.mathematical_structure"),
        upside,
    )


def _validate_unit_plan(unit: dict[str, Any], *, question_ids: set[str]) -> dict[str, Any]:
    """验证一个建模单元在实验前已经声明比较、回退和验证边界。"""
    unit_id = _require_text(unit.get("unit_id"), "unit.unit_id")
    question_id = _require_text(unit.get("question_id"), f"{unit_id}.question_id")
    if question_id not in question_ids:
        raise ContractError(f"{unit_id}.question_id 不是必答问题")
    core = unit.get("core_question")
    if not isinstance(core, bool):
        raise ContractError(
            f"{unit_id}.core_question 必须显式声明；不标出决定奖项上限的问题，"
            "预算就会被平均分配"
        )
    mode = unit.get("mode")
    if mode not in {"compare", "oracle_only"}:
        raise ContractError(f"{unit_id}.mode 必须为 compare 或 oracle_only")
    objective = _require_mapping(unit.get("objective"), f"{unit_id}.objective")
    _require_text(objective.get("exact_metric"), f"{unit_id}.objective.exact_metric")
    if objective.get("direction") not in _OBJECTIVE_DIRECTIONS:
        raise ContractError(f"{unit_id}.objective.direction 必须为 minimize 或 maximize")
    threshold = objective.get("significant_improvement_ratio")
    if threshold is None:
        # 核心问题必须事前声明"多大改善才算真的更强"，避免事后把任意结果解释为成功。
        if core:
            raise ContractError(
                f"{unit_id}.objective.significant_improvement_ratio 缺失："
                "核心问题必须事前声明相对 baseline 的显著改善阈值"
            )
        improvement_threshold = 0.0
    else:
        if (
            not isinstance(threshold, (int, float))
            or isinstance(threshold, bool)
            or not math.isfinite(float(threshold))
            or float(threshold) < 0
        ):
            raise ContractError(
                f"{unit_id}.objective.significant_improvement_ratio 必须是非负有限数"
            )
        improvement_threshold = float(threshold)
    budget = _require_mapping(unit.get("budget"), f"{unit_id}.budget")
    if budget.get("kind") != "wall_seconds":
        raise ContractError(f"{unit_id}.budget.kind 当前必须为 wall_seconds")
    tolerance = budget.get("tolerance_ratio")
    if (
        not isinstance(tolerance, (int, float))
        or isinstance(tolerance, bool)
        or not math.isfinite(float(tolerance))
        or float(tolerance) < 0
    ):
        raise ContractError(f"{unit_id}.budget.tolerance_ratio 必须是非负有限数")
    _require_text(unit.get("expected_outcome"), f"{unit_id}.expected_outcome")
    attack = _require_mapping(unit.get("first_batch_attack"), f"{unit_id}.first_batch_attack")
    _require_text(attack.get("attack"), f"{unit_id}.first_batch_attack.attack")
    _require_text(attack.get("decision"), f"{unit_id}.first_batch_attack.decision")
    refinement = _require_mapping(unit.get("refinement"), f"{unit_id}.refinement")
    families = _require_text_list(
        refinement.get("strategy_families"),
        f"{unit_id}.refinement.strategy_families",
        minimum=2,
    )
    reasons = _require_text_list(
        refinement.get("stop_reason_whitelist"),
        f"{unit_id}.refinement.stop_reason_whitelist",
    )
    unsupported = sorted(set(reasons) - STOP_REASON_WHITELIST)
    if unsupported:
        raise ContractError(f"{unit_id} 使用未授权搜索停止理由: {', '.join(unsupported)}")
    validation = _require_mapping(unit.get("validation"), f"{unit_id}.validation")
    oracle_required = _require_flagged_validation(validation.get("oracle"), f"{unit_id}.validation.oracle")
    sensitivity_required = _require_flagged_validation(
        validation.get("sensitivity"), f"{unit_id}.validation.sensitivity"
    )
    robustness_required = _require_flagged_validation(
        validation.get("robustness"), f"{unit_id}.validation.robustness"
    )
    if oracle_required:
        _require_text(validation["oracle"].get("oracle_kind"), f"{unit_id}.validation.oracle.oracle_kind")

    route_ids: list[str] = []
    expected_upsides: dict[str, float] = {}
    if mode == "compare":
        baseline_id, baseline_structure, _ = _route_definition(
            unit.get("baseline"), f"{unit_id}.baseline", require_potential=False
        )
        candidates_raw = unit.get("competitive_routes")
        if not isinstance(candidates_raw, list) or len(candidates_raw) < 2:
            raise ContractError(f"{unit_id}.competitive_routes 至少需要两条机制不同的路线")
        candidates = [
            _route_definition(
                route, f"{unit_id}.competitive_routes[{index}]", require_potential=core
            )
            for index, route in enumerate(candidates_raw)
        ]
        expected_upsides = {
            route_id: upside for route_id, _, upside in candidates if upside is not None
        }
        route_ids = [baseline_id, *(route_id for route_id, _, _ in candidates)]
        structures = [baseline_structure, *(structure for _, structure, _ in candidates)]
        if len(set(route_ids)) != len(route_ids):
            raise ContractError(f"{unit_id} 的 route_id 不得重复")
        if len(set(structures)) != len(structures):
            raise ContractError(f"{unit_id} 的竞争路线必须具有不同 mathematical_structure")
        fallback = _require_mapping(unit.get("fallback"), f"{unit_id}.fallback")
        fallback_route = _require_text(fallback.get("route_id"), f"{unit_id}.fallback.route_id")
        if fallback_route not in route_ids:
            raise ContractError(f"{unit_id}.fallback.route_id 必须引用已比较路线")
        _require_text(fallback.get("switch_condition"), f"{unit_id}.fallback.switch_condition")
    else:
        oracle = _require_mapping(unit.get("oracle"), f"{unit_id}.oracle")
        _require_text(oracle.get("oracle_kind"), f"{unit_id}.oracle.oracle_kind")
        _require_text(oracle.get("independence"), f"{unit_id}.oracle.independence")

    return {
        "unit_id": unit_id,
        "question_id": question_id,
        "core_question": core,
        "mode": mode,
        "exact_metric": objective["exact_metric"],
        "direction": objective["direction"],
        "improvement_threshold": improvement_threshold,
        "budget_tolerance_ratio": float(tolerance),
        "route_ids": route_ids,
        "expected_upsides": expected_upsides,
        "families": families,
        "stop_reasons": set(reasons),
        "oracle_required": oracle_required,
        "sensitivity_required": sensitivity_required,
        "robustness_required": robustness_required,
    }


def _production_result(
    results: dict[str, dict[str, Any]], *, result_id: object, question_id: str, label: str
) -> dict[str, Any]:
    """读取本问真实生产结果，拒绝让文字报告充当实验事实。"""
    identifier = _require_text(result_id, label)
    result = results.get(identifier)
    if result is None:
        raise ContractError(f"{label} 未绑定已登记 result_id: {identifier}")
    if (
        result.get("question_id") != question_id
        or result.get("execution_mode") != "production"
        or result.get("execution_valid") is not True
    ):
        raise ContractError(f"{label} 必须是本问 execution_valid 的 production 结果")
    return result


def _production_result_ids(
    results: dict[str, dict[str, Any]], *, value: object, question_id: str, label: str
) -> list[str]:
    """验证一组结果 ID 均为当前问题的真实生产执行。"""
    identifiers = _require_text_list(value, label)
    for identifier in identifiers:
        _production_result(results, result_id=identifier, question_id=question_id, label=label)
    return identifiers


def _better(candidate: float, incumbent: float, direction: str) -> bool:
    """按统一目标方向判断前者是否严格更优。"""
    return candidate < incumbent if direction == "minimize" else candidate > incumbent


def _improvement_ratio(baseline: float, winner: float, direction: str) -> float:
    """计算赢家相对 baseline 的正向改善比例。"""
    denominator = max(abs(baseline), 1e-12)
    if direction == "minimize":
        return (baseline - winner) / denominator
    return (winner - baseline) / denominator


def _validate_comparison_actual(
    actual: dict[str, Any], plan: dict[str, Any], results: dict[str, dict[str, Any]]
) -> None:
    """用统一 exact、实际预算和可行性事实复验 compare 单元。

    这里必须真正比较分数，而不只是确认每条路线都跑过：只验证"可行且预算公平"
    会允许一个比 baseline 更差的结果一路进入论文，等于取消了搜索下限。
    """
    comparison = _require_mapping(actual.get("comparison"), f"{plan['unit_id']}.actual.comparison")
    route_result_ids = _require_mapping(
        comparison.get("route_result_ids"), f"{plan['unit_id']}.actual.comparison.route_result_ids"
    )
    if set(route_result_ids) != set(plan["route_ids"]):
        raise ContractError(f"{plan['unit_id']} 的实际比较必须覆盖且仅覆盖已声明路线")
    scores: dict[str, float] = {}
    durations: list[float] = []
    for route_id in plan["route_ids"]:
        result = _production_result(
            results,
            result_id=route_result_ids[route_id],
            question_id=plan["question_id"],
            label=f"{plan['unit_id']}.actual.comparison.{route_id}",
        )
        metric = result.get("metrics", {}).get(plan["exact_metric"])
        if (
            not isinstance(metric, (int, float))
            or isinstance(metric, bool)
            or not math.isfinite(float(metric))
        ):
            raise ContractError(f"{plan['unit_id']} 的路线 {route_id} 缺少有限 exact 指标")
        if result.get("metrics", {}).get("feasible") is not True:
            raise ContractError(f"{plan['unit_id']} 的路线 {route_id} 缺少可行性通过事实")
        duration = result.get("duration_seconds")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or float(duration) <= 0:
            raise ContractError(f"{plan['unit_id']} 的路线 {route_id} 缺少正的实际耗时")
        scores[route_id] = float(metric)
        durations.append(float(duration))
    baseline_duration = durations[0]
    if any(
        abs(duration - baseline_duration) / baseline_duration > plan["budget_tolerance_ratio"]
        for duration in durations[1:]
    ):
        raise ContractError(f"{plan['unit_id']} 的路线实际预算不公平")
    _validate_winner_and_improvement(comparison, plan, scores)


def _validate_winner_and_improvement(
    comparison: dict[str, Any], plan: dict[str, Any], scores: dict[str, float]
) -> None:
    """要求赢家由实测 exact 决定，且核心问题真的比 baseline 更强。

    没有这道检查时，一条比 baseline 更差的路线只要"可行 + 预算公平 + 有两族
    深化 + 有规律"就能进论文，搜索强度就完全失去下限。
    """
    unit_id = plan["unit_id"]
    direction = plan["direction"]
    baseline_route = plan["route_ids"][0]
    winner = _require_text(comparison.get("winner_route_id"), f"{unit_id}.actual.comparison.winner_route_id")
    if winner not in scores:
        raise ContractError(f"{unit_id}.actual.comparison.winner_route_id 必须是已比较路线")
    measured_winner = min(scores, key=lambda key: scores[key]) if direction == "minimize" else max(
        scores, key=lambda key: scores[key]
    )
    if not math.isclose(scores[winner], scores[measured_winner], rel_tol=0.0, abs_tol=1e-9):
        raise ContractError(
            f"{unit_id} 声明的赢家 {winner} 不是实测 exact 最优路线（{measured_winner}）；"
            "赢家必须由统一 scorer 的真实结果决定"
        )
    final = plan.get("final_score")
    if final is not None and _better(scores[winner], final, direction):
        raise ContractError(
            f"{unit_id} 的最终结果比比较阶段的赢家更差；"
            "深化不能让结果退步，请回到搜索或改用赢家路线的解"
        )
    if not plan["core_question"]:
        return
    threshold = plan["improvement_threshold"]
    ratio = _improvement_ratio(scores[baseline_route], scores[winner], direction)
    if ratio < threshold:
        if comparison.get("baseline_near_bound") is not True:
            raise ContractError(
                f"{unit_id} 是核心问题，但赢家相对 baseline 仅改善 {ratio:.1%}，"
                f"低于计划声明的 {threshold:.1%}；必须继续搜索、换更强路线，"
                "或用 baseline_near_bound 与实际界证据说明已接近上限"
            )
        # baseline 已接近可证界时，"改善很小"是真实结论而不是搜索不足；
        # 此时路线预期上限落空只是同一事实的另一种说法，不再重复要求登记。
        _require_text(
            comparison.get("near_bound_evidence"),
            f"{unit_id}.actual.comparison.near_bound_evidence",
        )
        return
    _validate_route_upside_expectations(comparison, plan, scores, baseline_route)


def _validate_route_upside_expectations(
    comparison: dict[str, Any],
    plan: dict[str, Any],
    scores: dict[str, float],
    baseline_route: str,
) -> None:
    """把事前声明的路线上限与实测改善对照，避免"高上限"只是措辞。

    实测明显低于声明时不直接阻断——预期落空本身是有价值的结论——但必须显式
    登记为落空，并说明由此做了什么决定，不能继续以原声明叙述路线优势。
    """
    unit_id = plan["unit_id"]
    direction = plan["direction"]
    baseline_score = scores[baseline_route]
    shortfalls: list[str] = []
    for route_id, expected in plan["expected_upsides"].items():
        measured = _improvement_ratio(baseline_score, scores[route_id], direction)
        # 只在实测不足声明一半时判为落空，容忍正常的估计误差。
        if measured < expected * 0.5:
            shortfalls.append(f"{route_id}(声明 {expected:.1%} / 实测 {measured:.1%})")
    if not shortfalls:
        return
    review = comparison.get("upside_shortfall")
    if not isinstance(review, dict):
        raise ContractError(
            f"{unit_id} 的路线预期上限明显落空: {', '.join(sorted(shortfalls))}；"
            "必须登记 upside_shortfall，说明落空原因与由此做出的决定"
        )
    _require_text(review.get("cause"), f"{unit_id}.actual.comparison.upside_shortfall.cause")
    _require_text(review.get("decision"), f"{unit_id}.actual.comparison.upside_shortfall.decision")


def _duration_seconds(results: dict[str, dict[str, Any]], result_ids: set[str]) -> float:
    """汇总一组结果的实际执行耗时，用作可复验的预算度量。"""
    total = 0.0
    for result_id in result_ids:
        duration = results[result_id].get("duration_seconds")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
            value = float(duration)
            if math.isfinite(value) and value > 0:
                total += value
    return total


def _validate_insights(value: object, plan: dict[str, Any], results: dict[str, dict[str, Any]]) -> None:
    """要求核心问题在冻结论文口径前真的挖出规律，而不是只完成复算。

    每条规律必须绑定真实结果、说明机制并写明边界；核心问题至少需要一条
    机制、边际收益、活跃约束或权衡类规律，因为这几类才回答"为什么最优解
    是现在这个结构"。
    """
    unit_id = plan["unit_id"]
    label = f"{unit_id}.actual.insights"
    insights = value
    if not isinstance(insights, list) or not insights:
        if plan["core_question"]:
            raise ContractError(
                f"{label} 缺失：核心问题必须提炼规律（机制、边际收益、活跃约束或权衡），"
                "只做独立复算不构成理解"
            )
        return
    kinds: set[str] = set()
    identifiers: set[str] = set()
    for index, raw in enumerate(insights):
        item = _require_mapping(raw, f"{label}[{index}]")
        insight_id = _require_text(item.get("insight_id"), f"{label}[{index}].insight_id")
        if insight_id in identifiers:
            raise ContractError(f"{label} 的 insight_id 不得重复: {insight_id}")
        identifiers.add(insight_id)
        kind = item.get("kind")
        if kind not in _INSIGHT_KINDS:
            raise ContractError(
                f"{label}[{index}].kind 必须属于 " + ", ".join(sorted(_INSIGHT_KINDS))
            )
        _require_text(item.get("observation"), f"{label}[{index}].observation")
        _require_text(item.get("mechanism"), f"{label}[{index}].mechanism")
        _require_text(item.get("boundary"), f"{label}[{index}].boundary")
        _production_result_ids(
            results,
            value=item.get("evidence_result_ids"),
            question_id=plan["question_id"],
            label=f"{label}[{index}].evidence_result_ids",
        )
        kinds.add(kind)
    if plan["core_question"] and not kinds & {
        "mechanism",
        "marginal_gain",
        "active_constraint",
        "tradeoff",
    }:
        raise ContractError(
            f"{label} 只有描述性规律：核心问题至少需要一条机制、边际收益、活跃约束或权衡"
        )


def _validate_actual_unit(
    plan: dict[str, Any], raw_unit: dict[str, Any], results: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """验证事前预期已被首批攻击、深化和条件验证的实际结果回填。

    Returns:
        本单元的搜索与验证实际耗时，供全局预算倾斜检查使用。
    """
    actual = _require_mapping(raw_unit.get("actual"), f"{plan['unit_id']}.actual")
    if actual.get("expectation_status") not in _EXPECTATION_STATUSES:
        raise ContractError(f"{plan['unit_id']}.actual.expectation_status 不合法")
    _require_text(actual.get("summary"), f"{plan['unit_id']}.actual.summary")
    search_ids: set[str] = set()
    verify_ids: set[str] = set()
    attack = _require_mapping(actual.get("first_batch_attack"), f"{plan['unit_id']}.actual.first_batch_attack")
    verify_ids.update(
        _production_result_ids(
            results,
            value=attack.get("result_ids"),
            question_id=plan["question_id"],
            label=f"{plan['unit_id']}.actual.first_batch_attack.result_ids",
        )
    )
    _require_text(attack.get("conclusion"), f"{plan['unit_id']}.actual.first_batch_attack.conclusion")

    refinement = _require_mapping(actual.get("refinement"), f"{plan['unit_id']}.actual.refinement")
    first = _require_text(refinement.get("first_feasible_result_id"), f"{plan['unit_id']}.actual.refinement.first_feasible_result_id")
    final = _require_text(refinement.get("final_result_id"), f"{plan['unit_id']}.actual.refinement.final_result_id")
    _production_result(results, result_id=first, question_id=plan["question_id"], label=f"{plan['unit_id']}.first_feasible")
    final_result = _production_result(
        results, result_id=final, question_id=plan["question_id"], label=f"{plan['unit_id']}.final"
    )
    if first == final:
        raise ContractError(f"{plan['unit_id']} 不能把首个可行解直接作为最终解")
    final_metric = final_result.get("metrics", {}).get(plan["exact_metric"])
    if (
        isinstance(final_metric, (int, float))
        and not isinstance(final_metric, bool)
        and math.isfinite(float(final_metric))
    ):
        plan["final_score"] = float(final_metric)
    search_ids.update({first, final})
    family_results = _require_mapping(
        refinement.get("family_result_ids"), f"{plan['unit_id']}.actual.refinement.family_result_ids"
    )
    if set(family_results) != set(plan["families"]):
        raise ContractError(f"{plan['unit_id']} 的深化证据必须覆盖所有异构策略族")
    for family in plan["families"]:
        search_ids.update(
            _production_result_ids(
                results,
                value=family_results[family],
                question_id=plan["question_id"],
                label=f"{plan['unit_id']}.actual.refinement.family_result_ids.{family}",
            )
        )
    stop_reason = _require_text(refinement.get("stop_reason"), f"{plan['unit_id']}.actual.refinement.stop_reason")
    if stop_reason not in plan["stop_reasons"]:
        raise ContractError(f"{plan['unit_id']} 使用未在计划中白名单的停止理由")

    validation = _require_mapping(actual.get("validation"), f"{plan['unit_id']}.actual.validation")
    for name, required in (
        ("oracle", plan["oracle_required"]),
        ("sensitivity", plan["sensitivity_required"]),
        ("robustness", plan["robustness_required"]),
    ):
        result_ids = validation.get(f"{name}_result_ids", [])
        if required or result_ids not in (None, []):
            verify_ids.update(
                _production_result_ids(
                    results,
                    value=result_ids,
                    question_id=plan["question_id"],
                    label=f"{plan['unit_id']}.actual.validation.{name}_result_ids",
                )
            )
    if plan["mode"] == "compare":
        _validate_comparison_actual(actual, plan, results)
        route_result_ids = actual["comparison"]["route_result_ids"]
        search_ids.update(str(route_result_ids[route_id]) for route_id in plan["route_ids"])
    else:
        verify_ids.update(
            _production_result_ids(
                results,
                value=actual.get("oracle_result_ids"),
                question_id=plan["question_id"],
                label=f"{plan['unit_id']}.actual.oracle_result_ids",
            )
        )
    _validate_insights(actual.get("insights"), plan, results)
    # 同一结果既服务搜索又服务验证时按搜索计入，避免把深化证据算成验证开销。
    verify_ids -= search_ids
    search_seconds = _duration_seconds(results, search_ids)
    verify_seconds = _duration_seconds(results, verify_ids)
    if plan["core_question"] and verify_seconds > search_seconds:
        raise ContractError(
            f"{plan['unit_id']} 是核心问题，但验证与复算耗时 {verify_seconds:.1f}s "
            f"已超过搜索与深化耗时 {search_seconds:.1f}s；"
            "必须先继续寻找更强候选，再扩大验证"
        )
    return {
        "unit_id": plan["unit_id"],
        "core_question": plan["core_question"],
        "search_seconds": search_seconds,
        "verification_seconds": verify_seconds,
    }


def _validate_research_story(value: object, question_ids: set[str]) -> None:
    """确保论文有统一主线，并明确每个必答问题如何继承或升级。"""
    story = _require_mapping(value, "research_story")
    _require_text(story.get("central_tension"), "research_story.central_tension")
    progression = story.get("question_progression")
    if not isinstance(progression, list) or not progression:
        raise ContractError("research_story.question_progression 必须覆盖每个必答问题")
    seen: set[str] = set()
    for index, raw in enumerate(progression):
        item = _require_mapping(raw, f"research_story.question_progression[{index}]")
        question_id = _require_text(item.get("question_id"), f"research_story.question_progression[{index}].question_id")
        if question_id not in question_ids or question_id in seen:
            raise ContractError("research_story.question_progression 必须一一覆盖必答问题")
        _require_text(item.get("role"), f"research_story.question_progression[{index}].role")
        _require_text(item.get("upgrade"), f"research_story.question_progression[{index}].upgrade")
        seen.add(question_id)
    if seen != question_ids:
        raise ContractError("research_story.question_progression 缺少必答问题")


def validate_modeling_units(run_dir: Path, payload: dict[str, Any], *, require_actual: bool) -> None:
    """验证 v3.2 建模单元合同及其可选的实验完成事实。

    Args:
        run_dir: 当前运行目录。
        payload: ``MODELING_UNITS.json`` 内容。
        require_actual: 为真时要求所有单元完成真实结果回填。

    Raises:
        ContractError: 题意、路线、深化、验证或论文主线缺少生产事实。
    """
    state = read_simple_state(run_dir)
    if not is_competition_first_v32_state(state):
        raise ContractError("MODELING_UNITS 只适用于 Competition-First v3.2 运行")
    if payload.get("schema_version") != "1.0" or payload.get("run_id") != state["run_id"]:
        raise ContractError("MODELING_UNITS 的 schema_version 或 run_id 不匹配")
    # 网页讨论不是阶段门；但一旦选择登记，就必须保持本地先行和延迟揭示边界。
    validate_external_discussion_protocol_if_present(run_dir)
    question_ids = set(state["required_questions"])
    if not question_ids:
        raise ContractError("v3.2 运行必须先声明 required_questions")
    _semantic_reconstructions(run_dir, payload.get("semantic_reconstructions"))
    _validate_research_story(payload.get("research_story"), question_ids)
    raw_units = payload.get("units")
    if not isinstance(raw_units, list) or not raw_units:
        raise ContractError("MODELING_UNITS 至少需要一个建模单元")
    plans: list[dict[str, Any]] = []
    seen_units: set[str] = set()
    covered_questions: set[str] = set()
    for raw in raw_units:
        unit = _require_mapping(raw, "units[]")
        plan = _validate_unit_plan(unit, question_ids=question_ids)
        if plan["unit_id"] in seen_units:
            raise ContractError("MODELING_UNITS 的 unit_id 不得重复")
        seen_units.add(plan["unit_id"])
        covered_questions.add(plan["question_id"])
        plans.append(plan)
    if covered_questions != question_ids:
        raise ContractError("MODELING_UNITS 必须覆盖每个必答问题")
    if not any(plan["core_question"] for plan in plans):
        raise ContractError(
            "MODELING_UNITS 必须至少标记一个核心问题；"
            "每问平均用力会让决定奖项上限的问题得不到足够搜索预算"
        )
    if require_actual:
        results = {item["result_id"]: item for item in read_result_index(run_dir)["results"]}
        budgets = [
            _validate_actual_unit(plan, raw, results)
            for plan, raw in zip(plans, raw_units, strict=True)
        ]
        _require_core_budget_share(run_dir, budgets)


def _require_core_budget_share(run_dir: Path, budgets: list[dict[str, Any]]) -> None:
    """要求核心问题的搜索深化真的占据了主要生产算力。

    只看单元内部比例会漏掉另一种偏差：核心问题本身只跑了很少实验，而算力
    被平摊到次要问题或全局复算上。因此这里再核对全局份额。
    """
    core_search = sum(item["search_seconds"] for item in budgets if item["core_question"])
    total = 0.0
    for result in read_result_index(run_dir)["results"]:
        # 分母统计全部已执行结果（含 exploration 与已被替代者）：只算 current
        # production 时，把大量复算跑成 exploration 就能稀释这条检查。
        duration = result.get("duration_seconds")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
            value = float(duration)
            if math.isfinite(value) and value > 0:
                total += value
    if total <= 0:
        return
    share = core_search / total
    if share < CORE_SEARCH_BUDGET_SHARE:
        raise ContractError(
            f"核心问题搜索深化仅占实际算力 {share:.0%}，低于要求的 "
            f"{CORE_SEARCH_BUDGET_SHARE:.0%}；请把预算从复算与格式稳定性移回候选搜索"
        )


def write_modeling_units(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """原子保存已完成分析冻结的 v3.2 建模单元合同。"""
    validate_modeling_units(run_dir, payload, require_actual=False)
    document = dict(payload)
    document["updated_at"] = utc_now()
    atomic_json(run_dir / MODELING_UNITS_PATH, document)
    return document


def require_v32_modeling_plan(run_dir: Path) -> None:
    """要求 v3.2 在进入实验前完成题意冻结和轻量建模单元设计。"""
    state = read_simple_state(run_dir)
    if not is_competition_first_v32_state(state):
        return
    path = run_dir / MODELING_UNITS_PATH
    if not path.is_file():
        raise ContractError("进入实验前必须完成 analysis/MODELING_UNITS.json")
    validate_modeling_units(run_dir, load_json(path), require_actual=False)


_SUBSTANTIVE_INSIGHT_KINDS = frozenset(
    {"mechanism", "marginal_gain", "active_constraint", "tradeoff"}
)


def core_question_insights(run_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """返回核心问题已提炼的实质规律，供论文阶段检查是否真被使用。

    Args:
        run_dir: 当前运行目录。

    Returns:
        以 question_id 为键的规律列表；只包含机制、边际收益、活跃约束和权衡
        这四类能回答"为什么最优解是这个结构"的规律。
    """
    path = run_dir / MODELING_UNITS_PATH
    if not path.is_file():
        return {}
    try:
        payload = load_json(path)
    except (OSError, ValueError):
        return {}
    collected: dict[str, list[dict[str, Any]]] = {}
    for unit in payload.get("units", []):
        if not isinstance(unit, dict) or unit.get("core_question") is not True:
            continue
        question_id = unit.get("question_id")
        actual = unit.get("actual")
        if not isinstance(question_id, str) or not isinstance(actual, dict):
            continue
        for insight in actual.get("insights", []):
            if (
                isinstance(insight, dict)
                and insight.get("kind") in _SUBSTANTIVE_INSIGHT_KINDS
                and isinstance(insight.get("insight_id"), str)
            ):
                collected.setdefault(question_id, []).append(insight)
    return collected


def require_v32_experiment_evidence(run_dir: Path) -> None:
    """要求论文前的建模单元均已用真实执行完成反证、深化与对照。"""
    state = read_simple_state(run_dir)
    if not is_competition_first_v32_state(state):
        return
    path = run_dir / MODELING_UNITS_PATH
    if not path.is_file():
        raise ContractError("进入论文前缺少 analysis/MODELING_UNITS.json")
    validate_modeling_units(run_dir, load_json(path), require_actual=True)
