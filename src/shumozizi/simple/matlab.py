"""执行并登记 Competition-First MATLAB 建模、优化与科学绘图。"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, relative_inside, resolve_inside
from shumozizi.core.schema import require_valid
from shumozizi.engines.matlab import detect_engine
from shumozizi.simple.results import json_path_value, register_result
from shumozizi.simple.state import utc_now

_ROLES = frozenset(
    {"primary_model", "optimizer_challenger", "independent_oracle", "scientific_visualization"}
)
_REQUIRED_SUFFIXES = frozenset({".json", ".csv", ".pdf", ".png"})


def _relative_file(run_dir: Path, value: str, *, must_exist: bool) -> str:
    """把用户路径限制在当前运行目录并转成 POSIX 相对路径。"""
    path = resolve_inside(run_dir, value, must_exist=must_exist)
    return relative_inside(run_dir, path).as_posix()


def _read_metrics(
    run_dir: Path, metric_sources: dict[str, dict[str, str]]
) -> dict[str, Any]:
    """从 MATLAB 新生成的 JSON 中提取结果指标。"""
    metrics: dict[str, Any] = {}
    for name, source in metric_sources.items():
        path = resolve_inside(run_dir, source.get("file", ""), must_exist=True)
        if path.suffix.casefold() != ".json":
            raise ContractError(f"MATLAB 指标 {name} 必须来自 JSON 输出")
        metrics[name] = json_path_value(load_json(path), source.get("json_path", ""))
    return metrics


def _toolbox_inventory(command: str, *, timeout_seconds: int) -> list[str]:
    """从 MATLAB 自报信息读取工具箱名称；探测失败时明确返回空列表。"""
    expression = "v=ver; for k=1:numel(v), disp(v(k).Name); end"
    try:
        completed = subprocess.run(
            [command, "-batch", expression],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=min(timeout_seconds, 90),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    ignored_prefixes = ("matlab is selecting", "to get started", "for product information")
    names = {
        line.strip()
        for line in completed.stdout.splitlines()
        if line.strip() and not line.strip().casefold().startswith(ignored_prefixes)
    }
    return sorted(names)


def run_matlab_analysis(
    run_dir: Path,
    *,
    entrypoint: str,
    question_id: str,
    result_id: str,
    role: str,
    input_files: list[str],
    output_files: list[str],
    metric_sources: dict[str, dict[str, str]],
    objective_semantics_sha256: str,
    engine: str = "matlab",
    timeout_seconds: int = 600,
    execution_mode: str = "production",
) -> dict[str, Any]:
    """运行 MATLAB/Octave 入口，写 manifest 并登记真实结果。

    入口只通过 ``SHUMOZIZI_RUN_DIR`` 获得运行根目录。调用方必须声明 JSON、
    CSV、PDF 和 PNG 四类输出，使数值结果、结构数据和论文图在同一次执行中
    产生。manifest 只证明命令与文件闭环，不证明模型正确或独立性成立。

    Args:
        run_dir: 当前 Competition-First 运行目录。
        entrypoint: ``code/matlab/`` 下的真实 ``.m`` 入口。
        question_id: 对应必答问题。
        result_id: 写入结果索引的稳定 ID。
        role: MATLAB 承担的科学角色。
        input_files: 原始题面附件、受控参数或当前结果，不含入口自身。
        output_files: MATLAB 必须新鲜生成的 JSON、CSV、PDF、PNG 文件。
        metric_sources: 指标到 JSON 文件及点路径的映射。
        objective_semantics_sha256: 当前目标语义哈希。
        engine: ``matlab`` 或 ``octave``。
        timeout_seconds: 单次执行超时。
        execution_mode: ``production`` 或 ``exploration``。

    Returns:
        已写入 ``results/matlab/manifest.json`` 的执行 manifest。

    Raises:
        ContractError: 路径越界、产物合同不完整或参数不合法。
    """
    root = run_dir.resolve()
    if role not in _ROLES:
        raise ContractError("MATLAB role 必须是 " + ", ".join(sorted(_ROLES)))
    if engine not in {"matlab", "octave"}:
        raise ContractError("MATLAB runner 仅支持 matlab 或 octave")
    if timeout_seconds < 1 or timeout_seconds > 3600:
        raise ContractError("MATLAB timeout_seconds 必须在 1 至 3600 之间")

    script = _relative_file(root, entrypoint, must_exist=True)
    if not script.startswith("code/matlab/") or not script.casefold().endswith(".m"):
        raise ContractError("MATLAB 入口必须位于 code/matlab/ 且使用 .m 后缀")
    if "'" in script:
        raise ContractError("MATLAB 入口路径不能包含单引号")
    normalized_inputs = [_relative_file(root, item, must_exist=True) for item in input_files]
    normalized_inputs = list(dict.fromkeys([script, *normalized_inputs]))
    normalized_outputs = [_relative_file(root, item, must_exist=False) for item in output_files]
    suffixes = {Path(item).suffix.casefold() for item in normalized_outputs}
    if not _REQUIRED_SUFFIXES <= suffixes:
        missing = ", ".join(sorted(_REQUIRED_SUFFIXES - suffixes))
        raise ContractError(f"MATLAB 运行必须声明 JSON、CSV、PDF、PNG 输出，缺少: {missing}")
    if len(normalized_outputs) != len(set(normalized_outputs)):
        raise ContractError("MATLAB output_files 不允许重复")
    output_set = set(normalized_outputs)
    for source in metric_sources.values():
        normalized = _relative_file(root, source.get("file", ""), must_exist=False)
        if normalized not in output_set:
            raise ContractError("MATLAB 指标来源必须属于本次声明输出")

    logs_dir = root / "logs"
    result_dir = root / "results" / "matlab"
    logs_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    stdout_relative = f"logs/{result_id}.stdout.log"
    stderr_relative = f"logs/{result_id}.stderr.log"
    manifest_relative = "results/matlab/manifest.json"
    before = {
        item: (root / item).stat().st_mtime_ns
        for item in normalized_outputs
        if (root / item).is_file()
    }

    probe = detect_engine(engine)
    available = probe.get("available") is True and isinstance(probe.get("command"), str)
    command: list[str] = []
    stdout = ""
    stderr = ""
    exit_status = 127
    unavailable_reason: str | None = None
    started_at = utc_now()
    started_clock = time.perf_counter()
    if available:
        executable = str(probe["command"])
        expression = f"run('{script}')"
        command = (
            [executable, "-batch", expression]
            if engine == "matlab"
            else [executable, "--quiet", "--no-gui", "--eval", expression]
        )
        environment = dict(os.environ)
        environment["SHUMOZIZI_RUN_DIR"] = str(root)
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
            exit_status = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            exit_status = 124
            stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            stderr += f"\nMATLAB 运行超过 {timeout_seconds} 秒，已终止。\n"
        except OSError as exc:
            exit_status = 126
            stderr = f"无法启动 {engine}: {exc}\n"
    else:
        unavailable_reason = f"当前环境未找到通过探测的 {engine} 可执行文件"
        stderr = unavailable_reason + "\n"

    finished_at = utc_now()
    elapsed_seconds = round(time.perf_counter() - started_clock, 6)
    (root / stdout_relative).write_text(stdout, encoding="utf-8", newline="\n")
    (root / stderr_relative).write_text(stderr, encoding="utf-8", newline="\n")
    with (logs_dir / "matlab-run.log").open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(f"[{started_at}] result_id={result_id} role={role} exit_status={exit_status}\n")
        if stdout:
            stream.write(stdout.rstrip() + "\n")
        if stderr:
            stream.write(stderr.rstrip() + "\n")

    outputs_fresh = all(
        (root / item).is_file()
        and (root / item).stat().st_size > 0
        and ((item not in before) or (root / item).stat().st_mtime_ns != before[item])
        for item in normalized_outputs
    )
    execution_valid = available and exit_status == 0 and outputs_fresh
    toolboxes = (
        _toolbox_inventory(str(probe["command"]), timeout_seconds=timeout_seconds)
        if available and engine == "matlab"
        else []
    )
    manifest: dict[str, Any] = {
        "schema_name": "matlab_run_manifest",
        "schema_version": "2.0",
        "run_id": root.name,
        "result_id": result_id,
        "question_id": question_id,
        "role": role,
        "engine": engine,
        "availability": "available" if available else "unavailable",
        "entrypoint": script,
        "matlab_version": probe.get("version"),
        "toolboxes": toolboxes,
        "command": command,
        "input_files": normalized_inputs,
        "output_files": normalized_outputs,
        "stdout_path": stdout_relative,
        "stderr_path": stderr_relative,
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_seconds": elapsed_seconds,
        "exit_status": exit_status,
        "execution_valid": execution_valid,
        "unavailable_reason": unavailable_reason,
    }
    require_valid(manifest, "matlab_run_manifest")
    atomic_json(root / manifest_relative, manifest)

    metrics = _read_metrics(root, metric_sources) if execution_valid else {}
    register_result(
        root,
        result_id=result_id,
        question_id=question_id,
        kind=f"matlab_{role}",
        command=" ".join(command) if command else f"{engine} unavailable",
        source_script=script,
        input_files=normalized_inputs,
        output_files=[*normalized_outputs, manifest_relative],
        metrics=metrics,
        metric_sources=metric_sources if execution_valid else {},
        exit_code=exit_status if execution_valid else (exit_status or 1),
        stdout_path=stdout_relative,
        stderr_path=stderr_relative,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=elapsed_seconds,
        execution_mode=execution_mode,
        error=None if execution_valid else (unavailable_reason or "MATLAB 输出缺失、陈旧或执行失败"),
        objective_semantics_sha256=objective_semantics_sha256,
        method_facts={
            "uses_independent_oracle": role == "independent_oracle",
            "uses_optimizer_challenger": role == "optimizer_challenger",
            "generates_scientific_visualization": True,
        },
    )
    return manifest

