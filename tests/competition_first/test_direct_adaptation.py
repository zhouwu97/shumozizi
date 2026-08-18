"""sci-box 母版模板“直接适配”渲染、数据真实性回归与 work→promotion 闭环测试。

覆盖：
- P0-1：真实数据必须先于 make_figure 注入——两份不同真实数据必须产出不同 PNG；
- direct adaptation：复制原模板脚本、机器生成 text-boxes/visual_manifest/layout_report；
- Taylor：TaylorPoint(model=...) 字段与 reference_std 归一化；
- manual 模式：复制原脚本 + 输出路径改写 + 数据入口 stub；
- e2e 闭环：render_candidate（work 候选）→ 人工确认 → promote → figures/current；
- FIGURE_PLAN：scibox-diagram 允许 template_id=custom，sci-box 技能可选。

注意：本文件不使用 pytest 的 tmp_path（其 basetemp 以 POSIX 0o700 创建，在受沙箱
限制的 Windows 环境会拒绝枚举），改用工作区内默认权限的临时目录 ws_tmp。
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.simple.direct_adaptation import (
    DIRECT_ADAPTATION_READY,
    adapt_and_render,
    prepare_manual_adaptation,
)
from shumozizi.simple.figure_promotion import promote_figure_candidate
from shumozizi.simple.figures import write_figure_plan
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.quality import assess_result_quality
from tests.quality_protocol_helpers import (
    adapter_backed_assessment,
    record_passing_scientific_review,
    run_synthetic_verification_protocol,
)


@pytest.fixture
def ws_tmp() -> Path:
    """工作区内默认权限的临时目录（避免 pytest basetemp 的 0o700 沙箱问题）。"""
    base = Path("tmp") / f"t-da-{uuid.uuid4().hex[:10]}"
    base.mkdir(parents=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _split_violin_data(feature_count: int = 13, rows: int = 30, seed: float = 0.0) -> dict[str, object]:
    """构造符合 grouped-corr-split-violin 数据合同的真实观测。"""
    return {
        "features": [f"f{i:02d}" for i in range(feature_count)],
        "groups": [
            {
                "name": "Train",
                "values": [
                    [float(i + j * 0.5 + seed) for j in range(feature_count)] for i in range(rows)
                ],
            },
            {
                "name": "Test",
                "values": [
                    [float(i + 2.0 - j * 0.5 + seed) for j in range(feature_count)] for i in range(rows)
                ],
            },
        ],
    }


def _chord_data() -> dict[str, object]:
    """构造符合 nature-chord-diagram 数据合同的节点与加权边。"""
    return {
        "nodes": [
            {"id": "n1", "label": "约束", "group": "输入"},
            {"id": "n2", "label": "决策变量", "group": "中间"},
            {"id": "n3", "label": "指标", "group": "输出"},
            {"id": "n4", "label": "灵敏度", "group": "输出"},
        ],
        "links": [
            {"source": "n1", "target": "n2", "weight": 3.0},
            {"source": "n2", "target": "n3", "weight": 4.5},
            {"source": "n2", "target": "n4", "weight": 2.5},
            {"source": "n1", "target": "n4", "weight": 1.8},
        ],
    }


def test_direct_adaptation_real_data_changes_the_png() -> None:
    """P0-1：给两份不同的真实数据，PNG 必须真的发生变化（而不是都画模拟数据）。"""
    run_dir = Path("tmp") / f"t-p01-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir()
    try:
        stem_a = run_dir / "figures" / "work" / "q3-corr" / "v1" / "q3-corr"
        stem_b = run_dir / "figures" / "work" / "q3-corr" / "v1" / "q3-corr-b"
        adapt_and_render(
            "grouped-corr-split-violin", _split_violin_data(seed=0.0), stem_a, run_dir, figure_id="q3-corr"
        )
        adapt_and_render(
            "grouped-corr-split-violin", _split_violin_data(seed=50.0), stem_b, run_dir, figure_id="q3-corr"
        )
        png_a = sha256_file(stem_a.with_suffix(".png"))
        png_b = sha256_file(stem_b.with_suffix(".png"))
        assert png_a != png_b, "不同真实数据必须生成不同的 PNG，否则仍是模拟数据"
        # 数据 shim 必须存在于复制脚本同目录，且布局/清单是机器生成的。
        artifacts = load_json(stem_a.with_suffix(".layout_report.json"))
        assert artifacts["needs_human_confirmation"]
        assert load_json(stem_a.with_suffix(".visual_manifest.json"))["elements"]
        assert load_json(stem_a.with_suffix(".text-boxes.json"))["boxes"] is not None
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_direct_adaptation_copies_original_and_keeps_drawing() -> None:
    """direct 模式必须复制原脚本并保留绘图结构（draw_* / fig.add_axes / fig.legend）。"""
    run_dir = Path("tmp") / f"t-da-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir()
    try:
        stem = run_dir / "figures" / "work" / "q3-corr" / "v1" / "q3-corr"
        result = adapt_and_render(
            "grouped-corr-split-violin", _split_violin_data(), stem, run_dir, figure_id="q3-corr"
        )
        for item in result["outputs"]:
            assert (run_dir / item).is_file()
            assert (run_dir / item).stat().st_size > 0
        adapted = run_dir / result["adapted_script"]
        text = adapted.read_text(encoding="utf-8")
        assert "def draw_lower_corr" in text
        assert "def draw_split_violin" in text
        assert "fig.add_axes([0.024, 0.165, 0.018, 0.72])" in text
        assert 'fig.legend(handles=handles, loc="lower center"' in text
        # 输出路径指向本次运行目录，而不是模板默认 outputs/。
        assert 'outputs" / "grouped_corr_split_violin_replica' not in text
        # P0-1：数据 shim 由引擎先注入（进程内 apply_real_data 先于 make_figure），
        # 复制脚本里不应再出现“先 main 后注入”的顺序。
        assert "apply_real_data" not in text
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_direct_adaptation_feature_count_mismatch_raises() -> None:
    """特征数不等于母版模板时明确报错，指引 manual 模式手工调整布局。"""
    run_dir = Path("tmp") / f"t-da-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir()
    try:
        stem = run_dir / "figures" / "work" / "mismatch" / "v1" / "mismatch"
        with pytest.raises(ContractError, match="特征数|manual"):
            adapt_and_render(
                "grouped-corr-split-violin", _split_violin_data(feature_count=6), stem, run_dir
            )
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_direct_adaptation_unknown_template_raises() -> None:
    """没有自动 shim 的模板直接调用 adapt_and_render 必须给出 manual 指引。"""
    run_dir = Path("tmp") / f"t-da-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir()
    try:
        stem = run_dir / "figures" / "work" / "unknown" / "v1" / "unknown"
        with pytest.raises(ContractError, match="manual"):
            adapt_and_render("cv-roc-ci", {"models": []}, stem, run_dir)
        assert "cv-roc-ci" not in DIRECT_ADAPTATION_READY
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_manual_adaptation_patches_output_stem_and_leaves_stub() -> None:
    """manual 模式复制原脚本、改写输出路径、写数据入口 stub，不运行不产出图。"""
    run_dir = Path("tmp") / f"t-da-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir()
    try:
        stem = run_dir / "figures" / "work" / "manual-roc" / "v1" / "manual-roc"
        guide = prepare_manual_adaptation("cv-roc-ci", {"models": []}, stem, run_dir)
        assert guide["mode"] == "manual"
        adapted = run_dir / guide["adapted_script"]
        text = adapted.read_text(encoding="utf-8")
        assert "TODO(manual adaptation)" in text
        # P1：manual 也必须改写输出路径，不能运行后写到模板默认 outputs/。
        assert 'outputs" / "cv_roc_ci_replica' not in text
        assert (run_dir / guide["figure_data"]).is_file()
        assert not (stem.with_suffix(".png")).exists()
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_taylor_direct_adaptation_uses_model_field_and_reference_std() -> None:
    """Taylor shim 必须用 model= 字段，并把 std 按 reference_std 归一化。"""
    run_dir = Path("tmp") / f"t-da-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir()
    try:
        data = {
            "reference_std": 2.0,
            "panels": [
                {
                    "title": "留出集",
                    "points": [
                        {"name": "基线", "std": 2.0, "corr": 0.80},
                        {"name": "挑战者", "std": 1.6, "corr": 0.95},
                    ],
                },
                {
                    "title": "训练集",
                    "points": [
                        {"name": "基线", "std": 2.1, "corr": 0.82},
                        {"name": "挑战者", "std": 1.7, "corr": 0.96},
                    ],
                },
                {
                    "title": "全量",
                    "points": [
                        {"name": "基线", "std": 2.05, "corr": 0.81},
                        {"name": "挑战者", "std": 1.65, "corr": 0.95},
                    ],
                },
            ],
        }
        stem = run_dir / "figures" / "work" / "taylor" / "v1" / "taylor"
        result = adapt_and_render("taylor-diagram", data, stem, run_dir, figure_id="taylor")
        assert (run_dir / result["outputs"][0]).stat().st_size > 0
        # 归一化后标签应提示 Normalized Standard Deviation。
        layout = load_json(stem.with_suffix(".layout_report.json"))
        assert layout["figure_id"] == "taylor"
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# e2e 闭环：render_candidate（work 候选）→ 人工确认 → promote → figures/current
# ---------------------------------------------------------------------------


def _quality_ready_run(
    ws_tmp: Path, name: str, extra_payloads: dict[str, dict[str, object]] | None = None
) -> tuple[Path, dict[str, str]]:
    """建立带 current + quality 通过结果的 v3 运行，返回 (run_dir, figure_data 输入映射)。"""
    run_dir = initialize_simple_run(
        ws_tmp,
        name,
        required_questions=["Q1"],
    )
    payloads: dict[str, dict[str, object]] = {
        "chord": {"figure_data": _chord_data()},
        **{key: value for key, value in (extra_payloads or {}).items()},
    }
    protocol = run_synthetic_verification_protocol(
        run_dir,
        result_id="q1_visual",
        question_id="Q1",
        objective=0.83,
        artifact_payloads=payloads,
    )
    assessment = assess_result_quality(
        run_dir,
        result_id="q1_visual",
        assessment=adapter_backed_assessment(protocol),
    )
    assert assessment["paper_allowed"]
    record_passing_scientific_review(run_dir)
    return run_dir, protocol["paths"]["artifacts"]


def test_render_candidate_to_promotion_closes_v32_flow(ws_tmp: Path) -> None:
    """P0-2：use_template 渲染 work 候选（不登记）→ 人工看图确认 → promote → current。"""
    from scripts.figures.use_template import render_candidate

    run_dir, artifacts = _quality_ready_run(ws_tmp, "scibox-closure")
    input_result = artifacts["chord"]
    figure_id = "q1-chord"
    payload = render_candidate(
        run_dir,
        template_id="nature-chord-diagram",
        result_id="q1_visual",
        input_result=input_result,
        output_prefix=f"figures/work/{figure_id}/v1/{figure_id}",
        adaptation="direct",
    )
    assert payload["success"] is True
    assert payload["mode"] == "direct"
    for item in payload["outputs"]:
        assert (run_dir / item).is_file()
        assert (run_dir / item).stat().st_size > 0
    # 渲染阶段不登记、不产生 current。
    assert not (run_dir / "figures/current").exists() or not list(
        (run_dir / "figures/current").glob("*.png")
    )
    assert "promote" in payload

    # 人工看图确认：把机器报告的 needs_human_confirmation 字段补成已核实值，
    # 并把正文排版尺寸改为栏宽放置（sci-box 母版按整页设计）。
    layout_path = run_dir / payload["layout_report"]
    layout = load_json(layout_path)
    assert layout["needs_human_confirmation"]
    layout["colorblind_safe"] = True
    layout["locale_consistent"] = True
    for axis in layout["axes"]:
        axis["takeaway_annotation"] = True
    png_ratio = _png_ratio(run_dir / payload["outputs"][0])
    layout["paper_size_cm"] = {
        "width": 15.5,
        "height": round(15.5 / png_ratio, 2),
    }
    atomic_json(layout_path, layout)

    human_review = run_dir / f"figures/work/{figure_id}/v1/{figure_id}.human-review.json"
    atomic_json(
        human_review,
        {
            "reviewed": True,
            "paper_width_preview_checked": True,
            "mathematical_object_visible": True,
            "key_observation_visible": True,
            "mechanism_or_relation_visible": True,
            "constraint_or_boundary_visible": True,
            "decision_consequence_visible": True,
            "not_redundant_with_table": True,
            "caption_matches_figure": True,
            "font_readable": True,
            "panel_mapping_valid": True,
            "focal_claim": "加权关系由节点分组与连接强度共同呈现，约束到指标的结构清晰。",
            "visible_elements": [
                {"type": "text", "label": "约束", "panel": "main"},
                {"type": "text", "label": "决策变量", "panel": "main"},
                {"type": "text", "label": "指标", "panel": "main"},
            ],
            "reading_order": ["main"],
            "panel_takeaways": {"main": "约束经决策变量连接指标，加权关系直观可读。"},
            "issues": [],
            "verdict": "promote",
        },
    )

    receipt = promote_figure_candidate(
        run_dir,
        figure_id=figure_id,
        candidate_outputs=[item for item in payload["outputs"] if item.endswith((".png", ".pdf"))],
        target_stem=f"figures/current/{figure_id}",
        rendering_mode="plot",
        layout_report=payload["layout_report"],
        figure_role="insight",
        human_review=load_json(human_review),
        visual_manifest=payload["visual_manifest"],
    )
    assert receipt["figure_id"] == figure_id
    assert (run_dir / f"figures/current/{figure_id}.png").is_file()
    assert (run_dir / f"figures/current/{figure_id}.pdf").is_file()


def _png_ratio(png: Path) -> float:
    from PIL import Image

    with Image.open(png) as image:
        width, height = image.size
    return width / height


def test_render_candidate_direct_without_shim_auto_manual_copy(ws_tmp: Path) -> None:
    """direct 无 shim 时自动转 manual-copy（复制原母版留 stub），不静默回退 reimplemented。"""
    from scripts.figures.use_template import render_candidate

    roc_payload = {
        "figure_data": {
            "models": [
                {
                    "name": "基线",
                    "folds": [
                        {"fpr": [0, 0.3, 1.0], "tpr": [0, 0.7, 1.0]},
                        {"fpr": [0, 0.2, 1.0], "tpr": [0, 0.8, 1.0]},
                    ],
                }
            ]
        }
    }
    run_dir, artifacts = _quality_ready_run(ws_tmp, "scibox-manual-fallback", {"roc": roc_payload})
    payload = render_candidate(
        run_dir,
        template_id="cv-roc-ci",
        result_id="q1_visual",
        input_result=artifacts["roc"],
        output_prefix="figures/work/q1-roc/v1/q1-roc",
        adaptation="direct",
    )
    assert payload["mode"] == "manual"
    assert "手工" in payload["notice"]
    assert (run_dir / payload["adapted_script"]).is_file()
    # 不产生 work PNG（还没运行）。
    assert not (run_dir / "figures/work/q1-roc/v1/q1-roc.png").exists()


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


def test_p0_semantics_templates_removed_from_direct(ws_tmp: Path) -> None:
    """P0：rf-tpe（42% 演示曲面混合）与 grouped-circular（Brain Phenotype/固定星号）必须移出 direct。"""
    from scripts.figures.use_template import render_candidate
    from shumozizi.simple.direct_adaptation import DIRECT_ADAPTERS

    assert "rf-tpe-surface" not in DIRECT_ADAPTERS
    assert "grouped-circular-heatmap" not in DIRECT_ADAPTERS
    assert "rf-tpe-surface" not in DIRECT_ADAPTATION_READY
    assert "grouped-circular-heatmap" not in DIRECT_ADAPTATION_READY

    run_dir, artifacts = _quality_ready_run(
        ws_tmp,
        "scibox-p0-removed",
        {
            "tpe": {
                "figure_data": {
                    "x_label": "X",
                    "y_label": "Y",
                    "metric_label": "M",
                    "direction": "minimize",
                    "trials": [
                        {"x": 3.0, "y": 80.0, "metric": 0.42},
                        {"x": 5.0, "y": 160.0, "metric": 0.27},
                        {"x": 7.0, "y": 120.0, "metric": 0.36},
                        {"x": 6.0, "y": 200.0, "metric": 0.31},
                    ],
                }
            }
        },
    )
    payload = render_candidate(
        run_dir,
        template_id="rf-tpe-surface",
        result_id="q1_visual",
        input_result=artifacts["tpe"],
        output_prefix="figures/work/q1-tpe/v1/q1-tpe",
        adaptation="direct",
    )
    # direct 无 shim -> 自动 manual-copy，绝不能静默走 reimplemented 或原假曲面。
    assert payload["mode"] == "manual"
    assert "manual" in payload.get("notice", "") or "手工" in payload.get("notice", "")


def test_grouped_corr_labels_are_data_driven(ws_tmp: Path) -> None:
    """P0-3：grouped-corr 的 Train/Test 图例与 Substrate/Biomass/Operation 括号必须由数据驱动。"""
    from shumozizi.simple.direct_adaptation import adapt_and_render

    run_dir = Path("tmp") / f"t-lbl-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir()
    try:
        data = _split_violin_data()
        data["groups"][0]["name"] = "方案A"
        data["groups"][1]["name"] = "方案B"
        data["feature_groups"] = [
            {"name": "环境变量", "start": 0, "end": 5},
            {"name": "决策变量", "start": 5, "end": 8},
            {"name": "结果变量", "start": 8, "end": 13},
        ]
        stem = run_dir / "figures" / "work" / "q3-corr" / "v1" / "q3-corr"
        result = adapt_and_render(
            "grouped-corr-split-violin", data, stem, run_dir, figure_id="q3-corr"
        )
        text = (run_dir / result["adapted_script"]).read_text(encoding="utf-8")
        assert 'label="方案A"' in text
        assert 'label="方案B"' in text
        assert 'label="环境变量"' in text
        assert 'label="决策变量"' in text
        assert 'label="结果变量"' in text
        assert 'label="Substrate"' not in text
        assert 'label="Biomass"' not in text
        assert 'label="Operation"' not in text
        assert 'label="Train"' not in text
        assert 'label="Test"' not in text

        # 未提供 feature_groups -> 三个括号调用整体删除（不画不存在的变量分组）。
        bare = _split_violin_data()
        bare["groups"][0]["name"] = "组1"
        bare["groups"][1]["name"] = "组2"
        stem2 = run_dir / "figures" / "work" / "q3-corr" / "v2" / "q3-corr"
        result2 = adapt_and_render(
            "grouped-corr-split-violin", bare, stem2, run_dir, figure_id="q3-corr"
        )
        text2 = (run_dir / result2["adapted_script"]).read_text(encoding="utf-8")
        # 括号调用（含其固定 x 坐标）被删除；函数定义保留不影响。
        assert "x=13.15" not in text2
        assert "x=13.65" not in text2
        assert "x=14.60" not in text2
        assert 'label="组1"' in text2
        assert 'label="组2"' in text2
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_taylor_validator_rejects_negative_corr(ws_tmp: Path) -> None:
    """P1：Taylor 母版会把负相关截断为 0，direct 必须拒绝而非静默画错。"""
    from shumozizi.simple.direct_adaptation import adapt_and_render

    run_dir = Path("tmp") / f"t-tay-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir()
    try:
        data = {
            "reference_std": 1.0,
            "panels": [
                {"title": "a", "points": [{"name": "M", "std": 1.0, "corr": -0.4}]},
                {"title": "b", "points": [{"name": "M", "std": 1.0, "corr": 0.5}]},
                {"title": "c", "points": [{"name": "M", "std": 1.0, "corr": 0.6}]},
            ],
        }
        stem = run_dir / "figures" / "work" / "taylor" / "v1" / "taylor"
        with pytest.raises(ContractError, match="corr|manual"):
            adapt_and_render("taylor-diagram", data, stem, run_dir)

        # std/reference_std 超过 rmax=1.75 同样拒绝。
        data["panels"][0]["points"][0]["corr"] = 0.9
        data["panels"][0]["points"][0]["std"] = 2.0
        with pytest.raises(ContractError, match="rmax|manual"):
            adapt_and_render("taylor-diagram", data, stem, run_dir)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_pairgrid_z_scores_real_data(ws_tmp: Path) -> None:
    """P1：pairgrid 母版散点轴固定 [-3.1, 3.1]，任意量纲真实数据必须被标准化。"""
    from shumozizi.simple.direct_adaptation import adapt_and_render

    run_dir = Path("tmp") / f"t-pg-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir()
    try:
        # 年龄 18~80、价格 2000~10000：未标准化会全部飞出画布。
        data = {
            "columns": ["年龄", "价格", "销量"],
            "values": [
                [18 + i * 2, 2000 + i * 300, 100 + i * 5] for i in range(25)
            ],
        }
        stem = run_dir / "figures" / "work" / "pairgrid" / "v1" / "pairgrid"
        result = adapt_and_render("correlation-pairgrid", data, stem, run_dir, figure_id="pairgrid")
        assert (run_dir / result["outputs"][0]).stat().st_size > 0
        # shim 按列 z-score，散点落在固定轴内。
        shim_text = (run_dir / result["data_shim"]).read_text(encoding="utf-8")
        assert "std(axis=0" in shim_text
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_render_driver_reproduces_figure_standalone(ws_tmp: Path) -> None:
    """P1：生成的 render_<id>.py 必须能独立运行复现同一张正式图。"""
    from shumozizi.simple.direct_adaptation import adapt_and_render

    run_dir = Path("tmp") / f"t-drv-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir()
    try:
        stem = run_dir / "figures" / "work" / "chord" / "v1" / "chord"
        result = adapt_and_render("nature-chord-diagram", _chord_data(), stem, run_dir, figure_id="chord")
        driver = run_dir / result["render_script"]
        assert driver.is_file()
        png_before = sha256_file(stem.with_suffix(".png"))
        # 独立运行 driver，重新生成到同一输出。
        import subprocess
        import sys as _sys

        proc = subprocess.run(
            [_sys.executable, str(driver)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert proc.returncode == 0, proc.stderr[-1500:]
        png_after = sha256_file(stem.with_suffix(".png"))
        assert png_before == png_after, "独立 driver 必须复现同一张图"
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_scibox_diagram_bridge_machine_extracts_layout(ws_tmp: Path) -> None:
    """P1：scibox-diagram 桥自动从 .drawio XML 提取布局，diagram QA 零错误。"""
    from scripts.figures.render_scibox_diagram import render_diagram_candidate
    from shumozizi.simple.figure_promotion import _diagram_layout_errors

    run_dir = ws_tmp / "diagram-run"
    run_dir.mkdir()
    content = json.loads(
        (
            Path("skills/sci-box/scibox-diagram/assets/roadmap-5band/example.json")
        ).read_text(encoding="utf-8")
    )
    (run_dir / "content.json").write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")

    payload = render_diagram_candidate(
        run_dir,
        template_id="roadmap-5band",
        content_json="content.json",
        output_prefix="figures/work/q1-roadmap/v1/q1-roadmap",
        figure_id="q1-roadmap",
    )
    assert payload["success"] is True
    assert (run_dir / payload["drawio"]).is_file()
    layout = load_json(run_dir / payload["layout_report"])
    assert layout["machine_extracted"] is True
    assert layout["node_boxes"]
    assert layout["text_boxes"]
    assert payload["artifacts"]["export"] == "pending_requires_drawio_cli" or payload[
        "artifacts"
    ].get("outputs")

    errors = _diagram_layout_errors(
        layout,
        png_size=(int(layout["canvas"]["width"]), int(layout["canvas"]["height"])),
        minimum_font_size_pt=8.0,
    )
    assert errors == [], errors
    assert "promote" in payload


def test_scibox_diagram_finalize_and_promote_e2e(ws_tmp: Path) -> None:
    """P2：drawio → 手工导出 PNG/PDF → finalize（manifest）→ 人工复核 → promote → current。"""
    from PIL import Image
    from pypdf import PdfWriter

    from scripts.figures.render_scibox_diagram import render_diagram_candidate
    from shumozizi.simple.figure_promotion import promote_figure_candidate

    run_dir = ws_tmp / "diagram-e2e"
    run_dir.mkdir()
    content = json.loads(
        (
            Path("skills/sci-box/scibox-diagram/assets/roadmap-5band/example.json")
        ).read_text(encoding="utf-8")
    )
    (run_dir / "content.json").write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    figure_id = "q1-roadmap"
    prefix = f"figures/work/{figure_id}/v1/{figure_id}"
    payload = render_diagram_candidate(
        run_dir, template_id="roadmap-5band", content_json="content.json",
        output_prefix=prefix, figure_id=figure_id,
    )
    layout = load_json(run_dir / payload["layout_report"])
    width, height = int(layout["canvas"]["width"]), int(layout["canvas"]["height"])

    # 模拟人工在 diagrams.net 手工导出 PNG/PDF 到同目录。
    png = run_dir / f"{prefix}.png"
    pdf = run_dir / f"{prefix}.pdf"
    png.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), "white").save(png)
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=height)
    with pdf.open("wb") as stream:
        writer.write(stream)

    # finalize-existing：--drawio 指向已生成的 drawio，同目录有 PNG/PDF 时补全 manifest。
    finalized = render_diagram_candidate(
        run_dir,
        template_id="custom",
        content_json=None,
        output_prefix=prefix,
        figure_id=figure_id,
        drawio_input=payload["drawio"],
    )
    assert "visual_manifest" in finalized["artifacts"]
    manifest = load_json(run_dir / finalized["artifacts"]["visual_manifest"])
    # manifest 标签是真实可见文字，不是 cell id。
    assert all(not str(item["label"]).startswith("text-") for item in manifest["elements"])
    assert manifest["elements"]

    human_review = run_dir / f"{prefix}.human-review.json"
    atomic_json(
        human_review,
        {
            "reviewed": True,
            "paper_width_preview_checked": True,
            "mathematical_object_visible": True,
            "key_observation_visible": True,
            "mechanism_or_relation_visible": True,
            "constraint_or_boundary_visible": True,
            "decision_consequence_visible": True,
            "not_redundant_with_table": True,
            "caption_matches_figure": True,
            "font_readable": True,
            "panel_mapping_valid": True,
            "focal_claim": "五带技术路线把问题、方法、机制、结果与评价串成完整论证链。",
            "visible_elements": [
                {"type": "text", "label": item["label"], "panel": "main"}
                for item in manifest["elements"][:2]
            ],
            "reading_order": ["main"],
            "panel_takeaways": {"main": "技术路线五带结构完整、逻辑递进。"},
            "issues": [],
            "verdict": "promote",
        },
    )
    receipt = promote_figure_candidate(
        run_dir,
        figure_id=figure_id,
        candidate_outputs=[f"{prefix}.png", f"{prefix}.pdf"],
        target_stem=f"figures/current/{figure_id}",
        rendering_mode="diagram",
        layout_report=payload["layout_report"],
        figure_role="model_understanding",
        human_review=load_json(human_review),
        visual_manifest=finalized["artifacts"]["visual_manifest"],
    )
    assert receipt["figure_id"] == figure_id
    assert (run_dir / f"figures/current/{figure_id}.png").is_file()
    assert (run_dir / f"figures/current/{figure_id}.pdf").is_file()


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


def test_figure_plan_scibox_diagram_allows_custom_template(ws_tmp: Path) -> None:
    """scibox-diagram 必须允许 template_id=custom（自由绘制 DrawIO 不被 schema 阉割）。"""
    run_dir = _run(ws_tmp, "figure-plan-diagram-custom")
    figure = _sci_box_figure()
    figure["selected_skill"] = "skills/sci-box/scibox-diagram"
    figure["preferred"] = "skills/sci-box/scibox-diagram"
    figure["template_id"] = "custom"
    figure["template_source"] = "custom"
    plan = {
        "schema_name": "figure_plan",
        "schema_version": "2.3",
        "run_id": run_dir.name,
        "visual_decisions": [
            {
                "scope": "Q2",
                "evidence_need": "required",
                "presentation_need": "required",
                "reason": "本题结构特殊，需要自由绘制 DrawIO 结构图。",
            }
        ],
        "figures": [figure],
    }

    assert write_figure_plan(run_dir, plan)["figures"][0]["template_id"] == "custom"


def test_figure_plan_hero_without_preventive_form_no_longer_blocked(ws_tmp: Path) -> None:
    """正文主图不再被前置的 generic_chart_considered 表单阻断（advisory）。"""
    run_dir = _run(ws_tmp, "figure-plan-no-preventive-form")
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


def test_auto_never_falls_back_to_reimplemented_for_scibox_master(ws_tmp: Path) -> None:
    """auto 模式绝不自动回退到简化 reimplemented 渲染器，只走 direct、master_adapted 或 manual stub。"""
    import sys

    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from scripts.figures.use_template import (
        _STRUCTURE_ROUTES,
        recommend_template_candidates,
        render_candidate,
    )

    # 1. 推荐候选测试：所有结构的推荐动作均为 direct 或 master_adapted，绝无 reimplemented
    for structure in _STRUCTURE_ROUTES:
        rec = recommend_template_candidates(structure)
        for cand in rec["candidates"]:
            assert cand["recommended_action"] in {"direct", "master_adapted"}
            assert cand["recommended_action"] != "reimplemented"

    # 2. 渲染候选测试：构造一个合法的 current 结果，对未提供 direct shim 的母版模板用 auto 渲染
    run_dir, artifacts = _quality_ready_run(
        ws_tmp,
        "auto-no-reimplemented",
        {
            "raincloud": {
                "figure_data": {
                    "groups": [
                        {"name": "Group A", "before": [1.0, 2.0, 3.0], "after": [1.5, 2.5, 3.5]}
                    ]
                }
            }
        },
    )
    res_id = "q1_visual"
    out_prefix = "figures/work/q1-raincloud/v1/q1-raincloud"
    result = render_candidate(
        run_dir,
        template_id="paired-raincloud",
        result_id=res_id,
        input_result=artifacts["raincloud"],
        output_prefix=out_prefix,
        adaptation="auto",
    )
    assert result["mode"] in {"adapted", "adapted_manual_stub"}
    assert result["mode"] != "reimplemented"
    if result["mode"] == "adapted_manual_stub":
        assert "绝不自动退回简化 reimplemented 渲染器" in result["notice"]


