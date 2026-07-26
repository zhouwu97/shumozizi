"""在冻结主目标前比较候选目标的策略后果。

该模块解决一个真实失分模式：题面留有解释空间时，工作流过早把某个公式冻结
成主目标，之后所有代码、结果、图和论文都忠实绑定它，于是"数学自洽但策略难看"
的方案（例如累计收益最高却让某个实体几乎完全失守）会一路通过所有验证。

因此这里要求的不是更多审核，而是先看后果再冻结：
1. 开放目标至少保留两个候选定义，并声明各自预期偏好的策略；
2. 每个候选必须有真实低成本 probe，用同一批 guard 指标度量后果；
3. 若冻结候选让任一 guard 指标跌破下限，而另一候选没有，则必须给出显式
   权衡裁决和至少两点真实 Pareto 证据，不能靠报告文字掩盖。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import (
    is_competition_first_v32_state,
    read_simple_state,
    utc_now,
)

OBJECTIVE_CANDIDATES_PATH = Path("analysis/OBJECTIVE_CANDIDATES.json")
_GUARD_KINDS = frozenset({"efficiency", "fairness", "bottleneck", "safety"})
_DIRECTIONS = frozenset({"minimize", "maximize"})


def _require_text(value: object, label: str) -> str:
    """读取非空文本，避免用占位符伪造已完成的目标裁决。"""
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} 必须是非空文本")
    return value.strip()


def _require_mapping(value: object, label: str) -> dict[str, Any]:
    """验证对象字段，便于把错误定位到具体问题或候选目标。"""
    if not isinstance(value, dict):
        raise ContractError(f"{label} 必须是对象")
    return value


def _require_number(value: object, label: str) -> float:
    """读取有限数值，拒绝用字符串或 NaN 充当后果度量。"""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ContractError(f"{label} 必须是数值")
    number = float(value)
    if not math.isfinite(number):
        raise ContractError(f"{label} 必须是有限数值")
    return number


def _guard_metrics(value: object, label: str) -> dict[str, dict[str, Any]]:
    """读取后果度量集合，要求同时覆盖效率与公平/瓶颈/安全类指标。

    只有效率指标时无法暴露"总量最优但个体失守"，所以这里强制存在至少一个
    非 efficiency 的 guard 指标。
    """
    guards = value
    if not isinstance(guards, list) or not guards:
        raise ContractError(f"{label} 至少需要一个后果度量")
    parsed: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(guards):
        item = _require_mapping(raw, f"{label}[{index}]")
        metric = _require_text(item.get("metric"), f"{label}[{index}].metric")
        if metric in parsed:
            raise ContractError(f"{label} 的 metric 不得重复: {metric}")
        kind = item.get("kind")
        if kind not in _GUARD_KINDS:
            raise ContractError(
                f"{label}[{index}].kind 必须是 efficiency、fairness、bottleneck 或 safety"
            )
        direction = item.get("direction")
        if direction not in _DIRECTIONS:
            raise ContractError(f"{label}[{index}].direction 必须为 minimize 或 maximize")
        floor = item.get("acceptable_floor")
        parsed[metric] = {
            "metric": metric,
            "kind": kind,
            "direction": direction,
            "acceptable_floor": None if floor is None else _require_number(
                floor, f"{label}[{index}].acceptable_floor"
            ),
        }
    if not any(item["kind"] != "efficiency" for item in parsed.values()):
        raise ContractError(
            f"{label} 必须至少包含一个 fairness/bottleneck/safety 指标，"
            "否则无法发现总量最优但个体失守的目标"
        )
    return parsed


def _acceptable(value: float, guard: dict[str, Any]) -> bool:
    """判断某个后果度量是否仍在可接受范围内。"""
    floor = guard["acceptable_floor"]
    if floor is None:
        return True
    return value >= floor if guard["direction"] == "maximize" else value <= floor


def _probe_result(
    results: dict[str, dict[str, Any]], *, result_id: str, question_id: str, label: str
) -> dict[str, Any]:
    """读取本问真实生产 probe，拒绝让文字描述充当后果证据。"""
    result = results.get(result_id)
    if result is None:
        raise ContractError(f"{label} 未绑定已登记 result_id: {result_id}")
    if (
        result.get("question_id") != question_id
        or result.get("execution_mode") != "production"
        or result.get("execution_valid") is not True
    ):
        raise ContractError(f"{label} 必须是本问 execution_valid 的 production 结果")
    return result


def _candidate_plan(value: object, label: str) -> dict[str, Any]:
    """验证一个候选目标在实验前已说明公式和预期策略偏好。"""
    item = _require_mapping(value, label)
    return {
        "objective_id": _require_text(item.get("objective_id"), f"{label}.objective_id"),
        "formula": _require_text(item.get("formula"), f"{label}.formula"),
        "expected_strategy_bias": _require_text(
            item.get("expected_strategy_bias"), f"{label}.expected_strategy_bias"
        ),
        "problem_text_basis": _require_text(
            item.get("problem_text_basis"), f"{label}.problem_text_basis"
        ),
    }


def _ambiguous_questions(run_dir: Path) -> set[str]:
    """读取歧义登记中仍会改变主结果且未裁决的问题集合。

    ``determined`` 是自评字段，如果不与真实歧义登记交叉校验，它就成为跳过
    全部候选比较的合法出口。
    """
    path = run_dir / "analysis" / "objective-ambiguities.json"
    if not path.is_file():
        return set()
    try:
        payload = load_json(path)
    except (OSError, ValueError):
        return set()
    items = payload.get("ambiguities", payload.get("items", []))
    if not isinstance(items, list):
        return set()
    ambiguous: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        question_id = item.get("question_id")
        candidates = item.get("candidate_interpretations", [])
        if (
            isinstance(question_id, str)
            and isinstance(candidates, list)
            and len(candidates) >= 2
            and item.get("can_change_primary_result") is True
            and item.get("resolved_by_problem_text") is not True
            and not item.get("resolution")
        ):
            ambiguous.add(question_id)
    return ambiguous


def _validate_question_plan(raw: object, *, label: str, ambiguous: set[str]) -> dict[str, Any]:
    """验证单个问题的候选目标集合与后果度量声明。"""
    item = _require_mapping(raw, label)
    question_id = _require_text(item.get("question_id"), f"{label}.question_id")
    openness = item.get("objective_openness")
    if openness not in {"open", "determined"}:
        raise ContractError(f"{label}.objective_openness 必须为 open 或 determined")
    if openness == "determined":
        if question_id in ambiguous:
            raise ContractError(
                f"{question_id} 在 analysis/objective-ambiguities.json 中仍是未决且会改变"
                "主结果的歧义，不能声明 determined 跳过候选后果比较"
            )
        # 题面唯一确定目标时不强制候选比较，但必须写清凭什么唯一确定。
        _require_text(item.get("determined_basis"), f"{label}.determined_basis")
        return {"question_id": question_id, "openness": openness, "candidates": {}, "guards": {}}
    raw_candidates = item.get("candidates")
    if not isinstance(raw_candidates, list) or len(raw_candidates) < 2:
        raise ContractError(
            f"{label}.candidates 至少需要两个候选目标；开放目标不得在实验前只保留一个公式"
        )
    candidates: dict[str, dict[str, Any]] = {}
    for index, candidate in enumerate(raw_candidates):
        parsed = _candidate_plan(candidate, f"{label}.candidates[{index}]")
        if parsed["objective_id"] in candidates:
            raise ContractError(f"{label}.candidates 的 objective_id 不得重复")
        candidates[parsed["objective_id"]] = parsed
    formulas = [item["formula"] for item in candidates.values()]
    if len(set(formulas)) != len(formulas):
        raise ContractError(f"{label}.candidates 必须给出实质不同的目标公式")
    guards = _guard_metrics(item.get("consequence_metrics"), f"{label}.consequence_metrics")
    return {
        "question_id": question_id,
        "openness": openness,
        "candidates": candidates,
        "guards": guards,
    }


def _validate_question_actual(
    raw: dict[str, Any], plan: dict[str, Any], results: dict[str, dict[str, Any]]
) -> None:
    """用真实 probe 复验候选后果，并在牺牲 guard 指标时要求显式权衡。"""
    question_id = plan["question_id"]
    label = f"objective_candidates[{question_id}]"
    if plan["openness"] == "determined":
        return
    actual = _require_mapping(raw.get("actual"), f"{label}.actual")
    probes = _require_mapping(actual.get("candidate_probes"), f"{label}.actual.candidate_probes")
    if set(probes) != set(plan["candidates"]):
        raise ContractError(f"{label} 的后果实验必须覆盖且仅覆盖已声明候选目标")
    guards = plan["guards"]
    measured: dict[str, dict[str, float]] = {}
    for objective_id, result_id in probes.items():
        identifier = _require_text(result_id, f"{label}.actual.candidate_probes.{objective_id}")
        result = _probe_result(
            results,
            result_id=identifier,
            question_id=question_id,
            label=f"{label}.actual.candidate_probes.{objective_id}",
        )
        metrics = result.get("metrics", {})
        values: dict[str, float] = {}
        for metric in guards:
            if metric not in metrics:
                raise ContractError(
                    f"{label} 的候选 {objective_id} 缺少后果度量 {metric}；"
                    "候选比较必须在同一组指标上进行"
                )
            values[metric] = _require_number(
                metrics[metric], f"{label}.{objective_id}.metrics.{metric}"
            )
        measured[objective_id] = values

    frozen = _require_text(actual.get("frozen_objective_id"), f"{label}.actual.frozen_objective_id")
    if frozen not in plan["candidates"]:
        raise ContractError(f"{label}.actual.frozen_objective_id 必须是已比较候选之一")
    _require_text(actual.get("freeze_rationale"), f"{label}.actual.freeze_rationale")

    # 找出冻结目标牺牲、而其它候选没有牺牲的 guard 指标：这正是 Q5 式失分点。
    sacrificed = [
        metric
        for metric, guard in guards.items()
        if not _acceptable(measured[frozen][metric], guard)
        and any(
            _acceptable(measured[other][metric], guard)
            for other in measured
            if other != frozen
        )
    ]
    if not sacrificed:
        return
    tradeoff = actual.get("tradeoff_decision")
    if not isinstance(tradeoff, dict):
        raise ContractError(
            f"{label} 冻结目标使 {', '.join(sorted(sacrificed))} 跌破可接受下限，"
            "而其它候选没有；必须记录 tradeoff_decision 或改选目标"
        )
    _require_text(tradeoff.get("accepted_loss"), f"{label}.actual.tradeoff_decision.accepted_loss")
    _require_text(tradeoff.get("justification"), f"{label}.actual.tradeoff_decision.justification")
    pareto = tradeoff.get("pareto_result_ids")
    if not isinstance(pareto, list) or len(pareto) < 2:
        raise ContractError(
            f"{label} 接受 guard 指标损失时，必须绑定至少两点真实 Pareto 证据，"
            "说明放弃多少效率可以换回多少 " + ", ".join(sorted(sacrificed))
        )
    seen: set[str] = set()
    for index, identifier in enumerate(pareto):
        result_id = _require_text(
            identifier, f"{label}.actual.tradeoff_decision.pareto_result_ids[{index}]"
        )
        if result_id in seen:
            raise ContractError(f"{label} 的 Pareto 证据不得重复同一结果")
        seen.add(result_id)
        _probe_result(
            results,
            result_id=result_id,
            question_id=question_id,
            label=f"{label}.actual.tradeoff_decision.pareto_result_ids[{index}]",
        )
    covered = {
        metric
        for metric in sacrificed
        if all(
            metric in results[result_id].get("metrics", {})
            for result_id in seen
        )
    }
    missing = sorted(set(sacrificed) - covered)
    if missing:
        raise ContractError(
            f"{label} 的 Pareto 证据必须在每个点上度量被牺牲的指标: " + ", ".join(missing)
        )


def validate_objective_candidates(
    run_dir: Path, payload: dict[str, Any], *, require_actual: bool
) -> dict[str, Any]:
    """验证候选目标后果比较合同及其真实 probe 回填。

    Args:
        run_dir: 当前 v3.2 运行目录。
        payload: ``analysis/OBJECTIVE_CANDIDATES.json`` 内容。
        require_actual: 为真时要求所有开放目标已完成真实后果实验并冻结。

    Returns:
        逐问已解析的候选计划，键为 question_id。

    Raises:
        ContractError: 候选不足、后果度量缺失、probe 未真实执行，或牺牲
            guard 指标却没有显式权衡与 Pareto 证据。
    """
    state = read_simple_state(run_dir)
    if not is_competition_first_v32_state(state):
        raise ContractError("OBJECTIVE_CANDIDATES 只适用于 Competition-First v3.2 运行")
    if payload.get("schema_version") != "1.0" or payload.get("run_id") != state["run_id"]:
        raise ContractError("OBJECTIVE_CANDIDATES 的 schema_version 或 run_id 不匹配")
    required = set(state["required_questions"])
    raw_questions = payload.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise ContractError("OBJECTIVE_CANDIDATES 必须逐问声明目标开放性")
    ambiguous = _ambiguous_questions(run_dir)
    plans: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(raw_questions):
        plan = _validate_question_plan(raw, label=f"questions[{index}]", ambiguous=ambiguous)
        if plan["question_id"] not in required:
            raise ContractError(f"{plan['question_id']} 不是必答问题")
        if plan["question_id"] in plans:
            raise ContractError("OBJECTIVE_CANDIDATES 的 question_id 不得重复")
        plans[plan["question_id"]] = plan
    missing = sorted(required - set(plans))
    if missing:
        raise ContractError("OBJECTIVE_CANDIDATES 缺少必答问题: " + ", ".join(missing))
    if require_actual:
        results = {item["result_id"]: item for item in read_result_index(run_dir)["results"]}
        for raw in raw_questions:
            question_id = raw["question_id"]
            _validate_question_actual(raw, plans[question_id], results)
    return plans


def write_objective_candidates(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """原子保存候选目标后果比较合同。

    Args:
        run_dir: 当前运行目录。
        payload: 候选目标与后果度量声明，可含 ``actual`` 回填。

    Returns:
        已写入的文档。
    """
    validate_objective_candidates(run_dir, payload, require_actual=False)
    document = dict(payload)
    document["updated_at"] = utc_now()
    atomic_json(run_dir / OBJECTIVE_CANDIDATES_PATH, document)
    return document


def frozen_objectives(run_dir: Path) -> dict[str, str]:
    """返回已完成后果比较并冻结的逐问目标 ID。"""
    path = run_dir / OBJECTIVE_CANDIDATES_PATH
    if not path.is_file():
        return {}
    payload = load_json(path)
    frozen: dict[str, str] = {}
    for raw in payload.get("questions", []):
        if not isinstance(raw, dict):
            continue
        actual = raw.get("actual")
        question_id = raw.get("question_id")
        if isinstance(actual, dict) and isinstance(question_id, str):
            objective_id = actual.get("frozen_objective_id")
            if isinstance(objective_id, str):
                frozen[question_id] = objective_id
    return frozen


def require_objective_candidate_plan(run_dir: Path) -> None:
    """要求进入实验前已对开放目标保留候选集合与后果度量。"""
    state = read_simple_state(run_dir)
    if not is_competition_first_v32_state(state):
        return
    path = run_dir / OBJECTIVE_CANDIDATES_PATH
    if not path.is_file():
        raise ContractError(
            "进入实验前必须完成 analysis/OBJECTIVE_CANDIDATES.json："
            "开放目标要先保留候选集合，不能只冻结一个公式"
        )
    validate_objective_candidates(run_dir, load_json(path), require_actual=False)


def require_objective_consequences(run_dir: Path) -> None:
    """要求进入论文前每个开放目标都由真实后果实验决定并冻结。"""
    state = read_simple_state(run_dir)
    if not is_competition_first_v32_state(state):
        return
    path = run_dir / OBJECTIVE_CANDIDATES_PATH
    if not path.is_file():
        raise ContractError("进入论文前缺少 analysis/OBJECTIVE_CANDIDATES.json")
    validate_objective_candidates(run_dir, load_json(path), require_actual=True)
