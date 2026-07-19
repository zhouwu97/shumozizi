"""作为唯一受支持入口，将可复验候选结果提升为 accepted。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .verify_execution import (
        RuntimeContractError,
        atomic_json,
        execution_record_path,
        load_json_object,
        resolve_run_path,
        sha256_file,
        validate_document,
        verify_execution_record,
    )
except ImportError:
    from verify_execution import (  # type: ignore[no-redef]
        RuntimeContractError,
        atomic_json,
        execution_record_path,
        load_json_object,
        resolve_run_path,
        sha256_file,
        validate_document,
        verify_execution_record,
    )


ADMISSION_VERSION = "1.0"
ADMISSION_TOOL = "scripts/runtime/accept_result.py"
EVIDENCE_CYCLES = {"robustness", "ablation"}


def utc_now() -> str:
    """返回带时区的 UTC 时间。"""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def result_index(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """建立唯一结果 ID 索引。"""
    indexed: dict[str, dict[str, Any]] = {}
    for result in results:
        result_id = result.get("result_id")
        if not isinstance(result_id, str):
            raise RuntimeContractError("结果记录缺少合法 result_id")
        if result_id in indexed:
            raise RuntimeContractError(f"result_id 重复: {result_id}")
        indexed[result_id] = result
    return indexed


def verify_linked_result(run_dir: Path, result: dict[str, Any], purpose: str) -> None:
    """复验被引用的 accepted 结果，防止伪造基线或创新证据。"""
    execution_id = result.get("execution_record_id")
    acceptance = result.get("acceptance")
    if not isinstance(execution_id, str) or not isinstance(acceptance, dict):
        raise RuntimeContractError(f"{purpose} 缺少完整准入信息")
    report = verify_execution_record(run_dir, execution_id)
    if not report["valid"]:
        raise RuntimeContractError(f"{purpose} 的执行记录复验失败")
    record_path = execution_record_path(run_dir, execution_id)
    if acceptance.get("execution_record_sha256") != sha256_file(record_path):
        raise RuntimeContractError(f"{purpose} 的准入哈希与执行记录不一致")


def validate_check_evidence(run_dir: Path, result: dict[str, Any]) -> None:
    """要求全部检查通过，并验证可选证据路径。"""
    for collection_name in ("constraint_checks", "validation_checks"):
        checks = result.get(collection_name)
        if not isinstance(checks, list) or not checks:
            raise RuntimeContractError(f"{collection_name} 至少需要一项通过记录")
        for check in checks:
            if not isinstance(check, dict) or check.get("passed") is not True:
                raise RuntimeContractError(f"{collection_name} 存在未通过检查")
            evidence_path = check.get("evidence_path")
            if evidence_path:
                resolve_run_path(
                    run_dir,
                    evidence_path,
                    purpose=f"{collection_name}.evidence_path",
                    must_exist=True,
                )


def validate_baseline(
    run_dir: Path,
    result: dict[str, Any],
    indexed: dict[str, dict[str, Any]],
) -> None:
    """要求非基线结果引用同一问题的 accepted 基线。"""
    if result.get("cycle") == "baseline":
        if result.get("baseline_result_id") is not None:
            raise RuntimeContractError("baseline 结果的 baseline_result_id 必须为 null")
        return
    baseline_id = result.get("baseline_result_id")
    baseline = indexed.get(baseline_id)
    if not baseline:
        raise RuntimeContractError("非 baseline 结果必须引用真实 baseline_result_id")
    if (
        baseline.get("status") != "accepted"
        or baseline.get("cycle") != "baseline"
        or baseline.get("question_id") != result.get("question_id")
    ):
        raise RuntimeContractError("baseline_result_id 必须引用同一问题的 accepted baseline")
    verify_linked_result(run_dir, baseline, "baseline_result_id")


def validate_innovation_evidence(
    run_dir: Path,
    result: dict[str, Any],
    indexed: dict[str, dict[str, Any]],
) -> None:
    """要求每个创新主张指向同题已接受的稳健性或消融结果。"""
    claim_ids = result.get("innovation_claim_ids", [])
    evidence_items = result.get("innovation_evidence", [])
    if not isinstance(claim_ids, list) or not isinstance(evidence_items, list):
        raise RuntimeContractError("创新主张与证据必须为数组")
    evidence_by_claim: dict[str, str] = {}
    for item in evidence_items:
        if not isinstance(item, dict):
            raise RuntimeContractError("innovation_evidence 项必须为对象")
        claim_id = item.get("claim_id")
        evidence_result_id = item.get("evidence_result_id")
        if claim_id in evidence_by_claim:
            raise RuntimeContractError(f"创新主张重复登记证据: {claim_id}")
        evidence_by_claim[claim_id] = evidence_result_id
    if set(claim_ids) != set(evidence_by_claim):
        raise RuntimeContractError("每个 innovation_claim_id 必须且只能对应一项验证证据")
    for claim_id, evidence_result_id in evidence_by_claim.items():
        evidence = indexed.get(evidence_result_id)
        if not evidence:
            raise RuntimeContractError(f"创新主张 {claim_id} 引用了不存在的结果")
        if (
            evidence.get("status") != "accepted"
            or evidence.get("cycle") not in EVIDENCE_CYCLES
            or evidence.get("question_id") != result.get("question_id")
        ):
            raise RuntimeContractError(
                f"创新主张 {claim_id} 必须引用同一问题的 accepted robustness/ablation 结果"
            )
        verify_linked_result(run_dir, evidence, f"创新主张 {claim_id} 的证据")


def accept_result(
    run_dir: Path,
    result_id: str,
    *,
    accepted_by: str,
    paper_allowed: bool,
) -> dict[str, Any]:
    """复验候选结果并原子完成 candidate 到 accepted 的转换。"""
    run_root = run_dir.resolve()
    if not accepted_by.strip():
        raise RuntimeContractError("accepted_by 不能为空")
    registry_path = run_root / "results" / "result_registry.json"
    registry = load_json_object(registry_path)
    initial_schema_errors = validate_document(registry, "result_registry.schema.json")
    if initial_schema_errors:
        raise RuntimeContractError("; ".join(initial_schema_errors))
    results = registry.get("results")
    if not isinstance(results, list) or not all(isinstance(item, dict) for item in results):
        raise RuntimeContractError("result_registry.results 必须是对象数组")
    indexed = result_index(results)
    result = indexed.get(result_id)
    if not result:
        raise RuntimeContractError(f"结果不存在: {result_id}")
    if result.get("status") != "candidate":
        raise RuntimeContractError("只有 candidate 可以转为 accepted")
    metrics = result.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        raise RuntimeContractError("metrics 不能为空")
    if not isinstance(result.get("unit"), str) or not result["unit"].strip():
        raise RuntimeContractError("unit 必须存在；无量纲时使用 dimensionless")
    if not isinstance(result.get("conclusion"), str) or not result["conclusion"].strip():
        raise RuntimeContractError("conclusion 不能为空")

    execution_id = result.get("execution_record_id")
    if not isinstance(execution_id, str):
        raise RuntimeContractError("execution_record_id 不合法")
    execution_report = verify_execution_record(run_root, execution_id)
    if not execution_report["valid"]:
        raise RuntimeContractError("执行记录复验失败: " + "; ".join(execution_report["errors"]))
    validate_check_evidence(run_root, result)
    validate_baseline(run_root, result, indexed)
    validate_innovation_evidence(run_root, result, indexed)

    record_path = execution_record_path(run_root, execution_id)
    result["status"] = "accepted"
    result["paper_allowed"] = paper_allowed
    result["acceptance"] = {
        "accepted_by": accepted_by,
        "accepted_at": utc_now(),
        "execution_record_sha256": sha256_file(record_path),
        "admission_tool": ADMISSION_TOOL,
        "admission_version": ADMISSION_VERSION,
    }
    final_schema_errors = validate_document(registry, "result_registry.schema.json")
    if final_schema_errors:
        raise RuntimeContractError("准入后 Schema 校验失败: " + "; ".join(final_schema_errors))
    atomic_json(registry_path, registry)
    return {
        "accepted": True,
        "result_id": result_id,
        "execution_record_id": execution_id,
        "paper_allowed": paper_allowed,
        "registry_path": str(registry_path),
    }


def parse_args() -> argparse.Namespace:
    """解析结果准入命令行参数。"""
    parser = argparse.ArgumentParser(description="接受可复验的实验结果")
    parser.add_argument("run_dir", help="runs/<run_id> 目录")
    parser.add_argument("--result-id", required=True, help="候选结果 ID")
    parser.add_argument("--accepted-by", default="codex-desktop", help="接受者标识")
    parser.add_argument(
        "--paper-allowed",
        action="store_true",
        help="允许论文引用该 accepted 结果",
    )
    return parser.parse_args()


def main() -> int:
    """执行结果准入并输出 JSON。"""
    args = parse_args()
    try:
        payload = accept_result(
            Path(args.run_dir),
            args.result_id,
            accepted_by=args.accepted_by,
            paper_allowed=args.paper_allowed,
        )
    except RuntimeContractError as exc:
        payload = {"accepted": False, "errors": [str(exc)]}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("accepted") else 1


if __name__ == "__main__":
    raise SystemExit(main())
