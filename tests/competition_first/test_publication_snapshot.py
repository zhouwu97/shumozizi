"""验证正式论文只从一个可复验的发布快照读取事实。"""

from __future__ import annotations

from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json
from shumozizi.paper.publication import (
    freeze_publication_snapshot,
    publication_snapshot_errors,
    publication_source_digest,
    publication_source_paths,
)
from shumozizi.simple.initialization import initialize_simple_run


def _run_with_split_sources(tmp_path: Path) -> Path:
    """构造作者长稿和正式入口内容不同的最小运行。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "publication-snapshot",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    (run_dir / "paper/sections").mkdir(parents=True, exist_ok=True)
    (run_dir / "paper/main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\input{sections/questions}\n\\end{document}\n",
        encoding="utf-8",
    )
    (run_dir / "paper/sections/questions.tex").write_text(
        "\\section{问题 Q1}\n正式入口中的直接答案。\n",
        encoding="utf-8",
    )
    (run_dir / "paper/longform-source.tex").write_text(
        "\\section{问题 Q1}\n作者长稿中才有的图。"
        "\\includegraphics{figures/current/longform-only.png}\n",
        encoding="utf-8",
    )
    return run_dir


def test_publication_closure_excludes_author_draft_and_unrelated_audit(tmp_path: Path) -> None:
    """最终稿依赖摘要不得被长稿或审计 JSON 污染。"""
    run_dir = _run_with_split_sources(tmp_path)

    paths = publication_source_paths(run_dir)
    relatives = {path.relative_to(run_dir).as_posix() for path in paths}

    assert "paper/main.tex" in relatives
    assert "paper/sections/questions.tex" in relatives
    assert "paper/longform-source.tex" not in relatives
    first_digest = publication_source_digest(run_dir)
    atomic_json(
        run_dir / "paper/CUMCM_LAYOUT_AUDIT.json",
        {"schema_name": "audit", "note": "该文件不属于编译依赖"},
    )
    assert publication_source_digest(run_dir) == first_digest

    (run_dir / "paper/sections/questions.tex").write_text(
        "\\section{问题 Q1}\n正式入口已修改。\n", encoding="utf-8"
    )
    assert publication_source_digest(run_dir) != first_digest


def test_snapshot_detects_actual_entrypoint_drift(tmp_path: Path) -> None:
    """快照必须检测正式入口的变更，而不是仅记录一次字符串。"""
    run_dir = _run_with_split_sources(tmp_path)

    snapshot = freeze_publication_snapshot(run_dir)

    assert snapshot["entrypoint_path"] == "paper/main.tex"
    assert publication_snapshot_errors(run_dir) == []
    (run_dir / "paper/main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n改动后的正式稿。\\end{document}\n",
        encoding="utf-8",
    )
    assert any("正式论文入口" in error for error in publication_snapshot_errors(run_dir))


def test_publication_closure_accepts_parent_relative_current_figure_inside_run(
    tmp_path: Path,
) -> None:
    """paper/main.tex 的 ../figures 引用位于 run 内时必须进入正式闭包。"""
    run_dir = _run_with_split_sources(tmp_path)
    figure_path = run_dir / "figures/current/q1-main.pdf"
    figure_path.write_bytes(b"%PDF-1.4\n")
    (run_dir / "paper/main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\includegraphics{../figures/current/q1-main.pdf}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )

    relatives = {path.relative_to(run_dir).as_posix() for path in publication_source_paths(run_dir)}
    assert {"paper/main.tex", "figures/current/q1-main.pdf"}.issubset(relatives)


def test_publication_closure_resolves_nested_input_from_entrypoint_directory(
    tmp_path: Path,
) -> None:
    """嵌套子文件按主入口目录引用正文时必须进入正式闭包。"""
    run_dir = _run_with_split_sources(tmp_path)
    (run_dir / "paper/sections/questions.tex").write_text(
        "\\input{longform-source.tex}\n", encoding="utf-8"
    )

    relatives = {
        path.relative_to(run_dir).as_posix()
        for path in publication_source_paths(run_dir)
    }

    assert "paper/longform-source.tex" in relatives


def test_publication_closure_rejects_true_parent_escape(tmp_path: Path) -> None:
    """没有任何 run 内候选的相对路径仍须按越界引用拒绝。"""
    run_dir = _run_with_split_sources(tmp_path)
    (run_dir / "paper/main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\includegraphics{../../outside.pdf}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )

    with pytest.raises(ContractError, match="越过运行目录"):
        publication_source_paths(run_dir)
