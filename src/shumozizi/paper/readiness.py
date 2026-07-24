"""编译前轻量硬门：确认论证大纲存在、关键主张绑定当前结果、图表已生成、
MATLAB 源码与执行齐备、源码附录策略明确。

不检查字数、句数、页数、关键词密度——只检查"是否具备最小编译前提"。

此模块是硬门核心，由 ``shumozizi.paper.compiler.compile_paper`` 在启动编译器之前
调用；``scripts/paper/check_paper_readiness.py`` 只是它的薄 CLI 包装。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, load_json
from shumozizi.core.schema import validate_document
from shumozizi.simple.capabilities import require_capability_route
from shumozizi.simple.figures import verify_current_figure_files
from shumozizi.simple.quality import quality_allows_paper
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import read_simple_state

# MATLAB/Octave 工作脚本目录：与 mathmodel-matlab skill 一致（编译发生在 paper
# 阶段，source/ 提交包此时尚不存在，因此不能查 source/matlab/）。
_MATLAB_WORK_DIR = ("code", "matlab")
_MATLAB_ENGINES = {"matlab", "octave"}
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


def _current_production_result_ids(run_dir: Path) -> set[str]:
    """返回所有可作为论文事实的 current production 结果 ID。"""
    index = read_result_index(run_dir)
    allowed: set[str] = set()
    for result in index["results"]:
        if result.get("status") != "current":
            continue
        if result.get("execution_mode") != "production":
            continue
        if not quality_allows_paper(run_dir, result["result_id"]):
            continue
        allowed.add(result["result_id"])
    return allowed


def _matlab_required(run_dir: Path) -> bool:
    """判断当前能力路由是否要求 MATLAB/Octave 参与。"""
    try:
        route = require_capability_route(run_dir)
    except ContractError:
        return False
    toolchain = route["toolchain"]
    selected = {
        toolchain.get("production_engine"),
        toolchain.get("independent_engine"),
    }
    return bool(selected & _MATLAB_ENGINES)


def _has_matlab_source_and_execution(run_dir: Path) -> bool:
    """确认 code/matlab/ 有非空 .m 文件，且存在对应的 MATLAB/Octave 执行。

    只有真实登记、执行有效的 .m 结果才算"执行收据"，而非 rglob 到任意文件。
    """
    matlab_dir = run_dir.joinpath(*_MATLAB_WORK_DIR)
    if not matlab_dir.is_dir():
        return False
    has_nonempty_m = any(
        script.is_file() and script.stat().st_size > 0
        for script in matlab_dir.rglob("*.m")
    )
    if not has_nonempty_m:
        return False
    # 要求结果索引中存在由 code/matlab/ 脚本产生的有效执行（执行收据）
    try:
        index = read_result_index(run_dir)
    except ContractError:
        return False
    matlab_prefix = "/".join(_MATLAB_WORK_DIR) + "/"
    for result in index["results"]:
        source_script = result.get("source_script", "")
        if (
            isinstance(source_script, str)
            and source_script.startswith(matlab_prefix)
            and source_script.endswith(".m")
            and result.get("execution_valid")
        ):
            return True
    return False


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
    allowed_result_ids = _current_production_result_ids(run_dir)
    for claim in claims:
        claim_id = claim.get("claim_id", "<未命名>")
        result_ids = claim.get("result_ids", [])
        if not result_ids:
            errors.append(f"主张 {claim_id} 未绑定任何 result_id")
            continue
        stale = [rid for rid in result_ids if rid not in allowed_result_ids]
        if stale:
            errors.append(
                f"主张 {claim_id} 绑定了非当前/不可写入论文的结果: "
                f"{', '.join(stale)}"
            )

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

    # 5. MATLAB 路由但缺少 code/matlab/ 源码或执行收据
    if _matlab_required(run_dir) and not _has_matlab_source_and_execution(run_dir):
        errors.append(
            "能力路由选择了 MATLAB/Octave，但 code/matlab/ 缺少非空 .m 源码"
            "或缺少对应的有效执行收据"
        )

    # 6. 源码附录策略
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

