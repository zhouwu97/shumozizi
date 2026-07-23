"""为 v3 测试建立能力路由、图表合同和模板入口的最小真实边界。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from shumozizi.paper.templates import materialize_selected_template, select_paper_template
from shumozizi.simple.capabilities import write_capability_route, write_local_tooling
from shumozizi.simple.state import read_simple_state, update_simple_state, utc_now
from shumozizi.simple.visualization import new_visualization_plan, write_visualization_plan


def prepare_minimal_capability_route(run_dir: Path) -> None:
    """登记无需独立 oracle 的最小本地能力路由并进入实验阶段。"""
    state = read_simple_state(run_dir)
    if state["phase"] in {"analysis", "blocked"}:
        update_simple_state(run_dir, phase="capability_route")
    write_local_tooling(run_dir)
    write_capability_route(
        run_dir,
        {
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "status": "ready",
            "problem_families": ["other"],
            "primary_capability": {"id": "general-modeling", "reason": "测试夹具只验证工作流边界，不声明额外题型风险。"},
            "cross_capabilities": [],
            "verification_capability": None,
            "toolchain": {
                "production_engine": "python",
                "independent_engine": None,
                "independence_strategy": "not_required",
                "reason": "测试夹具只需要当前 Python 运行时执行最小输入。",
            },
            "knowledge_assets": [
                {
                    "path": "knowledge/cards/structural-preflight.json",
                    "purpose": "保留结构预检资产，确保路由验证真实本地知识路径。",
                }
            ],
            "created_at": utc_now(),
        },
    )
    if read_simple_state(run_dir)["phase"] == "capability_route":
        update_simple_state(run_dir, phase="experiment")


def prepare_minimal_visualization(run_dir: Path) -> None:
    """登记一张方法路线图，满足无专门题型夹具的可视化阶段边界。"""
    state = read_simple_state(run_dir)
    if state["phase"] == "scientific_review":
        update_simple_state(run_dir, phase="visualization")
    script = run_dir / "code" / "figures" / "workflow_visual.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("# 测试图示生成器\n", encoding="utf-8")
    output = run_dir / "figures" / "workflow-roadmap.png"
    Image.new("RGB", (320, 240), color=(48, 98, 148)).save(output)
    payload = new_visualization_plan(
        run_dir,
        [
            {
                "figure_id": "workflow-roadmap",
                "role": "method_roadmap",
                "question_id": "shared",
                "purpose": "说明测试运行的分析、实验、审查、可视化与写作衔接。",
                "evidence_scope": "method_structure",
                "source_paths": ["state/DECISIONS.md"],
                "rendering_mode": "diagram",
                "status": "complete",
                "outputs": ["figures/workflow-roadmap.png"],
                "generator": {"engine": "python", "script_path": "code/figures/workflow_visual.py"},
                "rationale": "最小夹具只声明 other 题型，因此路线图是唯一需要冻结的视觉证据。",
            }
        ],
    )
    write_visualization_plan(run_dir, payload)


def prepare_cumcm_template(run_dir: Path) -> None:
    """在进入写作前实例化真实 CUMCM Typst 模板。"""
    state = read_simple_state(run_dir)
    if state["competition"] != "cumcm":
        update_simple_state(run_dir, competition="cumcm")
    select_paper_template(
        run_dir,
        language="zh",
        engine="typst",
        selection_reason="测试运行按 CUMCM 中文稿使用仓内完整 Typst 模板。",
    )
    materialize_selected_template(run_dir)
