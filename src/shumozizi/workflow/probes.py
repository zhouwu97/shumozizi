"""受限科学 probe 的不可变计划、执行结果和事实绑定。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.core.schema import require_valid


def _require_relative_paths(paths: list[str], *, label: str) -> None:
    for value in paths:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ContractError(f"{label} 只能包含运行目录内规范相对路径: {value}")


def create_probe_plan(
    run_dir: Path,
    report_path: Path,
    adjudication_path: Path,
    plan: dict[str, Any],
) -> Path:
    """为一条 ``needs_probe`` finding 冻结受限 probe 计划。"""
    report = load_json(report_path)
    adjudication = load_json(adjudication_path)
    require_valid(report, "review_report")
    require_valid(adjudication, "review_adjudication")
    finding_id = plan.get("finding_id")
    needs_probe = {
        item["finding_id"]
        for item in adjudication["decisions"]
        if item["main_decision"] == "needs_probe"
    }
    if finding_id not in needs_probe:
        raise ContractError("PROBE_PLAN finding_id 必须对应 needs_probe 裁决")
    expected = {
        "run_id": report["run_id"],
        "request_id": report["request_id"],
        "source_report_sha256": sha256_file(report_path),
        "source_adjudication_sha256": sha256_file(adjudication_path),
    }
    if any(plan.get(key) != value for key, value in expected.items()):
        raise ContractError("PROBE_PLAN 未绑定当前报告或初始裁决")
    _require_relative_paths(plan["allowed_files"], label="allowed_files")
    _require_relative_paths(plan["expected_outputs"], label="expected_outputs")
    require_valid(plan, "probe_plan")
    path = report_path.with_name("PROBE_PLAN.json")
    if path.exists():
        raise ContractError("一轮审核只能生成一份不可变 PROBE_PLAN.json")
    atomic_json(path, plan)
    return path


def write_probe_result(plan_path: Path, result: dict[str, Any]) -> Path:
    """校验预算与输出边界后写入不可变 PROBE_RESULT.json。"""
    plan = load_json(plan_path)
    require_valid(plan, "probe_plan")
    expected = {
        "run_id": plan["run_id"],
        "request_id": plan["request_id"],
        "finding_id": plan["finding_id"],
        "probe_plan_sha256": sha256_file(plan_path),
    }
    if any(result.get(key) != value for key, value in expected.items()):
        raise ContractError("PROBE_RESULT 未绑定当前 PROBE_PLAN.json")
    if len(result["executed_commands"]) > plan["budget"]["max_commands"]:
        raise ContractError("probe 执行命令数超过冻结预算")
    allowed_commands = set(plan["allowed_commands"])
    if any(command not in allowed_commands for command in result["executed_commands"]):
        raise ContractError("PROBE_RESULT 包含未授权命令")
    _require_relative_paths(result["outputs"], label="outputs")
    if not set(result["outputs"]).issubset(plan["expected_outputs"]):
        raise ContractError("PROBE_RESULT 输出超出计划声明")
    run_dir = plan_path.parents[3]
    total_size = 0
    for relative in result["outputs"]:
        output = (run_dir / relative).resolve()
        try:
            output.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise ContractError("probe 输出越过运行目录") from exc
        if not output.is_file():
            raise ContractError(f"probe 输出不存在: {relative}")
        total_size += output.stat().st_size
    if total_size > plan["budget"]["max_output_bytes"]:
        raise ContractError("probe 输出总大小超过冻结预算")
    require_valid(result, "probe_result")
    path = plan_path.with_name("PROBE_RESULT.json")
    if path.exists():
        raise ContractError("一份 PROBE_PLAN 只能生成一份不可变 PROBE_RESULT.json")
    atomic_json(path, result)
    return path
