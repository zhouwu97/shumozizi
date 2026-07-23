"""记录并校验 v3 赛题的能力路由与本地工具可用性。"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import ContractError, atomic_json, load_json, resolve_inside, sha256_file
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import read_simple_state, utc_now

ROUTE_PATH = Path("state/capability-route.json")
TOOLING_PATH = Path("state/tooling.json")
_ORACLE_FAMILIES = {"geometry_kinematics", "mechanism_dynamics"}
_SUPPORTED_ENGINES = ("python", "matlab", "octave")
_ENGINE_SUFFIXES = {"python": ".py", "matlab": ".m", "octave": ".m"}


def _schema(name: str) -> dict[str, Any]:
    """读取运行协议 Schema。

    Args:
        name: Schema 文件名。

    Returns:
        JSON Schema 对象。
    """
    root = resolve_repo_root(Path(__file__))
    return load_json(root / "schemas" / name)


def _require_schema(payload: dict[str, Any], name: str) -> None:
    """校验 JSON Schema 并给出稳定的合同错误。"""
    validator = Draft202012Validator(_schema(name), format_checker=FormatChecker())
    errors = [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    ]
    if errors:
        raise ContractError("; ".join(errors))


def detect_local_tooling() -> dict[str, Any]:
    """探测本机可执行的生产与独立验证工具。

    检测只记录可执行路径，不安装、启动或调用任何商业软件；路由据此避免把
    不存在的 MATLAB/Octave 写成已完成能力。

    Returns:
        可序列化的工具可用性记录。
    """
    commands = {
        "python": shutil.which("python") or shutil.which("python3"),
        "matlab": shutil.which("matlab"),
        "octave": shutil.which("octave") or shutil.which("octave-cli"),
    }
    return {
        "schema_version": "1.0",
        "checked_at": utc_now(),
        "engines": [
            {"engine": engine, "available": command is not None, "command": command}
            for engine, command in commands.items()
        ],
    }


def write_local_tooling(run_dir: Path) -> dict[str, Any]:
    """将当前工具探测保存到运行目录。

    Args:
        run_dir: v3 运行目录。

    Returns:
        已保存的工具记录。
    """
    payload = detect_local_tooling()
    atomic_json(run_dir / TOOLING_PATH, payload)
    return payload


def read_capability_route(run_dir: Path) -> dict[str, Any]:
    """读取并校验已经冻结的能力路由。

    Args:
        run_dir: v3 运行目录。

    Returns:
        路由清单。
    """
    route_path = run_dir / ROUTE_PATH
    if not route_path.is_file():
        raise ContractError("缺少能力路由 state/capability-route.json")
    payload = load_json(route_path)
    _require_schema(payload, "simple_capability_route.schema.json")
    return payload


def _require_route_semantics(run_dir: Path, payload: dict[str, Any]) -> None:
    """检查题型、验证方式、工具链和本地知识资产是否自洽。"""
    state = read_simple_state(run_dir)
    if payload["run_id"] != state["run_id"]:
        raise ContractError("能力路由 run_id 与当前运行不一致")
    families = set(payload["problem_families"])
    verification = payload["verification_capability"]
    toolchain = payload["toolchain"]
    if families & _ORACLE_FAMILIES:
        if verification is None:
            raise ContractError("几何/机理题必须声明独立 oracle 能力")
        if toolchain["independence_strategy"] == "not_required":
            raise ContractError("几何/机理题不得跳过独立 oracle 策略")
    if toolchain["independence_strategy"] in {"alternative_runtime", "alternative_language"}:
        independent = toolchain["independent_engine"]
        if independent is None or independent == toolchain["production_engine"]:
            raise ContractError("替代运行时/语言验证必须选择不同的独立引擎")
    if toolchain["independence_strategy"] == "not_required" and toolchain["independent_engine"] is not None:
        raise ContractError("不需要独立验证时不得填写 independent_engine")
    root = resolve_repo_root(Path(__file__))
    for asset in payload["knowledge_assets"]:
        candidate = resolve_inside(root, asset["path"], must_exist=True)
        if not candidate.is_file():
            raise ContractError(f"知识资产必须是文件: {asset['path']}")
        if sha256_file(candidate) != asset["sha256"]:
            raise ContractError(f"能力路由引用的知识资产已漂移: {asset['path']}")


def _freeze_route_receipts(run_dir: Path, payload: dict[str, Any]) -> None:
    """在首次登记时冻结工具探测和本地知识资产，拒绝伪造旧哈希。"""
    tooling_path = run_dir / TOOLING_PATH
    if not tooling_path.is_file():
        raise ContractError("登记能力路由前必须先写入 state/tooling.json")
    tooling_sha256 = sha256_file(tooling_path)
    supplied_tooling_hash = payload.get("tooling_sha256")
    if supplied_tooling_hash is not None and supplied_tooling_hash != tooling_sha256:
        raise ContractError("能力路由中的 tooling_sha256 与当前工具探测不一致")
    payload["tooling_sha256"] = tooling_sha256

    assets = payload.get("knowledge_assets")
    if not isinstance(assets, list):
        return
    root = resolve_repo_root(Path(__file__))
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("path"), str):
            continue
        candidate = resolve_inside(root, asset["path"], must_exist=True)
        if not candidate.is_file():
            raise ContractError(f"知识资产必须是文件: {asset['path']}")
        current_sha256 = sha256_file(candidate)
        supplied_sha256 = asset.get("sha256")
        if supplied_sha256 is not None and supplied_sha256 != current_sha256:
            raise ContractError(f"能力路由中的知识资产哈希不一致: {asset['path']}")
        asset["sha256"] = current_sha256


def _read_available_engines(tooling: Any) -> dict[str, bool]:
    """从冻结工具探测中读取受支持引擎，拒绝非结构化或重复记录。"""
    if not isinstance(tooling, dict) or tooling.get("schema_version") != "1.0":
        raise ContractError("工具探测记录格式无效")
    records = tooling.get("engines")
    if not isinstance(records, list):
        raise ContractError("工具探测记录缺少 engines 列表")
    engines: dict[str, bool] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ContractError("工具探测记录包含非对象引擎项")
        engine = record.get("engine")
        available = record.get("available")
        command = record.get("command")
        if engine not in _SUPPORTED_ENGINES or not isinstance(available, bool):
            raise ContractError("工具探测记录包含不支持或格式错误的引擎")
        if command is not None and not isinstance(command, str):
            raise ContractError("工具探测记录 command 必须为字符串或 null")
        if engine in engines:
            raise ContractError(f"工具探测记录重复引擎: {engine}")
        engines[engine] = available
    return engines


def write_capability_route(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """写入已完成路线比较后的能力路由。

    Args:
        run_dir: v3 运行目录。
        payload: 由能力路由 Skill 形成的清单。

    Returns:
        已校验并保存的路由。
    """
    _freeze_route_receipts(run_dir, payload)
    _require_schema(payload, "simple_capability_route.schema.json")
    _require_route_semantics(run_dir, payload)
    atomic_json(run_dir / ROUTE_PATH, payload)
    return payload


def require_capability_route(run_dir: Path) -> dict[str, Any]:
    """要求运行已形成真实的能力路由，而不是只引用资产目录。

    Args:
        run_dir: v3 运行目录。

    Returns:
        当前有效路由。

    Raises:
        ContractError: 路由、资产或选用工具不满足执行前条件。
    """
    route = read_capability_route(run_dir)
    _require_route_semantics(run_dir, route)
    tooling_path = run_dir / TOOLING_PATH
    if not tooling_path.is_file():
        raise ContractError("缺少工具探测记录 state/tooling.json")
    tooling = load_json(tooling_path)
    if sha256_file(tooling_path) != route["tooling_sha256"]:
        raise ContractError("能力路由登记后的工具探测记录已漂移，请重新登记路由")
    engines = _read_available_engines(tooling)
    selected = [route["toolchain"]["production_engine"]]
    independent = route["toolchain"]["independent_engine"]
    if independent is not None:
        selected.append(independent)
    missing = [engine for engine in selected if engine not in _SUPPORTED_ENGINES or not engines.get(engine)]
    if missing:
        raise ContractError("能力路由选择的本地工具不可用: " + ", ".join(missing))
    return route


def require_independent_oracle_execution(run_dir: Path) -> None:
    """要求高风险题在科学红队前实际运行独立 oracle。

    路由的独立能力声明只能说明计划合理，不能替代已执行的独立实现。对于
    ``alternative_formulation``，oracle 可以与生产使用同一运行时，但仍必须以
    单独源码和 ``independent-oracle`` 结果记录保存；对于替代运行时/语言，
    源码扩展名还必须与路由选择的引擎一致。

    Args:
        run_dir: 当前 v3 运行目录。

    Raises:
        ContractError: 高风险题缺少真实、可追溯或运行时不匹配的独立 oracle。
    """
    route = require_capability_route(run_dir)
    if not (set(route["problem_families"]) & _ORACLE_FAMILIES):
        return
    toolchain = route["toolchain"]
    expected_engine = toolchain["independent_engine"] or toolchain["production_engine"]
    expected_suffix = _ENGINE_SUFFIXES[expected_engine]
    results = read_result_index(run_dir)["results"]
    candidates = [
        result
        for result in results
        if result["kind"] == "independent-oracle"
        and result["execution_mode"] == "production"
        and result["execution_valid"]
    ]
    if not candidates:
        raise ContractError("几何/机理题在科学红队前必须实际运行 independent-oracle")

    # 同一脚本换一种结果标签仍是同源实现，不能承担独立 oracle 的职责。
    production_sources = {
        result["source_script"]
        for result in results
        if result["kind"] != "independent-oracle"
        and result["execution_mode"] == "production"
        and result["execution_valid"]
        and isinstance(result.get("source_script"), str)
    }
    for result in candidates:
        source_script = result.get("source_script")
        if (
            isinstance(source_script, str)
            and source_script in result["input_hashes"]
            and Path(source_script).suffix.casefold() == expected_suffix
            and source_script not in production_sources
        ):
            return
    raise ContractError(
        "independent-oracle 缺少未与生产求解复用、且与能力路由一致的源码: "
        f"需要 {expected_engine} ({expected_suffix})"
    )
