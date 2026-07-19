"""校验工作流状态、路线锁和结果注册表的关键不变量。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError as exc:  # pragma: no cover - 由命令行环境负责安装依赖
    raise SystemExit(
        "缺少运行时依赖 jsonschema；请执行: python -m pip install -r requirements.txt"
    ) from exc


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
SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas"


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
    accepted_baselines = {
        result.get("result_id"): result.get("question_id")
        for result in results
        if isinstance(result, dict)
        and result.get("status") == "accepted"
        and result.get("cycle") == "baseline"
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
            if result.get("cycle") != "baseline":
                baseline_id = result.get("baseline_result_id")
                if accepted_baselines.get(baseline_id) != result.get("question_id"):
                    errors.append(
                        f"已接受结果 {result_id} 的 baseline_result_id 必须引用同一问题的已接受基线"
                    )
            evidenced_claim_ids = {
                claim_id
                for check in result.get("validation_checks", [])
                if isinstance(check, dict) and check.get("passed") is True
                for claim_id in check.get("claim_ids", [])
            }
            for claim_id in result.get("innovation_claim_ids", []):
                if claim_id not in evidenced_claim_ids:
                    errors.append(f"已接受结果 {result_id} 的创新主张 {claim_id} 缺少验证证据")
            for key in ("source_script", "source_output"):
                source = result.get(key)
                if not source:
                    errors.append(f"已接受结果 {result_id} 缺少 {key}")
                    continue
                source_path = Path(source)
                if not source_path.is_absolute():
                    source_path = run_dir / source_path
                source_path = source_path.resolve()
                if run_dir != source_path and run_dir not in source_path.parents:
                    errors.append(f"已接受结果 {result_id} 的 {key} 越过运行目录边界: {source}")
                    continue
                if not source_path.exists():
                    errors.append(f"已接受结果 {result_id} 的 {key} 不存在: {source}")
                    continue
                hash_key = "source_sha256" if key == "source_script" else "output_sha256"
                actual_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
                if result.get(hash_key) != actual_hash:
                    errors.append(f"已接受结果 {result_id} 的 {hash_key} 与当前文件不一致")


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
