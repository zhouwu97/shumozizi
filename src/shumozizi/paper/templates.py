"""选择、实例化并复验 v3 竞赛论文模板。"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_tree
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.simple.state import read_simple_state, utc_now

MANIFEST_PATH = Path("paper/template_manifest.json")
_COMPETITION_MAP = {
    "cumcm": ("zh", "cumcm"),
    "national": ("zh", "cumcm"),
    "全国大学生数学建模": ("zh", "cumcm"),
    "全国": ("zh", "cumcm"),
    "国赛": ("zh", "cumcm"),
    "mcm": ("en", "mcm"),
    "icm": ("en", "mcm"),
    "comap": ("en", "mcm"),
    "apmcm": ("en", "apmcm"),
}


def _schema() -> dict[str, Any]:
    """读取论文模板选择清单 Schema。"""
    root = resolve_repo_root(Path(__file__))
    return load_json(root / "schemas" / "paper_template_manifest.schema.json")


def _require_schema(payload: dict[str, Any]) -> None:
    """校验模板选择清单的结构。"""
    validator = Draft202012Validator(_schema(), format_checker=FormatChecker())
    errors = [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    ]
    if errors:
        raise ContractError("; ".join(errors))


def _template_base(competition: str, language: str) -> str:
    """将已识别竞赛映射为仓内完整写作 Skill 的模板键。"""
    normalized = competition.strip().casefold()
    for marker, mapped in _COMPETITION_MAP.items():
        if marker in normalized:
            if mapped[0] != language:
                raise ContractError("竞赛类型与论文语言不匹配，请显式确认语言")
            return mapped[1]
    root = resolve_repo_root(Path(__file__)) / "skills" / "5writing" / "templates" / language
    if (root / normalized).is_dir():
        return normalized
    raise ContractError("未识别比赛类型，不能静默回退 default；请指定已有模板键或补充映射")


def _source_dir(language: str, base: str, engine: str) -> tuple[str, Path]:
    """解析模板 ID 与必须存在的入口文件。"""
    suffix = "" if engine == "typst" else "-latex"
    template_id = f"{language}/{base}{suffix}"
    root = resolve_repo_root(Path(__file__))
    source = root / "skills" / "5writing" / "templates" / language / f"{base}{suffix}"
    entrypoint = source / ("main.typ" if engine == "typst" else "main.tex")
    if not entrypoint.is_file():
        raise ContractError(f"完整写作 Skill 缺少匹配模板入口: {template_id}")
    return template_id, source


def select_paper_template(
    run_dir: Path,
    *,
    language: str,
    engine: str,
    selection_reason: str,
) -> dict[str, Any]:
    """选择一个与比赛、语言和引擎匹配的完整模板，不复制文件。

    Args:
        run_dir: v3 运行目录。
        language: ``zh`` 或 ``en``。
        engine: ``typst`` 或 ``latex``。
        selection_reason: 对比赛与模板匹配的可审计理由。

    Returns:
        已保存的模板选择清单。
    """
    state = read_simple_state(run_dir)
    if language not in {"zh", "en"} or engine not in {"typst", "latex"}:
        raise ContractError("论文语言必须为 zh/en，排版引擎必须为 typst/latex")
    if not state["competition"].strip():
        raise ContractError("未声明 competition，不能选择论文模板")
    base = _template_base(state["competition"], language)
    template_id, source = _source_dir(language, base, engine)
    root = resolve_repo_root(Path(__file__))
    payload = {
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "competition": state["competition"],
        "language": language,
        "engine": engine,
        "template_id": template_id,
        "source_path": source.relative_to(root).as_posix(),
        "source_sha256": sha256_tree(source),
        "fallback_used": False,
        "selection_reason": selection_reason,
        "created_at": utc_now(),
    }
    _require_schema(payload)
    atomic_json(run_dir / MANIFEST_PATH, payload)
    return payload


def materialize_selected_template(run_dir: Path) -> dict[str, Any]:
    """将选择的完整模板复制到空白论文入口，拒绝覆盖已有正文。

    ``paper/sections`` 是运行目录骨架，不视为正文模板冲突；其他同名模板文件
    已存在时必须由写作任务显式处理，避免覆盖用户的论文内容。
    """
    manifest = read_template_manifest(run_dir)
    root = resolve_repo_root(Path(__file__))
    source = root / manifest["source_path"]
    paper_dir = run_dir / "paper"
    entry_name = "main.typ" if manifest["engine"] == "typst" else "main.tex"
    if (paper_dir / entry_name).exists():
        raise ContractError(f"论文入口已存在，拒绝覆盖: paper/{entry_name}")
    for item in source.iterdir():
        target = paper_dir / item.name
        if target.exists() and item.name != "sections":
            raise ContractError(f"模板目标已存在，拒绝覆盖: paper/{item.name}")
    for item in source.iterdir():
        target = paper_dir / item.name
        if item.is_dir():
            if item.name == "sections":
                target.mkdir(parents=True, exist_ok=True)
                for child in item.iterdir():
                    child_target = target / child.name
                    if child_target.exists():
                        raise ContractError(f"模板章节已存在，拒绝覆盖: {child_target.name}")
                    shutil.copytree(child, child_target) if child.is_dir() else shutil.copy2(child, child_target)
            else:
                shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
    return read_template_manifest(run_dir)


def read_template_manifest(run_dir: Path) -> dict[str, Any]:
    """读取并验证模板来源未变化的清单。"""
    manifest_path = run_dir / MANIFEST_PATH
    if not manifest_path.is_file():
        raise ContractError("缺少论文模板清单 paper/template_manifest.json")
    payload = load_json(manifest_path)
    _require_schema(payload)
    state = read_simple_state(run_dir)
    if payload["run_id"] != state["run_id"] or payload["competition"] != state["competition"]:
        raise ContractError("论文模板清单与当前运行不一致")
    root = resolve_repo_root(Path(__file__))
    source = root / payload["source_path"]
    if not source.is_dir() or sha256_tree(source) != payload["source_sha256"]:
        raise ContractError("论文模板来源缺失或已漂移")
    expected_id, expected_source = _source_dir(
        payload["language"], _template_base(state["competition"], payload["language"]), payload["engine"]
    )
    if payload["template_id"] != expected_id or source.resolve() != expected_source.resolve():
        raise ContractError("论文模板与比赛类型或排版引擎不匹配")
    return payload


def require_materialized_template(run_dir: Path) -> dict[str, Any]:
    """确保完整写作模板已经选择、未漂移且存在当前引擎入口。"""
    manifest = read_template_manifest(run_dir)
    entry_name = "main.typ" if manifest["engine"] == "typst" else "main.tex"
    entry = run_dir / "paper" / entry_name
    if not entry.is_file() or entry.stat().st_size == 0:
        raise ContractError("未实例化完整写作模板的论文入口")
    return manifest
