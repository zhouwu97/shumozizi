"""只依据结构化比较谓词生成创新主张证据。

本模块不解释自由文本，也不改写结果注册表或 sealed result。输入事实变化时，
旧的 claim evidence 会被标记为 stale；显式 ``refresh=True`` 才会生成新的证据。
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import rfc8785

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    load_json,
    sha256_bytes,
    sha256_file,
    sha256_tree,
)
from shumozizi.core.schema import require_valid
from shumozizi.results.sealing import verify_sealed_result

EVALUATOR_VERSION = "1.0.0"
CLAIM_STATUSES = {"supported", "partially_supported", "rejected", "inconclusive"}
RELATIONS = {
    "relative_increase",
    "relative_decrease",
    "relative_decrease_at_most",
    "relative_increase_at_most",
    "absolute_increase",
    "absolute_decrease",
    "absolute_decrease_at_most",
    "absolute_increase_at_most",
    "stable",
}


def _canonical_sha256(value: Any) -> str:
    """对结构化 JSON 值计算 RFC 8785 摘要。"""
    return sha256_bytes(rfc8785.dumps(value))


def _comparison_paths_hash(paths: Iterable[Path], comparisons: list[dict[str, Any]]) -> str:
    """稳定绑定外部比较文件；未提供文件时绑定本次结构化比较结果。"""
    resolved = sorted(path.resolve() for path in paths)
    if not resolved:
        return _canonical_sha256({"comparisons": comparisons})
    rows = []
    for path in resolved:
        if not path.is_file():
            raise ContractError(f"比较输出不存在: {path}")
        rows.append({"path": path.as_posix(), "sha256": sha256_file(path)})
    return _canonical_sha256(rows)


def _hash_bindings(
    run_dir: Path,
    *,
    evaluator_version: str,
    comparison_output_paths: Iterable[Path],
    comparisons: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """计算 evidence 的全部事实绑定。"""
    route_path = run_dir / "brief" / "ROUTE_LOCK.json"
    registry_path = run_dir / "results" / "result_registry.json"
    plans_path = run_dir / "experiments" / "plans"
    if not route_path.is_file():
        raise ContractError(f"缺少 ROUTE_LOCK.json: {route_path}")
    if not registry_path.is_file():
        raise ContractError(f"缺少 result_registry.json: {registry_path}")
    return {
        "evaluator_version": evaluator_version,
        "route_lock_sha256": sha256_file(route_path),
        "result_registry_sha256": sha256_file(registry_path),
        "experiment_plan_sha256": sha256_tree(plans_path),
        "comparison_output_sha256": _comparison_paths_hash(
            comparison_output_paths, comparisons or []
        ),
    }


def evidence_is_stale(evidence: dict[str, Any], bindings: dict[str, str]) -> tuple[bool, str]:
    """判断已有 evidence 是否绑定了当前输入。"""
    if evidence.get("stale") is True:
        return True, str(evidence.get("stale_reason") or "证据已被标记为 stale")
    for name, expected in bindings.items():
        if evidence.get(name) != expected:
            return True, f"{name} 已变化，旧 claim evidence 失效"
    return False, ""


def _metric_value(
    sealed_results: dict[str, dict[str, Any]], result_id: str, metric_name: str
) -> tuple[float, str] | None:
    """按 metric name 或 metric_spec_id 读取 sealed result 数值。"""
    result = sealed_results.get(result_id)
    if result is None:
        return None
    for metric in result.get("metrics", []):
        if metric.get("name") == metric_name or metric.get("metric_spec_id") == metric_name:
            value = metric.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            return float(value), str(metric.get("unit", ""))
    return None


def _result_ids_for_aggregation(
    registry: dict[str, Any],
    question_id: str,
    aggregation: str,
    baseline_result_ids: list[str],
) -> list[str]:
    """把 aggregation 名称解析为 accepted result IDs。"""
    accepted = [
        item
        for item in registry["results"]
        if item.get("status") == "accepted" and item.get("question_id") == question_id
    ]
    if aggregation == "baseline_result":
        accepted_ids = {row["result_id"] for row in accepted}
        return [result_id for result_id in baseline_result_ids if result_id in accepted_ids]
    cycle_by_aggregation = {
        "primary_result": "primary",
        "robustness_result": "robustness",
        "ablation_result": "ablation",
    }
    cycle = cycle_by_aggregation.get(aggregation)
    if cycle is not None:
        return [row["result_id"] for row in accepted if row.get("cycle") == cycle]
    if aggregation in {"mean_target", "all_accepted"}:
        return [row["result_id"] for row in accepted if row.get("cycle") != "baseline"]
    if aggregation == "latest_accepted":
        return [accepted[-1]["result_id"]] if accepted else []
    return []


def _aggregate_metric(
    sealed_results: dict[str, dict[str, Any]], result_ids: list[str], metric_name: str
) -> tuple[float, str, list[str]] | None:
    """读取并按结果集合求均值；单结果集合自然退化为该值。"""
    values = []
    units = set()
    used = []
    for result_id in result_ids:
        metric = _metric_value(sealed_results, result_id, metric_name)
        if metric is None:
            continue
        value, unit = metric
        values.append(value)
        units.add(unit)
        used.append(result_id)
    if not values or len(units) != 1:
        return None
    return sum(values) / len(values), units.pop(), used


def _predicate_check(
    predicate: dict[str, Any],
    *,
    baseline: tuple[float, str, list[str]] | None,
    target: tuple[float, str, list[str]] | None,
) -> tuple[dict[str, Any], list[str]]:
    """执行一个结构化 predicate，并返回检查记录与证据结果 IDs。"""
    prediction_id = predicate.get("prediction_id") or f"metric-{predicate['metric']}"
    check: dict[str, Any] = {
        "prediction_id": prediction_id,
        "metric": predicate["metric"],
        "status": "inconclusive",
        "required": float(predicate["threshold"]),
        "unit": predicate["unit"],
        "aggregation": predicate["aggregation"],
        "relation": predicate["relation"],
    }
    used_ids = []
    if baseline is None or target is None:
        check["reason"] = "缺少可比较的 accepted baseline 或目标结果"
        return check, used_ids
    baseline_value, baseline_unit, baseline_ids = baseline
    target_value, target_unit, target_ids = target
    used_ids = sorted(set(baseline_ids + target_ids))
    check["baseline"] = baseline_value
    check["target"] = target_value
    if predicate["unit"] not in {"any", baseline_unit} or target_unit != baseline_unit:
        check["reason"] = "比较指标单位不一致"
        return check, used_ids
    relation = predicate["relation"]
    threshold = float(predicate["threshold"])
    delta = target_value - baseline_value
    if relation.startswith("relative_"):
        if baseline_value == 0:
            check["reason"] = "基线值为零，无法计算相对变化"
            return check, used_ids
        observed = delta / abs(baseline_value)
    else:
        observed = delta
    check["observed"] = observed
    check["relative_change"] = observed if relation.startswith("relative_") else None
    checks = {
        "relative_increase": observed >= threshold,
        "relative_decrease": observed <= -threshold,
        "relative_decrease_at_most": observed >= -threshold,
        "relative_increase_at_most": observed <= threshold,
        "absolute_increase": observed >= threshold,
        "absolute_decrease": observed <= -threshold,
        "absolute_decrease_at_most": observed >= -threshold,
        "absolute_increase_at_most": observed <= threshold,
        "stable": abs(observed) <= threshold,
    }
    passed = checks.get(relation)
    if passed is None or relation not in RELATIONS:
        check["reason"] = f"不支持的结构化 relation: {relation}"
        return check, used_ids
    check["status"] = "passed" if passed else "failed"
    return check, used_ids


def _claim_permissions(status: str) -> dict[str, bool]:
    """按主张状态给出最小论文权限；详细文字门禁留给 P0c。"""
    return {
        "contribution_section": status == "supported",
        "results_section": True,
        "limitations_section": True,
    }


def evaluate_claim_documents(
    route_lock: dict[str, Any],
    registry: dict[str, Any],
    plans: list[dict[str, Any]],
    sealed_results: dict[str, dict[str, Any]],
    *,
    evaluator_version: str = EVALUATOR_VERSION,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """从已加载文档评估 claims；该函数不执行任何文件写入。"""
    structured_claims = [
        claim
        for claim in route_lock.get("innovation_claims", [])
        if {"claim_id", "prediction_ids"}.issubset(claim)
    ]
    if not structured_claims:
        return (
            {
                "schema_name": "claim_evidence",
                "schema_version": "2.0",
                "run_id": route_lock["run_id"],
                "evaluator_version": evaluator_version,
                "stale": False,
                "claimability": "none",
                "reason": "当前路线锁没有结构化创新主张",
                "claims": [],
            },
            [],
        )
    plan_by_claim: dict[str, list[dict[str, Any]]] = {}
    for plan in plans:
        for claim_id in plan.get("claim_ids", []):
            plan_by_claim.setdefault(claim_id, []).append(plan)
    all_comparisons: list[dict[str, Any]] = []
    claims_output = []
    for claim in structured_claims:
        claim_id = claim["claim_id"]
        checks: list[dict[str, Any]] = []
        evidence_ids: set[str] = set()
        claim_plans = plan_by_claim.get(claim_id, [])
        for plan in claim_plans:
            question_id = plan["question_id"]
            baseline_ids = plan.get("baseline_result_ids", [])
            predicates = plan.get("comparison_rule", {}).get("predicates", [])
            for predicate in predicates:
                prediction_id = predicate.get("prediction_id")
                if prediction_id and prediction_id not in claim["prediction_ids"]:
                    continue
                baseline_result_ids = _result_ids_for_aggregation(
                    registry, question_id, "baseline_result", baseline_ids
                )
                target_result_ids = _result_ids_for_aggregation(
                    registry,
                    question_id,
                    predicate["aggregation"],
                    baseline_ids,
                )
                baseline = _aggregate_metric(
                    sealed_results, baseline_result_ids, predicate["metric"]
                )
                target = _aggregate_metric(
                    sealed_results, target_result_ids, predicate["metric"]
                )
                check, used = _predicate_check(predicate, baseline=baseline, target=target)
                check["plan_id"] = plan["experiment_id"]
                checks.append(check)
                evidence_ids.update(used)
                all_comparisons.append(
                    {"claim_id": claim_id, "plan_id": plan["experiment_id"], "check": check}
                )
        statuses = [item["status"] for item in checks]
        if statuses and all(item == "passed" for item in statuses):
            status = "supported"
        elif any(item == "failed" for item in statuses):
            status = "rejected"
        elif any(item == "passed" for item in statuses):
            status = "partially_supported"
        else:
            status = "inconclusive"
        claims_output.append(
            {
                "claim_id": claim_id,
                "claim": claim.get("claim"),
                "status": status,
                "evidence_result_ids": sorted(evidence_ids),
                "prediction_checks": checks,
                "paper_permissions": _claim_permissions(status),
            }
        )
    return (
        {
            "schema_name": "claim_evidence",
            "schema_version": "2.0",
            "run_id": route_lock["run_id"],
            "evaluator_version": evaluator_version,
            "stale": False,
            "claims": claims_output,
        },
        all_comparisons,
    )


def _load_plans(plans_dir: Path) -> list[dict[str, Any]]:
    """加载并校验所有实验计划。"""
    if not plans_dir.is_dir():
        raise ContractError(f"缺少实验计划目录: {plans_dir}")
    plans = []
    for path in sorted(plans_dir.rglob("*.json")):
        plan = load_json(path)
        require_valid(plan, "experiment_plan")
        plans.append(plan)
    return plans


def evaluate_claims(
    run_dir: Path,
    *,
    evaluator_version: str = EVALUATOR_VERSION,
    comparison_output_paths: Iterable[Path] = (),
    output_path: Path | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    """评估运行目录中的 claims，并写入 claim evidence。

    默认复用仍然新鲜的 evidence；如果绑定输入变化，则只把旧证据标记为 stale。
    ``refresh=True`` 明确要求依据当前输入重新计算。
    """
    run_dir = run_dir.resolve()
    output = output_path or (run_dir / "claims" / "claim_evidence.json")
    route_lock = load_json(run_dir / "brief" / "ROUTE_LOCK.json")
    registry = load_json(run_dir / "results" / "result_registry.json")
    require_valid(route_lock, "route_lock")
    require_valid(registry, "result_registry")
    plans = _load_plans(run_dir / "experiments" / "plans")
    sealed_results: dict[str, dict[str, Any]] = {}
    for item in registry["results"]:
        if item.get("status") != "accepted":
            continue
        result_id = item["result_id"]
        verification = verify_sealed_result(run_dir, result_id)
        if not verification["valid"]:
            raise ContractError(f"accepted result 复验失败 {result_id}: {'; '.join(verification['errors'])}")
        sealed_results[result_id] = load_json(run_dir / item["sealed_result_path"])
    draft, comparisons = evaluate_claim_documents(
        route_lock,
        registry,
        plans,
        sealed_results,
        evaluator_version=evaluator_version,
    )
    bindings = _hash_bindings(
        run_dir,
        evaluator_version=evaluator_version,
        comparison_output_paths=comparison_output_paths,
        comparisons=comparisons,
    )
    existing = load_json(output) if output.is_file() else None
    if existing is not None and not refresh:
        stale, reason = evidence_is_stale(existing, bindings)
        if stale:
            existing["stale"] = True
            existing["stale_reason"] = reason
            atomic_json(output, existing)
        return existing
    draft.update(bindings)
    require_valid(draft, "claim_evidence")
    atomic_json(output, draft)
    return draft
