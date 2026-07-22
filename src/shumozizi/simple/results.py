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
JSON_PATH = re.compile(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*")


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


def json_path_value(payload: Any, json_path: str) -> Any:
    """读取仅由对象键组成的 JSON 点路径。

    Args:
        payload: 已解析 JSON 数据。
        json_path: 例如 ``metrics.objective`` 的点路径。

    Returns:
        路径对应的 JSON 值。

    Raises:
        ContractError: 路径不安全、字段不存在或中间节点不是对象。
    """
    if not JSON_PATH.fullmatch(json_path):
        raise ContractError(f"JSON 指标路径不合法: {json_path}")
    value = payload
    for key in json_path.split("."):
        if not isinstance(value, dict) or key not in value:
            raise ContractError(f"JSON 指标路径不存在: {json_path}")
        value = value[key]
    return value


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


def _normalize_paths(run_dir: Path, paths: list[str], *, must_exist: bool) -> list[str]:
    """规范化并校验一组运行目录内路径。

    Args:
        run_dir: v3 运行目录。
        paths: 相对运行目录的路径。
        must_exist: 是否要求路径已存在。

    Returns:
        规范的 POSIX 相对路径列表。
    """
    return [
        relative_inside(run_dir, resolve_inside(run_dir, path, must_exist=must_exist)).as_posix()
        for path in paths
    ]


def _hash_files(run_dir: Path, paths: list[str]) -> dict[str, str]:
    """计算一组运行目录内文件的哈希。

    Args:
        run_dir: v3 运行目录。
        paths: 相对运行目录的文件路径。

    Returns:
        路径到 SHA-256 的映射。
    """
    return {
        relative: sha256_file(resolve_inside(run_dir, relative, must_exist=True))
        for relative in paths
    }


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


def _metric_sources(
    run_dir: Path,
    metrics: dict[str, Any],
    requested_sources: dict[str, dict[str, str]],
    output_hashes: dict[str, str],
) -> dict[str, dict[str, str]]:
    """验证每个指标都由当前 JSON 输出中的具体字段导出。

    Args:
        run_dir: v3 运行目录。
        metrics: 已从输出提取的指标值。
        requested_sources: 指标到输出路径和 JSON 路径的映射。
        output_hashes: 本次输出文件哈希。

    Returns:
        含输出哈希的规范指标来源映射。

    Raises:
        ContractError: 指标来源缺失、越界、未声明为输出或与 JSON 不一致。
    """
    if set(metrics) != set(requested_sources):
        raise ContractError("每个指标必须恰好对应一个输出来源")
    normalized: dict[str, dict[str, str]] = {}
    for metric_name, source in requested_sources.items():
        source_file = source.get("file", "")
        json_path = source.get("json_path", "")
        canonical = _normalize_paths(run_dir, [source_file], must_exist=True)[0]
        if canonical not in output_hashes:
            raise ContractError(f"指标 {metric_name} 的来源不是本次预期输出: {canonical}")
        path = resolve_inside(run_dir, canonical, must_exist=True)
        if path.suffix.lower() != ".json":
            raise ContractError(f"指标 {metric_name} 的来源必须是 JSON 输出: {canonical}")
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(f"指标来源 JSON 不可读取: {canonical}") from exc
        if json_path_value(document, json_path) != metrics[metric_name]:
            raise ContractError(f"指标 {metric_name} 与来源 JSON 不一致")
        normalized[metric_name] = {
            "file": canonical,
            "json_path": json_path,
            "file_sha256": output_hashes[canonical],
        }
    return normalized


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
    metric_sources: dict[str, dict[str, str]],
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
        metrics: 从 JSON 输出自动提取的指标。
        metric_sources: 指标对应的输出文件和 JSON 路径。
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
        ContractError: 文件、指标来源、ID 或索引不满足协议。
    """
    identifier = _safe_result_id(result_id)
    index = read_result_index(run_dir)
    if any(item["result_id"] == identifier for item in index["results"]):
        raise ContractError(f"result_id 已存在: {identifier}")
    normalized_inputs = _normalize_paths(run_dir, input_files, must_exist=True)
    normalized_outputs = _normalize_paths(run_dir, output_files, must_exist=False)
    existing_outputs = [path for path in normalized_outputs if (run_dir / path).is_file()]
    succeeded = exit_code == 0 and len(existing_outputs) == len(normalized_outputs)
    if source_script is not None:
        source_script = _normalize_paths(run_dir, [source_script], must_exist=True)[0]
        if source_script not in normalized_inputs:
            raise ContractError("源脚本必须作为输入文件记录")
    input_hashes = _hash_files(run_dir, normalized_inputs)
    output_hashes = _hash_files(run_dir, existing_outputs)
    if succeeded:
        assert_outputs_readable(run_dir, existing_outputs)
        normalized_metric_sources = _metric_sources(
            run_dir, metrics, metric_sources, output_hashes
        )
    else:
        if metrics or metric_sources:
            raise ContractError("失败执行不能登记指标或指标来源")
        normalized_metric_sources = {}
    status = "current" if succeeded else "failed"
    entry: dict[str, Any] = {
        "result_id": identifier,
        "question_id": question_id,
        "kind": kind,
        "source_script": source_script,
        "command": command,
        "input_files": normalized_inputs,
        "input_hashes": input_hashes,
        "output_files": existing_outputs,
        "output_hashes": output_hashes,
        "metrics": metrics,
        "metric_sources": normalized_metric_sources,
        "status": status,
        "execution_valid": succeeded,
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
    index["results"].append(entry)
    require_result_index(index)
    atomic_json(run_dir / INDEX_PATH, index)
    return entry


def verify_current_result_files(run_dir: Path) -> dict[str, Any]:
    """复验仍可用于论文事实引用的执行输入、输出和指标来源。

    Args:
        run_dir: v3 运行目录。

    Returns:
        已检查结果、错误明细和整体通过状态。
    """
    index = read_result_index(run_dir)
    errors: list[dict[str, str]] = []
    checked_result_ids: list[str] = []
    for result in index["results"]:
        if result["status"] != "current":
            continue
        result_id = result["result_id"]
        checked_result_ids.append(result_id)
        if not result["execution_valid"]:
            errors.append(
                {
                    "result_id": result_id,
                    "message": "current 结果未标记为 execution_valid",
                }
            )
            continue
        for field, hashes in (
            ("input", result["input_hashes"]),
            ("output", result["output_hashes"]),
        ):
            for relative, expected_hash in hashes.items():
                try:
                    actual_hash = sha256_file(
                        resolve_inside(run_dir, relative, must_exist=True)
                    )
                except ContractError as exc:
                    errors.append({"result_id": result_id, "message": f"{field} 文件无效: {exc}"})
                    continue
                if actual_hash != expected_hash:
                    errors.append(
                        {"result_id": result_id, "message": f"{field} 哈希不一致: {relative}"}
                    )
        try:
            assert_outputs_readable(run_dir, result["output_files"])
        except ContractError as exc:
            errors.append({"result_id": result_id, "message": str(exc)})
        if set(result["metrics"]) != set(result["metric_sources"]):
            errors.append({"result_id": result_id, "message": "指标与指标来源集合不一致"})
            continue
        for metric_name, source in result["metric_sources"].items():
            try:
                source_path = resolve_inside(run_dir, source["file"], must_exist=True)
                current_hash = sha256_file(source_path)
                if current_hash != source["file_sha256"]:
                    raise ContractError(f"指标来源哈希不一致: {source['file']}")
                if source["file"] not in result["output_hashes"]:
                    raise ContractError(f"指标来源不是登记输出: {source['file']}")
                document = json.loads(source_path.read_text(encoding="utf-8"))
                if json_path_value(document, source["json_path"]) != result["metrics"][metric_name]:
                    raise ContractError(f"指标来源值不一致: {metric_name}")
            except (ContractError, OSError, json.JSONDecodeError) as exc:
                errors.append({"result_id": result_id, "message": str(exc)})
    return {
        "success": not errors,
        "checked_result_ids": checked_result_ids,
        "errors": errors,
    }
