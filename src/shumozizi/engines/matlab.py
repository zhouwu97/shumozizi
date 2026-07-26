"""MATLAB / Octave 独立执行引擎，用于红队独立复算和几何验证。

与 review.py 的 run_red_team_evidence 不同，本模块只负责"运行一个 .m 文件并返回
结构化结果"，不绑定审查包协议；适合在实验阶段按需触发独立 oracle。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.simple.state import utc_now

# 支持的引擎名称
_VALID_ENGINES = frozenset({"matlab", "octave"})

# MATLAB/Octave 版本探测正则
_MATLAB_VERSION = re.compile(r"MATLAB[^\d]*(\d[\d.]+)", re.IGNORECASE)
_OCTAVE_VERSION = re.compile(r"GNU Octave[^\d]*(\d[\d.]+)", re.IGNORECASE)


def detect_engine(engine: str) -> dict[str, Any]:
    """检测本机是否有可用的 MATLAB 或 Octave，并返回版本信息。

    Args:
        engine: ``"matlab"`` 或 ``"octave"``。

    Returns:
        包含 ``available``、``command``、``version``、``detected_at`` 的字典。
    """
    if engine not in _VALID_ENGINES:
        raise ContractError(f"不支持的引擎: {engine}，只接受 matlab 或 octave")

    command = shutil.which(engine)
    if command is None:
        return {
            "available": False,
            "engine": engine,
            "command": None,
            "version": None,
            "detected_at": utc_now(),
        }

    # 探测版本号
    version: str | None = None
    try:
        if engine == "matlab":
            result = subprocess.run(
                [command, "-batch", "disp(version)"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
            match = _MATLAB_VERSION.search(result.stdout + result.stderr)
            version = match.group(1) if match else result.stdout.strip()[:64] or None
        else:
            result = subprocess.run(
                [command, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
            )
            match = _OCTAVE_VERSION.search(result.stdout + result.stderr)
            version = match.group(1) if match else None
    except (subprocess.TimeoutExpired, OSError):
        pass

    return {
        "available": True,
        "engine": engine,
        "command": command,
        "version": version or "unknown",
        "detected_at": utc_now(),
    }


def run_matlab_script(
    script_path: Path,
    run_dir: Path,
    *,
    engine: str = "matlab",
    expected_outputs: list[str] | None = None,
    timeout_seconds: int = 300,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """在清洁环境执行一个 .m 脚本并返回结构化执行结果。

    脚本以 ``-batch "run('<script>')"``（MATLAB）或
    ``--eval "run('<script>')"``（Octave）的方式调用，不启动 GUI。
    当前工作目录设为脚本所在目录，脚本可通过相对路径读写同目录文件。

    Args:
        script_path: .m 脚本的绝对路径。
        run_dir: 当前运行目录，用于计算相对路径记录。
        engine: ``"matlab"`` 或 ``"octave"``。
        expected_outputs: 脚本应产出的文件名（相对 script_path 目录），
            执行后校验它们存在且非空。为 ``None`` 时不校验。
        timeout_seconds: 最长运行秒数，超时返回 exit_code=124。
        extra_env: 额外注入的环境变量，如 ``SHUMOZIZI_RUN_DIR``。

    Returns:
        包含 exit_code、stdout、stderr、timed_out、outputs、engine_info 的字典。

    Raises:
        ContractError: 脚本不存在、引擎不可用或脚本名含危险字符。
    """
    if not script_path.is_file():
        raise ContractError(f"MATLAB 脚本不存在: {script_path}")
    if script_path.suffix.casefold() != ".m":
        raise ContractError("MATLAB 脚本必须是 .m 文件")
    if "'" in script_path.name:
        raise ContractError("MATLAB/Octave 脚本名不允许单引号")
    if engine not in _VALID_ENGINES:
        raise ContractError(f"不支持的引擎: {engine}")

    probe = detect_engine(engine)
    if not probe["available"]:
        raise ContractError(
            f"当前环境未找到可执行的引擎 {engine}，"
            "请安装后重试或改用 octave/Python 替代实现"
        )

    command_path: str = probe["command"]  # type: ignore[assignment]
    script_dir = script_path.parent
    expression = f"run('{script_path.name}')"

    if engine == "matlab":
        command = [command_path, "-batch", expression]
    else:
        command = [command_path, "--quiet", "--no-gui", "--eval", expression]

    env = dict(os.environ)
    env["SHUMOZIZI_RUN_DIR"] = str(run_dir.resolve())
    if extra_env:
        env.update(extra_env)

    stdout = ""
    stderr = ""
    exit_code = -1
    timed_out = False

    started_at = utc_now()
    try:
        completed = subprocess.run(
            command,
            cwd=script_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            env=env,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        timed_out = True
        stdout = (
            exc.stdout.decode("utf-8", errors="replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        stderr = (
            exc.stderr.decode("utf-8", errors="replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        ) + f"\n[MATLAB runner] 超时（{timeout_seconds}s），已终止\n"
    except OSError as exc:
        raise ContractError(f"无法启动引擎 {engine}: {exc}") from exc

    finished_at = utc_now()

    # 校验期望输出文件
    output_results: list[dict[str, Any]] = []
    if expected_outputs is not None:
        for name in expected_outputs:
            candidate = script_dir / name
            if candidate.is_file() and candidate.stat().st_size > 0:
                output_results.append(
                    {"name": name, "exists": True, "size_bytes": candidate.stat().st_size}
                )
            else:
                output_results.append({"name": name, "exists": False, "size_bytes": 0})

    return {
        "engine": engine,
        "engine_version": probe["version"],
        "command": command,
        "script": str(script_path),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "success": exit_code == 0 and not timed_out,
        "stdout": stdout,
        "stderr": stderr,
        "started_at": started_at,
        "finished_at": finished_at,
        "outputs": output_results,
    }


def register_matlab_result(
    run_dir: Path,
    result: dict[str, Any],
    *,
    question_id: str,
    result_type: str,
    output_json_path: Path | None = None,
) -> dict[str, Any]:
    """将 MATLAB 独立执行结果登记到运行目录的证据索引。

    证据写入 ``results/evidence/<question_id>-matlab-<result_type>.json``，
    并追加到 ``results/evidence/index.json``（若存在）。

    Args:
        run_dir: 当前运行目录。
        result: ``run_matlab_script`` 的返回值。
        question_id: 对应的题目 ID（如 ``"Q3"``）。
        result_type: 证据类型标签（如 ``"interval_union"``、``"feasibility"``）。
        output_json_path: 脚本产出的 JSON 输出路径，将内联到证据记录。

    Returns:
        写入的证据记录。

    Raises:
        ContractError: 执行未成功或必要字段缺失。
    """
    if not result.get("success"):
        raise ContractError(
            f"MATLAB 执行未成功（exit_code={result.get('exit_code')}），"
            "不能登记证据；请先修复脚本错误"
        )
    if not question_id.strip():
        raise ContractError("登记 MATLAB 证据必须提供 question_id")

    output_data: dict[str, Any] | None = None
    if output_json_path is not None:
        if not output_json_path.is_file():
            raise ContractError(f"MATLAB 输出文件不存在: {output_json_path}")
        try:
            output_data = load_json(output_json_path)
        except (OSError, ValueError) as exc:
            raise ContractError(f"MATLAB 输出 JSON 无法解析: {exc}") from exc

    evidence_dir = run_dir / "results" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_dir / f"{question_id}-matlab-{result_type}.json"

    record: dict[str, Any] = {
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "question_id": question_id,
        "result_type": result_type,
        "engine": result["engine"],
        "engine_version": result.get("engine_version"),
        "script": result["script"],
        "exit_code": result["exit_code"],
        "started_at": result["started_at"],
        "finished_at": result["finished_at"],
        "registered_at": utc_now(),
    }
    if output_data is not None:
        record["output"] = output_data

    atomic_json(evidence_path, record)
    return record


def check_environment() -> dict[str, Any]:
    """报告当前环境中所有支持引擎的可用性。

    Returns:
        包含 ``matlab`` 和 ``octave`` 探测结果的字典。
    """
    return {
        "matlab": detect_engine("matlab"),
        "octave": detect_engine("octave"),
        "checked_at": utc_now(),
    }
