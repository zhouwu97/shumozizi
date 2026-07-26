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


def _creation_event_schema() -> dict[str, Any]:
    """返回 create_thread 原始事件的 Schema。"""
    return load_json(
        resolve_repo_root(Path(__file__)) / "schemas/review_task_creation_event.schema.json"
    )


def persist_review_task_creation_event(
    run_dir: Path,
    *,
    event_file: str,
    raw_event: dict[str, Any],
) -> Path:
    """保存协调器收到的 create_thread 原始元数据。

    该函数不创建任务，也不接受回执字段；协调器必须先实际调用 provider 的
    ``create_thread``，再把返回的 task/thread 元数据原样映射到 ``raw_event``。

    Args:
        run_dir: 当前运行目录。
        event_file: 运行目录内的创建事件保存位置。
        raw_event: 真实 create_thread 返回的标准化最小字段。

    Returns:
        已保存事件的绝对路径。

    Raises:
        ContractError: 事件结构不符合 fresh-thread 合同。
    """
    errors = [
        error.message
        for error in Draft202012Validator(
            _creation_event_schema(), format_checker=FormatChecker()
        ).iter_errors(raw_event)
    ]
    if errors:
        raise ContractError("审核任务创建事件不合法: " + "；".join(errors))
    path = resolve_inside(run_dir, event_file, must_exist=False)
    atomic_json(path, raw_event)
    return path


def create_review_task_receipt(
    run_dir: Path,
    *,
    task_id: str,
    task_type: str,
    thread_id: str | None = None,
    model_id: str,
    prompt_sha256: str,
    input_bindings: dict[str, Any],
    report_file: str,
    parent_task_id: str | None = None,
    created_at: str | None = None,
    completed_at: str | None = None,
    creation_event_file: str | None = None,
) -> Path:
    """写入一个绑定真实报告与输入清单的完成回执。

    新生产回执必须传入 ``creation_event_file``。保留 ``thread_id`` 仅用于读取
    历史回执；这类 v1.0 回执不能通过 ``require_fresh_thread`` 放行门。
    """
    report = resolve_inside(run_dir, report_file, must_exist=True)
    event: dict[str, Any] | None = None
    if creation_event_file is not None:
        event_path = resolve_inside(run_dir, creation_event_file, must_exist=True)
        event = load_json(event_path)
        event_errors = [
            error.message
            for error in Draft202012Validator(
                _creation_event_schema(), format_checker=FormatChecker()
            ).iter_errors(event)
        ]
        if event_errors:
            raise ContractError("create_thread 原始事件不合法: " + "；".join(event_errors))
        if thread_id is not None and thread_id != event["raw_thread_id"]:
            raise ContractError("手工 thread_id 与 create_thread 原始事件不一致")
        thread_id = event["raw_thread_id"]
    if not thread_id:
        raise ContractError("回执必须绑定 thread_id 或 create_thread 原始事件")
    payload = {
        "schema_name": "review_task_receipt",
        "schema_version": "1.1" if event is not None else "1.0",
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
    if event is not None:
        payload["creation_event_file"] = relative_inside(run_dir, event_path).as_posix()
        payload["creation_event_sha256"] = sha256_file(event_path)
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
    expected_prompt_sha256: str | None = None,
    require_fresh_thread: bool = False,
) -> dict[str, Any]:
    """复验任务类型、提示词、输入摘要、父任务与报告内容。"""
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
    if (
        expected_prompt_sha256 is not None
        and receipt["prompt_sha256"] != expected_prompt_sha256
    ):
        raise ContractError("审核任务回执未使用规定的独立审核提示词")
    if receipt["input_manifest_sha256"] != review_input_manifest_sha256(expected_input_bindings):
        raise ContractError("审核任务回执未绑定当前输入清单")
    if require_fresh_thread:
        if receipt.get("schema_version") != "1.1":
            raise ContractError("审核任务回执没有 create_thread 原始事件，不能证明 fresh thread")
        event_path = resolve_inside(run_dir, receipt["creation_event_file"], must_exist=True)
        if sha256_file(event_path) != receipt["creation_event_sha256"]:
            raise ContractError("create_thread 原始事件哈希已变化")
        event = load_json(event_path)
        event_errors = [
            error.message
            for error in Draft202012Validator(
                _creation_event_schema(), format_checker=FormatChecker()
            ).iter_errors(event)
        ]
        if event_errors:
            raise ContractError("create_thread 原始事件不合法: " + "；".join(event_errors))
        if event["raw_thread_id"] != receipt["thread_id"]:
            raise ContractError("回执 thread_id 未绑定 create_thread 原始 thread_id")
    report = resolve_inside(run_dir, receipt["report_file"], must_exist=True)
    expected = resolve_inside(run_dir, expected_report, must_exist=True)
    if report != expected or sha256_file(report) != receipt["report_sha256"]:
        raise ContractError("审核任务回执未绑定当前实际报告或报告已变化")
    return receipt
