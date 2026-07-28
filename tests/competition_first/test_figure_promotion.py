"""验证论文图先生成候选、检查版式，再晋级 current。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfWriter

from shumozizi.core.io import ContractError, atomic_json
from shumozizi.simple.capabilities import write_local_tooling
from shumozizi.simple.figure_promotion import (
    audit_figure_candidate,
    promote_figure_candidate,
)
from shumozizi.simple.figures import register_insight_figure
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.results import register_result
from shumozizi.simple.state import utc_now
from shumozizi.simple.visualization import run_figure_render


def _candidate(tmp_path: Path, *, collision: bool) -> tuple[Path, list[str], str]:
    """创建同尺寸 PNG/PDF 和可选箭头穿字的流程图几何报告。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "figure-candidate-collision" if collision else "figure-candidate-valid",
        workflow_version="3.2",
    )
    folder = run_dir / "figures/candidates/overall-workflow/v1"
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
    return run_dir, outputs, layout.relative_to(run_dir).as_posix()


def test_diagram_arrow_text_collision_blocks_promotion(tmp_path: Path) -> None:
    """箭头穿过文字时，即使文件可打开也不能进入论文。"""
    run_dir, outputs, layout = _candidate(tmp_path, collision=True)

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
    run_dir, outputs, layout = _candidate(tmp_path, collision=False)

    with pytest.raises(ContractError, match="人工检查"):
        promote_figure_candidate(
            run_dir,
            figure_id="overall-workflow",
            candidate_outputs=outputs,
            target_stem="figures/current/overall-paper-workflow",
            rendering_mode="diagram",
            layout_report=layout,
            human_reviewed=False,
            human_review_notes="",
        )
    receipt = promote_figure_candidate(
        run_dir,
        figure_id="overall-workflow",
        candidate_outputs=outputs,
        target_stem="figures/current/overall-paper-workflow",
        rendering_mode="diagram",
        layout_report=layout,
        human_reviewed=True,
        human_review_notes="已分别检查 PNG 与 PDF，文字、箭头和留白均正常。",
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
            human_reviewed=True,
            human_review_notes="重复检查同一个候选版本不应覆盖既有晋级回执。",
        )


def test_v32_registration_requires_promotion_receipt(tmp_path: Path) -> None:
    """current 文件存在还不够，v3.2 图索引必须绑定候选晋级证据。"""
    run_dir, outputs, layout = _candidate(tmp_path, collision=False)
    promotion = promote_figure_candidate(
        run_dir,
        figure_id="overall-workflow",
        candidate_outputs=outputs,
        target_stem="figures/current/overall-paper-workflow",
        rendering_mode="diagram",
        layout_report=layout,
        human_reviewed=True,
        human_review_notes="已分别检查 PNG 与 PDF，流程节点、文字和箭头均清晰。",
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
    entry = register_insight_figure(
        run_dir,
        promotion_receipt=promotion["receipt"]["path"],
        **common,
    )

    assert entry["promotion_receipt"]["path"] == promotion["receipt"]["path"]


def test_v32_render_never_overwrites_candidate_version(tmp_path: Path) -> None:
    """候选渲染必须换版本目录，不能覆盖已经看过的同名预览。"""
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
    output = "figures/candidates/workflow/v1/workflow.png"
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

    with pytest.raises(ContractError, match="新的 version 目录"):
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
