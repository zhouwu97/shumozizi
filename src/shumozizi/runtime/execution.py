"""统一执行实验并复验输入、输出和执行记录哈希。"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path, PurePath
from typing import Any

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    load_json,
    resolve_inside,
    sha256_file,
)
from shumozizi.core.schema import require_valid

RUNNER_VERSION = "2.0.0"
TIMEOUT_EXIT_CODE = 124
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
RuntimeContractError = ContractError


def utc_now() -> str:
    """返回 RFC 3339 UTC 时间。"""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def relative_run_path(run_dir: Path, path: Path) -> str:
    """返回运行目录内的 POSIX 相对路径。"""
    return path.resolve().relative_to(run_dir.resolve()).as_posix()


def execution_record_path(run_dir: Path, execution_id: str) -> Path:
    """返回不可变执行记录固定路径。"""
    if not SAFE_ID.fullmatch(execution_id):
        raise ContractError(f"execution_id 不合法: {execution_id}")
    return run_dir.resolve() / "executions" / execution_id / "execution_record.json"


def file_evidence(run_dir: Path, relative_path: str) -> dict[str, Any]:
    """生成运行内文件的内容证据。"""
    path = resolve_inside(run_dir, relative_path, must_exist=True)
    return {
        "path": relative_run_path(run_dir, path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _validate_python_args(run_dir: Path, cwd: Path, manifest: dict[str, Any]) -> None:
    """限制入口为已声明且位于 ``code/`` 下的 Python 文件。"""
    script_arg = manifest["args"][0]
    if script_arg in {"-c", "-m", "-"} or script_arg.startswith("-"):
        raise ContractError("Python 入口必须是运行目录内的 .py 脚本")
    script_input = Path(script_arg)
    if script_input.is_absolute() or ".." in PurePath(script_arg).parts:
        raise ContractError(f"Python 脚本路径不安全: {script_arg}")
    script_path = (cwd / script_input).resolve()
    run_root = run_dir.resolve()
    code_root = (run_root / "code").resolve()
    if (
        code_root not in script_path.parents
        or script_path.suffix.lower() != ".py"
        or not script_path.is_file()
    ):
        raise ContractError("Python 入口必须是 runs/<run_id>/code/ 内存在的 .py 文件")
    declared = {
        resolve_inside(run_root, value, must_exist=True) for value in manifest["input_files"]
    }
    if script_path not in declared:
        raise ContractError("Python 入口脚本必须列入 input_files")
    for argument in manifest["args"][1:]:
        if "\x00" in argument:
            raise ContractError("参数不得包含 NUL 字符")
        if Path(argument).is_absolute() or ".." in PurePath(argument).parts:
            raise ContractError(f"参数包含越界路径: {argument}")


def execute(run_dir: Path, manifest_path: Path) -> dict[str, Any]:
    """按 Schema v2 清单执行一次实验并生成不可变记录。"""
    run_root = run_dir.resolve()
    if not run_root.is_dir():
        raise ContractError(f"运行目录不存在: {run_root}")
    manifest_source = manifest_path.resolve()
    if run_root not in manifest_source.parents:
        raise ContractError("执行清单必须位于运行目录内")
    manifest = load_json(manifest_source)
    require_valid(manifest, "execution_manifest")
    execution_id = manifest["execution_id"]
    execution_dir = run_root / "executions" / execution_id
    if execution_dir.exists():
        raise ContractError(f"execution_id 已存在，拒绝覆盖: {execution_id}")
    cwd = resolve_inside(run_root, manifest["cwd"])
    if not cwd.is_dir():
        raise ContractError(f"cwd 目录不存在: {manifest['cwd']}")
    for value in manifest["input_files"]:
        resolve_inside(run_root, value, must_exist=True)
    for value in manifest["expected_outputs"]:
        output = resolve_inside(run_root, value)
        if output == run_root:
            raise ContractError("expected_output 不能指向运行目录本身")
        if output.exists():
            raise ContractError(f"expected_output 已存在，拒绝把旧文件登记为本次证据: {value}")
    _validate_python_args(run_root, cwd, manifest)
    execution_dir.mkdir(parents=True)
    immutable_manifest = execution_dir / "execution_manifest.json"
    atomic_json(immutable_manifest, manifest)
    stdout_path, stderr_path = execution_dir / "stdout.log", execution_dir / "stderr.log"
    input_evidence = [file_evidence(run_root, value) for value in manifest["input_files"]]
    environment = os.environ.copy()
    if manifest["random_seed"] is not None:
        environment["PYTHONHASHSEED"] = str(manifest["random_seed"])
    started_at, started_clock = utc_now(), time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            [sys.executable, *manifest["args"]],
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
        exit_code, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out, exit_code = True, TIMEOUT_EXIT_CODE
        stdout = (
            exc.stdout.decode("utf-8", errors="replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        stderr = (
            exc.stderr.decode("utf-8", errors="replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        )
        stderr += f"\n实验超过 {manifest['timeout_seconds']} 秒，已终止。\n"
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    output_evidence = [
        file_evidence(run_root, value)
        for value in manifest["expected_outputs"]
        if resolve_inside(run_root, value).is_file()
    ]
    record = {
        "schema_name": "execution_record",
        "schema_version": "2.0",
        "execution_id": execution_id,
        "manifest_path": relative_run_path(run_root, immutable_manifest),
        "manifest_sha256": sha256_file(immutable_manifest),
        "started_at": started_at,
        "finished_at": utc_now(),
        "duration_seconds": round(time.monotonic() - started_clock, 6),
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
    require_valid(record, "execution_record")
    record_path = execution_dir / "execution_record.json"
    atomic_json(record_path, record)
    expected = {
        relative_run_path(run_root, resolve_inside(run_root, value))
        for value in manifest["expected_outputs"]
    }
    missing = sorted(expected - {item["path"] for item in output_evidence})
    return {
        "success": exit_code == 0 and not timed_out and not missing,
        "execution_id": execution_id,
        "record_path": str(record_path),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "missing_outputs": missing,
    }


def verify_execution_record(run_dir: Path, execution_id: str) -> dict[str, Any]:
    """从当前文件重新计算哈希，复验执行记录全链路。"""
    errors: list[str] = []
    try:
        record_path = execution_record_path(run_dir, execution_id)
        record = load_json(record_path)
        require_valid(record, "execution_record")
        if record["execution_id"] != execution_id:
            errors.append("execution_record.execution_id 与目录不一致")
        if record["exit_code"] != 0 or record["timed_out"]:
            errors.append("执行未成功完成")
        manifest_path = resolve_inside(run_dir, record["manifest_path"], must_exist=True)
        if sha256_file(manifest_path) != record["manifest_sha256"]:
            errors.append("执行清单哈希与记录不一致")
        manifest = load_json(manifest_path)
        require_valid(manifest, "execution_manifest")
        for field in (
            "execution_id",
            "program",
            "args",
            "cwd",
            "timeout_seconds",
            "random_seed",
            "expected_outputs",
        ):
            if record[field] != manifest[field]:
                errors.append(f"执行记录字段与清单不一致: {field}")
        for collection in ("input_files", "output_files"):
            for item in record[collection]:
                path = resolve_inside(run_dir, item["path"], must_exist=True)
                if sha256_file(path) != item["sha256"]:
                    errors.append(f"{collection} 哈希不一致: {item['path']}")
                if path.stat().st_size != item["size_bytes"]:
                    errors.append(f"{collection} 大小不一致: {item['path']}")
        recorded_outputs = {item["path"] for item in record["output_files"]}
        for value in record["expected_outputs"]:
            normalized = relative_run_path(run_dir, resolve_inside(run_dir, value, must_exist=True))
            if normalized not in recorded_outputs:
                errors.append(f"预期输出缺少执行证据: {value}")
        for field in ("stdout_path", "stderr_path"):
            resolve_inside(run_dir, record[field], must_exist=True)
    except (ContractError, KeyError, OSError) as exc:
        errors.append(str(exc))
        record_path = execution_record_path(run_dir, execution_id)
    return {
        "valid": not errors,
        "execution_id": execution_id,
        "record_path": str(record_path),
        "record_sha256": sha256_file(record_path) if record_path.is_file() else None,
        "errors": errors,
    }
