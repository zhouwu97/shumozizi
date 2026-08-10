"""验证工作流修复：author-pass 必须引用已就绪 current 图（图消费门），
且 author brief 必须列出可引用图路径、内建 CUMCM 范式与学术文风。
"""

from __future__ import annotations

from pathlib import Path

from shumozizi.core.io import atomic_json
from shumozizi.paper.author_pass import _render_author_brief, _visual_requirement_brief
from shumozizi.paper.readiness import validate_required_figure_consumption
from shumozizi.simple.initialization import initialize_simple_run


def _run_with_current_figure(tmp_path: Path) -> Path:
    """构造有 current 图登记的运行。"""
    run_dir = initialize_simple_run(
        tmp_path, "figure-gate", required_questions=["Q1"], workflow_version="3.2"
    )
    atomic_json(
        run_dir / "figures/index.json",
        {
            "schema_name": "simple_figure_index",
            "schema_version": "1.3",
            "run_id": run_dir.name,
            "figures": [
                {
                    "figure_id": "fig1_scene",
                    "question_id": "Q1",
                    "status": "current",
                    "paper_allowed": True,
                    "takeaway": "组3 接触网络与导电骨架。",
                    "outputs": [
                        {"path": "figures/current/fig1_scene.pdf", "sha256": "0" * 64},
                        {"path": "figures/current/fig1_scene.png", "sha256": "0" * 64},
                    ],
                }
            ],
        },
    )
    return run_dir


def test_figure_consumption_gate_blocks_text_only_paper(tmp_path: Path) -> None:
    """正文完全没有 includegraphics 时必须 RENDER_FORBIDDEN。"""
    run_dir = _run_with_current_figure(tmp_path)
    (run_dir / "paper" / "main.tex").write_text(
        "\\section{问题一}\n\n纯文字结果，没有引用任何图。\n", encoding="utf-8"
    )
    errors = validate_required_figure_consumption(run_dir)
    assert errors, "应当拦截无图论文"
    assert any("RENDER_FORBIDDEN" in error for error in errors)


def test_figure_consumption_gate_passes_when_current_figure_referenced(tmp_path: Path) -> None:
    """正文引用了 current 图时必须通过。"""
    run_dir = _run_with_current_figure(tmp_path)
    (run_dir / "paper" / "main.tex").write_text(
        "\\section{问题一}\n\\includegraphics[width=0.9\\textwidth]{../figures/current/fig1_scene.pdf}\n"
        "图展示了接触网络与导电骨架。\n",
        encoding="utf-8",
    )
    errors = validate_required_figure_consumption(run_dir)
    assert errors == []


def test_visual_requirement_brief_lists_ready_figures_with_paths(tmp_path: Path) -> None:
    """brief 必须列出已就绪 current 图的 includegraphics 路径，而不是"需要评估"。"""
    run_dir = _run_with_current_figure(tmp_path)
    lines = _visual_requirement_brief(run_dir)
    text = "\n".join(lines)
    assert "fig1_scene" in text
    assert "includegraphics" in text
    assert "figures/current/fig1_scene.pdf" in text
    assert "必须引用" in text
    # 不再把已就绪图说成"需要视觉评估"
    assert "需要视觉评估" not in text


def test_author_brief_contains_cumcm_skeleton_and_second_step(tmp_path: Path) -> None:
    """author brief 必须内建 CUMCM 范式骨架、学术文风与 SECOND STEP 高级图。"""
    state = {"run_id": "x"}
    brief = _render_author_brief(state, {"cards": []}, None)
    assert "问题重述" in brief
    assert "模型假设" in brief
    assert "符号说明" in brief
    assert "模型检验与分析" in brief
    assert "模型评价与推广" in brief
    assert "SECOND STEP" in brief
    assert "高级图" in brief
    assert "禁止" in brief and "第一人称" in brief
    assert "主题句" in brief
