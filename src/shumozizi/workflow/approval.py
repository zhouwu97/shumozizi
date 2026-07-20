"""生成人工批准请求、回执并复验哈希绑定。"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    json_bytes,
    load_json,
    sha256_bytes,
    sha256_file,
)
from shumozizi.core.schema import require_valid
from shumozizi.knowledge.snapshot import verify_retrieval_snapshot
from shumozizi.questions.manifest import verify_problem_manifest


def utc_now() -> str:
    """返回 RFC 3339 UTC 时间。"""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _retrieval_snapshot_binding(
    run_dir: Path, candidates: dict | None = None
) -> tuple[str, str] | None:
    """返回当前快照引用，并确保候选路线没有替换该快照。"""
    path = run_dir / "knowledge" / "RETRIEVAL_SNAPSHOT.json"
    candidate_has_reference = bool(
        candidates
        and (
            candidates.get("retrieval_snapshot_path")
            or candidates.get("retrieval_snapshot_sha256")
        )
    )
    if not path.is_file():
        if candidate_has_reference:
            raise ContractError("候选路线引用的 RETRIEVAL_SNAPSHOT.json 不存在")
        return None
    report = verify_retrieval_snapshot(run_dir)
    if not report["valid"]:
        raise ContractError("RETRIEVAL_SNAPSHOT 无效: " + "; ".join(report["errors"]))
    relative = "knowledge/RETRIEVAL_SNAPSHOT.json"
    digest = sha256_file(path)
    if candidates is not None and (
        candidates.get("retrieval_snapshot_path") != relative
        or candidates.get("retrieval_snapshot_sha256") != digest
    ):
        raise ContractError("候选路线未绑定当前 RETRIEVAL_SNAPSHOT")
    return relative, digest


def _require_human_approval(raw_user_response: str, approved_by: str, selection: str) -> None:
    """拒绝空泛、否定或由代理自身伪造的人类批准。"""
    if not raw_user_response.strip():
        raise ContractError("原始用户批准回复不能为空")
    actor = approved_by.strip().lower()
    actor_tokens = set(re.findall(r"[a-z0-9]+", actor))
    blocked_actor_tokens = {"codex", "system", "agent", "assistant", "ai", "openai", "gpt"}
    if (
        not actor
        or actor_tokens & blocked_actor_tokens
        or any(token in actor for token in ("系统", "代理", "助手"))
    ):
        raise ContractError("批准人必须是明确的人类主体")
    response = raw_user_response.strip().lower()
    if any(
        token in response
        for token in (
            "拒绝",
            "不同意",
            "不批准",
            "不能批准",
            "无法批准",
            "未批准",
            "不接受",
            "不确认",
            "不要选择",
            "reject",
            "deny",
            "decline",
            "do not approve",
            "not approve",
            "not accept",
        )
    ):
        raise ContractError("批准回复包含拒绝语义")
    affirmative = ("批准", "同意", "确认", "选择", "approve", "accept", "confirm", "select")
    if selection.lower() not in response and not any(token in response for token in affirmative):
        raise ContractError("批准回复未明确选择或同意")


def create_approval_request(
    run_dir: Path,
    kind: str,
    bindings: dict[str, Path],
    *,
    warnings: list[str] | None = None,
) -> Path:
    """创建绑定当前事实快照的批准请求。"""
    state = load_json(run_dir / "state.json")
    effective_bindings = dict(bindings)
    if kind == "route":
        manifest_report = verify_problem_manifest(run_dir)
        if not manifest_report["valid"]:
            raise ContractError(
                "路线批准请求要求有效的 PROBLEM_MANIFEST: "
                + "; ".join(manifest_report["errors"])
            )
        effective_bindings["problem_manifest"] = run_dir / "problem/PROBLEM_MANIFEST.json"
        candidates_path = effective_bindings.get("route_candidates")
        candidates = load_json(candidates_path) if candidates_path else None
        snapshot = _retrieval_snapshot_binding(run_dir, candidates)
        if snapshot is not None:
            effective_bindings["retrieval_snapshot"] = run_dir / snapshot[0]
    document = {
        "schema_name": "approval_request",
        "schema_version": "2.0",
        "request_id": f"{run_dir.name}-{kind}-r{state['revision']}",
        "run_id": run_dir.name,
        "approval_kind": kind,
        "bindings": {name: sha256_file(path) for name, path in effective_bindings.items()},
        "state_revision": state["revision"],
        "warnings": warnings or [],
        "requested_at": utc_now(),
    }
    require_valid(document, "approval_request")
    path = run_dir / ("brief" if kind == "route" else "review") / f"{kind}_approval_request.json"
    atomic_json(path, document)
    return path


def materialize_route_approval(
    run_dir: Path,
    *,
    raw_user_response: str,
    selected_route_id: str,
    approved_by: str = "human",
    delegated_items: list[str] | None = None,
) -> tuple[Path, Path]:
    """仅依据明确的人类回复生成路线批准回执和路线锁。"""
    if not raw_user_response.strip():
        raise ContractError("原始用户批准回复不能为空")
    request_path = run_dir / "brief" / "route_approval_request.json"
    candidates_path = run_dir / "brief" / "route_candidates.json"
    config_path = run_dir / "config" / "RUN_CONFIG_LOCK.json"
    request = load_json(request_path)
    candidates = load_json(candidates_path)
    require_valid(request, "approval_request")
    require_valid(candidates, "route_candidates")
    manifest_report = verify_problem_manifest(run_dir)
    if not manifest_report["valid"]:
        raise ContractError("路线批准要求有效的 PROBLEM_MANIFEST: " + "; ".join(manifest_report["errors"]))
    manifest_path = run_dir / "problem/PROBLEM_MANIFEST.json"
    ids = {item["route_id"] for item in candidates.get("candidates", [])}
    if selected_route_id not in ids:
        raise ContractError("人工选择必须引用真实候选路线")
    bindings = {
        "run_config_lock": sha256_file(config_path),
        "route_candidates": sha256_file(candidates_path),
        "problem_manifest": sha256_file(manifest_path),
    }
    snapshot = _retrieval_snapshot_binding(run_dir, candidates)
    if snapshot is not None:
        bindings["retrieval_snapshot"] = snapshot[1]
    if candidates["run_id"] != run_dir.name:
        raise ContractError("候选路线 run_id 与运行目录不一致")
    if candidates["run_config_lock_sha256"] != bindings["run_config_lock"]:
        raise ContractError("候选路线未绑定当前配置锁")
    if request["bindings"] != bindings:
        raise ContractError("批准请求已失效：绑定事实发生变化")
    _require_human_approval(raw_user_response, approved_by, selected_route_id)
    receipt = {
        "schema_name": "approval_receipt",
        "schema_version": "2.0",
        "run_id": run_dir.name,
        "approval_kind": "route",
        "approval_request_sha256": sha256_file(request_path),
        "bindings": bindings,
        "raw_user_response": raw_user_response,
        "normalized_selection": selected_route_id,
        "delegated_items": delegated_items or [],
        "decision": "approved",
        "approved_by": approved_by,
        "approval_source": "codex-desktop-user-message",
        "approved_at": utc_now(),
    }
    require_valid(receipt, "approval_receipt")
    receipt_path = run_dir / "brief" / "route_approval_receipt.json"
    selected = next(
        item for item in candidates["candidates"] if item["route_id"] == selected_route_id
    )
    lock = {
        "schema_name": "route_lock",
        "schema_version": "2.0",
        "run_id": run_dir.name,
        "approved": True,
        "selected_route_id": selected_route_id,
        "run_config_lock_sha256": bindings["run_config_lock"],
        "route_candidates_sha256": bindings["route_candidates"],
        "approval_receipt_sha256": sha256_bytes(json_bytes(receipt)),
        "problem_manifest_sha256": bindings["problem_manifest"],
        "problem_interpretation": selected["problem_interpretation"],
        "primary_route": selected["primary_model"],
        "fallback_route": selected["fallback"],
        "required_baselines": [selected["baseline"]],
        "innovation_claims": [],
        "validation": [selected["validation"]],
        "resource_limits": {
            "max_experiment_families_per_question": 3,
            "max_execution_seconds_per_family": 7200,
            "max_model_fits_per_family": 100,
            "max_optimization_evaluations_per_family": 10000,
            "max_invalid_tuning_attempts_per_family": 3,
            "max_web_searches": 5,
            "max_full_self_reviews": 1,
            "route_drift_budget_ratio": 0.3,
        },
        "approved_by": approved_by,
        "approved_at": receipt["approved_at"],
    }
    if snapshot is not None:
        lock["retrieval_snapshot_path"] = snapshot[0]
        lock["retrieval_snapshot_sha256"] = snapshot[1]
    require_valid(lock, "route_lock")
    atomic_json(receipt_path, receipt)
    lock_path = run_dir / "brief" / "ROUTE_LOCK.json"
    atomic_json(lock_path, lock)
    return receipt_path, lock_path


def verify_route_approval(run_dir: Path) -> dict[str, object]:
    """复验路线请求、明确人类批准、路线锁和全部冻结事实。"""
    errors: list[str] = []
    request_path = run_dir / "brief/route_approval_request.json"
    receipt_path = run_dir / "brief/route_approval_receipt.json"
    lock_path = run_dir / "brief/ROUTE_LOCK.json"
    candidates_path = run_dir / "brief/route_candidates.json"
    config_path = run_dir / "config/RUN_CONFIG_LOCK.json"
    manifest_path = run_dir / "problem/PROBLEM_MANIFEST.json"
    try:
        request = load_json(request_path)
        receipt = load_json(receipt_path)
        lock = load_json(lock_path)
        candidates = load_json(candidates_path)
        require_valid(request, "approval_request")
        require_valid(receipt, "approval_receipt")
        require_valid(lock, "route_lock")
        require_valid(candidates, "route_candidates")
        bindings = {
            "run_config_lock": sha256_file(config_path),
            "route_candidates": sha256_file(candidates_path),
            "problem_manifest": sha256_file(manifest_path),
        }
        snapshot = _retrieval_snapshot_binding(run_dir, candidates)
        if snapshot is not None:
            bindings["retrieval_snapshot"] = snapshot[1]
        if request["approval_kind"] != "route" or receipt["approval_kind"] != "route":
            errors.append("路线批准请求或回执的 approval_kind 不正确")
        if request["run_id"] != run_dir.name or receipt["run_id"] != run_dir.name:
            errors.append("路线批准请求或回执的 run_id 不一致")
        if candidates["run_id"] != run_dir.name:
            errors.append("候选路线 run_id 与运行目录不一致")
        if candidates["run_config_lock_sha256"] != bindings["run_config_lock"]:
            errors.append("候选路线未绑定当前配置锁")
        if request["bindings"] != bindings or receipt["bindings"] != bindings:
            errors.append("路线批准未绑定当前配置、候选路线和问题全集")
        if receipt["approval_request_sha256"] != sha256_file(request_path):
            errors.append("路线批准回执未绑定当前批准请求")
        selection = receipt["normalized_selection"]
        _require_human_approval(receipt["raw_user_response"], receipt["approved_by"], selection)
        if receipt["decision"] != "approved" or lock["approved"] is not True:
            errors.append("路线批准决策不是 approved")
        if lock["selected_route_id"] != selection:
            errors.append("路线锁与人工选择不一致")
        if lock["approved_by"] != receipt["approved_by"] or lock["approved_at"] != receipt["approved_at"]:
            errors.append("路线锁与批准回执的批准主体或时间不一致")
        lock_bindings = {
            "run_config_lock": lock["run_config_lock_sha256"],
            "route_candidates": lock["route_candidates_sha256"],
            "problem_manifest": lock["problem_manifest_sha256"],
        }
        if snapshot is not None:
            lock_bindings["retrieval_snapshot"] = lock.get("retrieval_snapshot_sha256")
        if snapshot is not None:
            if (
                lock.get("retrieval_snapshot_path") != snapshot[0]
                or lock.get("retrieval_snapshot_sha256") != snapshot[1]
            ):
                errors.append("路线锁未绑定批准时的 RETRIEVAL_SNAPSHOT")
        elif lock.get("retrieval_snapshot_path") or lock.get("retrieval_snapshot_sha256"):
            errors.append("路线锁包含无效的 RETRIEVAL_SNAPSHOT 引用")
        if lock_bindings != bindings:
            errors.append("路线锁绑定事实已失效")
        if lock["approval_receipt_sha256"] != sha256_file(receipt_path):
            errors.append("路线锁未绑定当前批准回执")
        ids = {item["route_id"] for item in candidates["candidates"]}
        if selection not in ids:
            errors.append("路线锁选择不属于候选路线")
        selected = next((item for item in candidates["candidates"] if item["route_id"] == selection), None)
        if selected is not None:
            expected_fields = {
                "problem_interpretation": selected["problem_interpretation"],
                "primary_route": selected["primary_model"],
                "fallback_route": selected["fallback"],
                "required_baselines": [selected["baseline"]],
                "validation": [selected["validation"]],
            }
            for field, expected in expected_fields.items():
                if lock.get(field) != expected:
                    errors.append(f"路线锁字段 {field} 与候选路线不一致")
        manifest = verify_problem_manifest(run_dir)
        errors.extend(manifest["errors"])
    except (ContractError, KeyError, OSError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors}


def materialize_final_approval(
    run_dir: Path,
    *,
    raw_user_response: str,
    approved_by: str = "human",
) -> Path:
    """将明确的人类最终批准物化为绑定当前事实的回执。"""
    _require_human_approval(raw_user_response, approved_by, "最终提交")
    request_path = run_dir / "review" / "final_approval_request.json"
    request = load_json(request_path)
    require_valid(request, "approval_request")
    required = {
        "final_pdf_sha256",
        "qa_report_sha256",
        "evidence_report_sha256",
        "format_audit_sha256",
        "run_config_lock_sha256",
        "source_manifest_sha256",
    }
    if not required.issubset(request["bindings"]):
        raise ContractError("最终批准请求缺少事实绑定")
    from shumozizi.workflow.source_package import verify_source_manifest

    source_report = verify_source_manifest(run_dir)
    if not source_report["valid"]:
        raise ContractError("源码包校验失败: " + "; ".join(source_report["errors"]))
    if request["bindings"]["source_manifest_sha256"] != source_report["manifest_sha256"]:
        raise ContractError("最终批准请求未绑定当前 SOURCE_MANIFEST.json")
    qa = load_json(run_dir / "review" / "QA_AGGREGATE.json")
    format_audit = load_json(run_dir / "review" / "FORMAT_AUDIT.json")
    require_valid(qa, "qa_report")
    require_valid(format_audit, "format_audit")
    if format_audit["hard_failures"]:
        raise ContractError("最终批准不能覆盖 FORMAT_AUDIT 机器硬失败")
    if request["bindings"]["format_audit_sha256"] != sha256_file(
        run_dir / "review" / "FORMAT_AUDIT.json"
    ):
        raise ContractError("最终批准请求未绑定当前 FORMAT_AUDIT.json")
    if qa.get("source_manifest_sha256") != source_report["manifest_sha256"]:
        raise ContractError("最终 QA 未绑定当前 SOURCE_MANIFEST.json")
    receipt = {
        "schema_name": "final_approval_receipt",
        "schema_version": "2.0",
        "run_id": run_dir.name,
        "approval_request_sha256": sha256_file(request_path),
        **{name: request["bindings"][name] for name in sorted(required)},
        "decision": "approved",
        "approved_by": approved_by,
        "approval_source": "codex-desktop-user-message",
        "raw_user_response": raw_user_response,
        "approved_at": utc_now(),
    }
    require_valid(receipt, "final_approval_receipt")
    path = run_dir / "review" / "final_approval_receipt.json"
    atomic_json(path, receipt)
    return path


def create_final_approval_request(
    run_dir: Path,
    final_pdf: Path,
    *,
    warnings: list[str] | None = None,
) -> Path:
    """绑定当前 PDF、QA、证据报告、配置锁与源码包创建最终批准请求。"""
    from shumozizi.workflow.source_package import verify_source_manifest

    pdf = final_pdf.resolve()
    if run_dir.resolve() not in pdf.parents or not pdf.is_file():
        raise ContractError("最终 PDF 必须位于当前运行目录内")
    state = load_json(run_dir / "state.json")
    qa_path = run_dir / "review" / "QA_AGGREGATE.json"
    evidence_path = run_dir / "review" / "EVIDENCE_VALIDATION.json"
    config_path = run_dir / "config" / "RUN_CONFIG_LOCK.json"
    source_manifest_path = run_dir / "source" / "SOURCE_MANIFEST.json"
    format_audit_path = run_dir / "review" / "FORMAT_AUDIT.json"
    source_report = verify_source_manifest(run_dir, expected_final_pdf=pdf)
    if not source_report["valid"]:
        raise ContractError("源码包校验失败: " + "; ".join(source_report["errors"]))
    qa = load_json(qa_path)
    format_audit = load_json(format_audit_path)
    require_valid(qa, "qa_report")
    require_valid(format_audit, "format_audit")
    if format_audit["hard_failures"]:
        raise ContractError("FORMAT_AUDIT 存在机器硬失败，不能创建最终批准请求")
    source_manifest_sha256 = sha256_file(source_manifest_path)
    if qa.get("source_manifest_sha256") != source_manifest_sha256:
        raise ContractError("最终 QA 未绑定当前 SOURCE_MANIFEST.json")
    bindings = {
        "final_pdf_sha256": sha256_file(pdf),
        "qa_report_sha256": sha256_file(qa_path),
        "evidence_report_sha256": sha256_file(evidence_path),
        "format_audit_sha256": sha256_file(format_audit_path),
        "run_config_lock_sha256": sha256_file(config_path),
        "source_manifest_sha256": source_manifest_sha256,
    }
    document = {
        "schema_name": "approval_request",
        "schema_version": "2.0",
        "request_id": f"{run_dir.name}-final-r{state['revision']}",
        "run_id": run_dir.name,
        "approval_kind": "final",
        "bindings": bindings,
        "state_revision": state["revision"],
        "warnings": warnings or [],
        "final_pdf_path": pdf.relative_to(run_dir).as_posix(),
        "requested_at": utc_now(),
    }
    require_valid(document, "approval_request")
    path = run_dir / "review" / "final_approval_request.json"
    atomic_json(path, document)
    return path
