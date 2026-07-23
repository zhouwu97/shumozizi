"""管理 v3 图表叙事合同，避免只生成无解释力的结果条形图。"""

from __future__ import annotations

import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    load_json,
    relative_inside,
    resolve_inside,
    sha256_file,
)
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.simple.capabilities import require_capability_route
from shumozizi.simple.quality import quality_allows_paper
from shumozizi.simple.state import read_simple_state, utc_now
from tools.qa.figqa import audit_figure

PLAN_PATH = Path("state/visualization-plan.json")
_CURRENT_VISUALIZATION_SCHEMA_VERSION = "1.3"
_FIGURE_RECEIPTS_DIRECTORY = Path("figures/receipts")
_SAFE_FIGURE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_RENDER_ENGINES = {"python", "matlab", "octave"}
_RENDERING_MODES = {"2d", "3d", "orthographic", "diagram"}
_LEAN_COMPLETION_FIELDS = {
    "source_paths",
    "rendering_mode",
    "outputs",
    "generator",
    "source_receipts",
    "generator_sha256",
    "result_ids",
}
_LEGACY_COMPLETION_FIELDS = _LEAN_COMPLETION_FIELDS | {
    "render_receipt",
}
_FAMILY_REQUIREMENTS = {
    "geometry_kinematics": {"model_structure"},
    "optimization": {"solver_process", "optimality_evidence"},
    "mechanism_dynamics": {"model_structure"},
    "network_system": {"model_structure"},
    "prediction_statistical": {"result_stability"},
    "evaluation_ranking": {"result_stability"},
}
_LEGACY_FAMILY_ROLES = {
    "geometry_kinematics": {"spatial_scene", "geometric_boundary"},
    "optimization": {"optimization_convergence", "optimization_diagnostic"},
    "mechanism_dynamics": {"state_or_field"},
    "network_system": {"network_topology_or_flow"},
    "prediction_statistical": {"fit_residual_or_uncertainty"},
    "evaluation_ranking": {"sensitivity_or_rank_stability"},
}
_OPTIMIZATION_PROCESS_MODES = {
    "heuristic_trace",
    "bound_gap",
    "enumeration_coverage",
    "analytic_derivation",
    "residual_certificate",
}
_OPTIMIZATION_OPTIMALITY_MODES = {
    "proxy_calibration",
    "local_landscape",
    "bound_gap",
    "enumeration_coverage",
    "analytic_derivation",
    "residual_certificate",
}


def _schema() -> dict[str, Any]:
    """读取图表叙事计划 Schema。"""
    root = resolve_repo_root(Path(__file__))
    return load_json(root / "schemas" / "simple_visualization_plan.schema.json")


def _require_schema(payload: dict[str, Any]) -> None:
    """校验图表叙事计划的结构。"""
    validator = Draft202012Validator(_schema(), format_checker=FormatChecker())
    errors = [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    ]
    if errors:
        raise ContractError("; ".join(errors))


def _render_schema() -> dict[str, Any]:
    """读取图表真实渲染收据的 Schema。"""
    root = resolve_repo_root(Path(__file__))
    return load_json(root / "schemas" / "figure_render_receipt.schema.json")


def _require_render_receipt(receipt: dict[str, Any]) -> None:
    """校验真实渲染收据，不把声明性图表字段当作执行证据。"""
    validator = Draft202012Validator(_render_schema(), format_checker=FormatChecker())
    errors = [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(receipt), key=lambda item: list(item.path))
    ]
    if errors:
        raise ContractError("图表渲染收据不符合协议: " + "; ".join(errors))


def _file_evidence(run_dir: Path, path: Path) -> dict[str, Any]:
    """为图表脚本、输入、输出或日志生成冻结文件证据。"""
    return {
        "path": relative_inside(run_dir, path).as_posix(),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _verify_file_evidence(
    run_dir: Path, evidence: dict[str, Any], *, label: str, require_nonempty: bool
) -> Path:
    """复验渲染收据中的单个文件，避免计划复用漂移产物。"""
    path = resolve_inside(run_dir, evidence["path"], must_exist=True)
    if sha256_file(path) != evidence["sha256"] or path.stat().st_size != evidence["size_bytes"]:
        raise ContractError(f"图示{label}哈希不一致: {evidence['path']}")
    if require_nonempty and path.stat().st_size == 0:
        raise ContractError(f"图示{label}为空: {evidence['path']}")
    return path


def _available_engine_command(run_dir: Path, engine: str) -> str:
    """只允许使用路由烟雾测试确认可用的实际渲染引擎。"""
    if engine not in _RENDER_ENGINES:
        raise ContractError(f"不支持的图表渲染引擎: {engine}")
    tooling_path = run_dir / "state" / "tooling.json"
    tooling = load_json(tooling_path)
    records = tooling.get("engines")
    if not isinstance(records, list):
        raise ContractError("图表渲染缺少有效的工具探测记录")
    for record in records:
        if not isinstance(record, dict) or record.get("engine") != engine:
            continue
        command = record.get("command")
        probe = record.get("probe")
        if (
            record.get("available") is True
            and isinstance(command, str)
            and isinstance(probe, dict)
            and probe.get("exit_code") == 0
            and probe.get("timed_out") is False
        ):
            return command
    raise ContractError(f"图表渲染引擎未通过当前运行的烟雾测试: {engine}")


def _safe_render_argument(value: str) -> str:
    """限制传给图表脚本的参数，虽然不经 shell 仍拒绝目录越界。"""
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ContractError("图表渲染参数必须是非空字符串")
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ContractError("图表渲染参数不允许绝对路径或目录穿越")
    return value


def _render_command(engine: str, command: str, script_relative: str, arguments: list[str]) -> list[str]:
    """构造不经 shell 的图表渲染命令。"""
    if engine == "python":
        return [command, script_relative, *arguments]
    if "'" in script_relative:
        raise ContractError("MATLAB/Octave 图表脚本路径不允许单引号")
    if arguments:
        raise ContractError("MATLAB/Octave 图表脚本请通过环境变量读取冻结输入和输出目录")
    expression = f"run('{script_relative}')"
    if engine == "matlab":
        return [command, "-batch", expression]
    return [command, "--quiet", "--no-gui", "--eval", expression]


def run_figure_render(
    run_dir: Path,
    *,
    figure_id: str,
    engine: str,
    rendering_mode: str,
    script_path: str,
    input_paths: list[str],
    output_paths: list[str],
    arguments: list[str] | None = None,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """运行图表脚本并生成其输入、输出和命令的最小冻结收据。

    Args:
        run_dir: 当前 v3 运行目录。
        figure_id: 图表稳定标识。
        engine: Python、MATLAB 或 Octave。
        rendering_mode: 调用方声明的展示方式；它绑定到执行收据，供后续视觉证据
            覆盖校验使用，但不能证明 PNG 的内容确实具有该三维或几何语义。
        script_path: 运行内图表脚本路径。
        input_paths: 声明提供给渲染命令的输入文件。运行器只冻结这些文件的路径、
            哈希和大小，不能证明脚本实际读取了全部声明输入，也不能证明脚本没有
            读取未声明文件。
        output_paths: 本次命令必须新建的图表文件。
        arguments: 仅 Python 脚本使用的受控参数。
        timeout_seconds: 运行超时秒数。

    Returns:
        可直接写入 v1.3 Figure Contract 的收据路径和哈希。

    Raises:
        ContractError: 图表没有由受控命令新鲜生成，或工具和路径不满足边界。
    """
    if not _SAFE_FIGURE_ID.fullmatch(figure_id):
        raise ContractError("figure_id 不合法")
    if rendering_mode not in _RENDERING_MODES:
        raise ContractError("图表 rendering_mode 必须为 2d、3d、orthographic 或 diagram")
    if timeout_seconds < 1 or timeout_seconds > 3600:
        raise ContractError("图表渲染 timeout_seconds 必须在 1 至 3600 之间")
    root = run_dir.resolve()
    script = resolve_inside(root, script_path, must_exist=True)
    script_relative = relative_inside(root, script).as_posix()
    if not script_relative.startswith(("code/figures/", "code/matlab/")):
        raise ContractError("图表脚本必须位于 code/figures/ 或 code/matlab/ 下")
    expected_suffix = {"python": ".py", "matlab": ".m", "octave": ".m"}.get(engine)
    if expected_suffix is None or script.suffix.casefold() != expected_suffix:
        raise ContractError("图表脚本扩展名与渲染引擎不一致")
    if not script.is_file() or script.stat().st_size == 0:
        raise ContractError("图表生成脚本必须是非空文件")
    inputs = [resolve_inside(root, value, must_exist=True) for value in input_paths]
    if any(not path.is_file() for path in inputs):
        raise ContractError("图表输入必须是文件")
    outputs = [resolve_inside(root, value, must_exist=False) for value in output_paths]
    if not outputs:
        raise ContractError("图表渲染至少需要一个输出")
    if len({path.resolve() for path in outputs}) != len(outputs):
        raise ContractError("图表渲染输出路径重复")
    for output in outputs:
        relative = relative_inside(root, output).as_posix()
        if not relative.startswith("figures/") or relative.startswith("figures/receipts/"):
            raise ContractError("图表输出必须位于 figures/ 下且不能覆盖收据")
        if output.exists():
            if not output.is_file():
                raise ContractError("图表输出不能覆盖目录")
            output.unlink()
        output.parent.mkdir(parents=True, exist_ok=True)
    safe_arguments = [_safe_render_argument(value) for value in (arguments or [])]
    command_path = _available_engine_command(root, engine)
    command = _render_command(engine, command_path, script_relative, safe_arguments)
    receipt_id = f"{figure_id}-{uuid.uuid4().hex[:12]}"
    receipt_dir = root / _FIGURE_RECEIPTS_DIRECTORY / receipt_id
    receipt_dir.mkdir(parents=True, exist_ok=False)
    started_at = utc_now()
    environment = dict(os.environ)
    environment["SHUMOZIZI_FIGURE_INPUTS"] = ";".join(
        relative_inside(root, path).as_posix() for path in inputs
    )
    environment["SHUMOZIZI_FIGURE_OUTPUTS"] = ";".join(
        relative_inside(root, path).as_posix() for path in outputs
    )
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            env=environment,
        )
        exit_code, timed_out = completed.returncode, False
        stdout, stderr = completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code, timed_out = 124, True
        stdout = (
            exc.stdout.decode("utf-8", errors="replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        stderr = (
            exc.stderr.decode("utf-8", errors="replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        ) + f"\n图表渲染超过 {timeout_seconds} 秒，已终止。\n"
    stdout_path = receipt_dir / "stdout.log"
    stderr_path = receipt_dir / "stderr.log"
    stdout_path.write_text(stdout, encoding="utf-8", newline="\n")
    stderr_path.write_text(stderr, encoding="utf-8", newline="\n")
    if exit_code != 0 or timed_out:
        raise ContractError(f"图表渲染命令未成功完成（exit_code={exit_code}）")
    missing = [path for path in outputs if not path.is_file() or path.stat().st_size == 0]
    if missing:
        names = ", ".join(relative_inside(root, path).as_posix() for path in missing)
        raise ContractError("图表渲染缺少非空输出: " + names)
    receipt = {
        "schema_name": "figure_render",
        "schema_version": "1.0",
        "run_id": root.name,
        "figure_id": figure_id,
        "engine": engine,
        "rendering_mode": rendering_mode,
        "command": command,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "script": _file_evidence(root, script),
        "inputs": [_file_evidence(root, path) for path in inputs],
        "outputs": [_file_evidence(root, path) for path in outputs],
        "stdout": _file_evidence(root, stdout_path),
        "stderr": _file_evidence(root, stderr_path),
        "started_at": started_at,
        "finished_at": utc_now(),
    }
    _require_render_receipt(receipt)
    receipt_path = receipt_dir / "receipt.json"
    atomic_json(receipt_path, receipt)
    return {
        "path": relative_inside(root, receipt_path).as_posix(),
        "sha256": sha256_file(receipt_path),
    }


def required_visual_roles(run_dir: Path) -> set[str]:
    """兼容旧调用：返回当前题需要回答的视觉证据角色。"""
    route = require_capability_route(run_dir)
    return set().union(
        *(_FAMILY_REQUIREMENTS.get(family, set()) for family in route["problem_families"])
    )


def _required_evidence_modes(route: dict[str, Any]) -> dict[str, set[str]]:
    """按题型和空间结论风险推导证据问题，不规定固定图种或图数。"""
    families = set(route["problem_families"])
    required = {
        role: set()
        for family in families
        for role in _FAMILY_REQUIREMENTS.get(family, set())
    }
    if "geometry_kinematics" in families:
        spatial = route.get("visual_evidence", {}).get(
            "spatial_structure_affects_conclusion", False
        )
        required["model_structure"] = (
            {"spatial_3d"}
            if spatial
            else {"spatial_3d", "orthographic_geometry", "planar_geometry"}
        )
    if "optimization" in families:
        required["solver_process"] = _OPTIMIZATION_PROCESS_MODES
        required["optimality_evidence"] = _OPTIMIZATION_OPTIMALITY_MODES
    if "mechanism_dynamics" in families:
        required["model_structure"] = {"state_trajectory", "spatial_3d", "planar_geometry"}
    if "network_system" in families:
        required["model_structure"] = {"network_flow", "planar_geometry"}
    if "prediction_statistical" in families:
        required["result_stability"] = {"fit_diagnostics", "result_comparison"}
    if "evaluation_ranking" in families:
        required["result_stability"] = {"rank_stability", "result_comparison"}
    return required


def _read_render_receipt(
    run_dir: Path, contract: dict[str, Any], *, require_frozen_hash: bool
) -> tuple[Path, dict[str, Any]]:
    """读取当前 Figure Contract 引用的真实渲染收据。"""
    reference = contract.get("render_receipt")
    if isinstance(reference, str):
        receipt_relative = reference
        expected_hash = None
    elif isinstance(reference, dict):
        receipt_relative = reference.get("path")
        expected_hash = reference.get("sha256")
    else:
        raise ContractError("complete 图示必须引用真实渲染收据")
    if not isinstance(receipt_relative, str) or not receipt_relative.startswith("figures/receipts/"):
        raise ContractError("图表渲染收据必须位于 figures/receipts/ 下")
    receipt_path = resolve_inside(run_dir, receipt_relative, must_exist=True)
    if require_frozen_hash and not isinstance(expected_hash, str):
        raise ContractError("complete 图示缺少冻结渲染收据哈希")
    current_hash = sha256_file(receipt_path)
    if isinstance(expected_hash, str) and expected_hash != current_hash:
        raise ContractError("图表渲染收据哈希不一致")
    receipt = load_json(receipt_path)
    _require_render_receipt(receipt)
    return receipt_path, receipt


def _verify_render_receipt(run_dir: Path, contract: dict[str, Any]) -> None:
    """确认图表来自一条仍可重放、未漂移的真实渲染收据。"""
    receipt_path, receipt = _read_render_receipt(run_dir, contract, require_frozen_hash=True)
    if receipt["run_id"] != run_dir.name or receipt["figure_id"] != contract["figure_id"]:
        raise ContractError("图表渲染收据与当前运行或 figure_id 不一致")
    if receipt["rendering_mode"] not in _RENDERING_MODES:
        raise ContractError("图表渲染收据的 rendering_mode 不合法")
    if receipt["exit_code"] != 0 or receipt["timed_out"]:
        raise ContractError("图表渲染收据未记录成功执行")
    script = _verify_file_evidence(
        run_dir, receipt["script"], label="生成脚本", require_nonempty=True
    )
    script_relative = relative_inside(run_dir, script).as_posix()
    if not script_relative.startswith(("code/figures/", "code/matlab/")):
        raise ContractError("图表生成脚本位于受控目录外")
    if not any(script_relative in part for part in receipt["command"]):
        raise ContractError("图表渲染命令未绑定登记脚本")
    for item in receipt["inputs"]:
        _verify_file_evidence(run_dir, item, label="输入", require_nonempty=False)
    png_seen = False
    for item in receipt["outputs"]:
        output = _verify_file_evidence(run_dir, item, label="输出", require_nonempty=True)
        output_relative = relative_inside(run_dir, output).as_posix()
        if not output_relative.startswith("figures/") or output_relative.startswith("figures/receipts/"):
            raise ContractError("图表渲染输出位于 figures/ 目录外")
        if output.suffix.casefold() == ".png":
            png_seen = True
            audit = audit_figure(output)
            if audit["errors"]:
                raise ContractError("图示 PNG 无法通过可读性检查: " + "；".join(audit["errors"]))
    if not png_seen:
        raise ContractError("complete 图示至少必须输出一张可审计 PNG")
    _verify_file_evidence(run_dir, receipt["stdout"], label="标准输出", require_nonempty=False)
    _verify_file_evidence(run_dir, receipt["stderr"], label="标准错误", require_nonempty=False)
    if receipt_path.stat().st_size == 0:
        raise ContractError("图表渲染收据为空")


def _freeze_current_complete_contract(run_dir: Path, contract: dict[str, Any]) -> None:
    """把已实际执行的渲染收据绑定到精简 Figure Contract。"""
    if contract["status"] != "complete":
        supplied = sorted(_LEGACY_COMPLETION_FIELDS & set(contract))
        if supplied:
            raise ContractError(
                "planned 图只记录论证意图；完成后再引用渲染收据: " + ", ".join(supplied)
            )
        return
    receipt_path, receipt = _read_render_receipt(run_dir, contract, require_frozen_hash=False)
    if receipt["run_id"] != run_dir.name or receipt["figure_id"] != contract["figure_id"]:
        raise ContractError("图表渲染收据与当前运行或 figure_id 不一致")
    contract["render_receipt"] = {
        "path": relative_inside(run_dir, receipt_path).as_posix(),
        "sha256": sha256_file(receipt_path),
    }
    _verify_render_receipt(run_dir, contract)


def _freeze_complete_contract(
    run_dir: Path, contract: dict[str, Any], *, schema_version: str
) -> None:
    """在写入时冻结完成图的输入、脚本和输出，阻止手填过期哈希。"""
    if schema_version == _CURRENT_VISUALIZATION_SCHEMA_VERSION:
        _freeze_current_complete_contract(run_dir, contract)
        return
    outputs = contract.get("outputs", [])
    if contract["status"] != "complete":
        if schema_version == _CURRENT_VISUALIZATION_SCHEMA_VERSION:
            supplied = sorted(_LEAN_COMPLETION_FIELDS & set(contract))
            if supplied:
                raise ContractError(
                    "planned 图只记录论证意图；完成后再登记来源、脚本和输出: "
                    + ", ".join(supplied)
                )
        if outputs:
            raise ContractError("planned/waived 图示不得登记输出")
        return
    if not outputs:
        raise ContractError("complete 图示必须登记至少一个输出")
    normalized: list[dict[str, str]] = []
    for output in outputs:
        path_value = output if isinstance(output, str) else output.get("path") if isinstance(output, dict) else None
        if not isinstance(path_value, str) or not path_value:
            raise ContractError("图示输出必须为运行目录内路径或路径/哈希对象")
        path = resolve_inside(run_dir, path_value, must_exist=True)
        if not path.is_file() or path.stat().st_size == 0:
            raise ContractError(f"图示输出为空: {path_value}")
        normalized.append({"path": path.relative_to(run_dir).as_posix(), "sha256": sha256_file(path)})
    png_outputs = [item for item in normalized if Path(item["path"]).suffix.casefold() == ".png"]
    if not png_outputs:
        raise ContractError("complete 图示至少必须输出一张可审计 PNG")
    for output in png_outputs:
        audit = audit_figure(resolve_inside(run_dir, output["path"], must_exist=True))
        if audit["errors"]:
            raise ContractError("图示 PNG 无法通过可读性检查: " + "；".join(audit["errors"]))
    contract["outputs"] = normalized
    source_receipts: list[dict[str, str]] = []
    for source in contract["source_paths"]:
        source_path = resolve_inside(run_dir, source, must_exist=True)
        if not source_path.is_file():
            raise ContractError(f"图示输入必须是文件: {source}")
        source_receipts.append(
            {"path": source_path.relative_to(run_dir).as_posix(), "sha256": sha256_file(source_path)}
        )
    generator_path = resolve_inside(run_dir, contract["generator"]["script_path"], must_exist=True)
    if not generator_path.is_file() or generator_path.stat().st_size == 0:
        raise ContractError("图示生成脚本必须是非空文件")
    contract["source_receipts"] = source_receipts
    contract["generator_sha256"] = sha256_file(generator_path)


def _require_frozen_complete_contract(
    run_dir: Path, contract: dict[str, Any], *, schema_version: str
) -> None:
    """复验完成图的输入、脚本与输出仍对应登记时的同一份证据。"""
    if schema_version == _CURRENT_VISUALIZATION_SCHEMA_VERSION:
        if contract["status"] == "complete":
            _verify_render_receipt(run_dir, contract)
        return
    if contract["status"] != "complete":
        return
    outputs = contract["outputs"]
    if not outputs:
        raise ContractError("complete 图示必须登记至少一个输出")
    png_outputs: list[dict[str, str]] = []
    for output in outputs:
        if not isinstance(output, dict) or not isinstance(output.get("path"), str):
            raise ContractError("complete 图示缺少冻结输出收据")
        current = sha256_file(resolve_inside(run_dir, output["path"], must_exist=True))
        if current != output.get("sha256"):
            raise ContractError(f"图示输出哈希不一致: {output['path']}")
        if Path(output["path"]).suffix.casefold() == ".png":
            png_outputs.append(output)
    if not png_outputs:
        raise ContractError("complete 图示至少必须输出一张可审计 PNG")
    for output in png_outputs:
        audit = audit_figure(resolve_inside(run_dir, output["path"], must_exist=True))
        if audit["errors"]:
            raise ContractError("图示 PNG 无法通过可读性检查: " + "；".join(audit["errors"]))
    receipts = contract.get("source_receipts")
    if not isinstance(receipts, list):
        raise ContractError("complete 图示缺少冻结输入收据")
    expected_sources = list(contract["source_paths"])
    receipt_paths = [item.get("path") for item in receipts if isinstance(item, dict)]
    if len(receipt_paths) != len(expected_sources) or set(receipt_paths) != set(expected_sources):
        raise ContractError("图示输入收据与 Figure Contract 不一致")
    for receipt in receipts:
        if not isinstance(receipt, dict) or not isinstance(receipt.get("path"), str):
            raise ContractError("图示输入收据格式无效")
        current = sha256_file(resolve_inside(run_dir, receipt["path"], must_exist=True))
        if current != receipt.get("sha256"):
            raise ContractError(f"图示输入哈希不一致: {receipt['path']}")
    generator_path = resolve_inside(run_dir, contract["generator"]["script_path"], must_exist=True)
    if not generator_path.is_file() or sha256_file(generator_path) != contract.get("generator_sha256"):
        raise ContractError("图示生成脚本哈希不一致")


def _require_lean_contract(contract: dict[str, Any], *, schema_version: str) -> None:
    """拒绝把旧版重复叙述或完成态字段塞入 v1.2 计划。"""
    legacy_narrative = {
        "purpose",
        "selection_reason",
        "loss_if_omitted",
        "rationale",
        "waiver_reason",
        "replacement_for",
    }
    supplied = sorted(legacy_narrative & set(contract))
    if schema_version == _CURRENT_VISUALIZATION_SCHEMA_VERSION:
        supplied.extend(sorted(_LEAN_COMPLETION_FIELDS & set(contract)))
    if supplied:
        raise ContractError(
            "当前 Figure Contract 只保留科学问题、必要性和渲染收据，不能重复填写: "
            + ", ".join(supplied)
        )


def _require_semantics(run_dir: Path, payload: dict[str, Any], *, final: bool) -> None:
    """检查题型视觉覆盖、事实来源与已完成图的可复验性。"""
    state = read_simple_state(run_dir)
    if payload["run_id"] != state["run_id"]:
        raise ContractError("图表叙事计划 run_id 与当前运行不一致")
    if payload["state_revision"] > state["revision"]:
        raise ContractError("图表叙事计划不能来自未来状态修订")
    route = require_capability_route(run_dir)
    contracts = payload["contracts"]
    figure_ids = [item["figure_id"] for item in contracts]
    if len(figure_ids) != len(set(figure_ids)):
        raise ContractError("图表叙事计划存在重复 figure_id")
    role_to_contracts: dict[str, list[dict[str, Any]]] = {}
    for contract in contracts:
        if payload["schema_version"] in {"1.2", _CURRENT_VISUALIZATION_SCHEMA_VERSION}:
            _require_lean_contract(contract, schema_version=payload["schema_version"])
        if payload["schema_version"] == "1.0":
            role_to_contracts.setdefault(contract["role"], []).append(contract)
        _require_frozen_complete_contract(
            run_dir, contract, schema_version=payload["schema_version"]
        )
        requires_artifacts = (
            payload["schema_version"] != _CURRENT_VISUALIZATION_SCHEMA_VERSION
            or contract["status"] == "complete"
        )
        if requires_artifacts and payload["schema_version"] != _CURRENT_VISUALIZATION_SCHEMA_VERSION:
            for source in contract["source_paths"]:
                source_path = resolve_inside(run_dir, source, must_exist=True)
                if not source_path.is_file():
                    raise ContractError(f"图示输入必须是文件: {source}")
            generator_path = resolve_inside(run_dir, contract["generator"]["script_path"], must_exist=True)
            if not generator_path.is_file():
                raise ContractError("图示生成脚本必须是文件")
            if contract["evidence_scope"] == "production_result":
                result_ids = contract.get("result_ids", [])
                if not result_ids:
                    raise ContractError("production_result 图示必须声明 result_ids")
                unavailable = [result_id for result_id in result_ids if not quality_allows_paper(run_dir, result_id)]
                if unavailable:
                    raise ContractError("图示引用了未放行生产结果: " + ", ".join(unavailable))
            elif contract.get("result_ids"):
                raise ContractError("非 production_result 图示不得伪装为生产结果事实")
        if contract["status"] == "waived" and payload["schema_version"] == "1.1":
            if "waiver_reason" not in contract or "replacement_for" not in contract:
                raise ContractError("豁免图示必须写明原因和等价替代图")
            replacements = [
                item
                for item in contracts
                if item["figure_id"] in set(contract["replacement_for"])
                and item["status"] == "complete"
            ]
            if len(replacements) != len(contract["replacement_for"]):
                raise ContractError("豁免图示的等价替代图必须已完成")
            if payload["schema_version"] == "1.1" and not any(
                set(item["evidence_roles"]) >= set(contract["evidence_roles"])
                for item in replacements
            ):
                raise ContractError("豁免图示的替代图未覆盖相同证据问题")
        if (
            payload["schema_version"] in {"1.1", "1.2", _CURRENT_VISUALIZATION_SCHEMA_VERSION}
            and contract["status"] == "complete"
        ):
            mode = set(contract["evidence_modes"])
            if payload["schema_version"] == _CURRENT_VISUALIZATION_SCHEMA_VERSION:
                _, receipt = _read_render_receipt(
                    run_dir, contract, require_frozen_hash=True
                )
                rendering = receipt["rendering_mode"]
            else:
                rendering = contract["rendering_mode"]
            if "spatial_3d" in mode and rendering != "3d":
                raise ContractError("spatial_3d 证据必须使用 3d 渲染模式")
            if "orthographic_geometry" in mode and rendering not in {"orthographic", "2d"}:
                raise ContractError("orthographic_geometry 证据必须使用正交或二维渲染")

    if payload["schema_version"] == "1.0":
        # 已冻结旧计划继续按旧规则读取；新计划不再用固定图种/图数做形式门禁。
        legacy_required = set().union(
            *(_LEGACY_FAMILY_ROLES.get(family, set()) for family in route["problem_families"])
        )
        if len(state["required_questions"]) > 1:
            legacy_required.add("method_roadmap")
        missing = legacy_required - set(role_to_contracts)
        if missing:
            raise ContractError("图表叙事计划缺少题型视觉证据: " + ", ".join(sorted(missing)))
        if final:
            incomplete = sorted(
                role
                for role in legacy_required
                if not any(item["status"] == "complete" for item in role_to_contracts[role])
            )
            if incomplete:
                raise ContractError("必需视觉证据尚未完成: " + ", ".join(incomplete))
        return

    requirements = _required_evidence_modes(route)
    if final:
        unmet: list[str] = []
        for evidence_role, accepted_modes in requirements.items():
            covered = any(
                contract["status"] == "complete"
                and evidence_role in contract["evidence_roles"]
                and bool(set(contract["evidence_modes"]) & accepted_modes)
                for contract in contracts
            )
            if not covered:
                unmet.append(evidence_role)
        if unmet:
            raise ContractError("图表缺少等价的科学证据问题: " + ", ".join(sorted(unmet)))


def write_visualization_plan(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """登记图表合同或完成后的视觉证据。

    Args:
        run_dir: v3 运行目录。
        payload: 计划或完成清单；完成图的输出可只传字符串路径。

    Returns:
        标准化并保存的图表叙事计划。
    """
    _require_schema(payload)
    for contract in payload["contracts"]:
        _freeze_complete_contract(
            run_dir, contract, schema_version=payload["schema_version"]
        )
    _require_semantics(run_dir, payload, final=False)
    _require_schema(payload)
    atomic_json(run_dir / PLAN_PATH, payload)
    return payload


def read_visualization_plan(run_dir: Path) -> dict[str, Any]:
    """读取已经登记的图表叙事计划。"""
    plan_path = run_dir / PLAN_PATH
    if not plan_path.is_file():
        raise ContractError("缺少图表叙事计划 state/visualization-plan.json")
    payload = load_json(plan_path)
    _require_schema(payload)
    _require_semantics(run_dir, payload, final=False)
    return payload


def require_visualization_complete(run_dir: Path) -> dict[str, Any]:
    """确保写论文前所有题型必需的视觉证据都已完成。"""
    payload = read_visualization_plan(run_dir)
    _require_semantics(run_dir, payload, final=True)
    return payload


def new_visualization_plan(run_dir: Path, contracts: list[dict[str, Any]]) -> dict[str, Any]:
    """基于当前运行状态创建图表计划的稳定外壳。"""
    state = read_simple_state(run_dir)
    return {
        "schema_version": _CURRENT_VISUALIZATION_SCHEMA_VERSION,
        "run_id": state["run_id"],
        "state_revision": state["revision"],
        "contracts": contracts,
        "created_at": utc_now(),
    }
