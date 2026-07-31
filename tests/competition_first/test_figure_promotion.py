"""验证论文图先生成候选、检查版式，再晋级 current。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfWriter

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.simple.capabilities import write_local_tooling
from shumozizi.simple.figure_promotion import (
    audit_figure_candidate,
    promote_figure_candidate,
)
from shumozizi.simple.figures import (
    read_figure_index,
    register_insight_figure,
    register_presentation_figure,
    verify_current_figure_files,
)
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.results import register_result
from shumozizi.simple.state import utc_now
from shumozizi.simple.visualization import run_figure_render


def _human_review(**overrides: object) -> dict[str, object]:
    """构造通过所有角色检查的内容化人工复核。"""
    review: dict[str, object] = {
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
        "focal_claim": "最终方案由图中可见的活跃约束与决策点共同支持。",
        "visible_elements": [
            {"type": "selected_point", "label": "Final plan", "panel": "main"}
        ],
        "reading_order": ["main"],
        "panel_takeaways": {"main": "最终方案位于当前约束允许的有效区域内。"},
        "issues": [],
        "verdict": "promote",
    }
    review.update(overrides)
    return review


def _write_manifest(
    run_dir: Path,
    png: Path,
    *,
    panels: list[str] | None = None,
    elements: list[dict[str, object]] | None = None,
) -> str:
    """写入与当前候选 PNG 哈希绑定的视觉元素清单。"""
    manifest = png.parent / "visual_manifest.json"
    normalized_elements = elements or [
        {
            "type": "selected_point",
            "label": "Final plan",
            "panel": "main",
            "bbox": [0.4, 0.4, 0.6, 0.6],
            "paper_width_visible": True,
        }
    ]
    atomic_json(
        manifest,
        {
            "schema_version": "1.0",
            "output_sha256": sha256_file(png),
            "canvas": {"width": 400, "height": 200},
            "panels": panels or ["main"],
            "labels": [str(item["label"]) for item in normalized_elements],
            "elements": normalized_elements,
        },
    )
    return manifest.relative_to(run_dir).as_posix()


def _candidate(tmp_path: Path, *, collision: bool) -> tuple[Path, list[str], str, str]:
    """创建同尺寸 PNG/PDF 和可选箭头穿字的流程图几何报告。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "figure-candidate-collision" if collision else "figure-candidate-valid",
        workflow_version="3.2",
    )
    folder = run_dir / "figures/work/overall-workflow/v1"
    folder.mkdir(parents=True)
    png = folder / "overall-workflow.png"
    pdf = folder / "overall-workflow.pdf"
    Image.new("RGB", (400, 200), color="white").save(png)
    writer = PdfWriter()
    writer.add_blank_page(width=400, height=200)
    with pdf.open("wb") as stream:
        writer.write(stream)
    text_boxes = [
        {
            "id": "source-text",
            "node_id": "source",
            "x": 15,
            "y": 38,
            "width": 70,
            "height": 20,
            "font_size_pt": 10,
        },
        {
            "id": "target-text",
            "node_id": "target",
            "x": 315,
            "y": 38,
            "width": 70,
            "height": 20,
            "font_size_pt": 10,
        },
    ]
    if collision:
        text_boxes.append(
            {
                "id": "crossed-text",
                "x": 180,
                "y": 120,
                "width": 40,
                "height": 20,
                "font_size_pt": 10,
            }
        )
    layout = folder / "layout.json"
    atomic_json(
        layout,
        {
            "schema_version": "1.0",
            "figure_id": "overall-workflow",
            "canvas": {"width": 400, "height": 200},
            "node_boxes": [
                {"id": "source", "x": 0, "y": 20, "width": 100, "height": 60},
                {"id": "target", "x": 300, "y": 20, "width": 100, "height": 60},
            ],
            "text_boxes": text_boxes,
            "arrows": [
                {
                    "id": "source-to-target",
                    "source_node_id": "source",
                    "target_node_id": "target",
                    "points": [[100, 50], [100, 130], [300, 130], [300, 50]],
                }
            ],
            "alignment_tolerance_px": 4,
        },
    )
    outputs = [
        png.relative_to(run_dir).as_posix(),
        pdf.relative_to(run_dir).as_posix(),
    ]
    manifest = _write_manifest(run_dir, png)
    return run_dir, outputs, layout.relative_to(run_dir).as_posix(), manifest


def _promote_plot(
    run_dir: Path,
    figure_id: str,
    *,
    figure_role: str,
    presentation_role: str | None = None,
) -> dict[str, object]:
    """创建并晋级一张用于索引兼容测试的空白图。"""
    folder = run_dir / f"figures/work/{figure_id}/v1"
    folder.mkdir(parents=True)
    png = folder / f"{figure_id}.png"
    pdf = folder / f"{figure_id}.pdf"
    Image.new("RGB", (400, 200), color="white").save(png)
    writer = PdfWriter()
    writer.add_blank_page(width=400, height=200)
    with pdf.open("wb") as stream:
        writer.write(stream)
    layout = folder / f"{figure_id}.layout.json"
    atomic_json(
        layout,
        {
            "schema_version": "1.0",
            "figure_id": figure_id,
            "paper_size_cm": {"width": 17.0, "height": 8.5},
            "minimum_font_size_pt": 9.0,
            "colorblind_safe": True,
            "locale_consistent": True,
            "primary_panel_id": "main",
            "axes": [
                {
                    "id": "main",
                    "role": "primary",
                    "x_limits": [0.0, 10.0],
                    "x_data_range": [1.0, 9.0],
                    "y_limits": [0.0, 5.0],
                    "y_data_range": [0.5, 4.5],
                    "legend_overlaps_data": False,
                    "takeaway_annotation": True,
                    "decision_markers_labeled": True,
                }
            ],
        },
    )
    manifest = _write_manifest(run_dir, png)
    return promote_figure_candidate(
        run_dir,
        figure_id=figure_id,
        candidate_outputs=[
            png.relative_to(run_dir).as_posix(),
            pdf.relative_to(run_dir).as_posix(),
        ],
        target_stem=f"figures/current/{figure_id}",
        rendering_mode="plot",
        layout_report=layout.relative_to(run_dir).as_posix(),
        figure_role=figure_role,
        presentation_role=presentation_role,
        human_review=_human_review(),
        visual_manifest=manifest,
    )


def test_plot_layout_blocks_wasted_axis_and_covered_takeaway(tmp_path: Path) -> None:
    """普通统计图的轴域浪费和图例遮挡必须在晋级前被拒绝。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "plot-layout-invalid",
        workflow_version="3.2",
    )
    folder = run_dir / "figures/work/poor-plot/v1"
    folder.mkdir(parents=True)
    png = folder / "poor-plot.png"
    pdf = folder / "poor-plot.pdf"
    Image.new("RGB", (600, 400), color="white").save(png)
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=400)
    with pdf.open("wb") as stream:
        writer.write(stream)
    layout = folder / "poor-plot.layout.json"
    atomic_json(
        layout,
        {
            "schema_version": "1.0",
            "figure_id": "poor-plot",
            "paper_size_cm": {"width": 17.0, "height": 11.3},
            "minimum_font_size_pt": 7.0,
            "colorblind_safe": False,
            "locale_consistent": True,
            "primary_panel_id": "main",
            "axes": [
                {
                    "id": "main",
                    "role": "primary",
                    "x_limits": [0.0, 1.0],
                    "x_data_range": [0.1, 0.9],
                    "y_limits": [0.0, 1.0],
                    "y_data_range": [0.80, 0.95],
                    "legend_overlaps_data": True,
                    "takeaway_annotation": False,
                    "decision_markers_labeled": False,
                }
            ],
        },
    )

    audit = audit_figure_candidate(
        run_dir,
        figure_id="poor-plot",
        candidate_outputs=[
            png.relative_to(run_dir).as_posix(),
            pdf.relative_to(run_dir).as_posix(),
        ],
        rendering_mode="plot",
        layout_report=layout.relative_to(run_dir).as_posix(),
    )

    assert audit["success"] is False
    assert any("纵轴数据占用率" in error for error in audit["errors"])
    assert any("图例遮挡" in error for error in audit["errors"])
    assert any("最小字号" in error for error in audit["errors"])


def test_spatial_plot_requires_equal_scale_orthographic_metadata(tmp_path: Path) -> None:
    """三维图必须声明单位、视角和等比例，避免透视拉伸制造相交错觉。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "spatial-layout-invalid",
        workflow_version="3.2",
    )
    folder = run_dir / "figures/work/spatial-scene/v1"
    folder.mkdir(parents=True)
    png = folder / "spatial-scene.png"
    pdf = folder / "spatial-scene.pdf"
    Image.new("RGB", (600, 400), color="white").save(png)
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=400)
    with pdf.open("wb") as stream:
        writer.write(stream)
    layout = folder / "spatial-scene.layout.json"
    atomic_json(
        layout,
        {
            "schema_version": "1.1",
            "figure_id": "spatial-scene",
            "paper_size_cm": {"width": 18.0, "height": 12.0},
            "minimum_font_size_pt": 9.0,
            "colorblind_safe": True,
            "locale_consistent": True,
            "primary_panel_id": "overview",
            "axes": [
                {
                    "id": "overview",
                    "role": "primary",
                    "projection": "3d",
                    "x_limits": [-1.0, 4.0],
                    "x_data_range": [0.0, 3.0],
                    "y_limits": [-1.0, 4.0],
                    "y_data_range": [0.0, 3.0],
                    "z_limits": [-1.0, 4.0],
                    "z_data_range": [0.0, 3.0],
                    "data_aspect_ratio": [1.0, 1.0, 2.0],
                    "camera_projection": "perspective",
                    "camera_view": {"azimuth": 35.0, "elevation": 25.0},
                    "coordinate_unit": "",
                    "trajectory_direction_labeled": False,
                    "legend_overlaps_data": False,
                    "takeaway_annotation": True,
                    "decision_markers_labeled": True,
                }
            ],
        },
    )

    audit = audit_figure_candidate(
        run_dir,
        figure_id="spatial-scene",
        candidate_outputs=[
            png.relative_to(run_dir).as_posix(),
            pdf.relative_to(run_dir).as_posix(),
        ],
        rendering_mode="plot",
        layout_report=layout.relative_to(run_dir).as_posix(),
    )

    assert audit["success"] is False
    assert any("等比例" in error for error in audit["errors"])
    assert any("正交投影" in error for error in audit["errors"])
    assert any("坐标单位" in error for error in audit["errors"])
    assert any("轨迹方向" in error for error in audit["errors"])


def test_diagram_arrow_text_collision_blocks_promotion(tmp_path: Path) -> None:
    """箭头穿过文字时，即使文件可打开也不能进入论文。"""
    run_dir, outputs, layout, _ = _candidate(tmp_path, collision=True)

    audit = audit_figure_candidate(
        run_dir,
        figure_id="overall-workflow",
        candidate_outputs=outputs,
        rendering_mode="diagram",
        layout_report=layout,
    )

    assert audit["success"] is False
    assert any("穿过文字 crossed-text" in error for error in audit["errors"])


def test_valid_candidate_requires_human_review_and_unique_version(tmp_path: Path) -> None:
    """机械检查通过后仍需人工看 PNG/PDF，且同一版本不能反复覆盖。"""
    run_dir, outputs, layout, manifest = _candidate(tmp_path, collision=False)

    with pytest.raises(ContractError, match="角色内容检查"):
        promote_figure_candidate(
            run_dir,
            figure_id="overall-workflow",
            candidate_outputs=outputs,
            target_stem="figures/current/overall-paper-workflow",
            rendering_mode="diagram",
            layout_report=layout,
            figure_role="model_understanding",
            human_review=_human_review(reviewed=False),
            visual_manifest=manifest,
        )
    receipt = promote_figure_candidate(
        run_dir,
        figure_id="overall-workflow",
        candidate_outputs=outputs,
        target_stem="figures/current/overall-paper-workflow",
        rendering_mode="diagram",
        layout_report=layout,
        figure_role="model_understanding",
        human_review=_human_review(),
        visual_manifest=manifest,
    )

    assert receipt["qa"]["success"] is True
    assert (run_dir / "figures/current/overall-paper-workflow.png").is_file()
    assert (run_dir / "figures/current/overall-paper-workflow.pdf").is_file()
    with pytest.raises(ContractError, match="已经晋级"):
        promote_figure_candidate(
            run_dir,
            figure_id="overall-workflow",
            candidate_outputs=outputs,
            target_stem="figures/current/overall-paper-workflow",
            rendering_mode="diagram",
            layout_report=layout,
            figure_role="model_understanding",
            human_review=_human_review(),
            visual_manifest=manifest,
        )


def test_human_review_requires_content_fields_for_declared_role(tmp_path: Path) -> None:
    """人工勾选不能替代角色内容检查，insight 图必须真实显示机制。"""
    run_dir, outputs, layout, manifest = _candidate(tmp_path, collision=False)
    incomplete = _human_review()
    del incomplete["paper_width_preview_checked"]

    with pytest.raises(ContractError, match="缺少内容化字段"):
        promote_figure_candidate(
            run_dir,
            figure_id="overall-workflow",
            candidate_outputs=outputs,
            target_stem="figures/current/overall-paper-workflow",
            rendering_mode="diagram",
            layout_report=layout,
            figure_role="insight",
            human_review=incomplete,
            visual_manifest=manifest,
        )
    with pytest.raises(ContractError, match="mechanism_or_relation_visible"):
        promote_figure_candidate(
            run_dir,
            figure_id="overall-workflow",
            candidate_outputs=outputs,
            target_stem="figures/current/overall-paper-workflow",
            rendering_mode="diagram",
            layout_report=layout,
            figure_role="insight",
            human_review=_human_review(mechanism_or_relation_visible=False),
            visual_manifest=manifest,
        )


def test_advanced_custom_figure_requires_visual_manifest(tmp_path: Path) -> None:
    """高级 custom 图不能只靠人工勾选而缺少 renderer 元素清单。"""
    run_dir, outputs, layout, _ = _candidate(tmp_path, collision=False)

    with pytest.raises(ContractError, match="缺少 renderer 生成的 visual_manifest"):
        promote_figure_candidate(
            run_dir,
            figure_id="overall-workflow",
            candidate_outputs=outputs,
            target_stem="figures/current/no-manifest",
            rendering_mode="diagram",
            layout_report=layout,
            figure_role="insight",
            human_review=_human_review(),
        )


def test_claimed_threshold_must_exist_in_visual_manifest(tmp_path: Path) -> None:
    """人工声称阈值可见时，manifest 必须有同面板同类型标签。"""
    run_dir, outputs, layout, manifest = _candidate(tmp_path, collision=False)
    review = _human_review(
        visible_elements=[
            {"type": "decision_threshold", "label": "Safety threshold", "panel": "main"}
        ]
    )

    with pytest.raises(ContractError, match="可见元素未出现在 visual_manifest"):
        promote_figure_candidate(
            run_dir,
            figure_id="overall-workflow",
            candidate_outputs=outputs,
            target_stem="figures/current/missing-threshold",
            rendering_mode="diagram",
            layout_report=layout,
            figure_role="insight",
            human_review=review,
            visual_manifest=manifest,
        )


def test_visual_manifest_hash_must_match_candidate_png(tmp_path: Path) -> None:
    """旧图或手改清单不能借用当前候选的人工回执。"""
    run_dir, outputs, layout, manifest = _candidate(tmp_path, collision=False)
    document = load_json(run_dir / manifest)
    document["output_sha256"] = "0" * 64
    atomic_json(run_dir / manifest, document)

    with pytest.raises(ContractError, match="output_sha256 与当前候选 PNG 不一致"):
        promote_figure_candidate(
            run_dir,
            figure_id="overall-workflow",
            candidate_outputs=outputs,
            target_stem="figures/current/stale-manifest",
            rendering_mode="diagram",
            layout_report=layout,
            figure_role="insight",
            human_review=_human_review(),
            visual_manifest=manifest,
        )


def test_learned_visual_elements_must_exist_in_manifest_and_human_review(
    tmp_path: Path,
) -> None:
    """论文视觉模式承诺的元素必须在最终图和人工复核中同时出现。"""
    run_dir, outputs, layout, manifest = _candidate(tmp_path, collision=False)
    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "figures": [
                {
                    "figure_id": "overall-workflow",
                    "learned_pattern_ids": ["paper-1:V1"],
                }
            ]
        },
    )
    atomic_json(
        run_dir / "knowledge/analysis-retrieval.json",
        {
            "matched_cards": [
                {
                    "visual_patterns": [
                        {
                            "pattern_id": "paper-1:V1",
                            "visible_elements": ["selected_point", "active_constraint"],
                        }
                    ]
                }
            ]
        },
    )

    with pytest.raises(ContractError, match="未出现在 visual_manifest"):
        promote_figure_candidate(
            run_dir,
            figure_id="overall-workflow",
            candidate_outputs=outputs,
            target_stem="figures/current/overall-workflow",
            rendering_mode="diagram",
            layout_report=layout,
            figure_role="model_understanding",
            human_review=_human_review(),
            visual_manifest=manifest,
        )

    png = run_dir / outputs[0]
    manifest = _write_manifest(
        run_dir,
        png,
        elements=[
            {
                "type": "selected_point",
                "label": "Final plan",
                "panel": "main",
                "bbox": [0.4, 0.4, 0.6, 0.6],
                "paper_width_visible": True,
            },
            {
                "type": "active_constraint",
                "label": "Capacity boundary",
                "panel": "main",
                "bbox": [0.1, 0.2, 0.8, 0.3],
                "paper_width_visible": True,
            },
        ],
    )
    receipt = promote_figure_candidate(
        run_dir,
        figure_id="overall-workflow",
        candidate_outputs=outputs,
        target_stem="figures/current/overall-workflow",
        rendering_mode="diagram",
        layout_report=layout,
        figure_role="model_understanding",
        human_review=_human_review(
            visible_elements=[
                {"type": "selected_point", "label": "Final plan", "panel": "main"},
                {
                    "type": "active_constraint",
                    "label": "Capacity boundary",
                    "panel": "main",
                },
            ]
        ),
        visual_manifest=manifest,
    )

    assert "active_constraint" in receipt["visual_manifest"]["verified_element_types"]


def test_reading_order_panel_must_exist_in_manifest(tmp_path: Path) -> None:
    """阅读顺序不能引用 renderer 未生成的面板。"""
    run_dir, outputs, layout, manifest = _candidate(tmp_path, collision=False)
    review = _human_review(
        reading_order=["main", "B"],
        panel_takeaways={
            "main": "最终方案位于当前约束允许的有效区域内。",
            "B": "第二面板应解释活跃约束的边际影响。",
        },
    )

    with pytest.raises(ContractError, match="不存在的面板: B"):
        promote_figure_candidate(
            run_dir,
            figure_id="overall-workflow",
            candidate_outputs=outputs,
            target_stem="figures/current/missing-panel",
            rendering_mode="diagram",
            layout_report=layout,
            figure_role="insight",
            human_review=review,
            visual_manifest=manifest,
        )


def test_visual_manifest_rejects_out_of_canvas_bbox(tmp_path: Path) -> None:
    """元素定位越出归一化画布时不得晋级。"""
    run_dir, outputs, layout, _ = _candidate(tmp_path, collision=False)
    png = run_dir / outputs[0]
    manifest = _write_manifest(
        run_dir,
        png,
        elements=[
            {
                "type": "selected_point",
                "label": "Final plan",
                "panel": "main",
                "bbox": [0.4, 0.4, 1.2, 0.6],
                "paper_width_visible": True,
            }
        ],
    )

    with pytest.raises(ContractError, match="bbox 超出画布"):
        promote_figure_candidate(
            run_dir,
            figure_id="overall-workflow",
            candidate_outputs=outputs,
            target_stem="figures/current/outside-bbox",
            rendering_mode="diagram",
            layout_report=layout,
            figure_role="insight",
            human_review=_human_review(),
            visual_manifest=manifest,
        )


def test_dense_multi_panel_manifest_can_be_promoted(tmp_path: Path) -> None:
    """高密度四面板只要元素和阅读链真实对应即可晋级。"""
    run_dir, outputs, layout, _ = _candidate(tmp_path, collision=False)
    png = run_dir / outputs[0]
    panels = ["A", "B", "C", "D"]
    elements = [
        {
            "type": "panel_takeaway",
            "label": f"Evidence {panel}",
            "panel": panel,
            "bbox": [0.1, 0.1, 0.3, 0.2],
            "paper_width_visible": True,
        }
        for panel in panels
    ]
    manifest = _write_manifest(run_dir, png, panels=panels, elements=elements)
    review = _human_review(
        focal_claim="四个面板依次连接数据结构、模型约束、比较证据与最终决策。",
        visible_elements=[
            {"type": "panel_takeaway", "label": "Evidence D", "panel": "D"}
        ],
        reading_order=panels,
        panel_takeaways={
            panel: f"面板 {panel} 提供当前证据链中的独立且可核对结论。"
            for panel in panels
        },
    )

    receipt = promote_figure_candidate(
        run_dir,
        figure_id="overall-workflow",
        candidate_outputs=outputs,
        target_stem="figures/current/dense-evidence-chain",
        rendering_mode="diagram",
        layout_report=layout,
        figure_role="insight",
        human_review=review,
        visual_manifest=manifest,
    )

    assert receipt["schema_version"] == "1.2"
    assert receipt["visual_manifest"]["panels"] == panels


def test_v32_registration_requires_promotion_receipt(tmp_path: Path) -> None:
    """current 文件存在还不够，v3.2 图索引必须绑定候选晋级证据。"""
    run_dir, outputs, layout, manifest = _candidate(tmp_path, collision=False)
    promotion = promote_figure_candidate(
        run_dir,
        figure_id="overall-workflow",
        candidate_outputs=outputs,
        target_stem="figures/current/overall-paper-workflow",
        rendering_mode="diagram",
        layout_report=layout,
        figure_role="model_understanding",
        human_review=_human_review(),
        visual_manifest=manifest,
    )
    script = run_dir / "code/figures/overall-workflow.py"
    result_file = run_dir / "results/raw/workflow.json"
    script.parent.mkdir(parents=True, exist_ok=True)
    result_file.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("print('render')\n", encoding="utf-8")
    result_file.write_text(json.dumps({"nodes": 2}), encoding="utf-8")
    now = utc_now()
    register_result(
        run_dir,
        result_id="workflow-source",
        question_id="Q1",
        kind="workflow_source",
        command="python code/figures/overall-workflow.py",
        source_script="code/figures/overall-workflow.py",
        input_files=["code/figures/overall-workflow.py"],
        output_files=["results/raw/workflow.json"],
        metrics={},
        metric_sources={},
        exit_code=0,
        stdout_path="results/workflow.stdout.log",
        stderr_path="results/workflow.stderr.log",
        started_at=now,
        finished_at=now,
        duration_seconds=1.0,
        objective_semantics_sha256="d" * 64,
    )
    common = {
        "figure_id": "overall-workflow",
        "result_id": "workflow-source",
        "input_result": "results/raw/workflow.json",
        "renderer_script": "code/figures/overall-workflow.py",
        "outputs": [item["path"] for item in promotion["promoted_outputs"]],
        "question": "全篇模型与验证流程如何保持训练选择和外部评价隔离？",
        "takeaway": "路线只在训练内选择，冻结后验证折仅评价当前政策。",
        "role": "model_understanding",
        "placement": "body",
    }

    with pytest.raises(ContractError, match="promotion_receipt"):
        register_insight_figure(run_dir, **common)
    with pytest.raises(ContractError, match="当前角色"):
        register_insight_figure(
            run_dir,
            promotion_receipt=promotion["receipt"]["path"],
            **{**common, "role": "insight"},
        )
    entry = register_insight_figure(
        run_dir,
        promotion_receipt=promotion["receipt"]["path"],
        **common,
    )

    assert entry["promotion_receipt"]["path"] == promotion["receipt"]["path"]


def test_presentation_figure_binds_frozen_inputs_without_fake_result(tmp_path: Path) -> None:
    """数据画像可追溯到冻结输入，但不需要伪造实验 result_id。"""
    run_dir, outputs, layout, manifest = _candidate(tmp_path, collision=False)
    promotion = promote_figure_candidate(
        run_dir,
        figure_id="overall-workflow",
        candidate_outputs=outputs,
        target_stem="figures/current/data-portrait",
        rendering_mode="diagram",
        layout_report=layout,
        figure_role="model_understanding",
        presentation_role="data_portrait",
        human_review=_human_review(),
        visual_manifest=manifest,
    )
    source = run_dir / "analysis/DATA_AUDIT.json"
    script = run_dir / "code/figures/data_portrait.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('{"mothers": 267}\n', encoding="utf-8")
    script.write_text("print('render frozen data portrait')\n", encoding="utf-8")

    entry = register_presentation_figure(
        run_dir,
        figure_id="overall-workflow",
        source_files=["analysis/DATA_AUDIT.json"],
        renderer_script="code/figures/data_portrait.py",
        outputs=[item["path"] for item in promotion["promoted_outputs"]],
        question_id="whole_paper",
        question="重复测量与删失结构为什么决定后续模型选择？",
        takeaway="数据画像使统计单位、删失类型和标签稀缺性在模型前可见。",
        limitations="该图只描述当前附件结构，不产生新的模型数字或因果结论。",
        presentation_role="data_portrait",
        role="model_understanding",
        promotion_receipt=promotion["receipt"]["path"],
    )

    assert entry["provenance_type"] == "frozen_inputs"
    assert "result_id" not in entry
    assert verify_current_figure_files(run_dir, figure_stage="current")["success"] is True

    source.write_text('{"mothers": 268}\n', encoding="utf-8")
    stale = verify_current_figure_files(run_dir, figure_stage="current")
    assert stale["success"] is False
    assert any("哈希不一致" in item["message"] for item in stale["errors"])


def test_figure_index_13_supports_mixed_result_and_presentation_entries(
    tmp_path: Path,
) -> None:
    """1.3 索引升级后仍可继续登记结果图，且既有结果图保持有效。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "mixed-figure-index",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    script = run_dir / "code/figures/render.py"
    result_file = run_dir / "results/raw/source.json"
    portrait_source = run_dir / "analysis/DATA_AUDIT.json"
    script.parent.mkdir(parents=True, exist_ok=True)
    result_file.parent.mkdir(parents=True, exist_ok=True)
    portrait_source.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("print('render')\n", encoding="utf-8")
    result_file.write_text('{"score": 1}\n', encoding="utf-8")
    portrait_source.write_text('{"rows": 10}\n', encoding="utf-8")
    now = utc_now()
    register_result(
        run_dir,
        result_id="q1-source",
        question_id="Q1",
        kind="comparison",
        command="python code/figures/render.py",
        source_script="code/figures/render.py",
        input_files=["code/figures/render.py"],
        output_files=["results/raw/source.json"],
        metrics={},
        metric_sources={},
        exit_code=0,
        stdout_path="results/q1-source.stdout.log",
        stderr_path="results/q1-source.stderr.log",
        started_at=now,
        finished_at=now,
        duration_seconds=1.0,
        objective_semantics_sha256="e" * 64,
    )

    first = _promote_plot(run_dir, "q1-evidence", figure_role="decisive_evidence")
    register_insight_figure(
        run_dir,
        figure_id="q1-evidence",
        result_id="q1-source",
        input_result="results/raw/source.json",
        renderer_script="code/figures/render.py",
        outputs=[item["path"] for item in first["promoted_outputs"]],
        question="Q1 的关键比较结果是否稳定优于自然基线？",
        takeaway="统一评分下当前方案取得可复核的比较优势。",
        role="decisive_evidence",
        placement="body",
        promotion_receipt=first["receipt"]["path"],
    )

    portrait = _promote_plot(
        run_dir,
        "data-portrait",
        figure_role="model_understanding",
        presentation_role="data_portrait",
    )
    register_presentation_figure(
        run_dir,
        figure_id="data-portrait",
        source_files=["analysis/DATA_AUDIT.json"],
        renderer_script="code/figures/render.py",
        outputs=[item["path"] for item in portrait["promoted_outputs"]],
        question_id="whole_paper",
        question="数据结构中的重复测量和缺失模式是什么？",
        takeaway="数据画像在建模前明确统计单位与缺失边界。",
        limitations="该图仅描述冻结输入，不提供新的实验结论。",
        presentation_role="data_portrait",
        role="model_understanding",
        promotion_receipt=portrait["receipt"]["path"],
    )

    second = _promote_plot(run_dir, "q1-mechanism", figure_role="insight")
    register_insight_figure(
        run_dir,
        figure_id="q1-mechanism",
        result_id="q1-source",
        input_result="results/raw/source.json",
        renderer_script="code/figures/render.py",
        outputs=[item["path"] for item in second["promoted_outputs"]],
        question="Q1 的比较优势由哪个约束机制形成？",
        takeaway="结果图把最终优势与活跃约束直接对应。",
        role="insight",
        placement="body",
        promotion_receipt=second["receipt"]["path"],
    )

    index = read_figure_index(run_dir)
    assert index["schema_version"] == "1.3"
    assert [item["figure_id"] for item in index["figures"]] == [
        "q1-evidence",
        "data-portrait",
        "q1-mechanism",
    ]
    assert verify_current_figure_files(run_dir, figure_stage="current")["success"] is True


def test_v32_work_render_can_be_overwritten_during_iteration(tmp_path: Path) -> None:
    """work 区允许反复调试，只有晋级后的 current 才进入历史归档。"""
    run_dir = initialize_simple_run(
        tmp_path, "render-versioned-candidate", workflow_version="3.2"
    )
    write_local_tooling(run_dir)
    script = run_dir / "code/figures/render.py"
    source = run_dir / "analysis/source.json"
    script.parent.mkdir(parents=True, exist_ok=True)
    source.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "from PIL import Image\n"
        "from pathlib import Path\n"
        "import sys\n"
        "Path(sys.argv[1]).parent.mkdir(parents=True, exist_ok=True)\n"
        "Image.new('RGB', (40, 20), 'white').save(sys.argv[1])\n",
        encoding="utf-8",
    )
    source.write_text("{}\n", encoding="utf-8")
    output = "figures/work/workflow/v1/workflow.png"
    run_figure_render(
        run_dir,
        figure_id="workflow",
        engine="python",
        rendering_mode="diagram",
        script_path="code/figures/render.py",
        input_paths=["analysis/source.json"],
        output_paths=[output],
        arguments=[output],
    )

    second = run_figure_render(
        run_dir,
        figure_id="workflow",
        engine="python",
        rendering_mode="diagram",
        script_path="code/figures/render.py",
        input_paths=["analysis/source.json"],
        output_paths=[output],
        arguments=[output],
    )
    assert load_json(run_dir / second["path"])["outputs"][0]["path"] == output
