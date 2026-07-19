"""按 RFC 8785 封存 accepted 结果并提供不可变撤销记录。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import rfc8785

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_bytes, sha256_file
from shumozizi.core.schema import require_valid
from shumozizi.results.metrics import verify_metric
from shumozizi.results.semantics import require_candidate_semantics
from shumozizi.runtime.execution import execution_record_path, verify_execution_record


def utc_now() -> str:
    """返回 RFC 3339 UTC 时间。"""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def canonical_sha256(document: dict[str, Any]) -> str:
    """计算 RFC 8785 JSON Canonicalization Scheme 摘要。"""
    return sha256_bytes(rfc8785.dumps(document))


def admit_candidate(
    run_dir: Path,
    candidate: dict[str, Any],
    *,
    accepted_by: str,
    paper_allowed: bool,
) -> dict[str, Any]:
    """复验候选事实，生成 sealed result、seal 并更新注册表。"""
    required = {
        "result_id",
        "question_id",
        "cycle",
        "execution_record_id",
        "metrics",
        "conclusion",
        "constraint_checks",
        "validation_checks",
        "baseline_result_id",
        "innovation_claims",
    }
    missing = sorted(required - candidate.keys())
    if missing:
        raise ContractError(f"候选结果缺少字段: {', '.join(missing)}")
    if not accepted_by.strip():
        raise ContractError("接受者不能为空")
    require_candidate_semantics(run_dir, candidate)
    execution_id = candidate["execution_record_id"]
    execution = verify_execution_record(run_dir, execution_id)
    if not execution["valid"]:
        raise ContractError("执行记录复验失败: " + "; ".join(execution["errors"]))
    if not candidate["constraint_checks"] or not all(
        item.get("passed") is True for item in candidate["constraint_checks"]
    ):
        raise ContractError("约束检查必须全部通过")
    if not candidate["validation_checks"] or not all(
        item.get("passed") is True for item in candidate["validation_checks"]
    ):
        raise ContractError("验证检查必须全部通过")
    metric_rows: list[dict[str, Any]] = []
    metric_hashes: dict[str, str] = {}
    for metric in candidate["metrics"]:
        metric_id = metric.get("metric_spec_id")
        if not metric_id:
            raise ContractError("每个指标必须包含 metric_spec_id")
        verification = verify_metric(run_dir, metric_id)
        if not verification["valid"]:
            raise ContractError(f"指标来源复验失败: {metric_id}")
        provenance_path = run_dir / "results" / "metric_specs" / f"{metric_id}.json"
        provenance = load_json(provenance_path)
        if (
            metric.get("value") != provenance["final_value"]
            or metric.get("unit") != provenance["final_unit"]
        ):
            raise ContractError(f"候选指标与 provenance 不一致: {metric_id}")
        metric_rows.append(
            {
                "name": metric["name"],
                "metric_spec_id": metric_id,
                "value": provenance["final_value"],
                "unit": provenance["final_unit"],
            }
        )
        metric_hashes[metric_id] = sha256_file(provenance_path)
    for claim in candidate["innovation_claims"]:
        if not claim.get("evidence") or any(
            not item.get("metric_spec_ids") for item in claim["evidence"]
        ):
            raise ContractError(
                "每个 innovation_claim_id 必须包含明确的 result/metric evidence mapping"
            )
    registry_path = run_dir / "results" / "result_registry.json"
    registry = load_json(registry_path)
    require_valid(registry, "result_registry")
    if any(item["result_id"] == candidate["result_id"] for item in registry["results"]):
        raise ContractError("result_id 已存在，accepted 事实不可重写")
    baseline_id = candidate["baseline_result_id"]
    if candidate["cycle"] == "baseline":
        if baseline_id is not None:
            raise ContractError("baseline 结果的 baseline_result_id 必须为 null")
    else:
        baseline = next(
            (
                item
                for item in registry["results"]
                if item["result_id"] == baseline_id
                and item["status"] == "accepted"
                and item["cycle"] == "baseline"
                and item["question_id"] == candidate["question_id"]
            ),
            None,
        )
        if baseline is None:
            raise ContractError("baseline_result_id 必须引用同一问题的 accepted baseline")
        if not verify_sealed_result(run_dir, baseline_id)["valid"]:
            raise ContractError("baseline_result_id 的 sealed result 复验失败")
    for claim in candidate["innovation_claims"]:
        for evidence in claim["evidence"]:
            linked = next(
                (
                    item
                    for item in registry["results"]
                    if item["result_id"] == evidence["result_id"]
                    and item["status"] == "accepted"
                    and item["question_id"] == candidate["question_id"]
                    and item["cycle"] in {"robustness", "ablation"}
                ),
                None,
            )
            if linked is None:
                raise ContractError(
                    f"创新主张 {claim['claim_id']} 必须引用同题 accepted robustness/ablation 结果"
                )
            linked_result = load_json(run_dir / linked["sealed_result_path"])
            linked_metrics = {item["metric_spec_id"] for item in linked_result["metrics"]}
            if not set(evidence["metric_spec_ids"]).issubset(linked_metrics):
                raise ContractError(f"创新主张 {claim['claim_id']} 引用了不存在的指标")
    accepted_at = utc_now()
    sealed = {
        "schema_name": "sealed_result",
        "schema_version": "2.0",
        "result_id": candidate["result_id"],
        "run_id": run_dir.name,
        "question_id": candidate["question_id"],
        "cycle": candidate["cycle"],
        "execution_record_id": execution_id,
        "metrics": metric_rows,
        "conclusion": candidate["conclusion"],
        "constraint_checks": candidate["constraint_checks"],
        "validation_checks": candidate["validation_checks"],
        "baseline_result_id": candidate["baseline_result_id"],
        "innovation_claims": candidate["innovation_claims"],
        "paper_allowed": paper_allowed,
        "accepted_by": accepted_by,
        "accepted_at": accepted_at,
    }
    require_valid(sealed, "sealed_result")
    result_path = run_dir / "results" / "sealed" / f"{candidate['result_id']}.result.json"
    seal_path = run_dir / "results" / "sealed" / f"{candidate['result_id']}.seal.json"
    atomic_json(result_path, sealed)
    seal = {
        "schema_name": "result_seal",
        "schema_version": "2.0",
        "canonicalization": "RFC8785",
        "result_sha256": canonical_sha256(sealed),
        "execution_record_sha256": sha256_file(execution_record_path(run_dir, execution_id)),
        "metric_provenance_sha256": metric_hashes,
        "sealed_at": accepted_at,
    }
    require_valid(seal, "result_seal")
    atomic_json(seal_path, seal)
    registry["results"].append(
        {
            "result_id": candidate["result_id"],
            "question_id": candidate["question_id"],
            "cycle": candidate["cycle"],
            "status": "accepted",
            "paper_allowed": paper_allowed,
            "execution_record_id": execution_id,
            "metric_spec_ids": list(metric_hashes),
            "sealed_result_path": result_path.relative_to(run_dir).as_posix(),
            "result_seal_path": seal_path.relative_to(run_dir).as_posix(),
            "supersedes_result_id": candidate.get("supersedes_result_id"),
        }
    )
    require_valid(registry, "result_registry")
    atomic_json(registry_path, registry)
    return sealed


def verify_sealed_result(run_dir: Path, result_id: str) -> dict[str, Any]:
    """复验封存事实、执行证据与全部指标来源哈希。"""
    result_path = run_dir / "results" / "sealed" / f"{result_id}.result.json"
    seal_path = run_dir / "results" / "sealed" / f"{result_id}.seal.json"
    sealed, seal = load_json(result_path), load_json(seal_path)
    require_valid(sealed, "sealed_result")
    require_valid(seal, "result_seal")
    errors: list[str] = []
    if canonical_sha256(sealed) != seal["result_sha256"]:
        errors.append("sealed result 事实已被修改")
    record_path = execution_record_path(run_dir, sealed["execution_record_id"])
    if sha256_file(record_path) != seal["execution_record_sha256"]:
        errors.append("execution record 与 seal 不一致")
    execution = verify_execution_record(run_dir, sealed["execution_record_id"])
    errors.extend(execution["errors"])
    for metric_id, expected_hash in seal["metric_provenance_sha256"].items():
        path = run_dir / "results" / "metric_specs" / f"{metric_id}.json"
        if sha256_file(path) != expected_hash:
            errors.append(f"metric provenance 已变化: {metric_id}")
        elif not verify_metric(run_dir, metric_id)["valid"]:
            errors.append(f"metric provenance 复验失败: {metric_id}")
    return {"valid": not errors, "result_id": result_id, "errors": errors}


def revoke_result(
    run_dir: Path,
    result_id: str,
    *,
    reason: str,
    revoked_by: str,
    status: str = "revoked",
    superseded_by: str | None = None,
) -> Path:
    """追加撤销记录并只修改注册表生命周期状态。"""
    if status not in {"revoked", "superseded"} or not reason.strip():
        raise ContractError("撤销状态或原因不合法")
    registry_path = run_dir / "results" / "result_registry.json"
    registry = load_json(registry_path)
    item = next((entry for entry in registry["results"] if entry["result_id"] == result_id), None)
    if item is None or item["status"] != "accepted":
        raise ContractError("只有 accepted 结果可以撤销")
    stamp = utc_now().replace(":", "-")
    document = {
        "schema_name": "revocation_record",
        "schema_version": "2.0",
        "run_id": run_dir.name,
        "result_id": result_id,
        "previous_result_sha256": sha256_file(run_dir / item["sealed_result_path"]),
        "reason": reason,
        "status": status,
        "superseded_by": superseded_by,
        "revoked_by": revoked_by,
        "revoked_at": utc_now(),
    }
    require_valid(document, "revocation_record")
    path = run_dir / "results" / "revocations" / f"{result_id}.{stamp}.json"
    atomic_json(path, document)
    item["status"], item["paper_allowed"] = status, False
    if status == "superseded":
        item["supersedes_result_id"] = superseded_by
    atomic_json(registry_path, registry)
    return path
