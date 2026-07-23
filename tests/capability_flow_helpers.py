"""为 v3 测试建立能力路由、图表合同和模板入口的最小真实边界。"""

from __future__ import annotations

from pathlib import Path

from shumozizi.paper.templates import materialize_selected_template, select_paper_template
from shumozizi.simple.capabilities import (
    record_knowledge_consumption,
    write_capability_route,
    write_local_tooling,
)
from shumozizi.simple.state import read_simple_state, update_simple_state
from shumozizi.simple.visualization import (
    new_visualization_plan,
    run_figure_render,
    write_visualization_plan,
)


def prepare_minimal_capability_route(run_dir: Path) -> None:
    """登记无需独立 oracle 的最小本地能力路由并进入实验阶段。"""
    state = read_simple_state(run_dir)
    if state["phase"] in {"analysis", "blocked"}:
        update_simple_state(run_dir, phase="capability_route")
    write_local_tooling(run_dir)
    write_capability_route(
        run_dir,
        {
            "schema_version": "1.2",
            "problem_families": ["other"],
            "capabilities": [
                {
                    "id": "general-modeling",
                    "reason": "测试夹具只验证工作流边界，不声明额外题型风险。",
                }
            ],
            "verification_capability": None,
            "toolchain": {
                "production_engine": "python",
            },
            "knowledge_assets": ["knowledge/cards/structural-preflight.json"],
        },
    )
    record_knowledge_consumption(run_dir)
    if read_simple_state(run_dir)["phase"] == "capability_route":
        update_simple_state(run_dir, phase="experiment")


def prepare_minimal_visualization(run_dir: Path) -> None:
    """登记一张方法路线图，满足无专门题型夹具的可视化阶段边界。"""
    state = read_simple_state(run_dir)
    if state["phase"] == "scientific_review":
        update_simple_state(run_dir, phase="visualization")
    script = run_dir / "code" / "figures" / "workflow_visual.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "from PIL import Image\n"
        "from pathlib import Path\n"
        "import sys\n"
        "Path(sys.argv[1]).parent.mkdir(parents=True, exist_ok=True)\n"
        "Image.new('RGB', (320, 240), color=(48, 98, 148)).save(sys.argv[1])\n",
        encoding="utf-8",
    )
    output = run_dir / "figures" / "workflow-roadmap.png"
    receipt = run_figure_render(
        run_dir,
        figure_id="workflow-roadmap",
        engine="python",
        rendering_mode="diagram",
        script_path="code/figures/workflow_visual.py",
        input_paths=["state/DECISIONS.md"],
        output_paths=[output.relative_to(run_dir).as_posix()],
        arguments=[output.relative_to(run_dir).as_posix()],
    )
    payload = new_visualization_plan(
        run_dir,
        [
            {
                "figure_id": "workflow-roadmap",
                "question_id": "shared",
                "scientific_question": "当前运行的模型、执行和交付证据如何衔接。",
                "conclusion_impact": "context",
                "why_needed": "最小夹具只需说明证据在分析、实验和交付之间的衔接。",
                "evidence_roles": ["method_overview"],
                "evidence_modes": ["workflow_overview"],
                "evidence_scope": "method_structure",
                "status": "complete",
                "render_receipt": receipt,
            }
        ],
    )
    write_visualization_plan(run_dir, payload)


def prepare_cumcm_template(run_dir: Path) -> None:
    """在进入写作前实例化真实 CUMCM Typst 模板。"""
    state = read_simple_state(run_dir)
    if state["competition"] != "cumcm":
        update_simple_state(run_dir, competition="cumcm")
    if not state["required_questions"]:
        # 该夹具只构造最小论文边界；真实运行必须在分析阶段登记全部必答问题。
        update_simple_state(run_dir, required_questions=["Q1"])
    select_paper_template(
        run_dir,
        language="zh",
        engine="typst",
        selection_reason="测试运行按 CUMCM 中文稿使用仓内完整 Typst 模板。",
    )
    materialize_selected_template(run_dir)
