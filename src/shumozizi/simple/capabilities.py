"""记录并校验 v3 赛题的能力路由与本地工具可用性。"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import ContractError, atomic_json, load_json, resolve_inside, sha256_file
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.simple.results import read_result_index
from shumozizi.simple.source_closure import python_source_closure
from shumozizi.simple.state import read_simple_state, utc_now

ROUTE_PATH = Path("state/capability-route.json")
TOOLING_PATH = Path("state/tooling.json")
KNOWLEDGE_CONSUMPTION_PATH = Path("state/knowledge-consumption.json")
_ORACLE_FAMILIES = {"geometry_kinematics", "mechanism_dynamics"}
_SUPPORTED_ENGINES = ("python", "matlab", "octave")
_ENGINE_SUFFIXES = {"python": ".py", "matlab": ".m", "octave": ".m"}
_PROBE_TIMEOUT_SECONDS = {"python": 12, "octave": 20, "matlab": 60}
_PROBE_CACHE: dict[tuple[int, str, ...], dict[str, Any]] = {}
_CURRENT_ROUTE_SCHEMA_VERSION = "1.2"
_ALLOWED_SHARED_ORACLE_UTILITIES = {
    "code/shared/__init__.py",
    "code/shared/json_io.py",
    "code/shared/logging_utils.py",
    "code/shared/numeric_formatting.py",
}


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


def _digest_text(value: str) -> str:
    """返回命令输出的稳定摘要，避免把大量环境日志写入运行状态。"""
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _run_probe(command: list[str], *, timeout_seconds: int) -> dict[str, Any]:
    """运行受控工具探测，并把失败显式保留为不可用状态。"""
    cache_key = (timeout_seconds, *command)
    cached = _PROBE_CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        stdout, stderr = completed.stdout, completed.stderr
        result = {
            "command": command,
            "exit_code": completed.returncode,
            "timed_out": False,
            "stdout_sha256": _digest_text(stdout),
            "stderr_sha256": _digest_text(stderr),
            "summary": (stdout or stderr).strip()[:500],
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        timed_out = isinstance(exc, subprocess.TimeoutExpired)
        stdout = (
            exc.stdout.decode("utf-8", errors="replace")
            if isinstance(getattr(exc, "stdout", None), bytes)
            else (getattr(exc, "stdout", None) or "")
        )
        stderr = (
            exc.stderr.decode("utf-8", errors="replace")
            if isinstance(getattr(exc, "stderr", None), bytes)
            else (getattr(exc, "stderr", None) or str(exc))
        )
        result = {
            "command": command,
            "exit_code": None,
            "timed_out": timed_out,
            "stdout_sha256": _digest_text(stdout),
            "stderr_sha256": _digest_text(stderr),
            "summary": stderr.strip()[:500],
        }
    _PROBE_CACHE[cache_key] = dict(result)
    return result


def _engine_probe_command(engine: str, command: str) -> list[str]:
    """构造不会依赖 shell 的最小引擎探测命令。"""
    if engine == "python":
        return [command, "--version"]
    if engine == "matlab":
        return [
            command,
            "-batch",
            "disp(version); assert(exist('fmincon','file') || exist('fmincon','builtin')); disp('fmincon available')",
        ]
    if engine == "octave":
        return [command, "--quiet", "--no-gui", "--eval", "disp(version)"]
    raise ContractError(f"不支持的工具引擎: {engine}")


def detect_local_tooling() -> dict[str, Any]:
    """用最小真实命令探测本机生产与独立验证工具。

    ``which`` 只能说明路径存在，不能说明 MATLAB 许可证、批处理启动或 Octave
    实际可用。这里不安装工具，也不访问网络；每个候选引擎只执行版本级烟雾测试。

    Returns:
        可序列化的工具可用性记录。
    """
    commands = {
        "python": sys.executable or shutil.which("python") or shutil.which("python3"),
        "matlab": shutil.which("matlab"),
        "octave": shutil.which("octave") or shutil.which("octave-cli"),
    }
    engines: list[dict[str, Any]] = []
    for engine, command in commands.items():
        if command is None:
            engines.append(
                {
                    "engine": engine,
                    "available": False,
                    "command": None,
                    "probe": None,
                }
            )
            continue
        probe = _run_probe(
            _engine_probe_command(engine, command),
            timeout_seconds=_PROBE_TIMEOUT_SECONDS[engine],
        )
        engines.append(
            {
                "engine": engine,
                "available": probe["exit_code"] == 0 and not probe["timed_out"],
                "command": command,
                "probe": probe,
            }
        )
    return {"schema_version": "1.1", "checked_at": utc_now(), "engines": engines}


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


def _selected_knowledge_assets(route: dict[str, Any]) -> list[dict[str, str]]:
    """返回当前路由显式选择的本地知识资产。

    当前写入端只接受 v1.2，因此这里不为旧格式猜测资产用途。资产路径和哈希
    已由路由登记阶段冻结；消费收据只证明受控读取发生过，不把文件读取误报为
    数学推理正确。
    """
    assets = route.get("knowledge_assets", [])
    if not isinstance(assets, list):
        raise ContractError("能力路由 knowledge_assets 必须为数组")
    selected: list[dict[str, str]] = []
    seen: set[str] = set()
    for asset in assets:
        if not isinstance(asset, dict):
            raise ContractError("能力路由知识资产必须为对象")
        path = asset.get("path")
        digest = asset.get("sha256")
        if not isinstance(path, str) or not isinstance(digest, str):
            raise ContractError("能力路由知识资产缺少 path 或 sha256")
        if path in seen:
            raise ContractError(f"能力路由重复引用知识资产: {path}")
        seen.add(path)
        selected.append({"path": path, "sha256": digest})
    return selected


def record_knowledge_consumption(run_dir: Path) -> dict[str, Any]:
    """实际读取路由选定的本地知识资产并冻结最小消费收据。

    这个动作刻意不要求模型填写阅读摘要或复述内容。它只保证在实验开始前，
    受控进程逐字节读取了路由选择的本地文件，并将该读操作绑定到路由哈希。

    Args:
        run_dir: 当前 v3 运行目录。

    Returns:
        写入 state/knowledge-consumption.json 的消费收据。

    Raises:
        ContractError: 路由未选择知识资产，或资产在读取时已漂移。
    """
    route = read_capability_route(run_dir)
    assets = _selected_knowledge_assets(route)
    if not assets:
        raise ContractError("当前能力路由未选择本地知识资产，无需登记消费收据")
    route_path = run_dir / ROUTE_PATH
    root = resolve_repo_root(Path(__file__))
    receipts: list[dict[str, Any]] = []
    total_bytes = 0
    for asset in assets:
        source = resolve_inside(root, asset["path"], must_exist=True)
        if not source.is_file():
            raise ContractError(f"知识资产必须是文件: {asset['path']}")
        # 使用真实字节读取而不是只调用 stat/hash 辅助函数，避免把“已登记”误称为“已消费”。
        content = source.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != asset["sha256"]:
            raise ContractError(f"知识资产在读取时已漂移: {asset['path']}")
        total_bytes += len(content)
        receipts.append(
            {
                "path": asset["path"],
                "sha256": digest,
                "bytes_read": len(content),
            }
        )
    payload = {
        "schema_version": "1.0",
        "run_id": read_simple_state(run_dir)["run_id"],
        "route_path": ROUTE_PATH.as_posix(),
        "route_sha256": sha256_file(route_path),
        "reader": {
            "operation": "controlled_binary_read",
            "asset_count": len(receipts),
            "total_bytes_read": total_bytes,
        },
        "assets": receipts,
        "consumed_at": utc_now(),
    }
    _require_schema(payload, "simple_knowledge_consumption.schema.json")
    atomic_json(run_dir / KNOWLEDGE_CONSUMPTION_PATH, payload)
    return payload


def require_knowledge_consumption(
    run_dir: Path, route: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """复验本地知识确由受控读取消费，而非仅在路由中登记。

    Args:
        run_dir: 当前 v3 运行目录。
        route: 已读取的路由；提供它可避免状态机重复读取文件。

    Returns:
        无知识资产时返回 None，否则返回经验证的消费收据。

    Raises:
        ContractError: 缺少、篡改或不匹配的知识消费收据。
    """
    current_route = route or read_capability_route(run_dir)
    expected_assets = _selected_knowledge_assets(current_route)
    if not expected_assets:
        return None
    receipt_path = run_dir / KNOWLEDGE_CONSUMPTION_PATH
    if not receipt_path.is_file():
        raise ContractError("能力路由已选择本地知识资产，进入实验前必须登记实际消费收据")
    receipt = load_json(receipt_path)
    _require_schema(receipt, "simple_knowledge_consumption.schema.json")
    state = read_simple_state(run_dir)
    if receipt["run_id"] != state["run_id"]:
        raise ContractError("知识消费收据 run_id 与当前运行不一致")
    route_path = run_dir / ROUTE_PATH
    if receipt["route_sha256"] != sha256_file(route_path):
        raise ContractError("知识消费收据未绑定当前能力路由")
    actual_assets = receipt["assets"]
    expected_pairs = [(asset["path"], asset["sha256"]) for asset in expected_assets]
    actual_pairs = [(asset["path"], asset["sha256"]) for asset in actual_assets]
    if actual_pairs != expected_pairs:
        raise ContractError("知识消费收据与当前路由选择的资产不一致")
    root = resolve_repo_root(Path(__file__))
    total_bytes = 0
    for asset in actual_assets:
        source = resolve_inside(root, asset["path"], must_exist=True)
        if not source.is_file():
            raise ContractError(f"知识消费收据引用的资产不是文件: {asset['path']}")
        size = source.stat().st_size
        if asset["bytes_read"] != size:
            raise ContractError(f"知识消费收据的读取字节数不一致: {asset['path']}")
        if sha256_file(source) != asset["sha256"]:
            raise ContractError(f"知识消费后资产已漂移: {asset['path']}")
        total_bytes += size
    reader = receipt["reader"]
    if reader["asset_count"] != len(actual_assets) or reader["total_bytes_read"] != total_bytes:
        raise ContractError("知识消费收据的读取统计不一致")
    return receipt


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


def _normalize_current_route(run_dir: Path, payload: dict[str, Any]) -> None:
    """补齐 v1.2 中由运行时负责的路由元数据。

    主对话只应说明当前题实际要用的能力和工具选择。运行标识、时间、工具哈希、
    工具收据和知识资产哈希都可以从当前运行可靠推导，不应成为人工表单负担。
    """
    if payload.get("schema_version") != _CURRENT_ROUTE_SCHEMA_VERSION:
        return
    state = read_simple_state(run_dir)
    payload.setdefault("run_id", state["run_id"])
    payload.setdefault("status", "ready")
    payload.setdefault("created_at", utc_now())
    payload.setdefault("knowledge_assets", [])

    assets = payload.get("knowledge_assets")
    if isinstance(assets, list):
        payload["knowledge_assets"] = [
            {"path": item} if isinstance(item, str) else item for item in assets
        ]

    toolchain = payload.get("toolchain")
    if not isinstance(toolchain, dict):
        return
    toolchain.setdefault("production_engine", "python")
    toolchain.setdefault("independence_strategy", "not_required")
    strategy = toolchain.get("independence_strategy")
    if strategy in {"not_required", "alternative_formulation"}:
        toolchain.setdefault("independent_engine", None)
    toolchain.setdefault("requirements", [])


def _require_route_semantics(run_dir: Path, payload: dict[str, Any]) -> None:
    """检查题型、验证方式、工具链和本地知识资产是否自洽。"""
    state = read_simple_state(run_dir)
    if payload["run_id"] != state["run_id"]:
        raise ContractError("能力路由 run_id 与当前运行不一致")
    families = set(payload["problem_families"])
    verification = payload["verification_capability"]
    toolchain = payload["toolchain"]
    if payload["schema_version"] in {"1.1", _CURRENT_ROUTE_SCHEMA_VERSION}:
        capabilities = payload["capabilities"]
        if not capabilities:
            raise ContractError("能力路由至少要声明一项当前题实际需要的能力")
        if payload["schema_version"] == "1.1" and not any(
            item["mode"] == "required" for item in capabilities
        ):
            raise ContractError("能力路由至少要声明一项当前题实际需要的 required 能力")
        if payload["schema_version"] == "1.1" and any(
            item["mode"] == "optional"
            and (not isinstance(item.get("activation_condition"), str) or not item["activation_condition"].strip())
            for item in capabilities
        ):
            raise ContractError("可选能力必须写明触发条件")
        if "geometry_kinematics" in families:
            visual = payload.get("visual_evidence")
            if not isinstance(visual, dict):
                raise ContractError("几何/运动题必须说明空间结构是否影响核心结论")
        _require_tool_requirement_receipts(toolchain)
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

    if payload.get("schema_version") in {"1.1", _CURRENT_ROUTE_SCHEMA_VERSION}:
        tooling = load_json(tooling_path)
        commands = _read_available_commands(tooling)
        toolchain = payload.get("toolchain")
        if not isinstance(toolchain, dict):
            raise ContractError("能力路由缺少 toolchain")
        requirements = toolchain.get("requirements")
        if not isinstance(requirements, list):
            raise ContractError("当前能力路由必须声明工具 requirements")
        receipts = [_probe_tool_requirement(item, commands) for item in requirements]
        failed = [
            f"{item['engine']}:{item['kind']}:{item['name']}"
            for item in receipts
            if not item["passed"]
        ]
        if failed:
            raise ContractError("能力路由选择的工具/许可证未通过真实烟雾测试: " + ", ".join(failed))
        supplied = toolchain.get("requirement_receipts")
        if supplied not in (None, receipts):
            raise ContractError("工具 requirement_receipts 必须由当前探测生成，不能手工伪造")
        toolchain["requirement_receipts"] = receipts

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
    if not isinstance(tooling, dict) or tooling.get("schema_version") not in {"1.0", "1.1"}:
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
        if tooling["schema_version"] == "1.1":
            probe = record.get("probe")
            if available:
                if not isinstance(probe, dict) or probe.get("exit_code") != 0 or probe.get("timed_out"):
                    raise ContractError(f"工具探测记录缺少成功烟雾测试: {engine}")
        if engine in engines:
            raise ContractError(f"工具探测记录重复引擎: {engine}")
        engines[engine] = available
    return engines


def _read_available_commands(tooling: Any) -> dict[str, str]:
    """读取已通过烟雾测试的实际命令路径。"""
    available = _read_available_engines(tooling)
    commands: dict[str, str] = {}
    for record in tooling["engines"]:
        engine = record["engine"]
        command = record.get("command")
        if available.get(engine) and isinstance(command, str):
            commands[engine] = command
    return commands


def _require_tool_requirement_receipts(toolchain: dict[str, Any]) -> None:
    """检查路由冻结的可选工具需求与实际探测一一对应。"""
    requirements = toolchain.get("requirements")
    receipts = toolchain.get("requirement_receipts")
    if not isinstance(requirements, list) or not isinstance(receipts, list):
        raise ContractError("当前能力路由缺少工具需求或烟雾测试收据")
    expected = {(item["engine"], item["kind"], item["name"]) for item in requirements}
    actual = {
        (item.get("engine"), item.get("kind"), item.get("name"))
        for item in receipts
        if isinstance(item, dict) and item.get("passed") is True
    }
    if actual != expected:
        raise ContractError("工具需求与通过的烟雾测试收据不一致")


def _probe_tool_requirement(requirement: dict[str, Any], commands: dict[str, str]) -> dict[str, Any]:
    """对路线明确选择的函数或许可证执行一次真实查询。"""
    engine, kind, name = requirement["engine"], requirement["kind"], requirement["name"]
    command = commands.get(engine)
    if command is None:
        return {
            "engine": engine,
            "kind": kind,
            "name": name,
            "command": [],
            "passed": False,
            "output_sha256": _digest_text("engine unavailable"),
            "checked_at": utc_now(),
        }
    if engine == "python":
        if kind != "function":
            raise ContractError("Python 路由不支持许可证 requirement")
        expression = (
            "import importlib.util,sys; "
            f"sys.exit(0 if importlib.util.find_spec({name!r}) else 1)"
        )
        probe = _run_probe([command, "-c", expression])
    elif engine == "matlab":
        if kind == "function":
            expression = (
                f"assert(exist('{name}','file') || exist('{name}','builtin')); disp('{name} available');"
            )
        else:
            expression = f"assert(license('test','{name}')); disp('{name} licensed');"
        probe = _run_probe([command, "-batch", expression])
    elif engine == "octave":
        if kind == "license":
            probe = {
                "command": [command, "--quiet", "--no-gui", "--eval", "exit(1)"],
                "exit_code": 1,
                "timed_out": False,
                "stdout_sha256": _digest_text(""),
                "stderr_sha256": _digest_text("Octave does not provide MATLAB license checks"),
                "summary": "Octave does not provide MATLAB license checks",
            }
        else:
            probe = _run_probe(
                [
                    command,
                    "--quiet",
                    "--no-gui",
                    "--eval",
                    f"if (exist('{name}','file') || exist('{name}','builtin')); disp('{name} available'); else; error('missing {name}'); end",
                ]
            )
    else:
        raise ContractError(f"不支持的 requirement 引擎: {engine}")
    output_sha256 = _digest_text(
        f"{probe.get('stdout_sha256')}:{probe.get('stderr_sha256')}:{probe.get('exit_code')}"
    )
    return {
        "engine": engine,
        "kind": kind,
        "name": name,
        "command": probe["command"],
        "passed": probe.get("exit_code") == 0 and not probe.get("timed_out"),
        "output_sha256": output_sha256,
        "checked_at": utc_now(),
    }


def write_capability_route(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """写入已完成路线比较后的能力路由。

    Args:
        run_dir: v3 运行目录。
        payload: 由能力路由 Skill 形成的清单。

    Returns:
        已校验并保存的路由。
    """
    if payload.get("schema_version") != _CURRENT_ROUTE_SCHEMA_VERSION:
        raise ContractError("新建能力路由必须使用 schema_version 1.2；旧版仅供历史读取")
    _normalize_current_route(run_dir, payload)
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
    if route["schema_version"] not in {"1.1", _CURRENT_ROUTE_SCHEMA_VERSION}:
        raise ContractError("历史能力路由不能解锁当前 v3 工作流，请以 1.2 重新登记")
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
    require_knowledge_consumption(run_dir, route)
    return route


def _require_recorded_source_closure(run_dir: Path, result: dict[str, Any]) -> set[str]:
    """复算并核对一次实验登记的本地源码闭包。"""
    source_script = result.get("source_script")
    if not isinstance(source_script, str):
        raise ContractError("独立性检查缺少可定位的源码入口")
    closure = set(python_source_closure(run_dir, source_script))
    missing = closure - set(result["input_hashes"])
    if missing:
        raise ContractError("源码闭包未完整列入输入哈希: " + ", ".join(sorted(missing)))
    for relative in closure:
        path = resolve_inside(run_dir, relative, must_exist=True)
        if sha256_file(path) != result["input_hashes"][relative]:
            raise ContractError(f"源码闭包已漂移: {relative}")
    return closure


def _require_oracle_semantic_receipt(run_dir: Path, result: dict[str, Any]) -> None:
    """要求 oracle 输出声明不同公式并覆盖最小边界反例集。"""
    errors: list[str] = []
    for relative in result["output_files"]:
        if Path(relative).suffix.casefold() != ".json":
            continue
        path = resolve_inside(run_dir, relative, must_exist=True)
        if sha256_file(path) != result["output_hashes"].get(relative):
            errors.append(f"输出已漂移: {relative}")
            continue
        try:
            document = load_json(path)
        except (OSError, ValueError) as exc:
            errors.append(f"JSON 不可读取: {relative}: {exc}")
            continue
        receipt = document.get("oracle_semantics") if isinstance(document, dict) else None
        if not isinstance(receipt, dict):
            errors.append(f"缺少 oracle_semantics: {relative}")
            continue
        try:
            _require_schema(receipt, "oracle_semantic_receipt.schema.json")
        except ContractError as exc:
            errors.append(f"{relative}: {exc}")
            continue
        if receipt["formulation"].strip().casefold() == receipt[
            "production_formulation"
        ].strip().casefold():
            errors.append(f"{relative}: oracle 与生产 formulation 相同")
            continue
        return
    raise ContractError("independent-oracle 语义收据无效: " + "；".join(errors))


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
    production_results = [
        result
        for result in results
        if result["kind"] != "independent-oracle"
        and result["execution_mode"] == "production"
        and result["execution_valid"]
        and isinstance(result.get("source_script"), str)
        and result.get("status") == "current"
    ]
    if not production_results:
        raise ContractError("independent-oracle 缺少可比较的当前生产源码")
    production_sources = {result["source_script"] for result in production_results}
    production_closure: set[str] = set()
    for production in production_results:
        production_closure.update(_require_recorded_source_closure(run_dir, production))
    for result in candidates:
        source_script = result.get("source_script")
        if not isinstance(source_script, str):
            continue
        if Path(source_script).suffix.casefold() != expected_suffix or source_script in production_sources:
            continue
        oracle_closure = _require_recorded_source_closure(run_dir, result)
        shared = (oracle_closure & production_closure) - _ALLOWED_SHARED_ORACLE_UTILITIES
        if shared:
            raise ContractError("independent-oracle 源码闭包共享领域模块: " + ", ".join(sorted(shared)))
        _require_oracle_semantic_receipt(run_dir, result)
        return
    raise ContractError(
        "independent-oracle 缺少未与生产求解复用、且与能力路由一致的源码: "
        f"需要 {expected_engine} ({expected_suffix})"
    )
