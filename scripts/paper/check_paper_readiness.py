"""编译前轻量硬门：确认论证大纲存在、关键主张有证据、源码附录策略明确。

不检查字数、句数、页数、关键词密度——只检查"是否具备最小编译前提"。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, load_json
from shumozizi.simple.capabilities import require_capability_route
from shumozizi.simple.quality import quality_allows_paper
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import read_simple_state

_EXIT_OK = 0
_EXIT_BLOCKED = 1


def _find_argument_map(run_dir: Path) -> Path | None:
    """返回论文论证地图路径（优先 argument_map.json，其次 argument-outline.md）。"""
    candidates = [
        run_dir / "paper" / "argument_map.json",
        run_dir / "paper" / "argument-outline.md",
    ]
    for candidate in candidates:
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def _question_ids_from_state(run_dir: Path) -> list[str]:
    """读取必答问题列表。"""
    state = read_simple_state(run_dir)
    return list(state["required_questions"])


def _current_production_results(run_dir: Path) -> dict[str, list[str]]:
    """返回每道必答问题的当前 production 结果 ID。"""
    index = read_result_index(run_dir)
    by_question: dict[str, list[str]] = {}
    for result in index["results"]:
        if result.get("status") != "current":
            continue
        if result.get("execution_mode") != "production":
            continue
        if not quality_allows_paper(run_dir, result["result_id"]):
            continue
        question_id = result["question_id"]
        by_question.setdefault(question_id, []).append(result["result_id"])
    return by_question


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
    return bool(selected & {"matlab", "octave"})


def _has_matlab_sources(run_dir: Path) -> bool:
    """确认 source/matlab/ 目录存在非空 .m 文件。"""
    matlab_dir = run_dir / "source" / "matlab"
    if not matlab_dir.is_dir():
        return False
    return any(matlab_dir.rglob("*.m"))


def _source_appendix_strategy_clear(run_dir: Path) -> bool:
    """确认 content_blueprint.json 已记录源码附录策略。"""
    blueprint_path = run_dir / "paper" / "content_blueprint.json"
    if not blueprint_path.is_file():
        return False
    try:
        blueprint = load_json(blueprint_path)
    except (OSError, ValueError):
        return False
    # 只要蓝图存在并记录了 source_code_appendix，无论是否为空都视为有策略
    return "source_code_appendix" in blueprint


def _required_figures_present(run_dir: Path) -> tuple[bool, list[str]]:
    """检查 argument_map 中引用的图表是否已在 figure_plan 或 figures/ 目录中。

    宽松策略：argument_map 列出 figure_ids，figure_plan 或 figures/index.json
    列出已生成的图。只报告缺失，不要求一一对应（AI 可在写作阶段调整）。
    """
    map_path = _find_argument_map(run_dir)
    if map_path is None or map_path.suffix != ".json":
        return True, []

    try:
        arg_map = load_json(map_path)
    except (OSError, ValueError):
        return True, []

    required_ids: set[str] = set()
    for claim in arg_map.get("claims", []):
        for figure_id in claim.get("figure_ids", []):
            if isinstance(figure_id, str) and figure_id.strip():
                required_ids.add(figure_id)

    if not required_ids:
        return True, []

    # 从 figure_plan 或 figures/index.json 收集实际存在的图
    actual_ids: set[str] = set()

    plan_path = run_dir / "paper" / "figure_plan.json"
    if plan_path.is_file():
        try:
            plan = load_json(plan_path)
            for binding in plan.get("bindings", {}).get("figures_used", []):
                if isinstance(binding, dict):
                    fid = binding.get("figure_id")
                    if isinstance(fid, str):
                        actual_ids.add(fid)
        except (OSError, ValueError):
            pass

    fig_index = run_dir / "figures" / "index.json"
    if fig_index.is_file():
        try:
            fig_idx = load_json(fig_index)
            for item in fig_idx.get("figures", []):
                if isinstance(item, dict):
                    fid = item.get("figure_id")
                    if isinstance(fid, str):
                        actual_ids.add(fid)
        except (OSError, ValueError):
            pass

    missing = sorted(required_ids - actual_ids)
    return not missing, missing


def _validate_readiness(run_dir: Path) -> list[str]:
    """执行所有轻量检查，返回阻断原因列表。"""
    errors: list[str] = []

    # 1. 论证大纲
    outline = _find_argument_map(run_dir)
    if outline is None:
        errors.append("缺少 paper/argument_map.json 或 paper/argument-outline.md")
    elif outline.suffix == ".json":
        try:
            arg_map = load_json(outline)
            if not arg_map.get("claims"):
                errors.append("argument_map.json 存在但 claims 为空")
        except (OSError, ValueError) as exc:
            errors.append(f"argument_map.json 无法解析: {exc}")

    # 2. 必答问题覆盖
    required = _question_ids_from_state(run_dir)
    if required and outline is not None and outline.suffix == ".json":
        try:
            arg_map = load_json(outline)
            covered = {
                claim["question_id"]
                for claim in arg_map.get("claims", [])
                if isinstance(claim.get("question_id"), str)
            }
            missing_questions = sorted(set(required) - covered)
            if missing_questions:
                errors.append(
                    f"argument_map 缺少必答问题: {', '.join(missing_questions)}"
                )
        except (OSError, ValueError):
            pass

    # 3. 每问至少关联一个 current production 结果
    result_map = _current_production_results(run_dir)
    for question_id in required:
        if question_id not in result_map:
            errors.append(
                f"{question_id} 缺少当前 production 结果（status=current 且 quality 允许写入论文）"
            )

    # 4. 必填图表存在
    figures_ok, missing_figures = _required_figures_present(run_dir)
    if not figures_ok:
        errors.append(
            f"主张引用了尚未生成的图表: {', '.join(missing_figures)}"
        )

    # 5. MATLAB 路由但缺少 .m 产物
    if _matlab_required(run_dir) and not _has_matlab_sources(run_dir):
        errors.append(
            "能力路由选择了 MATLAB/Octave，但 source/matlab/ 缺少 .m 源码文件"
        )

    # 6. 源码附录策略
    if not _source_appendix_strategy_clear(run_dir):
        errors.append(
            "缺少 paper/content_blueprint.json 或未记录源码附录策略"
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

    Raises:
        ContractError: 最小编译前提未满足。
    """
    status = check_paper_readiness(run_dir)
    if not status["ready"]:
        raise ContractError(
            "论文编译前提未满足，请在编译前修复:\n- " + "\n- ".join(status["errors"])
        )


def _main() -> int:
    parser = argparse.ArgumentParser(description="编译前轻量硬门检查")
    parser.add_argument("run_dir", type=Path, help="v3 运行目录")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="仅检查不阻断（返回码 0 但报告问题）",
    )
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    if not run_dir.is_dir():
        print(f"运行目录不存在: {run_dir}", file=sys.stderr)
        return _EXIT_BLOCKED

    status = check_paper_readiness(run_dir)

    if status["ready"]:
        print("✅ 论文编译前提检查通过")
        return _EXIT_OK

    print("❌ 论文编译前提未满足:", file=sys.stderr)
    for error in status["errors"]:
        print(f"  - {error}", file=sys.stderr)

    if args.check_only:
        print("\n--check-only 模式：不阻断流程", file=sys.stderr)
        return _EXIT_OK

    return _EXIT_BLOCKED


if __name__ == "__main__":
    sys.exit(_main())
