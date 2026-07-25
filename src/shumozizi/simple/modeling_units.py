"""管理 Competition-First v3.2 的轻量建模单元合同。

该模块只冻结会改变建模决策的事实：题意双重独立重建、比较或 oracle-only
单元、首解后的异构深化、条件验证，以及事前预期与实际结果的对照。它不复制
旧工作区的大型模型组合 JSON，也不替代现有的 result、review 或论文协议。
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


def _route_definition(value: object, label: str) -> tuple[str, str]:
    """读取路线 ID 和数学结构，明确排除仅替换求解器的伪竞争。"""
    item = _require_mapping(value, label)
    return (
        _require_text(item.get("route_id"), f"{label}.route_id"),
        _require_text(item.get("mathematical_structure"), f"{label}.mathematical_structure"),
    )


def _validate_unit_plan(unit: dict[str, Any], *, question_ids: set[str]) -> dict[str, Any]:
    """验证一个建模单元在实验前已经声明比较、回退和验证边界。"""
    unit_id = _require_text(unit.get("unit_id"), "unit.unit_id")
    question_id = _require_text(unit.get("question_id"), f"{unit_id}.question_id")
    if question_id not in question_ids:
        raise ContractError(f"{unit_id}.question_id 不是必答问题")
    mode = unit.get("mode")
    if mode not in {"compare", "oracle_only"}:
        raise ContractError(f"{unit_id}.mode 必须为 compare 或 oracle_only")
    objective = _require_mapping(unit.get("objective"), f"{unit_id}.objective")
    _require_text(objective.get("exact_metric"), f"{unit_id}.objective.exact_metric")
    if objective.get("direction") not in _OBJECTIVE_DIRECTIONS:
        raise ContractError(f"{unit_id}.objective.direction 必须为 minimize 或 maximize")
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
    if mode == "compare":
        baseline_id, baseline_structure = _route_definition(unit.get("baseline"), f"{unit_id}.baseline")
        candidates_raw = unit.get("competitive_routes")
        if not isinstance(candidates_raw, list) or len(candidates_raw) < 2:
            raise ContractError(f"{unit_id}.competitive_routes 至少需要两条机制不同的路线")
        candidates = [
            _route_definition(route, f"{unit_id}.competitive_routes[{index}]")
            for index, route in enumerate(candidates_raw)
        ]
        route_ids = [baseline_id, *(route_id for route_id, _ in candidates)]
        structures = [baseline_structure, *(structure for _, structure in candidates)]
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
        "mode": mode,
        "exact_metric": objective["exact_metric"],
        "direction": objective["direction"],
        "budget_tolerance_ratio": float(tolerance),
        "route_ids": route_ids,
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


def _validate_comparison_actual(
    actual: dict[str, Any], plan: dict[str, Any], results: dict[str, dict[str, Any]]
) -> None:
    """用统一 exact、实际预算和可行性事实复验 compare 单元。"""
    comparison = _require_mapping(actual.get("comparison"), f"{plan['unit_id']}.actual.comparison")
    route_result_ids = _require_mapping(
        comparison.get("route_result_ids"), f"{plan['unit_id']}.actual.comparison.route_result_ids"
    )
    if set(route_result_ids) != set(plan["route_ids"]):
        raise ContractError(f"{plan['unit_id']} 的实际比较必须覆盖且仅覆盖已声明路线")
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
        durations.append(float(duration))
    baseline_duration = durations[0]
    if any(
        abs(duration - baseline_duration) / baseline_duration > plan["budget_tolerance_ratio"]
        for duration in durations[1:]
    ):
        raise ContractError(f"{plan['unit_id']} 的路线实际预算不公平")


def _validate_actual_unit(plan: dict[str, Any], raw_unit: dict[str, Any], results: dict[str, dict[str, Any]]) -> None:
    """验证事前预期已被首批攻击、深化和条件验证的实际结果回填。"""
    actual = _require_mapping(raw_unit.get("actual"), f"{plan['unit_id']}.actual")
    if actual.get("expectation_status") not in _EXPECTATION_STATUSES:
        raise ContractError(f"{plan['unit_id']}.actual.expectation_status 不合法")
    _require_text(actual.get("summary"), f"{plan['unit_id']}.actual.summary")
    attack = _require_mapping(actual.get("first_batch_attack"), f"{plan['unit_id']}.actual.first_batch_attack")
    _production_result_ids(
        results,
        value=attack.get("result_ids"),
        question_id=plan["question_id"],
        label=f"{plan['unit_id']}.actual.first_batch_attack.result_ids",
    )
    _require_text(attack.get("conclusion"), f"{plan['unit_id']}.actual.first_batch_attack.conclusion")

    refinement = _require_mapping(actual.get("refinement"), f"{plan['unit_id']}.actual.refinement")
    first = _require_text(refinement.get("first_feasible_result_id"), f"{plan['unit_id']}.actual.refinement.first_feasible_result_id")
    final = _require_text(refinement.get("final_result_id"), f"{plan['unit_id']}.actual.refinement.final_result_id")
    _production_result(results, result_id=first, question_id=plan["question_id"], label=f"{plan['unit_id']}.first_feasible")
    _production_result(results, result_id=final, question_id=plan["question_id"], label=f"{plan['unit_id']}.final")
    if first == final:
        raise ContractError(f"{plan['unit_id']} 不能把首个可行解直接作为最终解")
    family_results = _require_mapping(
        refinement.get("family_result_ids"), f"{plan['unit_id']}.actual.refinement.family_result_ids"
    )
    if set(family_results) != set(plan["families"]):
        raise ContractError(f"{plan['unit_id']} 的深化证据必须覆盖所有异构策略族")
    for family in plan["families"]:
        _production_result_ids(
            results,
            value=family_results[family],
            question_id=plan["question_id"],
            label=f"{plan['unit_id']}.actual.refinement.family_result_ids.{family}",
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
        if required:
            _production_result_ids(
                results,
                value=result_ids,
                question_id=plan["question_id"],
                label=f"{plan['unit_id']}.actual.validation.{name}_result_ids",
            )
        elif result_ids not in (None, []):
            _production_result_ids(
                results,
                value=result_ids,
                question_id=plan["question_id"],
                label=f"{plan['unit_id']}.actual.validation.{name}_result_ids",
            )
    if plan["mode"] == "compare":
        _validate_comparison_actual(actual, plan, results)
    else:
        _production_result_ids(
            results,
            value=actual.get("oracle_result_ids"),
            question_id=plan["question_id"],
            label=f"{plan['unit_id']}.actual.oracle_result_ids",
        )


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
    if require_actual:
        results = {item["result_id"]: item for item in read_result_index(run_dir)["results"]}
        for plan, raw in zip(plans, raw_units, strict=True):
            _validate_actual_unit(plan, raw, results)


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


def require_v32_experiment_evidence(run_dir: Path) -> None:
    """要求论文前的建模单元均已用真实执行完成反证、深化与对照。"""
    state = read_simple_state(run_dir)
    if not is_competition_first_v32_state(state):
        return
    path = run_dir / MODELING_UNITS_PATH
    if not path.is_file():
        raise ContractError("进入论文前缺少 analysis/MODELING_UNITS.json")
    validate_modeling_units(run_dir, load_json(path), require_actual=True)
