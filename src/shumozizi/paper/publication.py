"""定义正式论文的唯一发布入口及其可复验依赖闭包。

作者长篇稿、草稿和冷读输入都属于创作阶段产物；它们不能自动成为提交论文
的事实来源。本模块把最终入口及其真实 ``\\input`` / 图像 / 文献依赖收敛成
一个小接口，供编译、质量门和回执共同使用。
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from pathlib import Path

from shumozizi.core.io import ContractError, atomic_json, load_json, relative_inside, sha256_file
from shumozizi.simple.state import read_simple_state, utc_now

PUBLICATION_SNAPSHOT_PATH = Path("paper/PUBLICATION_SNAPSHOT.json")
_LATEX_REFERENCE_PATTERNS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (
        re.compile(r"\\(?:input|include|subfile)\s*\{([^}]+)\}"),
        ("", ".tex", ".typ"),
    ),
    (
        re.compile(r"\\includegraphics(?:\[[^]]*\])?\s*\{([^}]+)\}"),
        ("", ".pdf", ".png", ".jpg", ".jpeg", ".eps"),
    ),
    (
        re.compile(r"\\(?:addbibresource)\s*\{([^}]+)\}"),
        ("", ".bib"),
    ),
    (
        re.compile(r"\\bibliography\s*\{([^}]+)\}"),
        ("", ".bib"),
    ),
)
_TYPST_REFERENCE_PATTERNS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"#include\s*\(\s*\"([^\"]+)\"\s*\)"), ("", ".typ")),
    (re.compile(r"#image\s*\(\s*\"([^\"]+)\""), ("", ".pdf", ".png", ".jpg", ".jpeg", ".svg")),
    (re.compile(r"#bibliography\s*\(\s*\"([^\"]+)\""), ("", ".bib")),
)


def publication_entrypoint(run_dir: Path) -> Path:
    """返回正式候选稿的唯一入口，不回退到作者长稿。

    Args:
        run_dir: 当前运行目录。

    Returns:
        位于运行目录内、实际用于最终提交的 TeX 或 Typst 入口。

    Raises:
        ContractError: 正式入口不存在或模板清单指向非法位置。
    """
    root = run_dir.resolve()
    imported = root / "paper/imported-author/main.tex"
    if imported.is_file() and (root / "paper/imported-author/receipt.json").is_file():
        return imported

    manifest_path = root / "paper/template_manifest.json"
    if manifest_path.is_file():
        manifest = load_json(manifest_path)
        layout = manifest.get("question_layout")
        relative = layout.get("entrypoint_path") if isinstance(layout, dict) else None
        if isinstance(relative, str) and relative.strip():
            candidate = (root / "paper" / relative).resolve()
            paper_dir = (root / "paper").resolve()
            if candidate != paper_dir and paper_dir not in candidate.parents:
                raise ContractError("模板清单的正式论文入口越过 paper/ 边界")
            if candidate.is_file():
                return candidate

    for name in ("main.tex", "main.typ"):
        candidate = root / "paper" / name
        if candidate.is_file():
            return candidate
    raise ContractError("缺少正式论文入口 paper/main.tex、paper/main.typ 或已接受的外部稿")


def _strip_latex_comments(text: str) -> str:
    """去除未转义的 LaTeX 注释，避免注释中的伪依赖进入闭包。"""
    lines: list[str] = []
    for line in text.splitlines():
        index = 0
        while True:
            index = line.find("%", index)
            if index < 0:
                lines.append(line)
                break
            backslashes = 0
            cursor = index - 1
            while cursor >= 0 and line[cursor] == "\\":
                backslashes += 1
                cursor -= 1
            if backslashes % 2 == 0:
                lines.append(line[:index])
                break
            index += 1
    return "\n".join(lines)


def _resolve_reference(
    root: Path,
    owner: Path,
    raw_reference: str,
    suffixes: Iterable[str],
) -> list[Path]:
    """解析一个源码引用，只返回运行目录内真实存在的文件。"""
    references = [part.strip() for part in raw_reference.split(",") if part.strip()]
    resolved: list[Path] = []
    for reference in references:
        # 宏、URL 和通配符没有可冻结的本地依赖；实际编译器会对必须存在的输入报错。
        if any(token in reference for token in ("#", "\\", "://", "*", "$")):
            continue
        base = Path(reference)
        if base.is_absolute():
            raise ContractError(f"正式论文引用了绝对路径: {reference}")
        candidates: list[Path] = []
        escaped_candidates = 0
        for parent in (owner.parent, root):
            for suffix in suffixes:
                candidate = parent / (reference if not suffix or base.suffix else reference + suffix)
                try:
                    candidate.resolve().relative_to(root)
                except ValueError:
                    # WHY: ``paper/main.tex`` 常以 ``../figures/...`` 引用运行目录
                    # 内的正式图。第二个 root-relative 尝试会自然越界，不能因此
                    # 否定第一个相对当前 TeX 文件、且位于 run 内的合法解析结果。
                    escaped_candidates += 1
                    continue
                candidates.append(candidate)
        found = next((item.resolve() for item in candidates if item.is_file()), None)
        if found is not None and found not in resolved:
            resolved.append(found)
        elif not candidates and escaped_candidates:
            raise ContractError(f"正式论文引用越过运行目录: {reference}")
    return resolved


def _direct_dependencies(root: Path, path: Path) -> list[Path]:
    """解析单个正式源码文件的本地直接依赖。"""
    if path.suffix.casefold() not in {".tex", ".typ"}:
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    patterns = _TYPST_REFERENCE_PATTERNS if path.suffix.casefold() == ".typ" else _LATEX_REFERENCE_PATTERNS
    if path.suffix.casefold() == ".tex":
        text = _strip_latex_comments(text)
    dependencies: list[Path] = []
    for pattern, suffixes in patterns:
        for match in pattern.finditer(text):
            for dependency in _resolve_reference(root, path, match.group(1), suffixes):
                if dependency not in dependencies:
                    dependencies.append(dependency)
    return dependencies


def publication_source_paths(run_dir: Path, *, entrypoint: Path | None = None) -> list[Path]:
    """返回正式入口的递归文件闭包，绝不扫描作者草稿或无关审计文件。"""
    root = run_dir.resolve()
    start = (entrypoint or publication_entrypoint(root)).resolve()
    try:
        start.relative_to(root)
    except ValueError as exc:
        raise ContractError("正式论文入口越过运行目录") from exc
    if not start.is_file():
        raise ContractError(f"正式论文入口不存在: {relative_inside(root, start)}")
    queue = [start]
    visited: set[Path] = set()
    while queue:
        current = queue.pop()
        if current in visited:
            continue
        visited.add(current)
        queue.extend(dependency for dependency in _direct_dependencies(root, current) if dependency not in visited)
    return sorted(visited, key=lambda item: relative_inside(root, item).as_posix())


def publication_source_digest(run_dir: Path, *, entrypoint: Path | None = None) -> str:
    """计算正式入口依赖闭包的稳定摘要。"""
    root = run_dir.resolve()
    digest = hashlib.sha256()
    for path in publication_source_paths(root, entrypoint=entrypoint):
        digest.update(relative_inside(root, path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def publication_text_sources(run_dir: Path) -> list[Path]:
    """返回正式稿闭包中可供正文审核的 TeX/Typst 文件。"""
    return [
        path
        for path in publication_source_paths(run_dir)
        if path.suffix.casefold() in {".tex", ".typ"}
    ]


def freeze_publication_snapshot(run_dir: Path) -> dict[str, object]:
    """冻结当前正式入口及其真实依赖闭包，供后续候选稿复验。

    本函数不会把 ``longform-source`` 复制到最终稿；调用者必须先完成有意识的
    内容整合，避免把作者草稿静默当作提交稿。
    """
    root = run_dir.resolve()
    entrypoint = publication_entrypoint(root)
    paths = publication_source_paths(root, entrypoint=entrypoint)
    payload: dict[str, object] = {
        "schema_name": "publication_snapshot",
        "schema_version": "1.0",
        "run_id": read_simple_state(root)["run_id"],
        "entrypoint_path": relative_inside(root, entrypoint).as_posix(),
        "entrypoint_sha256": sha256_file(entrypoint),
        "source_paths": [
            {
                "path": relative_inside(root, path).as_posix(),
                "sha256": sha256_file(path),
            }
            for path in paths
        ],
        "paper_source_sha256": publication_source_digest(root, entrypoint=entrypoint),
        "frozen_at": utc_now(),
    }
    atomic_json(root / PUBLICATION_SNAPSHOT_PATH, payload)
    return payload


def publication_snapshot_errors(run_dir: Path, *, require_snapshot: bool = False) -> list[str]:
    """复验冻结快照仍对应当前正式入口与依赖闭包。"""
    root = run_dir.resolve()
    path = root / PUBLICATION_SNAPSHOT_PATH
    if not path.is_file():
        return ["缺少正式论文发布快照"] if require_snapshot else []
    try:
        snapshot = load_json(path)
    except ContractError as exc:
        return [f"正式论文发布快照无法读取: {exc}"]
    errors: list[str] = []
    if snapshot.get("run_id") != read_simple_state(root).get("run_id"):
        errors.append("正式论文发布快照 run_id 与当前运行不一致")
        return errors
    try:
        entrypoint = publication_entrypoint(root)
        relative = relative_inside(root, entrypoint).as_posix()
        if snapshot.get("entrypoint_path") != relative:
            errors.append("正式论文入口与冻结发布快照不一致")
        elif snapshot.get("entrypoint_sha256") != sha256_file(entrypoint):
            errors.append("正式论文入口在冻结后已变化")
        current_paths = publication_source_paths(root, entrypoint=entrypoint)
        current_records = [
            {"path": relative_inside(root, item).as_posix(), "sha256": sha256_file(item)}
            for item in current_paths
        ]
        if snapshot.get("source_paths") != current_records:
            errors.append("正式论文依赖闭包在冻结后已变化")
        if snapshot.get("paper_source_sha256") != publication_source_digest(root, entrypoint=entrypoint):
            errors.append("正式论文依赖摘要在冻结后已变化")
    except ContractError as exc:
        errors.append(f"正式论文发布快照无法复验: {exc}")
    return errors


def require_publication_snapshot(run_dir: Path) -> dict[str, object] | None:
    """要求质量合同或作者长稿已显式整合并冻结为正式候选稿。"""
    root = run_dir.resolve()
    has_author_draft = any(
        (root / relative).is_file()
        for relative in ("paper/longform-source.tex", "paper/longform-source.typ")
    )
    # WHY: 新质量合同不能靠删除长稿文件回避“正式入口必须显式冻结”的要求；
    # 历史运行仍仅在确有 Author Pass 长稿时提升该要求，保持迁移兼容。
    from shumozizi.paper.policy import workflow_quality_policy

    require_snapshot = (
        has_author_draft
        or workflow_quality_policy(root) == "competition-quality-v1"
    )
    errors = publication_snapshot_errors(root, require_snapshot=require_snapshot)
    if errors:
        raise ContractError("；".join(errors))
    path = root / PUBLICATION_SNAPSHOT_PATH
    return load_json(path) if path.is_file() else None
