"""按修改内容区分科学、论证和纯渲染返修。"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from shumozizi.core.io import ContractError

REVISION_IMPACTS = ("render", "argument", "science")
_SCIENCE_ROOTS = {"problem", "code", "results"}
_SCIENCE_ANALYSIS_NAMES = {
    "MODELING_UNITS.json",
    "OBJECTIVE_CANDIDATES.json",
    "BASELINE_FREEZE.json",
    "LOCAL_ROUTE_SNAPSHOT.json",
    "ROUTE_COMPETITION.md",
    "NEXT_EXPERIMENTS.md",
    "INSIGHTS.md",
}
_ARGUMENT_SUFFIXES = {".tex", ".typ", ".bib", ".md"}
_RENDER_SUFFIXES = {".png", ".pdf", ".svg", ".jpg", ".jpeg", ".webp"}
_INVALIDATION = {
    "science": ["science", "argument", "render"],
    "argument": ["argument", "render"],
    "render": ["render"],
}


def _normalized_path(value: str) -> PurePosixPath:
    """校验并规整运行内相对路径。"""
    if not isinstance(value, str) or not value.strip():
        raise ContractError("revision path 必须是非空相对路径")
    normalized = value.strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise ContractError(f"revision path 必须位于运行目录内: {value}")
    return path


def classify_revision_path(path: str) -> str:
    """返回单个运行文件修改的最小影响层级。

    Args:
        path: 相对当前运行目录的文件路径。

    Returns:
        ``science``、``argument`` 或 ``render``。
    """
    candidate = _normalized_path(path)
    if candidate.parts[:2] == ("code", "figures"):
        return "render"
    if candidate.parts[0] in _SCIENCE_ROOTS:
        return "science"
    if candidate.parts[:2] == ("analysis", "answer_map.json"):
        return "argument"
    if candidate.parts[0] == "analysis" and candidate.name in _SCIENCE_ANALYSIS_NAMES:
        return "science"
    if candidate.parts[0] == "figures":
        if candidate.name == "FIGURE_PLAN.json":
            return "argument"
        return "render"
    if candidate.parts[0] == "paper":
        if candidate.name in {"argument_map.json", "answer-map.json"}:
            return "argument"
        if candidate.suffix.casefold() in _RENDER_SUFFIXES or candidate.parts[1:2] == (
            "submission",
        ):
            return "render"
        if candidate.parts[1:2] == ("generated",):
            return "render"
        if candidate.suffix.casefold() in _ARGUMENT_SUFFIXES or candidate.name.endswith("answer-map.json"):
            return "argument"
    # 未识别的运行元数据不应把科学结论全部打回；按论证层保守复核。
    return "argument"


def classify_revision(paths: list[str]) -> dict[str, Any]:
    """汇总一组修改，并返回需要重新验证的最小层级。

    Args:
        paths: 相对运行目录的修改文件列表。

    Returns:
        逐文件分类、最高影响和所需失效层级。

    Raises:
        ContractError: 路径列表为空或包含越界路径。
    """
    if not paths:
        raise ContractError("revision paths 不能为空")
    classified = [
        {"path": _normalized_path(path).as_posix(), "impact": classify_revision_path(path)}
        for path in paths
    ]
    impact = max(
        (item["impact"] for item in classified),
        key=REVISION_IMPACTS.index,
    )
    return {
        "impact": impact,
        "invalidates": list(_INVALIDATION[impact]),
        "paths": classified,
    }
