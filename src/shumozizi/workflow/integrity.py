"""运行级完整性验证器，统一离线校验、状态推进和最终核包事实。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, load_json, sha256_file
from shumozizi.core.schema import require_valid, validate_document
from shumozizi.profiles.lock import verify_run_config_lock
from shumozizi.questions.acceptance import verify_question_acceptance
from shumozizi.questions.manifest import verify_problem_manifest
from shumozizi.results.sealing import verify_sealed_result
from shumozizi.workflow.approval import verify_route_approval
from shumozizi.workflow.reviews import verify_review_receipt
from shumozizi.workflow.source_package import verify_source_manifest

LOCKED_STATUSES = {
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
PAPER_STATUSES = {"PAPER_DRAFTED", "QA_RUNNING", "BLOCKED", "WAITING_HUMAN_FINAL", "COMPLETE"}


def verify_run_integrity(
    run_dir: Path,
    target_state: str | None = None,
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """验证指定运行在当前或目标状态下是否具备完整、未过期的证据链。"""
    run_dir = run_dir.resolve()
    root = repo_root.resolve() if repo_root else run_dir.parents[1]
    errors: list[str] = []
    try:
        state = load_json(run_dir / "state.json")
        errors.extend(validate_document(state, "workflow_state"))
        status = target_state or state.get("status")
        if state.get("run_id") != run_dir.name:
            errors.append("state.run_id 必须与运行目录名一致")
        try:
            verify_run_config_lock(root, run_dir)
        except (ContractError, OSError) as exc:
            errors.append(str(exc))
        if status != "NEW":
            _verify_candidates(run_dir, errors)
        if status in LOCKED_STATUSES:
            route = verify_route_approval(run_dir)
            errors.extend(f"路线批准: {item}" for item in route["errors"])
            manifest = verify_problem_manifest(run_dir)
            errors.extend(f"问题全集: {item}" for item in manifest["errors"])
        _verify_registry(run_dir, errors)
        if status in PAPER_STATUSES:
            acceptance = verify_question_acceptance(run_dir)
            errors.extend(f"逐问验收: {item}" for item in acceptance["errors"])
            from shumozizi.paper.receipts import verify_production_receipts

            production = verify_production_receipts(run_dir)
            errors.extend(f"生产回执: {item}" for item in production["errors"])
        if status in {"WAITING_HUMAN_FINAL", "COMPLETE"}:
            source_package = verify_source_manifest(run_dir)
            errors.extend(f"源码包: {item}" for item in source_package["errors"])
            _verify_final_review_gates(run_dir, state, errors)
        if status == "COMPLETE":
            _verify_final_package(run_dir, errors)
    except (ContractError, KeyError, OSError) as exc:
        errors.append(str(exc))
        status = target_state
    return {
        "valid": not errors,
        "status": status,
        "errors": errors,
        "target_state": target_state,
    }


def _verify_candidates(run_dir: Path, errors: list[str]) -> None:
    candidates = load_json(run_dir / "brief/route_candidates.json")
    require_valid(candidates, "route_candidates")
    ids = [item["route_id"] for item in candidates["candidates"]]
    if len(ids) != len(set(ids)):
        errors.append("候选路线 route_id 重复")
    if candidates["recommended_route_id"] not in ids:
        errors.append("recommended_route_id 必须引用真实存在的候选路线")


def _verify_registry(run_dir: Path, errors: list[str]) -> None:
    registry = load_json(run_dir / "results/result_registry.json")
    require_valid(registry, "result_registry")
    for item in registry["results"]:
        if item["status"] == "accepted":
            report = verify_sealed_result(run_dir, item["result_id"])
            errors.extend(f"结果 {item['result_id']}: {message}" for message in report["errors"])
        if item["status"] in {"revoked", "superseded"} and item.get("paper_allowed"):
            errors.append(f"revoked 结果不得进入论文: {item['result_id']}")


def _verify_final_review_gates(run_dir: Path, state: dict[str, Any], errors: list[str]) -> None:
    manifest = load_json(run_dir / "problem/PROBLEM_MANIFEST.json")
    gate_ids = ["R1_MODELING"] + [
        f"R2_EXPERIMENT_{item['question_id']}"
        for item in manifest["questions"]
        if item["required"]
    ] + ["R3_PAPER_LOGIC", "R4_FORMAT_VISUAL", "R5_STANDARD_FINAL", "J0_FINAL_BLIND_JUDGE"]
    for gate_id in gate_ids:
        gate = state.get("review_gates", {}).get(gate_id, {})
        if gate.get("status") != "passed" or not gate.get("receipt"):
            errors.append(f"审核门未通过或缺少回执: {gate_id}")
            continue
        receipt_path = run_dir / gate["receipt"]
        if not receipt_path.is_file() or gate.get("receipt_sha256") != sha256_file(receipt_path):
            errors.append(f"审核回执不存在或哈希失效: {gate_id}")
            continue
        report = verify_review_receipt(run_dir, receipt_path, require_current_revision=False)
        errors.extend(f"审核回执 {gate_id}: {item}" for item in report["errors"])


def _verify_final_package(run_dir: Path, errors: list[str]) -> None:
    qa_path = run_dir / "review/QA_AGGREGATE.json"
    evidence_path = run_dir / "review/EVIDENCE_VALIDATION.json"
    request_path = run_dir / "review/final_approval_request.json"
    receipt_path = run_dir / "review/final_approval_receipt.json"
    qa, evidence, request, receipt = map(load_json, (qa_path, evidence_path, request_path, receipt_path))
    require_valid(receipt, "final_approval_receipt")
    source_package = verify_source_manifest(run_dir)
    errors.extend(f"源码包: {item}" for item in source_package["errors"])
    if qa.get("status") != "pass" or qa.get("hard_failures"):
        errors.append("COMPLETE 要求 QA 聚合无 hard failure")
    if evidence.get("status") != "pass":
        errors.append("COMPLETE 要求证据校验通过")
    current = {
        "final_pdf_sha256": sha256_file(run_dir / request["final_pdf_path"]),
        "qa_report_sha256": sha256_file(qa_path),
        "evidence_report_sha256": sha256_file(evidence_path),
        "run_config_lock_sha256": sha256_file(run_dir / "config/RUN_CONFIG_LOCK.json"),
        "source_manifest_sha256": source_package["manifest_sha256"],
    }
    if receipt.get("approval_request_sha256") != sha256_file(request_path):
        errors.append("最终批准回执未绑定当前请求")
    for key, value in current.items():
        if request.get("bindings", {}).get(key) != value or receipt.get(key) != value:
            errors.append(f"最终批准事实绑定已失效: {key}")
