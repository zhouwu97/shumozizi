"""按照结构化清单安全执行 Python 实验并生成不可变证据记录。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path, PurePath
from typing import Any

try:
    from .verify_execution import (
        RUNNER_VERSION,
        RuntimeContractError,
        atomic_json,
        file_evidence,
        load_json_object,
        relative_run_path,
        resolve_run_path,
        sha256_file,
        validate_document,
    )
except ImportError:
    from verify_execution import (  # type: ignore[no-redef]
        RUNNER_VERSION,
        RuntimeContractError,
        atomic_json,
        file_evidence,
        load_json_object,
        relative_run_path,
        resolve_run_path,
        sha256_file,
        validate_document,
    )


TIMEOUT_EXIT_CODE = 124


def utc_now() -> str:
    """返回带时区的 UTC 时间。"""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_python_args(run_dir: Path, cwd: Path, manifest: dict[str, Any]) -> None:
    """限制 Python 入口为运行目录内声明过的脚本。"""
    arguments = manifest["args"]
    script_argument = arguments[0]
    if script_argument in {"-c", "-m", "-"} or script_argument.startswith("-"):
        raise RuntimeContractError("Python 入口必须是运行目录内的 .py 脚本")
    script_input = Path(script_argument)
    if script_input.is_absolute() or ".." in PurePath(script_argument).parts:
        raise RuntimeContractError(f"Python 脚本路径不安全: {script_argument}")
    script_path = (cwd / script_input).resolve()
    run_root = run_dir.resolve()
    if run_root not in script_path.parents or script_path.suffix.lower() != ".py":
        raise RuntimeContractError("Python 入口必须是运行目录内的 .py 文件")
    if not script_path.is_file():
        raise RuntimeContractError(f"Python 脚本不存在: {script_argument}")
    declared_inputs = {
        resolve_run_path(run_root, item, purpose="input_file", must_exist=True)
        for item in manifest["input_files"]
    }
    if script_path not in declared_inputs:
        raise RuntimeContractError("Python 入口脚本必须列入 input_files")

    for argument in arguments[1:]:
        if "\x00" in argument:
            raise RuntimeContractError("参数不得包含 NUL 字符")
        if Path(argument).is_absolute() or ".." in PurePath(argument).parts:
            raise RuntimeContractError(f"参数包含越界路径: {argument}")


def decode_timeout_stream(value: str | bytes | None) -> str:
    """统一处理 TimeoutExpired 中的文本或字节输出。"""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def execute(run_dir: Path, manifest_path: Path) -> dict[str, Any]:
    """执行一次清单并返回记录摘要。"""
    run_root = run_dir.resolve()
    if not run_root.is_dir():
        raise RuntimeContractError(f"运行目录不存在: {run_root}")
    manifest_source = manifest_path.resolve()
    if run_root not in manifest_source.parents:
        raise RuntimeContractError("执行清单必须位于运行目录内")
    manifest = load_json_object(manifest_source)
    schema_errors = validate_document(manifest, "execution_manifest.schema.json")
    if schema_errors:
        raise RuntimeContractError("; ".join(schema_errors))

    execution_id = manifest["execution_id"]
    execution_dir = run_root / "executions" / execution_id
    if execution_dir.exists():
        raise RuntimeContractError(f"execution_id 已存在，拒绝覆盖: {execution_id}")

    cwd = resolve_run_path(run_root, manifest["cwd"], purpose="cwd")
    if not cwd.is_dir():
        raise RuntimeContractError(f"cwd 目录不存在: {manifest['cwd']}")
    for relative_path in manifest["input_files"]:
        resolve_run_path(run_root, relative_path, purpose="input_file", must_exist=True)
    for relative_path in manifest["expected_outputs"]:
        output_path = resolve_run_path(run_root, relative_path, purpose="expected_output")
        if output_path == run_root:
            raise RuntimeContractError("expected_output 不能指向运行目录本身")
        if output_path.exists():
            raise RuntimeContractError(
                f"expected_output 已存在，拒绝把旧文件登记为本次证据: {relative_path}"
            )
    validate_python_args(run_root, cwd, manifest)

    execution_dir.mkdir(parents=True)
    immutable_manifest = execution_dir / "execution_manifest.json"
    atomic_json(immutable_manifest, manifest)
    stdout_path = execution_dir / "stdout.log"
    stderr_path = execution_dir / "stderr.log"
    record_path = execution_dir / "execution_record.json"
    input_evidence = [
        file_evidence(run_root, item, "input_file") for item in manifest["input_files"]
    ]

    environment = os.environ.copy()
    if manifest["random_seed"] is not None:
        environment["PYTHONHASHSEED"] = str(manifest["random_seed"])

    command = [sys.executable, *manifest["args"]]
    started_at = utc_now()
    started_clock = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=manifest["timeout_seconds"],
            env=environment,
            check=False,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = TIMEOUT_EXIT_CODE
        stdout = decode_timeout_stream(exc.stdout)
        stderr = decode_timeout_stream(exc.stderr)
        if stderr and not stderr.endswith("\n"):
            stderr += "\n"
        stderr += f"实验超过 {manifest['timeout_seconds']} 秒，已终止。\n"

    finished_at = utc_now()
    duration_seconds = round(time.monotonic() - started_clock, 6)
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")

    output_evidence: list[dict[str, Any]] = []
    for relative_path in manifest["expected_outputs"]:
        output_path = resolve_run_path(run_root, relative_path, purpose="expected_output")
        if output_path.is_file():
            output_evidence.append(file_evidence(run_root, relative_path, "expected_output"))

    record = {
        "schema_version": "1.0",
        "execution_id": execution_id,
        "manifest_path": relative_run_path(run_root, immutable_manifest),
        "manifest_sha256": sha256_file(immutable_manifest),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": duration_seconds,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "program": manifest["program"],
        "executable": sys.executable,
        "args": manifest["args"],
        "cwd": manifest["cwd"],
        "timeout_seconds": manifest["timeout_seconds"],
        "random_seed": manifest["random_seed"],
        "stdout_path": relative_run_path(run_root, stdout_path),
        "stderr_path": relative_run_path(run_root, stderr_path),
        "input_files": input_evidence,
        "expected_outputs": manifest["expected_outputs"],
        "output_files": output_evidence,
        "runner_version": RUNNER_VERSION,
    }
    atomic_json(record_path, record)
    normalized_expected_outputs = {
        relative_run_path(
            run_root,
            resolve_run_path(run_root, item, purpose="expected_output"),
        )
        for item in manifest["expected_outputs"]
    }
    missing_outputs = sorted(
        normalized_expected_outputs - {item["path"] for item in output_evidence}
    )
    return {
        "success": exit_code == 0 and not timed_out and not missing_outputs,
        "execution_id": execution_id,
        "record_path": str(record_path),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "missing_outputs": missing_outputs,
    }


def parse_args() -> argparse.Namespace:
    """解析执行命令行参数。"""
    parser = argparse.ArgumentParser(description="执行结构化数学建模实验")
    parser.add_argument("run_dir", help="runs/<run_id> 目录")
    parser.add_argument("manifest", help="运行目录内的执行清单 JSON")
    return parser.parse_args()


def main() -> int:
    """运行实验并输出机器可读摘要。"""
    args = parse_args()
    try:
        payload = execute(Path(args.run_dir), Path(args.manifest))
    except (RuntimeContractError, OSError) as exc:
        payload = {"success": False, "errors": [str(exc)]}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
