"""生成人工批准请求、回执并复验哈希绑定。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.core.schema import require_valid


def utc_now() -> str:
    """返回 RFC 3339 UTC 时间。"""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def create_approval_request(
    run_dir: Path,
    kind: str,
    bindings: dict[str, Path],
    *,
    warnings: list[str] | None = None,
) -> Path:
    """创建绑定当前事实快照的批准请求。"""
    state = load_json(run_dir / "state.json")
    document = {
        "schema_name": "approval_request",
        "schema_version": "2.0",
        "request_id": f"{run_dir.name}-{kind}-r{state['revision']}",
        "run_id": run_dir.name,
        "approval_kind": kind,
        "bindings": {name: sha256_file(path) for name, path in bindings.items()},
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
    ids = {item["route_id"] for item in candidates.get("candidates", [])}
    if selected_route_id not in ids:
        raise ContractError("人工选择必须引用真实候选路线")
    bindings = {
        "run_config_lock": sha256_file(config_path),
        "route_candidates": sha256_file(candidates_path),
    }
    if request["bindings"] != bindings:
        raise ContractError("批准请求已失效：绑定事实发生变化")
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
    atomic_json(receipt_path, receipt)
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
        "approval_receipt_sha256": sha256_file(receipt_path),
        "problem_interpretation": selected["problem_interpretation"],
        "primary_route": selected["primary_model"],
        "fallback_route": selected["fallback"],
        "required_baselines": [selected["baseline"]],
        "innovation_claims": [],
        "validation": [selected["validation"]],
        "resource_limits": {
            "max_main_experiment_cycles_per_question": 3,
            "max_web_searches": 5,
            "max_full_self_reviews": 1,
            "route_drift_budget_ratio": 0.3,
        },
        "approved_by": approved_by,
        "approved_at": receipt["approved_at"],
    }
    require_valid(lock, "route_lock")
    lock_path = run_dir / "brief" / "ROUTE_LOCK.json"
    atomic_json(lock_path, lock)
    return receipt_path, lock_path


def materialize_final_approval(
    run_dir: Path,
    *,
    raw_user_response: str,
    approved_by: str = "human",
) -> Path:
    """将明确的人类最终批准物化为绑定当前事实的回执。"""
    if not raw_user_response.strip():
        raise ContractError("原始用户批准回复不能为空")
    request_path = run_dir / "review" / "final_approval_request.json"
    request = load_json(request_path)
    require_valid(request, "approval_request")
    required = {
        "final_pdf_sha256",
        "qa_report_sha256",
        "evidence_report_sha256",
        "run_config_lock_sha256",
    }
    if not required.issubset(request["bindings"]):
        raise ContractError("最终批准请求缺少事实绑定")
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
    """绑定当前 PDF、QA、证据报告与配置锁创建最终批准请求。"""
    pdf = final_pdf.resolve()
    if run_dir.resolve() not in pdf.parents or not pdf.is_file():
        raise ContractError("最终 PDF 必须位于当前运行目录内")
    state = load_json(run_dir / "state.json")
    qa_path = run_dir / "review" / "QA_AGGREGATE.json"
    evidence_path = run_dir / "review" / "EVIDENCE_VALIDATION.json"
    config_path = run_dir / "config" / "RUN_CONFIG_LOCK.json"
    bindings = {
        "final_pdf_sha256": sha256_file(pdf),
        "qa_report_sha256": sha256_file(qa_path),
        "evidence_report_sha256": sha256_file(evidence_path),
        "run_config_lock_sha256": sha256_file(config_path),
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
