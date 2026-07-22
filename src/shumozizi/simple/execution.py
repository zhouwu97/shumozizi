"""执行 v3 实验并记录可复验的事实证据。"""

from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, relative_inside, resolve_inside
from shumozizi.simple.results import register_result
from shumozizi.simple.state import read_simple_state, utc_now


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


def execute_simple_experiment(
    run_dir: Path,
    *,
    result_id: str,
    question_id: str,
    kind: str,
    command: str,
    expected_outputs: list[str],
    input_files: list[str] | None = None,
    metrics: dict[str, Any] | None = None,
    timeout_seconds: float | None = None,
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
        metrics: 调用方提供的结果指标。
        timeout_seconds: 可选超时秒数。

    Returns:
        包含成功状态、结果条目和错误信息的执行摘要。

    Raises:
        ContractError: 运行目录、命令或路径不满足协议。
    """
    root = run_dir.resolve()
    read_simple_state(root)
    arguments = _parse_command(command)
    if not expected_outputs:
        raise ContractError("至少提供一个 --expect 输出文件")
    normalized_outputs = [resolve_inside(root, item).relative_to(root).as_posix() for item in expected_outputs]
    explicit_inputs = input_files or []
    source_script = _source_script(root, arguments)
    all_inputs = list(dict.fromkeys([*explicit_inputs, *([source_script] if source_script else [])]))
    for item in all_inputs:
        resolve_inside(root, item, must_exist=True)

    raw_dir = root / "results" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = (raw_dir / f"{result_id}.stdout.log").relative_to(root).as_posix()
    stderr_path = (raw_dir / f"{result_id}.stderr.log").relative_to(root).as_posix()
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
    try:
        result = register_result(
            root,
            result_id=result_id,
            question_id=question_id,
            kind=kind,
            command=command,
            source_script=source_script,
            input_files=all_inputs,
            output_files=normalized_outputs,
            metrics=metrics or {},
            exit_code=exit_code,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration_seconds,
            error=error,
        )
    except ContractError as exc:
        error = error or str(exc)
        result = None
    return {
        "success": result is not None and result["status"] == "current",
        "result": result,
        "error": error,
        "exit_code": exit_code,
    }
