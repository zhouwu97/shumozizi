"""验证工作流修复：author-pass 必须引用已就绪 current 图（图消费门），
且 author brief 必须列出可引用图路径、内建 CUMCM 范式与学术文风。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shumozizi.core.io import atomic_json
from shumozizi.paper.advanced_figure_policy import advanced_figure_quota_payload
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


def _run_with_advanced_figure_quota(
    tmp_path: Path,
    *,
    question_count: int = 4,
    figures_per_question: int | None = None,
) -> Path:
    """构造满足按题数自适应视觉合同的正式稿。"""
    question_ids = [f"Q{index}" for index in range(1, question_count + 1)]
    if figures_per_question is None:
        figures_per_question = 2 if question_count < 4 else 3
    run_dir = initialize_simple_run(
        tmp_path,
        "advanced-figure-quota",
        required_questions=question_ids,
        workflow_version="3.2",
        quality_policy="competition-quality-v1",
    )
    archetypes = ("probability_curve", "ci_forest", "group_violin")
    figures: list[dict[str, object]] = []
    tex_parts = ["\\documentclass{article}", "\\begin{document}"]
    for question_index, question_id in enumerate(question_ids):
        tex_parts.append(f"\\section{{{question_id}}}")
        for figure_index in range(figures_per_question):
            figure_id = f"fig_{question_id.lower()}_{figure_index + 1}"
            figures.append(
                {
                    "figure_id": figure_id,
                    "question_id": question_id,
                    "status": "current",
                    "paper_allowed": True,
                    "placement": "body",
                    "visual_archetype": archetypes[(question_index + figure_index) % 3],
                    "outputs": [
                        {
                            "path": f"figures/current/{figure_id}.pdf",
                            "sha256": "0" * 64,
                        }
                    ],
                }
            )
            tex_parts.append(
                "\\includegraphics[width=0.9\\textwidth]"
                f"{{../figures/current/{figure_id}.pdf}}"
            )
    tex_parts.append("\\end{document}")
    atomic_json(
        run_dir / "figures/index.json",
        {
            "schema_name": "simple_figure_index",
            "schema_version": "1.3",
            "run_id": run_dir.name,
            "figures": figures,
        },
    )
    (run_dir / "paper" / "main.tex").write_text("\n".join(tex_parts), encoding="utf-8")
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


@pytest.mark.parametrize("question_count", range(1, 7))
def test_adaptive_figure_quota_has_a_feasible_formal_paper_for_every_question_count(
    tmp_path: Path,
    question_count: int,
) -> None:
    """每种合法题数都存在不靠凑图的可通过正式稿。"""
    run_dir = _run_with_advanced_figure_quota(
        tmp_path,
        question_count=question_count,
    )

    assert validate_required_figure_consumption(run_dir) == []


def test_adaptive_figure_quota_only_enforces_global_targets_from_four_questions(
    tmp_path: Path,
) -> None:
    """少题运行保留逐题覆盖，但不被十二图或三图型反向强迫凑图。"""
    short = advanced_figure_quota_payload(3)
    long = advanced_figure_quota_payload(4)

    assert short["overall_enforcement"] == "coverage_driven_editorial_target"
    assert short["minimum_formal_current_figures"] is None
    assert short["minimum_visual_archetypes"] is None
    assert long["overall_enforcement"] == "hard_minimum"
    assert long["minimum_formal_current_figures"] == 12
    assert long["minimum_visual_archetypes"] == 3

    run_dir = _run_with_advanced_figure_quota(
        tmp_path / "shortage",
        question_count=1,
        figures_per_question=1,
    )
    errors = validate_required_figure_consumption(run_dir)
    assert any("Q1 在正式稿只消费 1 张" in error for error in errors)


def test_advanced_figure_quota_rejects_shortage_overflow_and_single_type(tmp_path: Path) -> None:
    """硬规格须能定位逐题不足、逐题超额和图型单一三类绕过方式。"""
    run_dir = _run_with_advanced_figure_quota(tmp_path)
    main_path = run_dir / "paper" / "main.tex"
    # Q1 少一张，同时总量从 12 降到 11；只删正文引用而不动登记，验证消费闭环。
    text = main_path.read_text(encoding="utf-8")
    text = text.replace(
        "\\includegraphics[width=0.9\\textwidth]{../figures/current/fig_q1_3.pdf}\n",
        "",
    )
    main_path.write_text(text, encoding="utf-8")
    errors = validate_required_figure_consumption(run_dir)
    assert not any("Q1 在正式稿只消费 2 张" in error for error in errors)
    # Q1 此时仍有两张，逐题最低配额通过；全篇最低配额必须失败。
    assert any("正式稿只消费 11 张" in error for error in errors)

    # 再删一张，触发逐题最低配额。
    text = main_path.read_text(encoding="utf-8")
    text = text.replace(
        "\\includegraphics[width=0.9\\textwidth]{../figures/current/fig_q1_2.pdf}\n",
        "",
    )
    main_path.write_text(text, encoding="utf-8")
    errors = validate_required_figure_consumption(run_dir)
    assert any("Q1 在正式稿只消费 1 张" in error for error in errors)

    # 恢复全部正文引用后，把全部图型伪装成同一种，硬门必须拒绝。
    run_dir = _run_with_advanced_figure_quota(tmp_path / "single-type")
    index_path = run_dir / "figures/index.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    for figure in payload["figures"]:
        figure["visual_archetype"] = "probability_curve"
    atomic_json(index_path, payload)
    errors = validate_required_figure_consumption(run_dir)
    assert any("只登记 1 种可审计图型" in error for error in errors)


def test_advanced_figure_quota_rejects_more_than_three_body_figures_for_one_question(
    tmp_path: Path,
) -> None:
    """同一问题第四张正文图不能用来挤压其他问题的论证空间。"""
    run_dir = _run_with_advanced_figure_quota(tmp_path)
    index_path = run_dir / "figures/index.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    payload["figures"].append(
        {
            "figure_id": "fig_q1_4",
            "question_id": "Q1",
            "status": "current",
            "paper_allowed": True,
            "placement": "body",
            "visual_archetype": "ci_forest",
            "outputs": [
                {"path": "figures/current/fig_q1_4.pdf", "sha256": "0" * 64}
            ],
        }
    )
    atomic_json(index_path, payload)
    main_path = run_dir / "paper" / "main.tex"
    main_path.write_text(
        main_path.read_text(encoding="utf-8").replace(
            "\\end{document}",
            "\\includegraphics[width=0.9\\textwidth]{../figures/current/fig_q1_4.pdf}\n\\end{document}",
        ),
        encoding="utf-8",
    )
    errors = validate_required_figure_consumption(run_dir)
    assert any("Q1 在正式稿消费 4 张" in error for error in errors)


def test_advanced_figure_quota_does_not_count_appendix_figures(tmp_path: Path) -> None:
    """附录稳定性图不能用来伪造正文十二图规格。"""
    run_dir = _run_with_advanced_figure_quota(tmp_path)
    index_path = run_dir / "figures/index.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    appendix_figure = next(
        item for item in payload["figures"] if item["figure_id"] == "fig_q1_3"
    )
    appendix_figure["placement"] = "appendix"
    atomic_json(index_path, payload)

    errors = validate_required_figure_consumption(run_dir)

    assert any("正式稿只消费 11 张 current 正文图" in error for error in errors)
    assert not any("Q1 在正式稿只消费 2 张" in error for error in errors)


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


def test_author_brief_prioritizes_claim_first_visuals_and_semantic_structure(
    tmp_path: Path,
) -> None:
    """Author 只接收叙事与论证视觉义务，不接收逐问报账或全篇凑图命令。"""
    state = {"run_id": "x", "required_questions": ["Q1", "Q2", "Q3"]}
    brief = _render_author_brief(state, {"cards": []}, None)
    for kw in [
        "共享数学对象", "允许合并相邻问题", "先回答每张图要证明什么",
        "数据直觉", "决定性证据", "current 数据",
    ]:
        assert kw in brief, f"brief 缺少: {kw}"
    for forbidden in ("不得混写", "每个问题单独成节", "至少 12 张", "至少 3 种可审计图型"):
        assert forbidden not in brief, f"brief 不应再强制: {forbidden}"
    assert "20 页以上" not in brief
    assert "第一人称" in brief
    assert "主题句" in brief
