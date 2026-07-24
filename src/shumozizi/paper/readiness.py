"""编译前轻量硬门：确认论证地图、当前结果、当前图表和源码策略真实绑定。

不检查字数、句数、页数、关键词密度——只检查"是否具备最小编译前提"。

此模块是硬门核心，由 ``shumozizi.paper.compiler.compile_paper`` 在启动编译器之前
调用；``scripts/paper/check_paper_readiness.py`` 只是它的薄 CLI 包装。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from shumozizi.core.io import (
    ContractError,
    json_bytes,
    load_json,
    sha256_bytes,
    sha256_file,
)
from shumozizi.core.schema import validate_document
from shumozizi.simple.capabilities import ROUTE_PATH
from shumozizi.simple.critical_claims import CRITICAL_CLAIMS_PATH, read_critical_claims
from shumozizi.simple.figures import verify_current_figure_files
from shumozizi.simple.method_profile import METHOD_PROFILE_PATH
from shumozizi.simple.objective_semantics import objective_semantics_digest
from shumozizi.simple.quality import quality_allows_paper
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import read_simple_state

_APPENDIX_MODES = {"pdf", "attachment", "both"}


def _argument_map_path(run_dir: Path) -> Path:
    """返回生产模式论证地图路径（只认结构化 argument_map.json）。"""
    return run_dir / "paper" / "argument_map.json"


def _load_argument_map(run_dir: Path) -> dict[str, Any] | None:
    """读取论证地图；不存在或不可解析返回 None。"""
    path = _argument_map_path(run_dir)
    if not path.is_file() or path.stat().st_size == 0:
        return None
    try:
        return load_json(path)
    except (OSError, ValueError):
        return None


def _question_ids_from_state(run_dir: Path) -> list[str]:
    """读取必答问题列表。"""
    state = read_simple_state(run_dir)
    return list(state["required_questions"])


def _current_production_results(run_dir: Path) -> dict[str, dict[str, Any]]:
    """返回所有可作为论文事实的 current production 结果。"""
    index = read_result_index(run_dir)
    allowed: dict[str, dict[str, Any]] = {}
    for result in index["results"]:
        if result.get("status") != "current":
            continue
        if result.get("execution_mode") != "production":
            continue
        if not quality_allows_paper(run_dir, result["result_id"]):
            continue
        allowed[result["result_id"]] = result
    return allowed


def _tree_digest(root: Path, *, exclude_names: set[str] | None = None) -> str:
    """计算目录内路径集合和文件内容的稳定摘要。"""
    digest = hashlib.sha256()
    if root.is_dir():
        excluded = exclude_names or set()
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            if path.name in excluded:
                continue
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def argument_map_bindings(run_dir: Path) -> dict[str, str]:
    """重新计算当前论证地图必须绑定的全部运行事实。"""
    results = _current_production_results(run_dir)
    accepted = [results[key] for key in sorted(results)]
    return {
        "capability_route_sha256": sha256_file(run_dir / ROUTE_PATH),
        "method_profile_sha256": sha256_file(run_dir / METHOD_PROFILE_PATH),
        "critical_claims_sha256": sha256_file(run_dir / CRITICAL_CLAIMS_PATH),
        "objective_semantics_digest": objective_semantics_digest(run_dir),
        "accepted_results_digest": sha256_bytes(json_bytes(accepted)),
        "claim_evidence_digest": _tree_digest(
            run_dir / "claims", exclude_names={"ARGUMENT_MAP.json"}
        ),
        "figure_index_sha256": sha256_file(run_dir / "figures" / "index.json"),
    }


def _source_appendix_strategy_clear(run_dir: Path) -> bool:
    """确认 content_blueprint.json 已记录非空源码附录策略。

    仅有 source_code_appendix 键但值为 null/空不算有策略；必须给出 mode 与
    included_roles，说明哪些源码进入论文附录。
    """
    blueprint_path = run_dir / "paper" / "content_blueprint.json"
    if not blueprint_path.is_file():
        return False
    try:
        blueprint = load_json(blueprint_path)
    except (OSError, ValueError):
        return False
    appendix = blueprint.get("source_code_appendix")
    if isinstance(appendix, list):
        return bool(appendix) and all(
            isinstance(item, dict)
            and isinstance(item.get("source_path"), str)
            and isinstance(item.get("sha256"), str)
            for item in appendix
        )
    if not isinstance(appendix, dict):
        return False
    if appendix.get("mode") not in _APPENDIX_MODES:
        return False
    roles = appendix.get("included_roles")
    return isinstance(roles, list) and bool(roles)


def _current_figure_ids(run_dir: Path) -> tuple[set[str], str | None]:
    """返回已真实生成、通过校验的当前图 ID 集合。

    只信任 verify_current_figure_files（校验 status=current、源结果 current、
    文件存在与哈希、图 QA）；figure_plan.json 仅表达计划，不计入。
    """
    try:
        verification = verify_current_figure_files(run_dir)
    except (ContractError, OSError, KeyError, ValueError) as exc:
        return set(), f"当前图校验失败: {exc}"
    if not verification["success"]:
        messages = "；".join(
            item.get("message", "") for item in verification.get("errors", [])
        )
        return set(), f"存在无效的当前图，不能作为论文图: {messages}"
    return set(verification.get("checked_figure_ids", [])), None


def _validate_readiness(run_dir: Path) -> list[str]:
    """执行所有轻量检查，返回阻断原因列表。"""
    errors: list[str] = []

    # 1. 论证大纲：生产模式只接受结构化 argument_map.json，并按 schema 校验
    arg_map = _load_argument_map(run_dir)
    if arg_map is None:
        errors.append(
            "缺少 paper/argument_map.json（生产模式只接受结构化论证地图，"
            "Markdown 提纲不能解锁编译）"
        )
        return errors  # 无论证地图，后续覆盖/图表检查无从谈起

    schema_errors = validate_document(arg_map, "argument_map")
    if schema_errors:
        errors.append("argument_map.json 不符合 schema: " + "；".join(schema_errors))
        return errors
    if arg_map.get("schema_version") != "3.0":
        errors.append("生产论文只接受 argument_map 3.0；2.0 仅供历史只读兼容")
        return errors
    if arg_map.get("status") != "current":
        errors.append(
            "argument_map 已失效（status=superseded），必须根据当前证据重新生成"
        )
        return errors
    if arg_map.get("run_id") != run_dir.name:
        errors.append("argument_map run_id 与当前运行不一致")
    try:
        expected_bindings = argument_map_bindings(run_dir)
    except (ContractError, OSError, KeyError, ValueError) as exc:
        errors.append(f"无法重算 argument_map 绑定: {exc}")
        return errors
    for field, expected in expected_bindings.items():
        if arg_map.get(field) != expected:
            errors.append(f"argument_map 绑定已失效: {field}")

    claims = arg_map.get("claims", [])
    if not claims:
        errors.append("argument_map.json 存在但 claims 为空")
        return errors

    # 2. 必答问题覆盖
    required = _question_ids_from_state(run_dir)
    covered = {
        claim["question_id"]
        for claim in claims
        if isinstance(claim.get("question_id"), str)
    }
    missing_questions = sorted(set(required) - covered)
    if missing_questions:
        errors.append(f"argument_map 缺少必答问题: {', '.join(missing_questions)}")

    # 3. 每个 claim 的 result_ids 必须绑定当前 production 结果
    allowed_results = _current_production_results(run_dir)
    critical_claims = {
        item["claim_id"]: item for item in read_critical_claims(run_dir)["claims"]
    }
    for claim in claims:
        claim_id = claim.get("claim_id", "<未命名>")
        critical = critical_claims.get(claim_id)
        if critical is None or critical.get("question_id") != claim.get("question_id"):
            errors.append(f"论证主张 {claim_id} 未绑定当前同问 critical claim")
        result_ids = claim.get("result_ids", [])
        if not result_ids:
            errors.append(f"主张 {claim_id} 未绑定任何 result_id")
            continue
        stale = [rid for rid in result_ids if rid not in allowed_results]
        if stale:
            errors.append(
                f"主张 {claim_id} 绑定了非当前/不可写入论文的结果: "
                f"{', '.join(stale)}"
            )
        for result_id in result_ids:
            result = allowed_results.get(result_id)
            if result is None:
                continue
            question_id = claim.get("question_id")
            if result.get("question_id") != question_id and not (
                result.get("dependency_scope") in {"shared", "global"}
                and question_id in result.get("affected_question_ids", [])
            ):
                errors.append(f"主张 {claim_id} 不能由其他问题结果 {result_id} 背书")

    # 4. 图表：claim 引用的 figure_ids 必须是已真实生成的当前图
    #    只有当确有主张引用图时才校验当前图，避免无图论文被图索引缺失误伤。
    required_figures: set[str] = set()
    for claim in claims:
        for figure_id in claim.get("figure_ids", []):
            if isinstance(figure_id, str) and figure_id.strip():
                required_figures.add(figure_id)
    if required_figures:
        current_figures, figure_error = _current_figure_ids(run_dir)
        if figure_error:
            errors.append(figure_error)
        else:
            missing_figures = sorted(required_figures - current_figures)
            if missing_figures:
                errors.append(
                    "主张引用了尚未生成的图表（仅 figure_plan 不算已生成）: "
                    + ", ".join(missing_figures)
                )
        figure_index = load_json(run_dir / "figures" / "index.json")
        current_figure_map = {
            item["figure_id"]: item
            for item in figure_index.get("figures", [])
            if item.get("status") == "current"
            and item.get("figure_stage", "publication") == "publication"
        }
        for claim in claims:
            for figure_id in claim.get("figure_ids", []):
                figure = current_figure_map.get(figure_id)
                if figure is not None and figure.get("question_id") not in {
                    None,
                    claim.get("question_id"),
                }:
                    errors.append(
                        f"主张 {claim.get('claim_id')} 不能引用其他问题图 {figure_id}"
                    )

    # 5. 源码附录策略
    if not _source_appendix_strategy_clear(run_dir):
        errors.append(
            "缺少 paper/content_blueprint.json 或 source_code_appendix 策略为空"
            "（需给出 mode 与非空 included_roles）"
        )

    return errors


def check_paper_readiness(run_dir: Path) -> dict[str, Any]:
    """返回就绪检查结果，不抛出异常。"""
    run_dir = run_dir.resolve()
    errors = _validate_readiness(run_dir)
    return {
        "ready": not errors,
        "errors": errors,
        "run_dir": str(run_dir),
    }


def require_paper_readiness(run_dir: Path) -> None:
    """编译前硬门：任一项未满足即阻断。

    Args:
        run_dir: 当前 v3 运行目录。

    Raises:
        ContractError: 最小编译前提未满足。
    """
    status = check_paper_readiness(run_dir)
    if not status["ready"]:
        raise ContractError(
            "论文编译前提未满足，请在编译前修复:\n- " + "\n- ".join(status["errors"])
        )
