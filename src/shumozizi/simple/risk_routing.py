"""在既有建模单元内记录前置风险攻击与双速实验分流。

这里不创建新的工作流阶段或平行状态文件。风险包只是 ``MODELING_UNITS`` 中的
分析合同：它把最可能推翻当前路线的低成本检查提前到第一次 production 运行前，
并把攻击结论转换成可供答案映射和 Author Pass 消费的主张边界。
"""

from __future__ import annotations

import math
from typing import Any

from shumozizi.core.io import ContractError

RISK_PACKAGE_VERSION = "1.0"
RISK_CHECK_KINDS = frozenset(
    {
        "nuisance_profile",
        "decomposition_counterexample",
        "blocked_holdout",
        "common_model_selection",
        "scorer_preflight",
    }
)
CLAIM_BOUNDARY_LABELS = frozenset(
    {"unconditional", "conditional_on_assumption", "sensitivity_only"}
)
RISK_OUTCOMES = frozenset({"clear", "triggered", "inconclusive"})
EXPERIMENT_ROUTES = frozenset({"fast", "deepening"})


def _text(value: object, label: str) -> str:
    """读取非空文本，拒绝把占位符写成已完成的风险判断。

    Args:
        value: 待校验字段。
        label: 面向用户的字段定位。

    Returns:
        去除首尾空白后的文本。

    Raises:
        ContractError: 字段不是非空字符串。
    """
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} 必须是非空文本")
    return value.strip()


def _mapping(value: object, label: str) -> dict[str, Any]:
    """读取对象字段。

    Args:
        value: 待校验字段。
        label: 面向用户的字段定位。

    Returns:
        原对象。

    Raises:
        ContractError: 字段不是对象。
    """
    if not isinstance(value, dict):
        raise ContractError(f"{label} 必须是对象")
    return value


def _text_list(value: object, label: str, *, minimum: int = 1) -> list[str]:
    """读取去重的文本数组。

    Args:
        value: 待校验字段。
        label: 面向用户的字段定位。
        minimum: 最少项目数。

    Returns:
        标准化后的文本列表。

    Raises:
        ContractError: 数组为空、元素非法或包含重复项。
    """
    if not isinstance(value, list):
        raise ContractError(f"{label} 必须是文本数组")
    values = [_text(item, f"{label}[]") for item in value]
    if len(values) < minimum:
        raise ContractError(f"{label} 至少需要 {minimum} 项")
    if len(values) != len(set(values)):
        raise ContractError(f"{label} 不得重复")
    return values


def _finite_nonnegative(value: object, label: str) -> float:
    """读取有限非负数。

    Args:
        value: 待校验字段。
        label: 面向用户的字段定位。

    Returns:
        浮点数值。

    Raises:
        ContractError: 数值缺失、不是有限数或为负数。
    """
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        raise ContractError(f"{label} 必须是非负有限数")
    return float(value)


def _validate_check_specifics(check: dict[str, Any], label: str) -> None:
    """校验五类高风险检查各自不能省略的最小合同。

    Args:
        check: 单个风险检查。
        label: 字段定位。

    Raises:
        ContractError: 与检查类型对应的关键结构缺失。
    """
    kind = check["kind"]
    if kind == "nuisance_profile":
        _text(check.get("target_parameter"), f"{label}.target_parameter")
        _text_list(check.get("nuisance_parameters"), f"{label}.nuisance_parameters")
        _text(check.get("profile_metric"), f"{label}.profile_metric")
        _text(check.get("near_optimal_definition"), f"{label}.near_optimal_definition")
        _text(check.get("compensation_band_output"), f"{label}.compensation_band_output")
    elif kind == "decomposition_counterexample":
        _text(check.get("decomposition"), f"{label}.decomposition")
        _text(check.get("joint_scorer"), f"{label}.joint_scorer")
        _text(check.get("minimal_counterexample"), f"{label}.minimal_counterexample")
    elif kind == "blocked_holdout":
        if check.get("split_scheme") not in {"blocked_holdout", "rolling_origin"}:
            raise ContractError(
                f"{label}.split_scheme 必须为 blocked_holdout 或 rolling_origin"
            )
        if check.get("random_point_split_prohibited") is not True:
            raise ContractError(f"{label} 必须明确禁止 random point split 泄漏")
        _text(check.get("heldout_unit"), f"{label}.heldout_unit")
    elif kind == "common_model_selection":
        for field in (
            "common_data_window",
            "common_split",
            "common_scorer",
            "common_budget",
        ):
            _text(check.get(field), f"{label}.{field}")
        _finite_nonnegative(check.get("improvement_threshold"), f"{label}.improvement_threshold")
    elif kind == "scorer_preflight":
        case_count = check.get("manual_case_count")
        if not isinstance(case_count, int) or isinstance(case_count, bool) or not 3 <= case_count <= 5:
            raise ContractError(f"{label}.manual_case_count 必须为 3–5 的整数")
        _text(check.get("expected_ordering"), f"{label}.expected_ordering")


def validate_risk_package(
    value: object,
    *,
    label: str,
    core_question: bool,
    unit_kind: str,
    semantic_risk_signals: set[str] | frozenset[str],
) -> dict[str, Any] | None:
    """验证可选的前置风险包与双速实验合同。

    旧运行没有本字段时保持兼容；一旦登记，所有检查都必须在第一次 production
    运行前完成，并明确其可能改变的路线、主张边界或建议。

    Args:
        value: ``unit.risk_package`` 原始值。
        label: 字段定位前缀。
        core_question: 当前单元是否为核心问题。
        unit_kind: 当前题型。
        semantic_risk_signals: 已由 ``question_delta`` 识别出的语义风险。

    Returns:
        标准化风险包；字段缺失时返回 ``None``。

    Raises:
        ContractError: 风险包没有定义低成本攻击、分流条件或主张标签。
    """
    if value is None:
        return None
    package = _mapping(value, label)
    if package.get("schema_version") != RISK_PACKAGE_VERSION:
        raise ContractError(f"{label}.schema_version 必须为 {RISK_PACKAGE_VERSION}")
    checks_raw = package.get("checks")
    if not isinstance(checks_raw, list) or not checks_raw:
        raise ContractError(f"{label}.checks 至少需要一项最低成本风险检查")
    checks: list[dict[str, Any]] = []
    check_ids: set[str] = set()
    check_kinds: set[str] = set()
    planned_seconds = 0.0
    for index, raw in enumerate(checks_raw):
        item_label = f"{label}.checks[{index}]"
        check = _mapping(raw, item_label)
        check_id = _text(check.get("check_id"), f"{item_label}.check_id")
        if check_id in check_ids:
            raise ContractError(f"{label}.checks.check_id 不得重复")
        kind = check.get("kind")
        if kind not in RISK_CHECK_KINDS:
            raise ContractError(
                f"{item_label}.kind 必须为 " + "、".join(sorted(RISK_CHECK_KINDS))
            )
        if check.get("before_first_production") is not True:
            raise ContractError(f"{item_label} 必须在第一次 production 前完成")
        _text(check.get("purpose"), f"{item_label}.purpose")
        _text(check.get("decision_value"), f"{item_label}.decision_value")
        _text(check.get("required_evidence"), f"{item_label}.required_evidence")
        estimated_seconds = _finite_nonnegative(
            check.get("estimated_seconds"), f"{item_label}.estimated_seconds"
        )
        _validate_check_specifics({**check, "kind": kind}, item_label)
        checks.append({**check, "check_id": check_id, "kind": kind})
        check_ids.add(check_id)
        check_kinds.add(str(kind))
        planned_seconds += estimated_seconds

    declared_labels = set(_text_list(package.get("claim_labels"), f"{label}.claim_labels", minimum=3))
    if declared_labels != CLAIM_BOUNDARY_LABELS:
        raise ContractError(
            f"{label}.claim_labels 必须完整声明 "
            + "、".join(sorted(CLAIM_BOUNDARY_LABELS))
        )
    fast = _mapping(package.get("fast_route"), f"{label}.fast_route")
    entry_conditions = _text_list(
        fast.get("entry_conditions"), f"{label}.fast_route.entry_conditions", minimum=4
    )
    _text(fast.get("stop_rule"), f"{label}.fast_route.stop_rule")
    triggers_raw = package.get("deepening_triggers")
    if not isinstance(triggers_raw, list) or not triggers_raw:
        raise ContractError(f"{label}.deepening_triggers 至少需要一个风险触发条件")
    trigger_ids: set[str] = set()
    triggers: list[dict[str, str]] = []
    for index, raw in enumerate(triggers_raw):
        item_label = f"{label}.deepening_triggers[{index}]"
        trigger = _mapping(raw, item_label)
        trigger_id = _text(trigger.get("trigger_id"), f"{item_label}.trigger_id")
        if trigger_id in trigger_ids:
            raise ContractError(f"{label}.deepening_triggers.trigger_id 不得重复")
        triggers.append(
            {
                "trigger_id": trigger_id,
                "condition": _text(trigger.get("condition"), f"{item_label}.condition"),
                "action": _text(trigger.get("action"), f"{item_label}.action"),
            }
        )
        trigger_ids.add(trigger_id)

    if core_question and unit_kind in {"optimization", "coordination"} and "scorer_preflight" not in check_kinds:
        raise ContractError(f"{label} 的核心优化/协同题必须包含 scorer_preflight")
    if (
        {"multiple_entities", "decompose_then_combine"} & set(semantic_risk_signals)
        and "decomposition_counterexample" not in check_kinds
    ):
        raise ContractError(f"{label} 的多主体或分解风险必须包含 decomposition_counterexample")

    advisories: list[str] = []
    if planned_seconds > 15 * 60:
        advisories.append(
            f"最低成本风险包预计 {planned_seconds:.0f}s，超过 15 分钟目标；"
            "这只提示压缩或并行设计，不允许跳过正确性攻击。"
        )
    return {
        "checks": checks,
        "check_ids": check_ids,
        "check_kinds": check_kinds,
        "planned_seconds": planned_seconds,
        "fast_entry_conditions": entry_conditions,
        "deepening_triggers": triggers,
        "advisories": advisories,
    }


def default_risk_package(
    *,
    question_id: str,
    core_question: bool,
    unit_kind: str,
    semantic_risk_signals: set[str] | frozenset[str],
) -> dict[str, Any]:
    """生成可编辑的最低成本风险包模板。

    Args:
        question_id: 当前问题 ID。
        core_question: 是否核心问题。
        unit_kind: 题型。
        semantic_risk_signals: 现有问题差分识别的风险。

    Returns:
        可以直接写入 ``unit.risk_package`` 的结构化模板。
    """
    checks: list[dict[str, Any]] = []
    signals = set(semantic_risk_signals)
    if {"multiple_entities", "decompose_then_combine"} & signals:
        checks.append(
            {
                "check_id": "joint-counterexample",
                "kind": "decomposition_counterexample",
                "before_first_production": True,
                "purpose": "用最小反例检验分别求解后组合是否仍等价于联合目标。",
                "decision_value": "若排序翻转，则改为联合 scorer 并进入深化路线。",
                "required_evidence": "两个可比较方案在分解与联合评分下的排序。",
                "estimated_seconds": 300,
                "decomposition": "分别求解后组合的候选路线。",
                "joint_scorer": "当前问题的统一联合 exact scorer。",
                "minimal_counterexample": "构造局部最优组合但联合目标排序反转的最小实例。",
            }
        )
    if unit_kind in {"optimization", "coordination"} and core_question:
        checks.append(
            {
                "check_id": "scorer-preflight",
                "kind": "scorer_preflight",
                "before_first_production": True,
                "purpose": "先确认 scorer 对人工可解释案例的排序符合题意。",
                "decision_value": "排序失败时先修订 endpoint 或 scorer，再运行 baseline。",
                "required_evidence": "3–5 个人工案例的预期排序与实际排序。",
                "estimated_seconds": 300,
                "manual_case_count": 3,
                "expected_ordering": "同步满足优于错开满足，硬约束失守不得获得高分。",
            }
        )
    if unit_kind == "data_modeling":
        checks.append(
            {
                "check_id": "blocked-holdout",
                "kind": "blocked_holdout",
                "before_first_production": True,
                "purpose": "用连续留出块检验模型没有通过随机切分泄漏未来信息。",
                "decision_value": "若留出方向与训练方向相反，则进入深化路线并重新选择验证方案。",
                "required_evidence": "连续留出或滚动留出的独立评分。",
                "estimated_seconds": 600,
                "split_scheme": "blocked_holdout",
                "random_point_split_prohibited": True,
                "heldout_unit": "按时间连续的留出区间。",
            }
        )
    if not checks:
        checks.append(
            {
                "check_id": "common-model-selection",
                "kind": "common_model_selection",
                "before_first_production": True,
                "purpose": "在共同数据和 scorer 下确认自然 baseline 与 challenger 可公平比较。",
                "decision_value": "若比较条件不一致，则先修订实验合同，不登记正式赢家。",
                "required_evidence": "共同窗口、共同切分、共同 scorer 与共同预算的配置记录。",
                "estimated_seconds": 300,
                "common_data_window": "当前题面冻结的数据窗口。",
                "common_split": "同一留出或同一固定评价集合。",
                "common_scorer": "同一个 exact scorer。",
                "common_budget": "同一墙钟或评价次数预算。",
                "improvement_threshold": 0.0,
            }
        )
    return {
        "schema_version": RISK_PACKAGE_VERSION,
        "checks": checks,
        "claim_labels": sorted(CLAIM_BOUNDARY_LABELS),
        "fast_route": {
            "entry_conditions": [
                "目标与聚合解释唯一，或已由最小反例区分。",
                "baseline 与结构不同 challenger 使用共同 scorer。",
                "未发现结构不可辨识、分解失效、硬约束冲突或数据泄漏。",
                "challenger 已停止快速改善，或 baseline 有合理上界证据。",
            ],
            "stop_rule": "普通问题完成 baseline、自然比较和关键验证后停止新增无决策价值实验。",
        },
        "deepening_triggers": [
            {
                "trigger_id": "objective-divergence",
                "condition": "两个合法目标解释产生不同主结果。",
                "action": "返回 analysis 比较目标后果。",
            },
            {
                "trigger_id": "nonidentifiability",
                "condition": "nuisance profile 出现宽补偿带或多峰近优集合。",
                "action": "把主张改为条件结果或范围，并增加 profile 证据。",
            },
            {
                "trigger_id": "challenger-improving",
                "condition": "challenger 仍快速改善或达到显著收益。",
                "action": "继续同一统一 scorer 下的结构深化。",
            },
            {
                "trigger_id": "holdout-reversal",
                "condition": "留出结果与训练结果方向相反。",
                "action": "重新检查切分、泄漏和模型选择。",
            },
            {
                "trigger_id": "oracle-conflict",
                "condition": "独立 oracle、硬约束或性质测试冲突。",
                "action": "暂停主张并返回 analysis 或 experiment 修复。",
            },
        ],
        "generated_for_question": question_id,
    }


def validate_risk_assessment(
    value: object,
    *,
    package: dict[str, Any] | None,
    results: dict[str, dict[str, Any]],
    question_id: str,
    label: str,
    require_before_first_production: bool,
) -> dict[str, Any] | None:
    """验证风险攻击事实、路线选择和自动主张边界。

    Args:
        value: ``actual.risk_assessment`` 原始值。
        package: 已标准化的风险包；为 ``None`` 时不要求实际记录。
        results: 按结果 ID 索引的执行结果。
        question_id: 当前问题 ID。
        label: 字段定位前缀。
        require_before_first_production: 为真时复验攻击结果确实先于 production。

    Returns:
        可直接附加到 ``objective_answer`` 的主张边界摘要；无风险包时为 ``None``。

    Raises:
        ContractError: 结果没有真实执行、路线与证据不一致，或主张边界掩盖结构攻击。
    """
    if package is None:
        return None
    assessment = _mapping(value, label)
    outcomes_raw = assessment.get("outcomes")
    if not isinstance(outcomes_raw, list):
        raise ContractError(f"{label}.outcomes 必须覆盖全部风险检查")
    expected_ids = set(package["check_ids"])
    seen_ids: set[str] = set()
    outcome_kinds: list[str] = []
    result_ids: list[str] = []
    result_times: list[str] = []
    for index, raw in enumerate(outcomes_raw):
        item_label = f"{label}.outcomes[{index}]"
        item = _mapping(raw, item_label)
        check_id = _text(item.get("check_id"), f"{item_label}.check_id")
        if check_id not in expected_ids or check_id in seen_ids:
            raise ContractError(f"{label}.outcomes 必须一一对应已声明 check_id")
        outcome = item.get("outcome")
        if outcome not in RISK_OUTCOMES:
            raise ContractError(
                f"{item_label}.outcome 必须为 " + "、".join(sorted(RISK_OUTCOMES))
            )
        _text(item.get("finding"), f"{item_label}.finding")
        evidence_ids = _text_list(item.get("result_ids"), f"{item_label}.result_ids")
        for result_id in evidence_ids:
            result = results.get(result_id)
            if result is None:
                raise ContractError(f"{item_label}.result_ids 引用了未知结果 {result_id}")
            if result.get("question_id") != question_id or result.get("execution_valid") is not True:
                raise ContractError(
                    f"{item_label}.result_ids 必须绑定本问 execution_valid 真实执行"
                )
            created_at = result.get("created_at")
            if not isinstance(created_at, str) or not created_at:
                raise ContractError(f"{item_label}.result_ids 缺少 created_at")
            result_times.append(created_at)
        seen_ids.add(check_id)
        outcome_kinds.append(str(outcome))
        result_ids.extend(evidence_ids)
    if seen_ids != expected_ids:
        missing = sorted(expected_ids - seen_ids)
        raise ContractError(f"{label}.outcomes 缺少风险检查: " + "、".join(missing))

    if assessment.get("completed_before_first_production") is not True:
        raise ContractError(f"{label}.completed_before_first_production 必须为 true")
    if require_before_first_production:
        production_times = [
            str(item["created_at"])
            for item in results.values()
            if item.get("question_id") == question_id
            and item.get("execution_mode") == "production"
            and item.get("execution_valid") is True
            and isinstance(item.get("created_at"), str)
        ]
        if not production_times:
            raise ContractError(f"{label} 尚无 production 结果，无法复验前置攻击时序")
        first_production = min(production_times)
        late = [value for value in result_times if value > first_production]
        if late:
            raise ContractError(f"{label} 的风险攻击晚于首次 production 结果")

    route = assessment.get("route")
    if route not in EXPERIMENT_ROUTES:
        raise ContractError(f"{label}.route 必须为 fast 或 deepening")
    _text(assessment.get("route_rationale"), f"{label}.route_rationale")
    has_trigger = any(item == "triggered" for item in outcome_kinds)
    has_uncertainty = any(item == "inconclusive" for item in outcome_kinds)
    if route == "fast" and (has_trigger or has_uncertainty):
        raise ContractError(f"{label} 已出现风险触发或不确定证据，不能进入 fast 路线")
    if route == "deepening" and not (has_trigger or has_uncertainty):
        raise ContractError(f"{label} 缺少触发证据，不能把常规工作伪装成深化路线")

    boundary = _mapping(assessment.get("claim_boundary"), f"{label}.claim_boundary")
    boundary_label = boundary.get("label")
    if boundary_label not in CLAIM_BOUNDARY_LABELS:
        raise ContractError(
            f"{label}.claim_boundary.label 必须为 "
            + "、".join(sorted(CLAIM_BOUNDARY_LABELS))
        )
    statement = _text(boundary.get("statement"), f"{label}.claim_boundary.statement")
    if (has_trigger or has_uncertainty) and boundary_label == "unconditional":
        raise ContractError(
            f"{label} 的结构攻击已触发，正式主张必须降为条件结果或范围"
        )
    assumptions: list[str] = []
    range_result_ids: list[str] = []
    if boundary_label == "conditional_on_assumption":
        assumptions = _text_list(boundary.get("assumptions"), f"{label}.claim_boundary.assumptions")
    elif boundary_label == "sensitivity_only":
        range_result_ids = _text_list(
            boundary.get("range_result_ids"), f"{label}.claim_boundary.range_result_ids", minimum=1
        )
        for result_id in range_result_ids:
            result = results.get(result_id)
            if result is None or result.get("question_id") != question_id or result.get("execution_valid") is not True:
                raise ContractError(
                    f"{label}.claim_boundary.range_result_ids 必须绑定本问真实执行"
                )
    return {
        "label": boundary_label,
        "statement": statement,
        "assumptions": assumptions,
        "range_result_ids": range_result_ids,
        "risk_result_ids": list(dict.fromkeys(result_ids)),
        "route": route,
        "advisories": list(package.get("advisories", [])),
    }
