"""执行 v3 实验并记录可复验的事实证据。"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, relative_inside, resolve_inside, sha256_file
from shumozizi.simple.results import json_path_value, register_result, safe_result_id
from shumozizi.simple.source_closure import python_source_closure
from shumozizi.simple.state import read_simple_state, utc_now


def _output_snapshot(run_dir: Path, paths: list[str]) -> dict[str, dict[str, Any]]:
    """保存运行前的输出文件状态，用于运行后检测新鲜度。

    Returns:
        路径到 ``{exists, sha256, size, mtime_ns}`` 的映射。
    """
    snap: dict[str, dict[str, Any]] = {}
    for path in paths:
        full = run_dir / path
        try:
            stat = full.stat()
            snap[path] = {
                "exists": True,
                "sha256": sha256_file(full),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        except (OSError, ValueError):
            snap[path] = {"exists": False}
    return snap


def _verify_output_freshness(
    run_dir: Path,
    paths: list[str],
    before: dict[str, dict[str, Any]],
) -> list[str]:
    """返回未发生变化的输出路径列表（非新鲜输出）。

    文件不存在/新增/内容变化都视为新鲜。
    """
    stale: list[str] = []
    for path in paths:
        before_state = before.get(path, {})
        full = run_dir / path
        try:
            after_sha = sha256_file(full)
        except (OSError, ValueError):
            after_sha = None
        if before_state.get("exists") and after_sha == before_state.get("sha256"):
            stale.append(path)
    return stale


def _parse_command(command: str) -> list[str]:
    """解析不含 Shell 组合语义的执行命令。

    Args:
        command: 用户提供的命令字符串。

    Returns:
        可直接交给 ``subprocess.run(shell=False)`` 的参数列表。

    Raises:
        ContractError: 命令为空或包含重定向、管道等 Shell 语义。
    """
    if not command.strip():
        raise ContractError("执行命令不能为空")
    if any(token in command for token in ("|", ">", "<", "&&", ";")):
        raise ContractError("v3 执行命令不允许管道、重定向或组合命令")
    # Windows 保留反斜杠路径；随后去掉 ``shlex`` 为带空格可执行文件保留的外层引号。
    arguments = shlex.split(command, posix=False)
    arguments = [
        item[1:-1] if len(item) >= 2 and item[0] == item[-1] and item[0] in {"'", '"'} else item
        for item in arguments
    ]
    if not arguments:
        raise ContractError("执行命令不能为空")
    return arguments


def _source_script(run_dir: Path, arguments: list[str]) -> str | None:
    """从命令参数中识别运行目录内的源脚本。

    Args:
        run_dir: v3 运行目录。
        arguments: 已解析命令参数。

    Returns:
        第一个可验证脚本的相对路径；找不到时为 ``None``。
    """
    for argument in arguments[1:]:
        candidate = Path(argument)
        if candidate.is_absolute() or candidate.suffix.lower() not in {".py", ".m", ".r", ".jl"}:
            continue
        try:
            script = resolve_inside(run_dir, argument, must_exist=True)
        except ContractError:
            continue
        return relative_inside(run_dir, script).as_posix()
    return None


def _extract_output_metrics(
    run_dir: Path,
    *,
    metrics_from: str | None,
    metric_paths: dict[str, str],
    expected_outputs: list[str],
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    """从本次 JSON 输出提取指标及其来源，而不接受自由手填数值。

    Args:
        run_dir: v3 运行目录。
        metrics_from: 指标 JSON 输出路径；省略时不登记指标。
        metric_paths: 指标名到 JSON 点路径的映射。
        expected_outputs: 本次执行声明的输出路径。

    Returns:
        指标值和不含哈希的来源描述。

    Raises:
        ContractError: 来源不属于预期输出、非 JSON 或路径无法读取。
    """
    if metrics_from is None:
        if metric_paths:
            raise ContractError("--metric-path 必须与 --metrics-from 一起使用")
        return {}, {}
    source = resolve_inside(run_dir, metrics_from, must_exist=True)
    relative_source = relative_inside(run_dir, source).as_posix()
    normalized_outputs = {
        relative_inside(run_dir, resolve_inside(run_dir, item)).as_posix()
        for item in expected_outputs
    }
    if relative_source not in normalized_outputs:
        raise ContractError("指标来源必须同时通过 --expect 声明")
    if source.suffix.lower() != ".json":
        raise ContractError("--metrics-from 必须指向 JSON 输出")
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"指标来源 JSON 不可读取: {relative_source}") from exc
    if metric_paths:
        metrics = {
            name: json_path_value(document, json_path)
            for name, json_path in metric_paths.items()
        }
        paths = metric_paths
    else:
        raw_metrics = json_path_value(document, "metrics")
        if not isinstance(raw_metrics, dict) or not raw_metrics:
            raise ContractError("指标来源 JSON 必须包含非空 metrics 对象")
        metrics = raw_metrics
        paths = {name: f"metrics.{name}" for name in metrics}
    return (
        metrics,
        {
            name: {"file": relative_source, "json_path": json_path}
            for name, json_path in paths.items()
        },
    )


def execute_simple_experiment(
    run_dir: Path,
    *,
    result_id: str,
    question_id: str,
    kind: str,
    command: str,
    expected_outputs: list[str],
    input_files: list[str] | None = None,
    metrics_from: str | None = None,
    metric_paths: dict[str, str] | None = None,
    timeout_seconds: float | None = None,
    require_fresh_outputs: bool = False,
    provisional: bool = False,
) -> dict[str, Any]:
    """实际运行一次 v3 实验并将事实写入 ``results/index.json``。

    Args:
        run_dir: v3 运行目录。
        result_id: 新结果 ID。
        question_id: 对应问题 ID。
        kind: 结果类型。
        command: 不含 Shell 语义的命令。
        expected_outputs: 运行后必须出现的输出路径。
        input_files: 显式输入文件路径。
        metrics_from: 指标 JSON 输出路径；必须属于 ``expected_outputs``。
        metric_paths: 可选的指标名到 JSON 点路径映射。
        timeout_seconds: 可选超时秒数。
        require_fresh_outputs: 为真时拒绝命令启动前已存在的预期输出。
        provisional: 为真时只登记诊断执行，等待上层质量协议提升。

    Returns:
        包含成功状态、结果条目和错误信息的执行摘要。

    Raises:
        ContractError: 运行目录、命令或路径不满足协议。
    """
    identifier = safe_result_id(result_id)
    root = run_dir.resolve()
    state = read_simple_state(root)
    arguments = _parse_command(command)
    if not expected_outputs:
        raise ContractError("至少提供一个 --expect 输出文件")
    configured_metric_paths = metric_paths or {}
    if configured_metric_paths and metrics_from is None:
        raise ContractError("--metric-path 必须与 --metrics-from 一起使用")
    normalized_outputs = [resolve_inside(root, item).relative_to(root).as_posix() for item in expected_outputs]
    if require_fresh_outputs:
        existing = [item for item in normalized_outputs if (root / item).exists()]
        if existing:
            raise ContractError(f"要求新鲜输出，但预期文件已存在: {', '.join(existing)}")
    # 生产模式默认要求输出文件被实际更新（不信任旧文件存在+退出码0）
    output_snapshot = _output_snapshot(root, normalized_outputs)
    enforce_fresh = (
        require_fresh_outputs
        or str(state.get("execution_mode")) == "production"
    )
    explicit_inputs = input_files or []
    source_script = _source_script(root, arguments)
    source_inputs = python_source_closure(root, source_script) if source_script else []
    all_inputs = list(dict.fromkeys([*explicit_inputs, *source_inputs]))
    for item in all_inputs:
        resolve_inside(root, item, must_exist=True)

    raw_dir = root / "results" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = (raw_dir / f"{identifier}.stdout.log").relative_to(root).as_posix()
    stderr_path = (raw_dir / f"{identifier}.stderr.log").relative_to(root).as_posix()
    started_at = utc_now()
    started = time.monotonic()
    exit_code = 1
    error: str | None = None
    stdout = ""
    stderr = ""
    try:
        completed = subprocess.run(
            arguments,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            shell=False,
            check=False,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
        if exit_code != 0:
            error = f"命令退出码为 {exit_code}"
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        error = f"命令执行超时: {timeout_seconds} 秒"
    except OSError as exc:
        error = f"命令无法执行: {exc}"
    finished_at = utc_now()
    duration_seconds = time.monotonic() - started
    (root / stdout_path).write_text(stdout, encoding="utf-8", newline="\n")
    (root / stderr_path).write_text(stderr, encoding="utf-8", newline="\n")

    missing = [path for path in normalized_outputs if not (root / path).is_file()]
    if missing and error is None:
        error = f"缺少预期输出: {', '.join(missing)}"
        exit_code = exit_code or 1
    # 生产模式下验证输出新鲜度
    if enforce_fresh and error is None:
        stale = _verify_output_freshness(root, normalized_outputs, output_snapshot)
        if stale:
            error = f"生产模式要求输出被实际更新，但以下文件未变化: {', '.join(stale)}"
            exit_code = exit_code or 1
    metrics: dict[str, Any] = {}
    metric_sources: dict[str, dict[str, str]] = {}
    if error is None:
        try:
            metrics, metric_sources = _extract_output_metrics(
                root,
                metrics_from=metrics_from,
                metric_paths=configured_metric_paths,
                expected_outputs=normalized_outputs,
            )
        except ContractError as exc:
            error = str(exc)
            exit_code = exit_code or 1
            metrics = {}
            metric_sources = {}
    try:
        result = register_result(
            root,
            result_id=identifier,
            question_id=question_id,
            kind=kind,
            command=command,
            source_script=source_script,
            input_files=all_inputs,
            output_files=normalized_outputs,
            metrics=metrics,
            metric_sources=metric_sources,
            exit_code=exit_code,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration_seconds,
            execution_mode=str(state["execution_mode"]),
            provisional=provisional,
            error=error,
        )
    except ContractError as exc:
        error = error or str(exc)
        result = None
    return {
        "success": result is not None and bool(result["execution_valid"]),
        "result": result,
        "error": error,
        "exit_code": exit_code,
    }
