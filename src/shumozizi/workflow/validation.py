"""校验运行状态和跨文件权威关系。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, load_json, sha256_file
from shumozizi.core.schema import require_valid, validate_document
from shumozizi.profiles.lock import verify_run_config_lock
from shumozizi.results.sealing import verify_sealed_result
from shumozizi.workflow.reviews import verify_review_receipt

LOCKED = {
    "ROUTE_LOCKED",
    "MODEL_SPEC_READY",
    "EXPERIMENTING",
    "RESULTS_ACCEPTED",
    "PAPER_DRAFTED",
    "QA_RUNNING",
    "BLOCKED",
    "WAITING_HUMAN_FINAL",
    "COMPLETE",
}


def validate_run(run_dir: Path, repo_root: Path | None = None) -> dict[str, Any]:
    """返回完整机器可读校验结果，不写入运行状态。"""
    root = repo_root.resolve() if repo_root else run_dir.resolve().parents[1]
    errors: list[str] = []
    warnings: list[str] = []
    try:
        state = load_json(run_dir / "state.json")
    except ContractError as exc:
        return {"valid": False, "status": None, "errors": [str(exc)], "warnings": []}
    errors.extend(validate_document(state, "workflow_state"))
    if state.get("run_id") != run_dir.name:
        errors.append("state.run_id 必须与运行目录名一致")
    try:
        verify_run_config_lock(root, run_dir)
    except Exception as exc:
        errors.append(str(exc))
    status = state.get("status")
    candidates: dict[str, Any] | None = None
    candidates_path = run_dir / "brief" / "route_candidates.json"
    if status != "NEW":
        try:
            candidates = load_json(candidates_path)
            require_valid(candidates, "route_candidates")
            ids = [item["route_id"] for item in candidates["candidates"]]
            if len(ids) != len(set(ids)):
                errors.append("候选路线 route_id 重复")
            if candidates["recommended_route_id"] not in ids:
                errors.append("recommended_route_id 必须引用真实存在的候选路线")
        except Exception as exc:
            errors.append(str(exc))
    if status in LOCKED:
        try:
            lock_path = run_dir / "brief" / "ROUTE_LOCK.json"
            receipt_path = run_dir / "brief" / "route_approval_receipt.json"
            lock, receipt = load_json(lock_path), load_json(receipt_path)
            require_valid(lock, "route_lock")
            require_valid(receipt, "approval_receipt")
            if lock["approval_receipt_sha256"] != sha256_file(receipt_path):
                errors.append("ROUTE_LOCK 未绑定当前批准回执")
            if lock["run_config_lock_sha256"] != sha256_file(
                run_dir / "config/RUN_CONFIG_LOCK.json"
            ):
                errors.append("ROUTE_LOCK 绑定的 RUN_CONFIG_LOCK 已变化")
            if lock["route_candidates_sha256"] != sha256_file(candidates_path):
                errors.append("ROUTE_LOCK 绑定的候选路线已变化")
            if candidates and lock["selected_route_id"] not in {
                item["route_id"] for item in candidates["candidates"]
            }:
                errors.append("selected_route_id 必须引用真实存在的候选路线")
        except Exception as exc:
            errors.append(str(exc))
    try:
        registry = load_json(run_dir / "results" / "result_registry.json")
        require_valid(registry, "result_registry")
        for item in registry["results"]:
            if item["status"] == "accepted":
                report = verify_sealed_result(run_dir, item["result_id"])
                errors.extend(
                    f"结果 {item['result_id']}: {message}" for message in report["errors"]
                )
            if item["status"] in {"revoked", "superseded"} and item["paper_allowed"]:
                errors.append(f"revoked 结果不得进入论文: {item['result_id']}")
    except Exception as exc:
        errors.append(str(exc))
    if state.get("paper_ready") and not (run_dir / "paper").is_dir():
        errors.append("paper_ready=true 但 paper/ 不存在")
    # 审核回执是当前 revision 的只读证据；作者修复后旧回执必须失效并重新申请。
    for receipt_path in sorted((run_dir / "review").rglob("review_receipt.json")):
        try:
            receipt = load_json(receipt_path)
            # 已完成阶段的历史回执保留作证据；只有绑定当前 revision 的活动回执参与状态校验。
            state_revision = receipt.get("state_revision")
        except ContractError:
            state_revision = None
        if state_revision == state.get("revision"):
            review = verify_review_receipt(run_dir, receipt_path)
            errors.extend(f"审核回执 {receipt_path.relative_to(run_dir).as_posix()}: {message}" for message in review["errors"])
    return {
        "valid": not errors,
        "status": status,
        "schema_version": state.get("schema_version"),
        "errors": errors,
        "warnings": warnings,
    }
