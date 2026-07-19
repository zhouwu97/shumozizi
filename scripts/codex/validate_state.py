"""校验工作流状态、路线锁和结果注册表的关键不变量。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError as exc:  # pragma: no cover - 由命令行环境负责安装依赖
    raise SystemExit(
        "缺少运行时依赖 jsonschema；请执行: python -m pip install -r requirements.txt"
    ) from exc


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.runtime.verify_execution import (  # noqa: E402
    RuntimeContractError,
    execution_record_path,
    resolve_run_path,
    sha256_file,
    verify_execution_record,
)


STATUSES = (
    "NEW",
    "ROUTE_PROPOSED",
    "WAITING_HUMAN_ROUTE",
    "ROUTE_LOCKED",
    "MODEL_SPEC_READY",
    "EXPERIMENTING",
    "RESULTS_ACCEPTED",
    "PAPER_DRAFTED",
    "SELF_REVIEWED",
    "WAITING_HUMAN_FINAL",
    "COMPLETE",
    "BLOCKED",
)
LOCKED_STATUSES = set(STATUSES[3:]) - {"BLOCKED"}
PAPER_STATUSES = {"PAPER_DRAFTED", "SELF_REVIEWED", "WAITING_HUMAN_FINAL", "COMPLETE"}
SCHEMA_ROOT = REPO_ROOT / "schemas"


def parse_args() -> argparse.Namespace:
    """解析运行目录参数。"""
    parser = argparse.ArgumentParser(description="校验 MathModelAgent 运行状态")
    parser.add_argument("run_dir", help="runs/<run_id> 目录")
    return parser.parse_args()


def load_json(path: Path, errors: list[str]) -> dict:
    """读取 JSON，并把格式错误加入错误列表。"""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"缺少文件: {path}")
        return {}
    except json.JSONDecodeError as exc:
        errors.append(f"JSON 格式错误 {path}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"根节点必须是对象: {path}")
        return {}
    return value


def validate_schema(document: dict, schema_name: str, errors: list[str]) -> None:
    """使用正式 JSON Schema 校验完整文档，包括嵌套结构和格式。"""
    schema_path = SCHEMA_ROOT / schema_name
    schema = load_json(schema_path, errors)
    if not schema:
        return
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for violation in sorted(validator.iter_errors(document), key=lambda item: list(item.path)):
        location = ".".join(str(part) for part in violation.absolute_path) or "<root>"
        errors.append(f"{schema_name} 校验失败 [{location}]: {violation.message}")


def validate_state(run_dir: Path, errors: list[str], warnings: list[str]) -> dict:
    """校验状态结构与人工检查点不变量。"""
    state = load_json(run_dir / "state.json", errors)
    if state:
        validate_schema(state, "workflow_state.schema.json", errors)
    required = {
        "schema_version",
        "run_id",
        "problem_source",
        "mode",
        "status",
        "completed_stages",
        "active_stage",
        "route_locked",
        "paper_ready",
        "question_progress",
        "last_updated_by",
        "updated_at",
    }
    missing = sorted(required - state.keys())
    if missing:
        errors.append(f"state.json 缺少字段: {', '.join(missing)}")
        return state
    status = state["status"]
    if status not in STATUSES:
        errors.append(f"未知状态: {status}")
    if state["mode"] not in {"competition", "training", "audit"}:
        errors.append(f"未知模式: {state['mode']}")
    if state["run_id"] != run_dir.name:
        errors.append("state.run_id 必须与运行目录名一致")

    candidates_path = run_dir / "brief" / "route_candidates.json"
    candidates: dict = {}
    candidates_required = isinstance(status, str) and status in set(STATUSES[1:]) - {"BLOCKED"}
    if candidates_path.exists():
        candidates = load_json(candidates_path, errors)
        if candidates:
            validate_schema(candidates, "route_candidates.schema.json", errors)
            if candidates.get("run_id") != state.get("run_id"):
                errors.append("route_candidates.run_id 与 state.run_id 不一致")
            candidate_ids = [
                item.get("route_id")
                for item in candidates.get("candidates", [])
                if isinstance(item, dict) and isinstance(item.get("route_id"), str)
            ]
            if len(candidate_ids) != len(set(candidate_ids)):
                errors.append("候选路线 route_id 重复")
            if candidates.get("recommended_route_id") not in candidate_ids:
                errors.append("recommended_route_id 必须引用真实存在的候选路线")
    elif candidates_required:
        errors.append("当前状态要求存在 brief/route_candidates.json")

    route_lock = run_dir / "brief" / "ROUTE_LOCK.json"
    route_lock_document: dict = {}
    if isinstance(status, str) and status in LOCKED_STATUSES:
        if not state["route_locked"]:
            errors.append(f"状态 {status} 要求 route_locked=true")
        if not route_lock.exists():
            errors.append("路线锁定后必须存在 brief/ROUTE_LOCK.json")
        else:
            route_lock_document = load_json(route_lock, errors)
            if route_lock_document:
                validate_schema(route_lock_document, "route_lock.schema.json", errors)
    elif state["route_locked"]:
        errors.append(f"状态 {status} 不应设置 route_locked=true")
    elif route_lock.exists():
        route_lock_document = load_json(route_lock, errors)
        if route_lock_document:
            validate_schema(route_lock_document, "route_lock.schema.json", errors)

    if candidates and route_lock_document:
        candidate_ids = {
            item.get("route_id")
            for item in candidates.get("candidates", [])
            if isinstance(item, dict) and isinstance(item.get("route_id"), str)
        }
        if route_lock_document.get("selected_route_id") not in candidate_ids:
            errors.append("selected_route_id 必须引用真实存在的候选路线")

    if isinstance(status, str) and status in PAPER_STATUSES and not state["paper_ready"]:
        warnings.append(f"状态 {status} 通常应设置 paper_ready=true")
    if state["paper_ready"] and not (run_dir / "paper").exists():
        errors.append("paper_ready=true 但 paper/ 不存在")
    return state


def validate_results(run_dir: Path, state: dict, errors: list[str]) -> None:
    """校验结果注册表和论文准入规则。"""
    registry = load_json(run_dir / "results" / "result_registry.json", errors)
    if not registry:
        return
    validate_schema(registry, "result_registry.schema.json", errors)
    if registry.get("run_id") != state.get("run_id"):
        errors.append("result_registry.run_id 与 state.run_id 不一致")
    results = registry.get("results")
    if not isinstance(results, list):
        errors.append("result_registry.results 必须是数组")
        return
    indexed = {
        result.get("result_id"): result
        for result in results
        if isinstance(result, dict) and isinstance(result.get("result_id"), str)
    }
    seen: set[str] = set()
    for index, result in enumerate(results):
        if not isinstance(result, dict):
            errors.append(f"results[{index}] 必须是对象")
            continue
        result_id = result.get("result_id")
        if not result_id:
            errors.append(f"results[{index}] 缺少 result_id")
        elif result_id in seen:
            errors.append(f"result_id 重复: {result_id}")
        else:
            seen.add(result_id)
        if result.get("paper_allowed") and result.get("status") != "accepted":
            errors.append(f"结果 {result_id} 未 accepted 却允许进入论文")
        if result.get("status") == "accepted":
            execution_id = result.get("execution_record_id")
            if not isinstance(execution_id, str):
                errors.append(f"已接受结果 {result_id} 缺少 execution_record_id")
            else:
                report = verify_execution_record(run_dir, execution_id)
                if not report["valid"]:
                    for message in report["errors"]:
                        errors.append(f"已接受结果 {result_id} 的执行证据无效: {message}")
                acceptance = result.get("acceptance")
                if not isinstance(acceptance, dict):
                    errors.append(f"已接受结果 {result_id} 缺少 accept_result.py 准入记录")
                else:
                    try:
                        record_path = execution_record_path(run_dir, execution_id)
                        if acceptance.get("execution_record_sha256") != sha256_file(record_path):
                            errors.append(f"已接受结果 {result_id} 的执行记录哈希不一致")
                    except (RuntimeContractError, FileNotFoundError) as exc:
                        errors.append(f"已接受结果 {result_id} 的执行记录不可用: {exc}")

            if result.get("cycle") != "baseline":
                baseline_id = result.get("baseline_result_id")
                baseline = indexed.get(baseline_id)
                if (
                    not baseline
                    or baseline.get("status") != "accepted"
                    or baseline.get("cycle") != "baseline"
                    or baseline.get("question_id") != result.get("question_id")
                ):
                    errors.append(
                        f"已接受结果 {result_id} 的 baseline_result_id 必须引用同一问题的已接受基线"
                    )

            claims = {
                claim_id
                for claim_id in result.get("innovation_claim_ids", [])
                if isinstance(claim_id, str)
            }
            evidence_by_claim: dict[str, str] = {}
            for item in result.get("innovation_evidence", []):
                if not isinstance(item, dict):
                    continue
                claim_id = item.get("claim_id")
                evidence_id = item.get("evidence_result_id")
                if not isinstance(claim_id, str) or not isinstance(evidence_id, str):
                    continue
                if claim_id in evidence_by_claim:
                    errors.append(f"已接受结果 {result_id} 的创新主张重复登记证据: {claim_id}")
                evidence_by_claim[claim_id] = evidence_id
            if claims != set(evidence_by_claim):
                errors.append(f"已接受结果 {result_id} 的创新主张与证据引用不完整")
            for claim_id, evidence_id in evidence_by_claim.items():
                evidence = indexed.get(evidence_id)
                if (
                    evidence_id == result_id
                    or not evidence
                    or evidence.get("status") != "accepted"
                    or evidence.get("cycle") not in {"robustness", "ablation"}
                    or evidence.get("question_id") != result.get("question_id")
                ):
                    errors.append(
                        f"已接受结果 {result_id} 的创新主张 {claim_id} 缺少同题验证或消融结果"
                    )

            for collection_name in ("constraint_checks", "validation_checks"):
                for check in result.get(collection_name, []):
                    if not isinstance(check, dict) or not check.get("evidence_path"):
                        continue
                    try:
                        resolve_run_path(
                            run_dir,
                            check["evidence_path"],
                            purpose=f"{collection_name}.evidence_path",
                            must_exist=True,
                        )
                    except RuntimeContractError as exc:
                        errors.append(f"已接受结果 {result_id} 的检查证据无效: {exc}")


def main() -> int:
    """执行校验并输出机器可读摘要。"""
    args = parse_args()
    run_dir = Path(args.run_dir).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    if not run_dir.is_dir():
        errors.append(f"运行目录不存在: {run_dir}")
        state = {}
    else:
        state = validate_state(run_dir, errors, warnings)
        validate_results(run_dir, state, errors)
    payload = {
        "valid": not errors,
        "run_dir": str(run_dir),
        "status": state.get("status"),
        "errors": errors,
        "warnings": warnings,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
