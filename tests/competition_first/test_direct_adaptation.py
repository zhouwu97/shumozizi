"""sci-box 母版模板“直接适配”渲染与图计划选型合同测试。

覆盖：
- direct adaptation：复制原模板脚本 -> 注入真实数据 shim -> 原样运行 -> PNG/PDF/SVG 产出；
- 特征数不匹配、无 shim 模板、manual 模式；
- FIGURE_PLAN 允许 sci-box 技能（selected_skill / preferred / template_id 放宽）。

注意：本文件不使用 pytest 的 tmp_path（其 basetemp 以 POSIX 0o700 创建，在受沙箱
限制的 Windows 环境会拒绝枚举），改用工作区内默认权限的临时目录 ws_tmp。
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError
from shumozizi.simple.direct_adaptation import (
    DIRECT_ADAPTATION_READY,
    adapt_and_render,
    prepare_manual_adaptation,
)
from shumozizi.simple.figures import write_figure_plan
from shumozizi.simple.initialization import initialize_simple_run


@pytest.fixture
def ws_tmp() -> Path:
    """工作区内默认权限的临时目录（避免 pytest basetemp 的 0o700 沙箱问题）。"""
    base = Path("tmp") / f"t-da-{uuid.uuid4().hex[:10]}"
    base.mkdir(parents=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _split_violin_data(feature_count: int = 13, rows: int = 30) -> dict[str, object]:
    """构造符合 grouped-corr-split-violin 数据合同的真实观测。"""
    return {
        "features": [f"f{i:02d}" for i in range(feature_count)],
        "groups": [
            {
                "name": "Train",
                "values": [
                    [float(i + j * 0.5) for j in range(feature_count)] for i in range(rows)
                ],
            },
            {
                "name": "Test",
                "values": [
                    [float(i + 2.0 - j * 0.5) for j in range(feature_count)] for i in range(rows)
                ],
            },
        ],
    }


def test_direct_adaptation_copies_original_and_swaps_data_entry(
    ws_tmp: Path,
) -> None:
    """direct 模式必须复制原脚本、只替换数据入口并产出三种格式。"""
    run_dir = ws_tmp / "run"
    run_dir.mkdir()
    output_stem = run_dir / "figures" / "publication" / "q3-corr"

    outputs, boxes = adapt_and_render(
        "grouped-corr-split-violin", _split_violin_data(), output_stem, run_dir
    )

    assert boxes == "figures/publication/q3-corr.text-boxes.json"
    for item in outputs:
        assert (run_dir / item).is_file()
        assert (run_dir / item).stat().st_size > 0
    assert any(item.endswith(".png") for item in outputs)
    assert any(item.endswith(".pdf") for item in outputs)
    assert any(item.endswith(".svg") for item in outputs)

    adapted = run_dir / "code" / "figures" / "adapted_grouped-corr-split-violin.py"
    shim = run_dir / "code" / "figures" / "_real_data_grouped_corr_split_violin.py"
    assert adapted.is_file()
    assert shim.is_file()
    text = adapted.read_text(encoding="utf-8")
    # 数据入口被替换，但绘图结构保留。
    assert "apply_real_data(globals())" in text
    assert "def draw_lower_corr" in text
    assert "def draw_split_violin" in text
    assert "fig.add_axes([0.024, 0.165, 0.018, 0.72])" in text
    assert 'fig.legend(handles=handles, loc="lower center"' in text
    # 输出路径指向本次运行目录（绝对路径），而不是模板默认 outputs/。
    import json

    assert f'Path({json.dumps(str(output_stem.resolve()))})' in text
    assert 'outputs" / "grouped_corr_split_violin_replica' not in text


def test_direct_adaptation_feature_count_mismatch_raises(ws_tmp: Path) -> None:
    """特征数不等于母版模板时明确报错，指引 manual 模式手工调整布局。"""
    run_dir = ws_tmp / "run"
    run_dir.mkdir()
    output_stem = run_dir / "figures" / "evidence" / "mismatch"

    with pytest.raises(ContractError, match="特征数|manual"):
        adapt_and_render(
            "grouped-corr-split-violin", _split_violin_data(feature_count=6), output_stem, run_dir
        )


def test_direct_adaptation_unknown_template_raises(ws_tmp: Path) -> None:
    """没有自动 shim 的模板必须给出 direct/manual/reimplemented 三种指引。"""
    run_dir = ws_tmp / "run"
    run_dir.mkdir()
    output_stem = run_dir / "figures" / "evidence" / "unknown"

    with pytest.raises(ContractError, match="manual|reimplemented"):
        adapt_and_render("cv-roc-ci", {"models": []}, output_stem, run_dir)

    assert "cv-roc-ci" not in DIRECT_ADAPTATION_READY


def test_manual_adaptation_prepares_stub_without_running(ws_tmp: Path) -> None:
    """manual 模式只复制原脚本并写入标记好的数据入口 stub，不运行、不产出图。"""
    run_dir = ws_tmp / "run"
    run_dir.mkdir()
    output_stem = run_dir / "figures" / "evidence" / "manual-roc"

    guide = prepare_manual_adaptation("cv-roc-ci", {"models": []}, output_stem, run_dir)

    assert guide["mode"] == "manual"
    adapted = run_dir / guide["adapted_script"]
    assert adapted.is_file()
    assert "TODO(manual adaptation)" in adapted.read_text(encoding="utf-8")
    assert (run_dir / guide["figure_data"]).is_file()
    # 没有产出任何图。
    assert not (output_stem.with_suffix(".png")).exists()
    assert "instructions" in guide


def _run(ws_tmp: Path, name: str) -> Path:
    """创建一个允许登记生产结果的最小 v3.2 运行。"""
    return initialize_simple_run(
        ws_tmp,
        name,
        required_questions=["Q2"],
        workflow_version="3.2",
    )


def _sci_box_figure() -> dict[str, object]:
    """构造一张使用 sci-box 母版模板的 FIGURE_PLAN 2.3 正文图。"""
    return {
        "figure_id": "q2-corr",
        "preferred": "skills/sci-box/scibox-figure",
        "fallback": "skills/sci-box/scibox-diagram",
        "selected_skill": "skills/sci-box/scibox-figure",
        "template_id": "grouped-corr-split-violin",
        "template_source": "master_original",
        "template_preview_viewed": True,
        "template_adaptation": "仅替换数据入口，保留相关矩阵与半边小提琴布局。",
        "selection_reason": "多变量相关性与两个分组分布需要同时呈现。",
        "question_id": "Q2",
        "role": "insight",
        "presentation_role": "question_hero",
        "claim": "两个分组在多变量空间中的相关性结构不同。",
        "source_result_ids": ["q2-primary"],
        "script": "code/figures/adapted_grouped-corr-split-violin.py",
        "output": "figures/current/q2-corr.pdf",
        "paper_section": "paper/sections/q2.tex",
        "caption": "两个分组的变量相关矩阵与分布对比",
        "latex_label": "fig:q2-corr",
        "explanation_anchor": "相关矩阵显示结构差异",
        "required": True,
        "visual_archetype": "multi_panel_evidence_chain",
        "information_structure": "tradeoff",
        "renderer": "python",
        "visual_question": "两个分组的相关结构是否一致？",
        "expected_observation": "相关矩阵呈分组差异，小提琴分布偏移。",
        "decision_consequence": "分组建模优于合并建模。",
    }


def test_figure_plan_accepts_sci_box_skills_and_template_fields(ws_tmp: Path) -> None:
    """sci-box 技能必须成为正式可选技能，preferred 不再固定旧模板技能。"""
    run_dir = _run(ws_tmp, "figure-plan-scibox")
    plan = {
        "schema_name": "figure_plan",
        "schema_version": "2.3",
        "run_id": run_dir.name,
        "visual_decisions": [
            {
                "scope": "Q2",
                "evidence_need": "required",
                "presentation_need": "required",
                "reason": "分组相关结构与分布差异必须形成可读的主图。",
            }
        ],
        "figures": [_sci_box_figure()],
    }

    written = write_figure_plan(run_dir, plan)
    figure = written["figures"][0]
    assert figure["selected_skill"] == "skills/sci-box/scibox-figure"
    assert figure["preferred"] == "skills/sci-box/scibox-figure"
    assert figure["template_id"] == "grouped-corr-split-violin"
    assert figure["template_preview_viewed"] is True


def test_figure_plan_hero_without_preventive_form_no_longer_blocked(ws_tmp: Path) -> None:
    """正文主图不再被前置的 generic_chart_considered 表单阻断（advisory）。"""
    run_dir = _run(ws_tmp, "figure-plan-no-preventive-form")
    # _sci_box_figure() 不含 generic_chart_* 字段：结构匹配时直接放行。
    plan = {
        "schema_name": "figure_plan",
        "schema_version": "2.3",
        "run_id": run_dir.name,
        "visual_decisions": [
            {
                "scope": "Q2",
                "evidence_need": "required",
                "presentation_need": "required",
                "reason": "分组相关结构差异必须形成一张可快速阅读的主图，否则结论只能靠表格。",
            }
        ],
        "figures": [_sci_box_figure()],
    }

    assert write_figure_plan(run_dir, plan)["figures"][0]["figure_id"] == "q2-corr"

    # 显式声明“已考虑通用图且拒绝”但没给理由 -> 仍阻断（唯一保留的前置表单）。
    bad = _sci_box_figure()
    bad["generic_chart_considered"] = False
    with pytest.raises(ContractError, match="generic_chart_rejected_because"):
        write_figure_plan(run_dir, {**plan, "figures": [bad]})

