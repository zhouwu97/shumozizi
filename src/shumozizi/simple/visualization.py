"""管理 v3 图表叙事合同，避免只生成无解释力的结果条形图。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import ContractError, atomic_json, load_json, resolve_inside, sha256_file
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.simple.capabilities import require_capability_route
from shumozizi.simple.quality import quality_allows_paper
from shumozizi.simple.state import read_simple_state, utc_now
from tools.qa.figqa import audit_figure

PLAN_PATH = Path("state/visualization-plan.json")
_FAMILY_ROLES = {
    "geometry_kinematics": {"spatial_scene", "geometric_boundary"},
    "optimization": {"optimization_convergence", "optimization_diagnostic"},
    "mechanism_dynamics": {"state_or_field"},
    "network_system": {"network_topology_or_flow"},
    "prediction_statistical": {"fit_residual_or_uncertainty"},
    "evaluation_ranking": {"sensitivity_or_rank_stability"},
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


def required_visual_roles(run_dir: Path) -> set[str]:
    """从已选能力路线派生本题需要的视觉证据类型。"""
    route = require_capability_route(run_dir)
    state = read_simple_state(run_dir)
    roles = set().union(
        *(_FAMILY_ROLES.get(family, set()) for family in route["problem_families"])
    )
    if len(state["required_questions"]) > 1:
        roles.add("method_roadmap")
    return roles


def _freeze_complete_contract(run_dir: Path, contract: dict[str, Any]) -> None:
    """在写入时冻结完成图的输入、脚本和输出，阻止手填过期哈希。"""
    outputs = contract["outputs"]
    if contract["status"] != "complete":
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


def _require_frozen_complete_contract(run_dir: Path, contract: dict[str, Any]) -> None:
    """复验完成图的输入、脚本与输出仍对应登记时的同一份证据。"""
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


def _require_semantics(run_dir: Path, payload: dict[str, Any], *, final: bool) -> None:
    """检查题型视觉覆盖、事实来源与已完成图的可复验性。"""
    state = read_simple_state(run_dir)
    if payload["run_id"] != state["run_id"]:
        raise ContractError("图表叙事计划 run_id 与当前运行不一致")
    if payload["state_revision"] > state["revision"]:
        raise ContractError("图表叙事计划不能来自未来状态修订")
    route = require_capability_route(run_dir)
    families = set(route["problem_families"])
    required_roles = required_visual_roles(run_dir)
    contracts = payload["contracts"]
    figure_ids = [item["figure_id"] for item in contracts]
    if len(figure_ids) != len(set(figure_ids)):
        raise ContractError("图表叙事计划存在重复 figure_id")
    role_to_contracts: dict[str, list[dict[str, Any]]] = {}
    for contract in contracts:
        role_to_contracts.setdefault(contract["role"], []).append(contract)
        _require_frozen_complete_contract(run_dir, contract)
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
        if contract["status"] == "waived" and contract["role"] in required_roles:
            raise ContractError(f"题型必需视觉证据不得豁免: {contract['role']}")
        if contract["status"] == "waived" and "waiver_reason" not in contract:
            raise ContractError("豁免图示必须记录原因")
    missing = required_roles - set(role_to_contracts)
    if missing:
        raise ContractError("图表叙事计划缺少题型视觉证据: " + ", ".join(sorted(missing)))
    if "geometry_kinematics" in families and not any(
        contract["rendering_mode"] == "3d"
        for contract in role_to_contracts["spatial_scene"]
    ):
        raise ContractError("几何/运动题的 spatial_scene 必须提供 3d 空间场景图")
    if "optimization" in families:
        for role in ("optimization_convergence", "optimization_diagnostic"):
            if any(
                contract["evidence_scope"] != "search_diagnostic"
                for contract in role_to_contracts[role]
            ):
                raise ContractError(f"优化题的 {role} 必须绑定 search_diagnostic 证据")
    if final:
        incomplete = sorted(
            role
            for role in required_roles
            if not any(item["status"] == "complete" for item in role_to_contracts[role])
        )
        if incomplete:
            raise ContractError("必需视觉证据尚未完成: " + ", ".join(incomplete))


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
        _freeze_complete_contract(run_dir, contract)
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
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "state_revision": state["revision"],
        "contracts": contracts,
        "created_at": utc_now(),
    }
