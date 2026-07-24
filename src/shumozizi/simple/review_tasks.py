"""创建并复验独立审核任务的统一完成回执。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    json_bytes,
    load_json,
    relative_inside,
    resolve_inside,
    sha256_bytes,
    sha256_file,
)
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.simple.state import utc_now


def review_input_manifest_sha256(bindings: dict[str, Any]) -> str:
    """返回审核任务输入绑定的规范摘要。"""
    return sha256_bytes(json_bytes(bindings))


def _schema() -> dict[str, Any]:
    """返回审核任务回执 Schema。"""
    return load_json(resolve_repo_root(Path(__file__)) / "schemas/review_task_receipt.schema.json")


def create_review_task_receipt(
    run_dir: Path,
    *,
    task_id: str,
    task_type: str,
    thread_id: str,
    model_id: str,
    prompt_sha256: str,
    input_bindings: dict[str, Any],
    report_file: str,
    parent_task_id: str | None = None,
    created_at: str | None = None,
    completed_at: str | None = None,
) -> Path:
    """写入一个绑定真实报告与输入清单的完成回执。"""
    report = resolve_inside(run_dir, report_file, must_exist=True)
    payload = {
        "schema_name": "review_task_receipt",
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "task_id": task_id,
        "task_type": task_type,
        "thread_id": thread_id,
        "model_id": model_id,
        "prompt_sha256": prompt_sha256,
        "input_manifest_sha256": review_input_manifest_sha256(input_bindings),
        "parent_task_id": parent_task_id,
        "created_at": created_at or utc_now(),
        "completed_at": completed_at or utc_now(),
        "report_file": relative_inside(run_dir, report).as_posix(),
        "report_sha256": sha256_file(report),
    }
    errors = [error.message for error in Draft202012Validator(_schema(), format_checker=FormatChecker()).iter_errors(payload)]
    if errors:
        raise ContractError("审核任务回执不合法: " + "；".join(errors))
    path = run_dir / "review" / "tasks" / task_id / "receipt.json"
    atomic_json(path, payload)
    return path


def validate_review_task_receipt(
    run_dir: Path,
    receipt_file: str,
    *,
    expected_type: str,
    expected_report: str,
    expected_input_bindings: dict[str, Any],
    expected_parent_task_id: str | None = None,
) -> dict[str, Any]:
    """复验任务类型、输入摘要、父任务与报告内容。"""
    path = resolve_inside(run_dir, receipt_file, must_exist=True)
    receipt = load_json(path)
    validator = Draft202012Validator(_schema(), format_checker=FormatChecker())
    errors = [error.message for error in validator.iter_errors(receipt)]
    if errors:
        raise ContractError("审核任务回执不符合 Schema: " + "；".join(errors))
    if receipt["run_id"] != run_dir.name or receipt["task_type"] != expected_type:
        raise ContractError("审核任务回执的 run_id 或 task_type 不匹配")
    if receipt["parent_task_id"] != expected_parent_task_id:
        raise ContractError("审核任务回执未绑定当前父任务")
    if receipt["input_manifest_sha256"] != review_input_manifest_sha256(expected_input_bindings):
        raise ContractError("审核任务回执未绑定当前输入清单")
    report = resolve_inside(run_dir, receipt["report_file"], must_exist=True)
    expected = resolve_inside(run_dir, expected_report, must_exist=True)
    if report != expected or sha256_file(report) != receipt["report_sha256"]:
        raise ContractError("审核任务回执未绑定当前实际报告或报告已变化")
    return receipt
