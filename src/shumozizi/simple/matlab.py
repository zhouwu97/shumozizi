"""执行并登记 Competition-First MATLAB 建模、优化与科学绘图。"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, relative_inside, resolve_inside
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.core.schema import require_valid
from shumozizi.engines.matlab import detect_engine
from shumozizi.simple.results import json_path_value, register_result
from shumozizi.simple.state import utc_now

_ROLES = frozenset(
    {"primary_model", "optimizer_challenger", "independent_oracle", "scientific_visualization"}
)
_ROLE_REQUIRED_SUFFIXES = {
    "primary_model": frozenset({".json"}),
    "optimizer_challenger": frozenset({".json"}),
    "independent_oracle": frozenset({".json"}),
    "scientific_visualization": frozenset({".pdf", ".png"}),
}
_IMAGE_SUFFIXES = frozenset({".pdf", ".png"})


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


def _validate_image_outputs(output_files: list[str]) -> list[str]:
    """校验 MATLAB 图像必须成对进入版本化候选目录并带布局报告。

    Args:
        output_files: 已规范化为 POSIX 路径的 MATLAB 输出。

    Returns:
        每组 PNG/PDF 共用的不含扩展名候选路径。

    Raises:
        ContractError: 图像直写 current、缺少配对格式或缺少布局报告。
    """
    output_set = set(output_files)
    image_files = [
        item for item in output_files if Path(item).suffix.casefold() in _IMAGE_SUFFIXES
    ]
    grouped: dict[str, set[str]] = {}
    for item in image_files:
        if not item.startswith("figures/work/"):
            raise ContractError(
                "MATLAB 图片无论由何种角色生成，都必须先输出到 figures/work/"
            )
        path = Path(item)
        if len(path.parts) < 5:
            raise ContractError(
                "MATLAB 图片必须位于 figures/work/<figure_id>/<version>/"
            )
        stem = path.with_suffix("").as_posix()
        grouped.setdefault(stem, set()).add(path.suffix.casefold())
    for stem, suffixes in grouped.items():
        if suffixes != _IMAGE_SUFFIXES:
            raise ContractError(f"MATLAB 图像候选 {stem} 必须同时输出 PNG 和 PDF")
        layout = f"{stem}.layout.json"
        if layout not in output_set:
            raise ContractError(
                f"MATLAB 图像候选 {stem} 必须同时声明 {Path(layout).name}"
            )
    return sorted(grouped)


def _install_figure_kit(run_dir: Path) -> list[str]:
    """把仓内 MATLAB 论文图工具包冻结到当前运行的代码目录。

    Args:
        run_dir: 当前运行根目录。

    Returns:
        安装后应写入 manifest 输入清单的相对文件路径。

    Raises:
        ContractError: 当前运行已有同名但内容不同的工具文件。
    """
    repository = resolve_repo_root(Path(__file__))
    source_root = repository / "templates" / "matlab" / "figures" / "+shumoviz"
    if not source_root.is_dir():
        raise ContractError("仓库缺少 MATLAB 论文图工具包 templates/matlab/figures/+shumoviz")
    target_root = run_dir / "code" / "matlab" / "+shumoviz"
    target_root.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []
    for source in sorted(source_root.glob("*.m")):
        target = target_root / source.name
        if target.exists() and target.read_bytes() != source.read_bytes():
            raise ContractError(
                f"当前运行已有不同内容的 MATLAB 图工具文件: {target.name}"
            )
        if not target.exists():
            shutil.copy2(source, target)
        installed.append(relative_inside(run_dir, target).as_posix())
    if not installed:
        raise ContractError("MATLAB 论文图工具包不含可安装的 .m 文件")
    return installed


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

    入口只通过 ``SHUMOZIZI_RUN_DIR`` 获得运行根目录。数值模型、优化挑战和
    独立 oracle 至少输出 JSON；科学绘图输出 PNG/PDF 候选。CSV 和图像只在
    科学角色确实需要时生成。manifest 只证明命令与文件闭环，不证明模型正确
    或独立性成立。

    Args:
        run_dir: 当前 Competition-First 运行目录。
        entrypoint: ``code/matlab/`` 下的真实 ``.m`` 入口。
        question_id: 对应必答问题。
        result_id: 写入结果索引的稳定 ID。
        role: MATLAB 承担的科学角色。
        input_files: 原始题面附件、受控参数或当前结果，不含入口自身。
        output_files: 按 MATLAB 科学角色声明的最小新鲜产物。
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
    normalized_outputs = [_relative_file(root, item, must_exist=False) for item in output_files]
    suffixes = {Path(item).suffix.casefold() for item in normalized_outputs}
    required_suffixes = _ROLE_REQUIRED_SUFFIXES[role]
    if not required_suffixes <= suffixes:
        missing = ", ".join(sorted(required_suffixes - suffixes))
        raise ContractError(f"MATLAB 角色 {role} 缺少必需输出类型: {missing}")
    if len(normalized_outputs) != len(set(normalized_outputs)):
        raise ContractError("MATLAB output_files 不允许重复")
    image_stems = _validate_image_outputs(normalized_outputs)
    normalized_inputs = [_relative_file(root, item, must_exist=True) for item in input_files]
    kit_inputs = _install_figure_kit(root) if image_stems else []
    normalized_inputs = list(dict.fromkeys([script, *normalized_inputs, *kit_inputs]))
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
    image_related = {
        item
        for item in normalized_outputs
        if Path(item).suffix.casefold() in {*_IMAGE_SUFFIXES, ".json"}
        and any(item == f"{stem}.layout.json" or item.startswith(f"{stem}.") for stem in image_stems)
    }
    existing_images = sorted(item for item in image_related if (root / item).exists())
    if existing_images:
        raise ContractError(
            "MATLAB 图像候选版本已存在，必须使用新的 version 目录: "
            + ", ".join(existing_images)
        )

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
        environment["SHUMOZIZI_FIGURE_OUTPUT_STEMS"] = ";".join(image_stems)
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
            "generates_scientific_visualization": role == "scientific_visualization",
        },
    )
    return manifest
