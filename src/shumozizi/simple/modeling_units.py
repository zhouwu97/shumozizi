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
_ENDPOINT_RESOLUTION_STATUSES = frozenset({"determined", "comparison_planned"})
_PROMOTION_STATUSES = frozenset({"promoted", "fallback_selected", "redesign_required"})
_PROMOTION_CHECKS = frozenset(
    {
        "route_upgrade_passed",
        "endpoint_consistent",
        "guard_constraints_passed",
        "decision_stable",
    }
)
_QUALIFICATION_FAILURE_KINDS = frozenset(
    {
        "model_repair",
        "objective_redesign",
        "endpoint_unresolved",
        "search_insufficient",
        "validation_insufficient",
        "answer_rejected",
        "missing_natural_baseline",
    }
)
_ROLLBACK_TARGETS = frozenset({"analysis", "experiment"})
_CHECK_OPERATORS = frozenset({"<", "<=", "==", "!=", ">=", ">"})
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
_PLANNING_PLACEHOLDERS = frozenset(
    {"待填写", "待补充", "待分析", "待确认", "todo", "tbd", "placeholder"}
)
_RECONSTRUCTION_ROLES = frozenset(
    {"faithful_reconstruction", "semantic_adversary"}
)
_SEMANTIC_RISK_SIGNALS = frozenset(
    {
        "multiple_entities",
        "nested_quantifiers",
        "aggregation_language",
        "objective_form_ambiguity",
        "question_entity_change",
        "decompose_then_combine",
        "shared_resources",
        "multi_stage",
    }
)
_DECOMPOSITION_MODES = frozenset(
    {"joint", "exact_decomposition", "heuristic_decomposition", "initialization_only"}
)
_COUNTEREXAMPLE_RANKINGS = frozenset({"A>B", "B>A", "tie"})


def semantic_reconstruction_input_bindings(
    run_dir: Path, *, role: str | None = None
) -> dict[str, Any]:
    """构造题意独立重建唯一允许使用的题面绑定。

    Args:
        run_dir: 当前 v3.2 运行目录。

    Returns:
        仅含 problem/ 树摘要的任务输入绑定。
    """
    problem_dir = run_dir / "problem"
    if not problem_dir.is_dir():
        raise ContractError("v3.2 题意重建缺少 problem/ 输入目录")
    bindings: dict[str, Any] = {
        "input_scope": ["problem"],
        "problem_tree_sha256": sha256_tree(problem_dir),
    }
    if role is not None:
        if role not in _RECONSTRUCTION_ROLES:
            raise ContractError("题意重建角色不受支持")
        bindings["reconstruction_role"] = role
        bindings["required_analysis"] = (
            [
                "decision_variables",
                "evaluated_entities",
                "success_event",
                "temporal_aggregation",
                "cross_entity_aggregation",
                "required_output",
            ]
            if role == "faithful_reconstruction"
            else [
                "quantifier_order",
                "aggregation_alternatives",
                "decomposition_equivalence",
                "question_delta",
                "minimal_counterexample",
            ]
        )
    return bindings


def _require_text(value: object, label: str) -> str:
    """读取非空文本，避免用空占位符伪造已完成决策。"""
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} 必须是非空文本")
    return value.strip()


def _require_substantive_plan_text(value: object, label: str) -> str:
    """读取已经形成决策的规划文本，拒绝短标签和待办占位符。"""
    text = _require_text(value, label)
    if len(text) < 8 or any(marker in text.casefold() for marker in _PLANNING_PLACEHOLDERS):
        raise ContractError(f"{label} 必须是已完成的实质规划文本，不能使用短标签或待办占位符")
    return text


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


def _semantic_reconstructions(
    run_dir: Path, value: object, *, require_asymmetric_roles: bool
) -> None:
    """验证两轮 problem-only 重建的独立性与非对称职责。"""
    reconstructions = value
    if not isinstance(reconstructions, list) or len(reconstructions) < 2:
        raise ContractError("semantic_reconstructions 至少需要两轮真实 fresh-thread 重建")
    if require_asymmetric_roles and len(reconstructions) != 2:
        raise ContractError("MODELING_UNITS 1.3 只使用两轮重建：一次忠实重建和一次语义攻击")
    thread_ids: set[str] = set()
    reports: set[str] = set()
    roles: set[str] = set()
    for index, raw in enumerate(reconstructions):
        item = _require_mapping(raw, f"semantic_reconstructions[{index}]")
        role = item.get("role")
        if require_asymmetric_roles:
            if role not in _RECONSTRUCTION_ROLES:
                raise ContractError(
                    f"semantic_reconstructions[{index}].role 必须为 "
                    "faithful_reconstruction 或 semantic_adversary"
                )
            roles.add(str(role))
        bindings = semantic_reconstruction_input_bindings(
            run_dir, role=str(role) if role in _RECONSTRUCTION_ROLES else None
        )
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
    if require_asymmetric_roles and roles != _RECONSTRUCTION_ROLES:
        raise ContractError("两轮题意重建必须分别承担忠实重建与语义攻击职责")


def _text_list_allow_empty(value: object, label: str) -> list[str]:
    """读取允许为空的非重复文本列表。"""
    if not isinstance(value, list):
        raise ContractError(f"{label} 必须是文本数组")
    values = [_require_text(item, f"{label}[]") for item in value]
    if len(set(values)) != len(values):
        raise ContractError(f"{label} 不得重复")
    return values


def _validate_question_delta(value: object, label: str) -> dict[str, Any]:
    """识别相邻问题新增对象、共享资源和聚合风险。"""
    item = _require_mapping(value, label)
    inherits = item.get("inherits_from")
    if inherits is not None:
        _require_text(inherits, f"{label}.inherits_from")
    added_entities = _text_list_allow_empty(item.get("added_entities"), f"{label}.added_entities")
    added_resources = _text_list_allow_empty(
        item.get("added_resources"), f"{label}.added_resources"
    )
    shared_resources = _text_list_allow_empty(
        item.get("shared_resources"), f"{label}.shared_resources"
    )
    changed_constraints = _text_list_allow_empty(
        item.get("changed_constraints"), f"{label}.changed_constraints"
    )
    signals = _text_list_allow_empty(
        item.get("semantic_risk_signals"), f"{label}.semantic_risk_signals"
    )
    unsupported = sorted(set(signals) - _SEMANTIC_RISK_SIGNALS)
    if unsupported:
        raise ContractError(f"{label} 包含未知语义风险信号: {', '.join(unsupported)}")
    _require_substantive_plan_text(
        item.get("possible_objective_change"), f"{label}.possible_objective_change"
    )
    must_recheck = item.get("must_recheck_aggregation")
    if not isinstance(must_recheck, bool):
        raise ContractError(f"{label}.must_recheck_aggregation 必须是布尔值")
    triggered = bool(
        added_entities
        or added_resources
        or shared_resources
        or changed_constraints
        or signals
    )
    if triggered and not must_recheck:
        raise ContractError(
            f"{label} 已登记实体、资源、约束或语义信号变化，必须重新检查目标聚合"
        )
    return {"semantic_high_risk": must_recheck, "semantic_risk_signals": set(signals)}


def _validate_semantic_counterexample(value: object, label: str) -> dict[str, str]:
    """验证能让至少两个解释产生不同排序的最小反例。"""
    item = _require_mapping(value, label)
    _require_substantive_plan_text(item.get("case_a"), f"{label}.case_a")
    _require_substantive_plan_text(item.get("case_b"), f"{label}.case_b")
    _require_substantive_plan_text(
        item.get("expected_preference"), f"{label}.expected_preference"
    )
    rankings = _require_mapping(item.get("candidate_rankings"), f"{label}.candidate_rankings")
    if len(rankings) < 2:
        raise ContractError(f"{label}.candidate_rankings 至少需要两个解释")
    normalized: dict[str, str] = {}
    for objective_id, ranking in rankings.items():
        identifier = _require_text(objective_id, f"{label}.candidate_rankings objective_id")
        if ranking not in _COUNTEREXAMPLE_RANKINGS:
            raise ContractError(f"{label}.{identifier} 必须为 A>B、B>A 或 tie")
        normalized[identifier] = str(ranking)
    if len(set(normalized.values())) < 2:
        raise ContractError(f"{label} 必须让至少两个解释产生不同排序")
    return normalized


def _validate_aggregation_contract(value: object, label: str) -> None:
    """要求 endpoint 明确原子事件、资源、主体与时间四层聚合。"""
    item = _require_mapping(value, label)
    for field in (
        "atomic_success",
        "within_entity",
        "across_resources",
        "across_entities",
        "temporal",
        "quantifier_order",
    ):
        _require_substantive_plan_text(item.get(field), f"{label}.{field}")


def _validate_scorer_preflight(value: object, label: str) -> dict[str, str]:
    """验证正式搜索前计划的 3--5 个评分语义案例。"""
    item = _require_mapping(value, label)
    cases = item.get("cases")
    if not isinstance(cases, list) or not 3 <= len(cases) <= 5:
        raise ContractError(f"{label}.cases 必须包含 3--5 个人工语义案例")
    seen: set[str] = set()
    for index, raw in enumerate(cases):
        case = _require_mapping(raw, f"{label}.cases[{index}]")
        case_id = _require_text(case.get("case_id"), f"{label}.cases[{index}].case_id")
        if case_id in seen:
            raise ContractError(f"{label}.cases.case_id 不得重复")
        seen.add(case_id)
        for field in ("construction", "expected_ranking", "rationale"):
            _require_substantive_plan_text(
                case.get(field), f"{label}.cases[{index}].{field}"
            )
    _require_substantive_plan_text(item.get("pass_criterion"), f"{label}.pass_criterion")
    return {
        str(case["case_id"]): str(case["expected_ranking"])
        for case in cases
    }


def _validate_route_composition(value: object, label: str) -> str:
    """声明分解路线与联合目标的关系，禁止把局部最优冒充全局最优。"""
    item = _require_mapping(value, label)
    mode = item.get("mode")
    if mode not in _DECOMPOSITION_MODES:
        raise ContractError(
            f"{label}.mode 必须为 joint、exact_decomposition、"
            "heuristic_decomposition 或 initialization_only"
        )
    if mode == "joint":
        _require_text(item.get("joint_rationale"), f"{label}.joint_rationale")
    elif mode == "exact_decomposition":
        _require_substantive_plan_text(
            item.get("equivalence_basis"), f"{label}.equivalence_basis"
        )
    else:
        _require_substantive_plan_text(
            item.get("joint_scorer_followup"), f"{label}.joint_scorer_followup"
        )
    return str(mode)


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


def _validate_answer_contract(
    value: object,
    label: str,
    *,
    derive_qualification: bool,
    require_semantic_contract: bool,
    semantic_high_risk: bool,
    core_question: bool,
) -> dict[str, Any]:
    """验证实验前逐问直接答案合同，避免先跑模型再倒推回答口径。"""
    contract = _require_mapping(value, label)
    _require_text(contract.get("required_output"), f"{label}.required_output")
    _require_text(contract.get("decision_scope"), f"{label}.decision_scope")
    _require_text(contract.get("natural_baseline"), f"{label}.natural_baseline")
    _require_text(contract.get("fallback_rule"), f"{label}.fallback_rule")
    endpoint = _require_mapping(contract.get("primary_endpoint"), f"{label}.primary_endpoint")
    endpoint_id = endpoint.get("endpoint_id")
    if derive_qualification:
        endpoint_id = _require_text(endpoint_id, f"{label}.primary_endpoint.endpoint_id")
    _require_text(endpoint.get("name"), f"{label}.primary_endpoint.name")
    _require_text(endpoint.get("definition"), f"{label}.primary_endpoint.definition")
    if require_semantic_contract:
        _require_text(endpoint.get("formula"), f"{label}.primary_endpoint.formula")
        _validate_aggregation_contract(
            endpoint.get("aggregation"), f"{label}.primary_endpoint.aggregation"
        )
    _require_text(
        endpoint.get("exact_metric_alignment"),
        f"{label}.primary_endpoint.exact_metric_alignment",
    )
    _require_text(contract.get("primary_criterion"), f"{label}.primary_criterion")
    resolution = _require_mapping(
        contract.get("endpoint_resolution"), f"{label}.endpoint_resolution"
    )
    status = resolution.get("status")
    if status not in _ENDPOINT_RESOLUTION_STATUSES:
        raise ContractError(
            f"{label}.endpoint_resolution.status 必须为 determined 或 comparison_planned"
        )
    _require_text(resolution.get("basis"), f"{label}.endpoint_resolution.basis")
    candidate_ids = [endpoint_id] if isinstance(endpoint_id, str) else []
    if derive_qualification and status == "comparison_planned":
        candidates = resolution.get("candidate_endpoints")
        if not isinstance(candidates, list) or len(candidates) < 2:
            raise ContractError(
                f"{label}.endpoint_resolution.candidate_endpoints 至少需要两个候选 endpoint"
            )
        candidate_ids: list[str] = []
        for index, raw in enumerate(candidates):
            item = _require_mapping(
                raw, f"{label}.endpoint_resolution.candidate_endpoints[{index}]"
            )
            candidate_ids.append(
                _require_text(
                    item.get("endpoint_id"),
                    f"{label}.endpoint_resolution.candidate_endpoints[{index}].endpoint_id",
                )
            )
            _require_text(
                item.get("definition"),
                f"{label}.endpoint_resolution.candidate_endpoints[{index}].definition",
            )
            _require_text(
                item.get("problem_text_basis"),
                f"{label}.endpoint_resolution.candidate_endpoints[{index}].problem_text_basis",
            )
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ContractError(f"{label}.endpoint_resolution 的候选 endpoint_id 不得重复")
        if endpoint_id not in candidate_ids:
            raise ContractError(
                f"{label}.primary_endpoint.endpoint_id 必须出现在候选 endpoint 中"
            )
        _require_text(
            resolution.get("decision_rule"), f"{label}.endpoint_resolution.decision_rule"
        )
    counterexample_rankings: dict[str, str] = {}
    scorer_cases: dict[str, str] = {}
    semantic_high_risk = semantic_high_risk or status == "comparison_planned"
    if require_semantic_contract and semantic_high_risk:
        counterexample_rankings = _validate_semantic_counterexample(
            contract.get("semantic_counterexample"), f"{label}.semantic_counterexample"
        )
    if require_semantic_contract and semantic_high_risk and core_question:
        scorer_cases = _validate_scorer_preflight(
            contract.get("semantic_scorer_preflight"),
            f"{label}.semantic_scorer_preflight",
        )
    return {
        "primary_endpoint_id": endpoint_id,
        "endpoint_candidate_ids": candidate_ids,
        "endpoint_resolution_status": status,
        "counterexample_rankings": counterexample_rankings,
        "scorer_cases": scorer_cases,
        "semantic_high_risk_from_endpoint": semantic_high_risk,
    }


def _validate_unit_plan(
    unit: dict[str, Any],
    *,
    question_ids: set[str],
    require_decision_contract: bool,
    schema_version: str,
) -> dict[str, Any]:
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
    require_semantic_contract = schema_version == "1.3"
    delta = {"semantic_high_risk": False, "semantic_risk_signals": set()}
    if require_semantic_contract:
        delta = _validate_question_delta(
            unit.get("question_delta"), f"{unit_id}.question_delta"
        )
    answer_contract: dict[str, Any] = {}
    if require_decision_contract:
        answer_contract = _validate_answer_contract(
            unit.get("answer_contract"),
            f"{unit_id}.answer_contract",
            derive_qualification=schema_version in {"1.2", "1.3"},
            require_semantic_contract=require_semantic_contract,
            semantic_high_risk=bool(delta["semantic_high_risk"]),
            core_question=core,
        )
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
    composition_modes: dict[str, str] = {}
    expected_upsides: dict[str, float] = {}
    fallback_route: str | None = None
    if mode == "compare":
        baseline = _require_mapping(unit.get("baseline"), f"{unit_id}.baseline")
        baseline_id, baseline_structure, _ = _route_definition(
            baseline, f"{unit_id}.baseline", require_potential=False
        )
        if require_semantic_contract:
            composition_modes[baseline_id] = _validate_route_composition(
                baseline.get("composition"), f"{unit_id}.baseline.composition"
            )
        if require_decision_contract:
            _require_text(
                baseline.get("natural_rationale"), f"{unit_id}.baseline.natural_rationale"
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
        if require_semantic_contract:
            for index, (route_id, _structure, _upside) in enumerate(candidates):
                composition_modes[route_id] = _validate_route_composition(
                    candidates_raw[index].get("composition"),
                    f"{unit_id}.competitive_routes[{index}].composition",
                )
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
        if (
            require_semantic_contract
            and any(mode != "joint" for mode in composition_modes.values())
            and "decompose_then_combine" not in delta["semantic_risk_signals"]
        ):
            raise ContractError(
                f"{unit_id} 含分解路线，question_delta.semantic_risk_signals "
                "必须登记 decompose_then_combine"
            )
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
        "fallback_route": fallback_route,
        "require_decision_contract": require_decision_contract,
        "derive_qualification": schema_version in {"1.2", "1.3"},
        "semantic_high_risk": bool(
            delta["semantic_high_risk"]
            or answer_contract.get("semantic_high_risk_from_endpoint")
        ),
        "composition_modes": composition_modes,
        **answer_contract,
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


def _finite_metric(result: dict[str, Any], metric: str, label: str) -> float:
    """读取登记结果中的有限数值指标。"""
    value = result.get("metrics", {}).get(metric)
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise ContractError(f"{label} 引用的指标 {metric} 不是有限数")
    return float(value)


def _compare_metric(value: float, operator: str, threshold: float) -> bool:
    """执行预登记阈值比较，不接受任意表达式。"""
    if operator == "<":
        return value < threshold
    if operator == "<=":
        return value <= threshold
    if operator == "==":
        return math.isclose(value, threshold, rel_tol=0.0, abs_tol=1e-12)
    if operator == "!=":
        return not math.isclose(value, threshold, rel_tol=0.0, abs_tol=1e-12)
    if operator == ">=":
        return value >= threshold
    return value > threshold


def _evaluate_metric_checks(
    checks: object,
    *,
    results: dict[str, dict[str, Any]],
    question_id: str,
    label: str,
    minimum: int = 1,
) -> tuple[bool, list[str]]:
    """从真实结果指标计算一组 guard 或稳定性检查。"""
    if not isinstance(checks, list) or len(checks) < minimum:
        raise ContractError(f"{label} 至少需要 {minimum} 项结果指标检查")
    failed: list[str] = []
    for index, raw in enumerate(checks):
        check_label = f"{label}[{index}]"
        check = _require_mapping(raw, check_label)
        result_id = _require_text(check.get("result_id"), f"{check_label}.result_id")
        metric = _require_text(check.get("metric"), f"{check_label}.metric")
        operator = check.get("operator")
        if operator not in _CHECK_OPERATORS:
            raise ContractError(
                f"{check_label}.operator 必须属于 {', '.join(sorted(_CHECK_OPERATORS))}"
            )
        threshold_raw = check.get("threshold")
        if (
            not isinstance(threshold_raw, (int, float))
            or isinstance(threshold_raw, bool)
            or not math.isfinite(float(threshold_raw))
        ):
            raise ContractError(f"{check_label}.threshold 必须是有限数")
        result = _production_result(
            results,
            result_id=result_id,
            question_id=question_id,
            label=f"{check_label}.result_id",
        )
        value = _finite_metric(result, metric, check_label)
        if not _compare_metric(value, str(operator), float(threshold_raw)):
            failed.append(
                f"{result_id}.{metric}={value:g} 未满足 {operator} {float(threshold_raw):g}"
            )
    return not failed, failed


def evaluate_route_upgrade(
    plan: dict[str, Any],
    scores: dict[str, float],
    winner_route_id: str,
    comparison: dict[str, Any],
) -> dict[str, Any]:
    """由 exact 分数、事前阈值和真实界证据计算路线晋级价值。"""
    baseline_route = plan["route_ids"][0]
    ratio = _improvement_ratio(
        scores[baseline_route], scores[winner_route_id], plan["direction"]
    )
    passed = ratio >= plan["improvement_threshold"]
    near_bound = comparison.get("baseline_near_bound") is True
    near_bound_evidence: str | None = None
    if near_bound and not passed:
        near_bound_evidence = _require_text(
            comparison.get("near_bound_evidence"),
            f"{plan['unit_id']}.actual.comparison.near_bound_evidence",
        )
        # 当自然 baseline 已接近真实可证界时，改善很小是问题上限而非搜索失败。
        passed = True
    return {
        "passed": passed,
        "measured_improvement_ratio": ratio,
        "required_improvement_ratio": plan["improvement_threshold"],
        "baseline_near_bound": near_bound,
        "near_bound_evidence": near_bound_evidence,
    }


def evaluate_endpoint_consistency(
    actual: dict[str, Any],
    plan: dict[str, Any],
    results: dict[str, dict[str, Any]],
    checks: object,
    *,
    label: str,
) -> dict[str, Any]:
    """裁决 endpoint 是否最终确定且未导致合理口径下的路线翻转。"""
    resolution = _require_mapping(actual.get("actual_endpoint_resolution"), label)
    status = resolution.get("status")
    selected = resolution.get("selected_endpoint_id")
    _require_text(resolution.get("problem_text_basis"), f"{label}.problem_text_basis")
    _production_result_ids(
        results,
        value=resolution.get("evidence_result_ids"),
        question_id=plan["question_id"],
        label=f"{label}.evidence_result_ids",
    )
    winners = _require_mapping(resolution.get("winner_route_ids"), f"{label}.winner_route_ids")
    expected_endpoint_ids = set(plan["endpoint_candidate_ids"])
    if not winners or set(winners) != expected_endpoint_ids:
        raise ContractError(
            f"{label}.winner_route_ids 必须完整覆盖预登记候选 endpoint: "
            + ", ".join(sorted(expected_endpoint_ids))
        )
    winner_values: set[str] = set()
    for endpoint_id, value in winners.items():
        route_id = _require_text(value, f"{label}.winner_route_ids.{endpoint_id}")
        if route_id not in plan["route_ids"]:
            raise ContractError(
                f"{label}.winner_route_ids.{endpoint_id} 必须引用已真实比较的路线"
            )
        winner_values.add(route_id)
    metrics_passed, failures = _evaluate_metric_checks(
        checks,
        results=results,
        question_id=plan["question_id"],
        label=f"{label}.checks",
    )
    if len(winner_values) > 1:
        failures.append("合理 endpoint 下赢家路线翻转")
    if status != "determined":
        failures.append("actual endpoint 尚未裁决为 determined")
    if selected != plan.get("primary_endpoint_id"):
        failures.append("最终 endpoint 与事前 primary endpoint 不一致")
    return {
        "passed": metrics_passed and not failures,
        "selected_endpoint_id": selected,
        "failures": failures,
    }


def evaluate_guards(
    checks: object,
    *,
    results: dict[str, dict[str, Any]],
    question_id: str,
    label: str,
) -> dict[str, Any]:
    """由登记结果中的 guard 指标计算约束是否通过。"""
    passed, failures = _evaluate_metric_checks(
        checks, results=results, question_id=question_id, label=label
    )
    return {"passed": passed, "failures": failures}


def evaluate_decision_stability(
    checks: object,
    *,
    results: dict[str, dict[str, Any]],
    question_id: str,
    label: str,
) -> dict[str, Any]:
    """由行动漂移或翻转率等真实指标计算决策稳定性。"""
    passed, failures = _evaluate_metric_checks(
        checks, results=results, question_id=question_id, label=label
    )
    return {"passed": passed, "failures": failures}


def derive_answer_qualification(
    actual: dict[str, Any],
    plan: dict[str, Any],
    results: dict[str, dict[str, Any]],
    scores: dict[str, float],
) -> dict[str, Any]:
    """从生产结果派生唯一逐问答案资格，不信任作者填写的结论。"""
    label = f"{plan['unit_id']}.actual.qualification_evidence"
    evidence = _require_mapping(actual.get("qualification_evidence"), label)
    comparison = _require_mapping(actual.get("comparison"), f"{plan['unit_id']}.actual.comparison")
    winner = _require_text(
        comparison.get("winner_route_id"),
        f"{plan['unit_id']}.actual.comparison.winner_route_id",
    )
    upgrade = evaluate_route_upgrade(plan, scores, winner, comparison)
    endpoint = evaluate_endpoint_consistency(
        actual, plan, results, evidence.get("endpoint_checks"),
        label=f"{plan['unit_id']}.actual.actual_endpoint_resolution",
    )
    guards = evaluate_guards(
        evidence.get("guards"), results=results, question_id=plan["question_id"],
        label=f"{label}.guards",
    )
    stability = evaluate_decision_stability(
        evidence.get("decision_stability"),
        results=results, question_id=plan["question_id"],
        label=f"{label}.decision_stability",
    )
    checks = {
        "route_upgrade_passed": upgrade["passed"],
        "endpoint_consistent": endpoint["passed"],
        "guard_constraints_passed": guards["passed"],
        "decision_stable": stability["passed"],
    }
    details = {
        "route_upgrade": upgrade,
        "endpoint": endpoint,
        "guards": guards,
        "decision_stability": stability,
    }
    if all(checks.values()):
        return {
            "status": "promoted",
            "route_id": winner,
            "result_id": actual["refinement"]["final_result_id"],
            "checks": checks,
            "details": details,
        }

    fallback_evidence = evidence.get("fallback")
    fallback_passed = False
    fallback_details: dict[str, Any] = {}
    if isinstance(fallback_evidence, dict) and endpoint["passed"]:
        fallback_guards = evaluate_guards(
            fallback_evidence.get("guards"),
            results=results, question_id=plan["question_id"],
            label=f"{label}.fallback.guards",
        )
        fallback_stability = evaluate_decision_stability(
            fallback_evidence.get("decision_stability"),
            results=results, question_id=plan["question_id"],
            label=f"{label}.fallback.decision_stability",
        )
        fallback_details = {
            "guards": fallback_guards,
            "decision_stability": fallback_stability,
        }
        fallback_passed = fallback_guards["passed"] and fallback_stability["passed"]
    if fallback_passed:
        fallback_route = plan["fallback_route"]
        return {
            "status": "fallback_selected",
            "route_id": fallback_route,
            "result_id": comparison["route_result_ids"][fallback_route],
            "checks": checks,
            "details": {**details, "fallback": fallback_details},
        }

    if not endpoint["passed"]:
        failure_kind, rollback_target = "endpoint_unresolved", "analysis"
    elif not guards["passed"] or not stability["passed"]:
        failure_kind, rollback_target = "validation_insufficient", "experiment"
    else:
        failure_kind, rollback_target = "search_insufficient", "experiment"
    return {
        "status": "redesign_required",
        "failure_kind": failure_kind,
        "rollback_target": rollback_target,
        "checks": checks,
        "details": details,
    }


def _validate_comparison_actual(
    actual: dict[str, Any], plan: dict[str, Any], results: dict[str, dict[str, Any]]
) -> dict[str, float]:
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
    _validate_winner_and_improvement(
        comparison,
        plan,
        scores,
        promotion_decision=(
            actual.get("promotion_decision")
            if not plan["derive_qualification"]
            else None
        ),
    )
    return scores


def _validate_winner_and_improvement(
    comparison: dict[str, Any],
    plan: dict[str, Any],
    scores: dict[str, float],
    *,
    promotion_decision: object,
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
        if plan["derive_qualification"]:
            # 1.2 由答案资格派生器决定 fallback 或回退，比较层只保留实测事实。
            return
        if (
            isinstance(promotion_decision, dict)
            and promotion_decision.get("status") == "fallback_selected"
            and promotion_decision.get("route_upgrade_passed") is False
        ):
            # 弱赢家没有资格成为主答案，但可以触发事前声明的可靠 fallback。
            return
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


def _require_boolean(value: object, label: str) -> bool:
    """读取显式布尔结论，拒绝用缺失字段把失败检查默认为通过。"""
    if not isinstance(value, bool):
        raise ContractError(f"{label} 必须是布尔值")
    return value


def _validate_promotion_decision(
    actual: dict[str, Any], plan: dict[str, Any], results: dict[str, dict[str, Any]]
) -> None:
    """验证比较赢家是否有资格晋级为主答案，或是否正确启用回退。"""
    if plan["mode"] != "compare":
        return
    unit_id = plan["unit_id"]
    label = f"{unit_id}.actual.promotion_decision"
    decision = _require_mapping(actual.get("promotion_decision"), label)
    status = decision.get("status")
    if status not in _PROMOTION_STATUSES:
        raise ContractError(
            f"{label}.status 必须为 promoted、fallback_selected 或 redesign_required"
        )
    checks = {
        name: _require_boolean(decision.get(name), f"{label}.{name}")
        for name in _PROMOTION_CHECKS
    }
    _production_result_ids(
        results,
        value=decision.get("evidence_result_ids"),
        question_id=plan["question_id"],
        label=f"{label}.evidence_result_ids",
    )
    _require_text(decision.get("rationale"), f"{label}.rationale")

    comparison = actual["comparison"]
    refinement = actual["refinement"]
    winner = comparison["winner_route_id"]
    if status == "promoted":
        if not all(checks.values()):
            failed = ", ".join(sorted(name for name, passed in checks.items() if not passed))
            raise ContractError(
                f"{unit_id} 的主路线晋级检查失败 ({failed})，不能标记 promoted；"
                "应选择可靠 fallback，或返回 analysis/experiment 重设计"
            )
        selected_route = _require_text(decision.get("selected_route_id"), f"{label}.selected_route_id")
        selected_result = _require_text(
            decision.get("selected_result_id"), f"{label}.selected_result_id"
        )
        if selected_route != winner or selected_result != refinement["final_result_id"]:
            raise ContractError(
                f"{unit_id} 的 promoted 主答案必须使用 exact 赢家及其深化后的 final 结果"
            )
        _production_result(
            results,
            result_id=selected_result,
            question_id=plan["question_id"],
            label=f"{label}.selected_result_id",
        )
        return

    if status == "fallback_selected":
        selected_route = _require_text(decision.get("selected_route_id"), f"{label}.selected_route_id")
        selected_result = _require_text(
            decision.get("selected_result_id"), f"{label}.selected_result_id"
        )
        expected_result = comparison["route_result_ids"].get(plan["fallback_route"])
        if selected_route != plan["fallback_route"] or selected_result != expected_result:
            raise ContractError(f"{unit_id} 只能启用事前声明且已真实比较的 fallback")
        if not all(
            checks[name]
            for name in ("endpoint_consistent", "guard_constraints_passed", "decision_stable")
        ):
            raise ContractError(
                f"{unit_id} 的 fallback 仍有端点、guard 或决策稳定性失败，必须返回重设计"
            )
        failed_winner_checks = _require_text_list(
            decision.get("failed_winner_checks"), f"{label}.failed_winner_checks"
        )
        unknown = sorted(set(failed_winner_checks) - _PROMOTION_CHECKS)
        if unknown:
            raise ContractError(f"{label}.failed_winner_checks 含未知检查: {', '.join(unknown)}")
        _require_text(decision.get("fallback_trigger"), f"{label}.fallback_trigger")
        _production_result(
            results,
            result_id=selected_result,
            question_id=plan["question_id"],
            label=f"{label}.selected_result_id",
        )
        return

    rollback_target = decision.get("rollback_target")
    if rollback_target not in {"analysis", "experiment"}:
        raise ContractError(f"{label}.rollback_target 必须为 analysis 或 experiment")
    if all(checks.values()):
        raise ContractError(f"{unit_id} 的所有晋级检查均通过，不能标记 redesign_required")
    raise ContractError(
        f"{unit_id} 的主答案尚未冻结：晋级检查失败，必须返回 {rollback_target} 重设计"
    )


def _validate_derived_qualification(
    actual: dict[str, Any],
    plan: dict[str, Any],
    results: dict[str, dict[str, Any]],
    scores: dict[str, float],
) -> dict[str, Any]:
    """验证可选人工快照与系统派生答案资格完全一致。"""
    qualification = derive_answer_qualification(actual, plan, results, scores)
    declared = actual.get("promotion_decision")
    if declared is None:
        return qualification
    decision = _require_mapping(
        declared, f"{plan['unit_id']}.actual.promotion_decision"
    )
    expected = {
        "status": qualification["status"],
        "selected_route_id": qualification.get("route_id"),
        "selected_result_id": qualification.get("result_id"),
        "rollback_target": qualification.get("rollback_target"),
        "failure_kind": qualification.get("failure_kind"),
    }
    actual_snapshot = {key: decision.get(key) for key in expected}
    if actual_snapshot != expected:
        raise ContractError(
            f"{plan['unit_id']}.actual.promotion_decision 与系统派生答案资格不一致；"
            "不得人工覆盖 route upgrade、endpoint、guard 或稳定性结论"
        )
    for name, passed in qualification["checks"].items():
        if decision.get(name) != passed:
            raise ContractError(
                f"{plan['unit_id']}.actual.promotion_decision.{name} 与系统计算不一致"
            )
    return qualification


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


def _validate_semantic_scorer_preflight_actual(
    run_dir: Path,
    actual: dict[str, Any],
    plan: dict[str, Any],
    results: dict[str, dict[str, Any]],
    search_ids: set[str],
) -> str | None:
    """确认高风险核心问题在正式路线搜索前先通过评分语义案例。"""
    expected_cases = dict(plan.get("scorer_cases", {}))
    expected_count = len(expected_cases)
    if expected_count == 0:
        return None
    label = f"{plan['unit_id']}.actual.semantic_scorer_preflight_result_id"
    result_id = _require_text(actual.get("semantic_scorer_preflight_result_id"), label)
    result = _production_result(
        results,
        result_id=result_id,
        question_id=plan["question_id"],
        label=label,
    )
    metrics = result.get("metrics", {})
    case_count = metrics.get("semantic_case_count")
    pass_rate = metrics.get("semantic_case_pass_rate")
    if (
        not isinstance(case_count, (int, float))
        or isinstance(case_count, bool)
        or int(case_count) != expected_count
    ):
        raise ContractError(f"{label} 必须报告计划中的 {expected_count} 个语义案例")
    if (
        not isinstance(pass_rate, (int, float))
        or isinstance(pass_rate, bool)
        or not math.isclose(float(pass_rate), 1.0, rel_tol=0.0, abs_tol=1e-12)
    ):
        raise ContractError(f"{label} 的评分器未通过全部语义排序案例，不能接受路线搜索")
    raw_cases: list[dict[str, Any]] | None = None
    for output_file in result.get("output_files", []):
        if not isinstance(output_file, str) or not output_file.lower().endswith(".json"):
            continue
        try:
            output = load_json(run_dir / output_file)
        except (OSError, ValueError):
            continue
        candidate_cases = output.get("semantic_cases")
        if isinstance(candidate_cases, list):
            raw_cases = candidate_cases
            break
    if raw_cases is None:
        raise ContractError(f"{label} 的真实 JSON 输出必须包含 semantic_cases 逐案例记录")
    observed: dict[str, dict[str, Any]] = {}
    for index, case in enumerate(raw_cases):
        if not isinstance(case, dict):
            raise ContractError(f"{label}.semantic_cases[{index}] 必须是对象")
        case_id = _require_text(
            case.get("case_id"), f"{label}.semantic_cases[{index}].case_id"
        )
        if case_id in observed:
            raise ContractError(f"{label}.semantic_cases.case_id 不得重复")
        expected = _require_text(
            case.get("expected_ranking"),
            f"{label}.semantic_cases[{index}].expected_ranking",
        )
        actual_ranking = _require_text(
            case.get("actual_ranking"),
            f"{label}.semantic_cases[{index}].actual_ranking",
        )
        if (
            case_id not in expected_cases
            or expected != expected_cases[case_id]
            or case.get("passed") is not True
            or actual_ranking != expected_cases[case_id]
        ):
            raise ContractError(f"{label} 的案例 {case_id} 未得到预期排序")
        observed[case_id] = case
    if set(observed) != set(expected_cases):
        raise ContractError(f"{label} 的逐案例输出必须覆盖且仅覆盖计划案例")
    result_order = {identifier: index for index, identifier in enumerate(results)}
    later_or_missing = [
        identifier
        for identifier in search_ids
        if result_order.get(identifier, -1) <= result_order.get(result_id, -1)
    ]
    if later_or_missing:
        raise ContractError(
            f"{label} 必须早于 baseline、竞争路线和深化搜索登记；"
            "先测试评分器奖励什么，再测试优化器"
        )
    return result_id


def _validate_actual_unit(
    run_dir: Path,
    plan: dict[str, Any],
    raw_unit: dict[str, Any],
    results: dict[str, dict[str, Any]],
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
        scores = _validate_comparison_actual(actual, plan, results)
        route_result_ids = actual["comparison"]["route_result_ids"]
        search_ids.update(str(route_result_ids[route_id]) for route_id in plan["route_ids"])
        if plan["require_decision_contract"]:
            if plan["derive_qualification"]:
                qualification = _validate_derived_qualification(
                    actual, plan, results, scores
                )
                if qualification["status"] == "redesign_required":
                    raise ContractError(
                        f"{plan['unit_id']} 尚无可提交答案："
                        f"{qualification['failure_kind']}，必须返回 "
                        f"{qualification['rollback_target']}"
                    )
            else:
                _validate_promotion_decision(actual, plan, results)
    else:
        verify_ids.update(
            _production_result_ids(
                results,
                value=actual.get("oracle_result_ids"),
                question_id=plan["question_id"],
                label=f"{plan['unit_id']}.actual.oracle_result_ids",
            )
        )
    preflight_result_id = _validate_semantic_scorer_preflight_actual(
        run_dir, actual, plan, results, search_ids
    )
    if preflight_result_id is not None:
        verify_ids.add(preflight_result_id)
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


def _validate_research_story(
    value: object,
    question_ids: set[str],
    *,
    require_progression_contract: bool,
) -> None:
    """确保论文有统一主线，并明确每个必答问题如何继承或升级。"""
    story = _require_mapping(value, "research_story")
    text_reader = _require_substantive_plan_text if require_progression_contract else _require_text
    text_reader(story.get("central_tension"), "research_story.central_tension")
    if require_progression_contract:
        text_reader(
            story.get("central_mathematical_object"),
            "research_story.central_mathematical_object",
        )
    progression = story.get("question_progression")
    if not isinstance(progression, list) or not progression:
        raise ContractError("research_story.question_progression 必须覆盖每个必答问题")
    seen: set[str] = set()
    for index, raw in enumerate(progression):
        item = _require_mapping(raw, f"research_story.question_progression[{index}]")
        question_id = _require_text(item.get("question_id"), f"research_story.question_progression[{index}].question_id")
        if question_id not in question_ids or question_id in seen:
            raise ContractError("research_story.question_progression 必须一一覆盖必答问题")
        label = f"research_story.question_progression[{index}]"
        text_reader(item.get("role"), f"{label}.role")
        text_reader(item.get("upgrade"), f"{label}.upgrade")
        if require_progression_contract:
            inherited = item.get("inherits_from")
            if not isinstance(inherited, list):
                raise ContractError(f"{label}.inherits_from 必须是问题 ID 列表")
            inherited_ids = [_require_text(value, f"{label}.inherits_from[]") for value in inherited]
            if len(set(inherited_ids)) != len(inherited_ids):
                raise ContractError(f"{label}.inherits_from 不得重复")
            invalid = sorted(set(inherited_ids) - seen)
            if invalid:
                raise ContractError(
                    f"{label}.inherits_from 只能引用此前已定义的问题: {', '.join(invalid)}"
                )
            for field in (
                "inherited_object",
                "new_difficulty",
                "new_mechanism",
                "why_previous_insufficient",
                "answer_increment",
            ):
                text_reader(item.get(field), f"{label}.{field}")
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
    schema_version = payload.get("schema_version")
    if schema_version not in {"1.0", "1.1", "1.2", "1.3"} or payload.get("run_id") != state["run_id"]:
        raise ContractError("MODELING_UNITS 的 schema_version 或 run_id 不匹配")
    # 网页讨论不是阶段门；但一旦选择登记，就必须保持本地先行和延迟揭示边界。
    validate_external_discussion_protocol_if_present(run_dir)
    question_ids = set(state["required_questions"])
    if not question_ids:
        raise ContractError("v3.2 运行必须先声明 required_questions")
    _semantic_reconstructions(
        run_dir,
        payload.get("semantic_reconstructions"),
        require_asymmetric_roles=schema_version == "1.3",
    )
    _validate_research_story(
        payload.get("research_story"),
        question_ids,
        require_progression_contract=schema_version in {"1.2", "1.3"},
    )
    raw_units = payload.get("units")
    if not isinstance(raw_units, list) or not raw_units:
        raise ContractError("MODELING_UNITS 至少需要一个建模单元")
    plans: list[dict[str, Any]] = []
    seen_units: set[str] = set()
    covered_questions: set[str] = set()
    question_unit_counts: dict[str, int] = {}
    for raw in raw_units:
        unit = _require_mapping(raw, "units[]")
        plan = _validate_unit_plan(
            unit,
            question_ids=question_ids,
            require_decision_contract=schema_version in {"1.1", "1.2", "1.3"},
            schema_version=schema_version,
        )
        if plan["unit_id"] in seen_units:
            raise ContractError("MODELING_UNITS 的 unit_id 不得重复")
        seen_units.add(plan["unit_id"])
        covered_questions.add(plan["question_id"])
        question_unit_counts[plan["question_id"]] = (
            question_unit_counts.get(plan["question_id"], 0) + 1
        )
        plans.append(plan)
    if covered_questions != question_ids:
        raise ContractError("MODELING_UNITS 必须覆盖每个必答问题")
    if schema_version in {"1.2", "1.3"}:
        duplicates = sorted(
            question_id
            for question_id, count in question_unit_counts.items()
            if count != 1
        )
        if duplicates:
            raise ContractError(
                f"MODELING_UNITS {schema_version} 每个必答问题必须恰有一个答案单元: "
                + ", ".join(duplicates)
            )
    if not any(plan["core_question"] for plan in plans):
        raise ContractError(
            "MODELING_UNITS 必须至少标记一个核心问题；"
            "每问平均用力会让决定奖项上限的问题得不到足够搜索预算"
        )
    if require_actual:
        results = {item["result_id"]: item for item in read_result_index(run_dir)["results"]}
        budgets = [
            _validate_actual_unit(run_dir, plan, raw, results)
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
    existing_path = run_dir / MODELING_UNITS_PATH
    if existing_path.is_file():
        existing = load_json(existing_path)
        old_routes = {
            route.get("route_id")
            for unit in existing.get("units", [])
            if isinstance(unit, dict)
            for route in [unit.get("baseline"), *unit.get("competitive_routes", [])]
            if isinstance(route, dict) and isinstance(route.get("route_id"), str)
        }
        new_routes = {
            route.get("route_id")
            for unit in payload.get("units", [])
            if isinstance(unit, dict)
            for route in [unit.get("baseline"), *unit.get("competitive_routes", [])]
            if isinstance(route, dict) and isinstance(route.get("route_id"), str)
        }
        if new_routes - old_routes:
            from shumozizi.simple.delivery import require_delivery_action_allowed

            require_delivery_action_allowed(run_dir, "add_new_route")
        existing_version = existing.get("schema_version")
        requested_version = payload.get("schema_version")
        if (
            existing_version == "1.3"
            and existing.get("units")
            and requested_version != "1.3"
        ):
            raise ContractError("MODELING_UNITS 1.3 不得降级绕过语义反例与评分器预检")
        if existing_version == "1.2" and requested_version not in {"1.2", "1.3"}:
            raise ContractError("新 v3.2 运行的 MODELING_UNITS 不得降级绕过系统派生答案资格")
        if existing_version == "1.1" and requested_version == "1.0":
            raise ContractError("MODELING_UNITS 不得降级到 1.0 绕过决策合同")
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
    from shumozizi.knowledge.retrieval import require_analysis_knowledge_retrieval

    # 路线草案可以自由迭代，但正式投入实验前必须显式消费一次仓内经验。
    require_analysis_knowledge_retrieval(run_dir)
    path = run_dir / MODELING_UNITS_PATH
    if not path.is_file():
        raise ContractError("进入实验前必须完成 analysis/MODELING_UNITS.json")
    validate_modeling_units(run_dir, load_json(path), require_actual=False)


def semantic_high_risk_questions(run_dir: Path) -> set[str]:
    """返回已由问题差分识别为聚合高风险的问题。"""
    path = run_dir / MODELING_UNITS_PATH
    if not path.is_file():
        return set()
    try:
        payload = load_json(path)
    except (OSError, ValueError):
        return set()
    if payload.get("schema_version") != "1.3":
        return set()
    return {
        str(unit["question_id"])
        for unit in payload.get("units", [])
        if isinstance(unit, dict)
        and isinstance(unit.get("question_id"), str)
        and isinstance(unit.get("question_delta"), dict)
        and unit["question_delta"].get("must_recheck_aggregation") is True
    }


def semantic_counterexample_for_question(
    run_dir: Path, question_id: str
) -> dict[str, Any] | None:
    """读取建模单元中的唯一语义反例，供目标合法性校验复用。"""
    path = run_dir / MODELING_UNITS_PATH
    if not path.is_file():
        return None
    payload = load_json(path)
    if payload.get("schema_version") != "1.3":
        return None
    for unit in payload.get("units", []):
        if not isinstance(unit, dict) or unit.get("question_id") != question_id:
            continue
        contract = unit.get("answer_contract")
        if isinstance(contract, dict) and isinstance(contract.get("semantic_counterexample"), dict):
            return dict(contract["semantic_counterexample"])
    return None


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


def final_answer_selections(run_dir: Path) -> dict[str, dict[str, str]]:
    """读取已晋级或已回退的逐问主答案，供论文答案映射保持一致。

    Args:
        run_dir: 当前运行目录。

    Returns:
        以问题 ID 为键的主路线、主结果和决策状态；未完成决策的单元不返回。
    """
    path = run_dir / MODELING_UNITS_PATH
    if not path.is_file():
        return {}
    try:
        payload = load_json(path)
    except (OSError, ValueError):
        return {}
    schema_version = payload.get("schema_version")
    if schema_version in {"1.2", "1.3"}:
        state = read_simple_state(run_dir)
        question_ids = set(state["required_questions"])
        results = {
            item["result_id"]: item for item in read_result_index(run_dir)["results"]
        }
        selections: dict[str, dict[str, str]] = {}
        for raw in payload.get("units", []):
            unit = _require_mapping(raw, "units[]")
            plan = _validate_unit_plan(
                unit,
                question_ids=question_ids,
                require_decision_contract=True,
                schema_version=str(schema_version),
            )
            actual = _require_mapping(
                unit.get("actual"), f"{plan['unit_id']}.actual"
            )
            if plan["mode"] == "oracle_only":
                refinement = _require_mapping(
                    actual.get("refinement"),
                    f"{plan['unit_id']}.actual.refinement",
                )
                result_id = _require_text(
                    refinement.get("final_result_id"),
                    f"{plan['unit_id']}.actual.refinement.final_result_id",
                )
                _production_result(
                    results,
                    result_id=result_id,
                    question_id=plan["question_id"],
                    label=f"{plan['unit_id']}.final_answer",
                )
                selections[plan["question_id"]] = {
                    "status": "promoted",
                    "route_id": "oracle_only",
                    "result_id": result_id,
                }
                continue
            comparison = _require_mapping(
                actual.get("comparison"), f"{plan['unit_id']}.actual.comparison"
            )
            route_result_ids = _require_mapping(
                comparison.get("route_result_ids"),
                f"{plan['unit_id']}.actual.comparison.route_result_ids",
            )
            scores = {
                route_id: _finite_metric(
                    _production_result(
                        results,
                        result_id=route_result_ids[route_id],
                        question_id=plan["question_id"],
                        label=f"{plan['unit_id']}.actual.comparison.{route_id}",
                    ),
                    plan["exact_metric"],
                    f"{plan['unit_id']}.actual.comparison.{route_id}",
                )
                for route_id in plan["route_ids"]
            }
            qualification = derive_answer_qualification(actual, plan, results, scores)
            selection: dict[str, str] = {"status": qualification["status"]}
            for source, target in (
                ("route_id", "route_id"),
                ("result_id", "result_id"),
                ("failure_kind", "failure_kind"),
                ("rollback_target", "rollback_target"),
            ):
                value = qualification.get(source)
                if isinstance(value, str):
                    selection[target] = value
            selections[plan["question_id"]] = selection
        return selections

    selections = {}
    for unit in payload.get("units", []):
        if not isinstance(unit, dict):
            continue
        actual = unit.get("actual")
        question_id = unit.get("question_id")
        if not isinstance(actual, dict) or not isinstance(question_id, str):
            continue
        decision = actual.get("promotion_decision")
        if not isinstance(decision, dict):
            continue
        status = decision.get("status")
        route_id = decision.get("selected_route_id")
        result_id = decision.get("selected_result_id")
        if status == "redesign_required":
            selections[question_id] = {"status": status}
        elif (
            status in {"promoted", "fallback_selected"}
            and isinstance(route_id, str)
            and isinstance(result_id, str)
        ):
            selections[question_id] = {
                "status": status,
                "route_id": route_id,
                "result_id": result_id,
            }
    return selections
