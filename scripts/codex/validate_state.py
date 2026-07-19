"""校验工作流状态、路线锁和结果注册表的关键不变量。"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


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


def yaml_top_level(path: Path) -> dict[str, str]:
    """读取路线锁顶层标量；避免为校验脚本引入 YAML 依赖。"""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line[0].isspace() or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if match:
            values[match.group(1)] = match.group(2).strip().strip('"\'')
    return values


def validate_state(run_dir: Path, errors: list[str], warnings: list[str]) -> dict:
    """校验状态结构与人工检查点不变量。"""
    state = load_json(run_dir / "state.json", errors)
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
    if state["status"] not in STATUSES:
        errors.append(f"未知状态: {state['status']}")
    if state["mode"] not in {"competition", "training", "audit"}:
        errors.append(f"未知模式: {state['mode']}")
    if state["run_id"] != run_dir.name:
        errors.append("state.run_id 必须与运行目录名一致")

    route_lock = run_dir / "brief" / "ROUTE_LOCK.yaml"
    if state["status"] in LOCKED_STATUSES:
        if not state["route_locked"]:
            errors.append(f"状态 {state['status']} 要求 route_locked=true")
        if not route_lock.exists():
            errors.append("路线锁定后必须存在 brief/ROUTE_LOCK.yaml")
        else:
            values = yaml_top_level(route_lock)
            if values.get("approved", "").lower() != "true":
                errors.append("ROUTE_LOCK.yaml 必须包含 approved: true")
            for field in (
                "selected_route_id",
                "problem_interpretation",
                "primary_route",
                "fallback_route",
            ):
                if not values.get(field):
                    errors.append(f"ROUTE_LOCK.yaml 缺少有效字段: {field}")
    elif state["route_locked"]:
        errors.append(f"状态 {state['status']} 不应设置 route_locked=true")

    if state["status"] in PAPER_STATUSES and not state["paper_ready"]:
        warnings.append(f"状态 {state['status']} 通常应设置 paper_ready=true")
    if state["paper_ready"] and not (run_dir / "paper").exists():
        errors.append("paper_ready=true 但 paper/ 不存在")
    return state


def validate_results(run_dir: Path, state: dict, errors: list[str]) -> None:
    """校验结果注册表和论文准入规则。"""
    registry = load_json(run_dir / "results" / "result_registry.json", errors)
    if not registry:
        return
    if registry.get("run_id") != state.get("run_id"):
        errors.append("result_registry.run_id 与 state.run_id 不一致")
    results = registry.get("results")
    if not isinstance(results, list):
        errors.append("result_registry.results 必须是数组")
        return
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
            for key in ("source_script", "source_output"):
                source = result.get(key)
                if not source:
                    errors.append(f"已接受结果 {result_id} 缺少 {key}")
                    continue
                source_path = Path(source)
                if not source_path.is_absolute():
                    source_path = run_dir / source_path
                if not source_path.exists():
                    errors.append(f"已接受结果 {result_id} 的 {key} 不存在: {source}")


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
