"""验证 v3.4 对象感知视觉路由与需求归并（8.2/8.3）。"""

from __future__ import annotations

from pathlib import Path

from shumozizi.core.io import atomic_json
from shumozizi.paper.visual_requirements import build_visual_requirements_from_paper
from shumozizi.simple.initialization import initialize_simple_run


def _routed_run(tmp_path: Path, *, unit_kind: str, outputs: list[dict]) -> Path:
    """构造声明数学对象 visual_outputs 的最小运行。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "object-aware-routing",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    atomic_json(
        run_dir / "analysis/MODELING_UNITS.json",
        {
            "schema_name": "modeling_units",
            "schema_version": "1.4",
            "run_id": run_dir.name,
            "units": [
                {
                    "unit_id": "u1",
                    "question_id": "Q1",
                    "unit_kind": unit_kind,
                    "core_question": True,
                    "visual_outputs": outputs,
                }
            ],
        },
    )
    atomic_json(
        run_dir / "paper/answer-map.json",
        {
            "answers": {
                "Q1": {
                    "primary_result_id": "result-q1",
                    "result_ids": ["result-q1"],
                    "objective_answer": {"result_id": "result-q1", "answer": "正式答案。"},
                }
            }
        },
    )
    return run_dir


def _contract(
    argument_unit_id: str,
    mathematical_object: str,
    required_data: list[str],
    *,
    role: str = "decisive_evidence",
) -> dict:
    """构造带数学对象的事前视觉合同。"""
    return {
        "argument_unit_id": argument_unit_id,
        "visual_question": "如何让评委直接看到该数学对象及其判定机制？",
        "takeaway": "该对象的可见性直接决定正式答案能否被理解。",
        "mathematical_object": mathematical_object,
        "argument_role": role,
        "candidate_archetypes": [],
        "required_visibility": ["threshold", "boundary"],
        "required_data": required_data,
        "output_path": f"results/raw/{argument_unit_id}.json",
    }


def test_periodic_contact_network_routes_to_spatial_backbone_not_flowchart(
    tmp_path: Path,
) -> None:
    """周期接触网络必须路由到空间+网络候选，禁止通用 flowchart（8.2）。"""
    run_dir = _routed_run(
        tmp_path,
        unit_kind="exact_oracle",
        outputs=[
            _contract(
                "q1-scene",
                "periodic_contact_network",
                [
                    "particles",
                    "wrapped_fragments",
                    "identity_map",
                    "contact_edges",
                    "electrodes",
                    "conductive_backbone",
                ],
            )
        ],
    )

    payload = build_visual_requirements_from_paper(run_dir)
    requirement = payload["requirements"][0]

    assert requirement["mathematical_object"] == "periodic_contact_network"
    archetype_ids = [item["id"] for item in requirement["preferred_archetypes"]]
    assert "spatial_contact_backbone_triptych" in archetype_ids
    assert "conductance_bar_chart" in requirement["forbidden_defaults"]
    assert "academic_flowchart" not in requirement["preferred_structures"]


def test_probability_transition_routes_to_threshold_curve(tmp_path: Path) -> None:
    """概率转变路由到阈值曲线，不路由到 model evolution schematic（8.2）。"""
    run_dir = _routed_run(
        tmp_path,
        unit_kind="simulation",
        outputs=[
            _contract(
                "q1-probability",
                "probability_transition",
                ["n", "successes", "trials", "wilson_low", "wilson_high", "threshold"],
            )
        ],
    )

    payload = build_visual_requirements_from_paper(run_dir)
    requirement = payload["requirements"][0]

    archetype_ids = [item["id"] for item in requirement["preferred_archetypes"]]
    assert "probability_threshold_curve" in archetype_ids
    assert "logistic_smooth_curve_only" in requirement["forbidden_defaults"]


def test_integer_feasible_region_routes_to_active_constraint_map(tmp_path: Path) -> None:
    """整数格点路由到可行域 archetype，不退回候选表（8.2）。"""
    run_dir = _routed_run(
        tmp_path,
        unit_kind="optimization",
        outputs=[
            _contract(
                "q1-region",
                "integer_feasible_region",
                [
                    "lattice_points",
                    "feasible_mask",
                    "constraint_margins",
                    "costs",
                    "selected_point",
                ],
            )
        ],
    )

    payload = build_visual_requirements_from_paper(run_dir)
    requirement = payload["requirements"][0]

    archetype_ids = [item["id"] for item in requirement["preferred_archetypes"]]
    assert "integer_feasible_region" in archetype_ids
    assert "candidate_table_only" in requirement["forbidden_defaults"]


def test_latex_tables_figures_and_formulas_generate_no_requirements(
    tmp_path: Path,
) -> None:
    """LaTeX 表格、已有图环境和纯公式段不能反向生成新图需求（8.3.1）。"""
    run_dir = _routed_run(
        tmp_path,
        unit_kind="evaluation",
        outputs=[
            _contract(
                "q1-aggregation",
                "shared_model_pipeline",
                ["stages", "relations"],
                role="model_understanding",
            )
        ],
    )
    (run_dir / "paper/longform-source.tex").write_text(
        "\\section{问题一}\n\n"
        "\\begin{table}[H]\n"
        "\\begin{tabular}{clcl}\n"
        "方案 & 成本 & 方案 & 成本 \\\\\n"
        "A & 1.0 & B & 2.0 \\\\\n"
        "\\end{tabular}\n"
        "\\end{table}\n\n"
        "\\includegraphics{figures/current/q1_aggregation.png}\n\n"
        "\\begin{equation}\n"
        "p^* = 8 V_{AL}^3 / 100\\% = 0.0113\n"
        "\\end{equation}\n",
        encoding="utf-8",
    )

    payload = build_visual_requirements_from_paper(run_dir)

    # 只保留事前合同一条需求；表格/图/公式段不产生新需求。
    assert payload["summary"]["total"] == 1
    assert payload["requirements"][0]["argument_unit_ids"] == ["q1-aggregation"]


def test_duplicate_object_paragraphs_merge_into_single_requirement(
    tmp_path: Path,
) -> None:
    """同一对象、角色和结果集合的重复段落必须归并（8.3.3/8.3.4）。"""
    run_dir = _routed_run(
        tmp_path,
        unit_kind="exact_oracle",
        outputs=[
            _contract(
                "q1-scene",
                "periodic_contact_network",
                [
                    "particles",
                    "wrapped_fragments",
                    "identity_map",
                    "contact_edges",
                    "electrodes",
                    "conductive_backbone",
                ],
            )
        ],
    )
    (run_dir / "paper/longform-source.tex").write_text(
        "\\section{问题一}\n\n"
        "回绕片段必须合并为同一物理粒子，由于身份不合并会产生伪接触边，"
        "接触网络与贯通路径都会改变。\n\n"
        "同一粒子的回绕片段若不合并身份，网络会多出虚假接触边，"
        "因为接触图多了一条不存在的边，导电骨架的判断会出错。\n",
        encoding="utf-8",
    )

    payload = build_visual_requirements_from_paper(run_dir)
    mechanism = [
        item for item in payload["requirements"] if item["purpose"] == "mechanism"
    ]

    assert len(mechanism) == 1
    assert len(mechanism[0]["argument_unit_ids"]) == 2
    assert "接触边" in mechanism[0]["claim"]


def test_clean_extraction_strips_noise_but_keeps_semantics() -> None:
    """清洗保留可读断言，同时删除表格 token 与引用标签。"""
    from shumozizi.paper.visual_requirements import _clean_extraction_text

    cleaned = _clean_extraction_text(
        "\\begin{itemize} 关键差异 tab:answer-overview 是 $p^*=0.90$ "
        "\\textwidth 阈值；\\ref{fig:q1} 决定方案切换。\\end{itemize}"
    )
    assert "阈值" in cleaned
    assert "tab:" not in cleaned
    assert "\\textwidth" not in cleaned
    assert "$" not in cleaned
