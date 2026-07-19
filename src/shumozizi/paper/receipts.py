"""验证论文计划和构建回执绑定的生产事实。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, load_json, sha256_file
from shumozizi.core.schema import require_valid
from shumozizi.results.references import verify_referenced_result
from shumozizi.results.sealing import verify_sealed_result


def _repo_root(run_dir: Path) -> Path:
    """按标准 runs/<run_id> 布局解析仓库根目录。"""
    return run_dir.resolve().parents[1]


def _resolve_bound_file(run_dir: Path, path: str) -> Path:
    """解析运行内或仓库内绑定文件，拒绝越界路径。"""
    candidate = Path(path)
    if candidate.is_absolute():
        raise ContractError(f"绑定路径必须为相对路径: {path}")
    for root in (run_dir.resolve(), _repo_root(run_dir)):
        resolved = (root / candidate).resolve()
        if resolved.is_file() and (resolved == root or root in resolved.parents):
            return resolved
    raise ContractError(f"绑定文件不存在: {path}")


def _check_file_binding(run_dir: Path, item: dict[str, str], label: str) -> list[str]:
    """校验单个路径和 SHA-256 绑定。"""
    try:
        path = _resolve_bound_file(run_dir, item["path"])
        if sha256_file(path) != item["sha256"]:
            return [f"{label} 哈希不匹配: {item['path']}"]
    except (ContractError, KeyError) as exc:
        return [f"{label} 无效: {exc}"]
    return []


def verify_paper_build_receipt(
    run_dir: Path,
    *,
    expected_state_revision: int | None = None,
) -> dict[str, Any]:
    """验证论文计划、构建回执及其所有输入输出绑定。"""
    errors: list[str] = []
    plan_path = run_dir / "paper" / "paper_plan.json"
    receipt_path = run_dir / "paper" / "PAPER_BUILD_RECEIPT.json"
    try:
        plan = load_json(plan_path)
        receipt = load_json(receipt_path)
        require_valid(plan, "paper_plan")
        require_valid(receipt, "paper_build_receipt")
        state = load_json(run_dir / "state.json")
        if plan["run_id"] != run_dir.name or receipt["run_id"] != run_dir.name:
            errors.append("论文计划或回执 run_id 与运行目录不一致")
        if receipt["plan_path"] != "paper/paper_plan.json":
            errors.append("论文回执 plan_path 必须为 paper/paper_plan.json")
        if receipt["plan_sha256"] != sha256_file(plan_path):
            errors.append("论文回执未绑定当前 paper_plan.json")
        if expected_state_revision is not None:
            if receipt["state_revision"] != expected_state_revision:
                errors.append("论文构建回执不是指定 state revision 生成")
        elif receipt["state_revision"] > state["revision"]:
            errors.append("论文构建回执来自未来 state revision")
        if receipt["final_pdf_path"] != plan["final_pdf_path"]:
            errors.append("论文回执 final_pdf_path 与计划不一致")
        final_pdf = _resolve_bound_file(run_dir, receipt["final_pdf_path"])
        if final_pdf.suffix.lower() != ".pdf":
            errors.append("final_pdf_path 必须指向 PDF")
        elif sha256_file(final_pdf) != receipt["final_pdf_sha256"]:
            errors.append("论文回执未绑定当前最终 PDF")
        bindings = plan["bindings"]
        for key, value in bindings.items():
            items = value if key in {"section_files", "figures_used"} else [value]
            for index, item in enumerate(items):
                errors.extend(_check_file_binding(run_dir, item, f"论文绑定 {key}[{index}]"))
        errors.extend(_verify_accepted_result_bindings(run_dir, bindings["result_registry"]))
    except (ContractError, KeyError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors, "plan_path": str(plan_path), "receipt_path": str(receipt_path)}


def _verify_accepted_result_bindings(run_dir: Path, registry_binding: dict[str, str]) -> list[str]:
    """确保计划引用的结果注册表只把真实 accepted 结果带入论文。"""
    errors: list[str] = []
    try:
        registry_path = _resolve_bound_file(run_dir, registry_binding["path"])
        registry = load_json(registry_path)
        for item in registry.get("results", []):
            if item.get("status") == "accepted":
                verification = verify_sealed_result(run_dir, item["result_id"])
                errors.extend(f"结果 {item['result_id']}: {message}" for message in verification["errors"])
                if item.get("paper_allowed") is not True:
                    errors.append(f"accepted 结果未允许写入论文: {item['result_id']}")
    except (ContractError, KeyError) as exc:
        errors.append(f"结果注册表绑定无效: {exc}")
    return errors


def verify_figure_receipts(run_dir: Path) -> dict[str, Any]:
    """验证图表计划及每张图的 accepted 结果、数据、脚本和输出哈希。"""
    errors: list[str] = []
    plan_path = run_dir / "figures" / "FIGURE_PLAN.json"
    try:
        plan = load_json(plan_path)
        require_valid(plan, "figure_plan")
        if plan["run_id"] != run_dir.name:
            errors.append("图表计划 run_id 与运行目录不一致")
        for item in plan["figures"]:
            figure_id = item["figure_id"]
            receipt_path = run_dir / "figures" / f"{figure_id}.receipt.json"
            receipt = load_json(receipt_path)
            require_valid(receipt, "figure_receipt")
            if receipt["run_id"] != run_dir.name or receipt["figure_id"] != figure_id:
                errors.append(f"图表回执身份不一致: {figure_id}")
            for key in ("data_files", "outputs"):
                for index, binding in enumerate(receipt[key]):
                    errors.extend(_check_file_binding(run_dir, binding, f"图表 {figure_id}.{key}[{index}]"))
            errors.extend(_check_file_binding(run_dir, receipt["script"], f"图表 {figure_id}.script"))
            registry = load_json(run_dir / "results" / "result_registry.json")
            require_valid(registry, "result_registry")
            for result_id in receipt["accepted_result_ids"]:
                errors.extend(
                    f"图表 {figure_id}: {message}"
                    for message in verify_referenced_result(
                        run_dir,
                        registry,
                        result_id,
                        question_id=receipt["question_id"],
                    )
                )
    except (ContractError, KeyError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors, "plan_path": str(plan_path)}


def verify_production_receipts(
    run_dir: Path,
    *,
    expected_state_revision: int | None = None,
) -> dict[str, Any]:
    """汇总论文和图表生产回执校验，供状态门调用。"""
    paper = verify_paper_build_receipt(
        run_dir,
        expected_state_revision=expected_state_revision,
    )
    figures = verify_figure_receipts(run_dir)
    return {"valid": paper["valid"] and figures["valid"], "errors": [*paper["errors"], *figures["errors"]], "paper": paper, "figures": figures}
