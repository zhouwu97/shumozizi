"""维护 v3 运行的可追溯结果索引，而不评价科学结论。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    load_json,
    relative_inside,
    resolve_inside,
    sha256_file,
)
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.simple.state import utc_now

INDEX_PATH = Path("results/index.json")


def _schema() -> dict[str, Any]:
    """读取 v3 结果索引 Schema。

    Returns:
        JSON Schema 对象。
    """
    return load_json(resolve_repo_root(Path(__file__)) / "schemas/simple_result_index.schema.json")


def validate_result_index(payload: dict[str, Any]) -> list[str]:
    """校验结果索引。

    Args:
        payload: 待校验索引对象。

    Returns:
        全部校验错误；为空表示通过。
    """
    validator = Draft202012Validator(_schema())
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    ]


def require_result_index(payload: dict[str, Any]) -> None:
    """确保结果索引符合 v3 协议。

    Args:
        payload: 待校验索引对象。

    Raises:
        ContractError: 索引不符合 Schema。
    """
    errors = validate_result_index(payload)
    if errors:
        raise ContractError("; ".join(errors))


def read_result_index(run_dir: Path) -> dict[str, Any]:
    """读取并校验结果索引。

    Args:
        run_dir: v3 运行目录。

    Returns:
        已校验结果索引。
    """
    payload = load_json(run_dir / INDEX_PATH)
    require_result_index(payload)
    return payload


def _safe_result_id(value: str) -> str:
    """验证结果 ID。

    Args:
        value: 候选结果 ID。

    Returns:
        原样返回的安全 ID。

    Raises:
        ContractError: ID 含有不安全字符。
    """
    if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise ContractError(f"result_id 不合法: {value}")
    return value


def _hash_files(run_dir: Path, paths: list[str]) -> dict[str, str]:
    """计算一组运行目录内文件的哈希。

    Args:
        run_dir: v3 运行目录。
        paths: 相对运行目录的文件路径。

    Returns:
        路径到 SHA-256 的映射。
    """
    hashes: dict[str, str] = {}
    for relative in paths:
        hashes[relative] = sha256_file(resolve_inside(run_dir, relative, must_exist=True))
    return hashes


def assert_outputs_readable(run_dir: Path, paths: list[str]) -> None:
    """检查预期输出存在且 JSON 输出可读取。

    Args:
        run_dir: v3 运行目录。
        paths: 相对运行目录的输出路径。

    Raises:
        ContractError: 输出不存在、为空或 JSON 损坏。
    """
    for relative in paths:
        output = resolve_inside(run_dir, relative, must_exist=True)
        if output.stat().st_size == 0:
            raise ContractError(f"输出文件为空: {relative}")
        if output.suffix.lower() == ".json":
            try:
                json.loads(output.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ContractError(f"JSON 输出不可读取: {relative}") from exc


def register_result(
    run_dir: Path,
    *,
    result_id: str,
    question_id: str,
    kind: str,
    command: str,
    source_script: str | None,
    input_files: list[str],
    output_files: list[str],
    metrics: dict[str, Any],
    exit_code: int,
    stdout_path: str,
    stderr_path: str,
    started_at: str,
    finished_at: str,
    duration_seconds: float,
    error: str | None = None,
) -> dict[str, Any]:
    """登记一次执行，不把执行成功误写成科学结论。

    Args:
        run_dir: v3 运行目录。
        result_id: 唯一结果 ID。
        question_id: 对应问题 ID。
        kind: 结果类型，例如 baseline、primary 或 robustness。
        command: 实际执行命令。
        source_script: 可定位的源脚本相对路径。
        input_files: 本次使用的输入文件。
        output_files: 预期输出文件。
        metrics: 执行器接收到的数值指标。
        exit_code: 子进程退出码。
        stdout_path: stdout 日志路径。
        stderr_path: stderr 日志路径。
        started_at: 执行开始时间。
        finished_at: 执行结束时间。
        duration_seconds: 执行耗时。
        error: 失败原因。

    Returns:
        新登记的结果条目。

    Raises:
        ContractError: 文件、ID 或索引不满足协议。
    """
    identifier = _safe_result_id(result_id)
    index = read_result_index(run_dir)
    if any(item["result_id"] == identifier for item in index["results"]):
        raise ContractError(f"result_id 已存在: {identifier}")
    normalized_inputs = [relative_inside(run_dir, resolve_inside(run_dir, path, must_exist=True)).as_posix() for path in input_files]
    normalized_outputs = [relative_inside(run_dir, resolve_inside(run_dir, path, must_exist=True)).as_posix() for path in output_files if (run_dir / path).is_file()]
    succeeded = exit_code == 0 and len(normalized_outputs) == len(output_files)
    if succeeded:
        assert_outputs_readable(run_dir, normalized_outputs)
    status = "current" if succeeded else "failed"
    entry: dict[str, Any] = {
        "result_id": identifier,
        "question_id": question_id,
        "kind": kind,
        "source_script": source_script,
        "command": command,
        "input_files": normalized_inputs,
        "input_hashes": _hash_files(run_dir, normalized_inputs),
        "output_files": normalized_outputs,
        "output_hashes": _hash_files(run_dir, normalized_outputs),
        "metrics": metrics,
        "status": status,
        "paper_allowed": succeeded,
        "exit_code": exit_code,
        "stdout_path": stdout_path,
        "stderr_path": stderr_path,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": round(duration_seconds, 6),
        "error": error,
        "created_at": utc_now(),
    }
    if succeeded:
        for existing in index["results"]:
            if (
                existing["question_id"] == question_id
                and existing["kind"] == kind
                and existing["status"] == "current"
            ):
                existing["status"] = "superseded"
                existing["paper_allowed"] = False
    index["results"].append(entry)
    require_result_index(index)
    atomic_json(run_dir / INDEX_PATH, index)
    return entry
