"""验证 v3.5 视觉数据可画性解析器与字段贯穿修复（P0/P1 接线）。

覆盖四类修复：

1. ``required_visibility`` 从事前 visual_outputs 贯穿到 requirement 与机会池。
2. ``candidate_archetypes`` 传真实 renderer archetype ID，而不是人类可读结构描述。
3. ``resolve_visual_data_availability`` 读取 production 结果工件判断
   ``available_fields / missing_fields / can_render``。
4. 路由分离：有确定性 renderer 的 decisive_evidence 不再被误送 academic_flowchart；
   ``data_missing`` 被明确暴露，禁止 silent fallback。
"""

from __future__ import annotations

from pathlib import Path

from shumozizi.core.io import atomic_json, load_json
from shumozizi.paper.visual_requirements import (
    VISUAL_REQUIREMENTS_PATH,
    build_visual_requirements_from_paper,
)
from shumozizi.simple.data_availability import (
    _DATA_MISSING,
    _DIRECT_RENDER,
    availability_for_requirement,
    resolve_visual_data_availability,
)
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.paper_image_prompts import build_paper_image_prompts


def _contract_run(
    tmp_path: Path,
    *,
    mathematical_object: str,
    archetype: str,
    required_data: list[str],
    required_visibility: list[str],
    artifact: dict,
    output_path: str = "results/raw/visual_output_artifact.json",
    result_id: str = "result-current",
    unit_kind: str = "simulation",
) -> Path:
    """构造声明对象视觉合同的最小运行，并写入 production 结果工件。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "data-availability",
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
                    "visual_outputs": [
                        {
                            "visual_question": "如何让评委直接看到该对象及其判定机制？",
                            "takeaway": "该对象的可见性直接决定正式答案能否被理解。",
                            "argument_unit_id": "u1-visual",
                            "mathematical_object": mathematical_object,
                            "argument_role": "decisive_evidence",
                            "candidate_archetypes": [archetype],
                            "required_visibility": required_visibility,
                            "required_data": required_data,
                            "output_path": output_path,
                        }
                    ],
                }
            ],
        },
    )
    atomic_json(
        run_dir / "paper/answer-map.json",
        {
            "answers": {
                "Q1": {
                    "primary_result_id": result_id,
                    "result_ids": [result_id],
                    "objective_answer": {"result_id": result_id, "answer": "正式答案。"},
                }
            }
        },
    )
    (run_dir / output_path).parent.mkdir(parents=True, exist_ok=True)
    atomic_json(run_dir / output_path, artifact)
    atomic_json(
        run_dir / "results/index.json",
        {
            "results": [
                {
                    "result_id": result_id,
                    "question_id": "Q1",
                    "status": "current",
                    "execution_valid": True,
                    "output_files": [output_path],
                    "metrics": {},
                }
            ]
        },
    )
    return run_dir


def _probability_artifact() -> dict:
    """Q2 风格概率转变工件：results[] 列表携带点估计与区间。"""
    return {
        "result_id": "result-current",
        "results": [
            {"volume_fraction": 0.5, "p_estimate": 0.0775, "ci_lower": 0.061, "ci_upper": 0.098},
            {"volume_fraction": 0.6, "p_estimate": 0.209, "ci_lower": 0.190, "ci_upper": 0.230},
        ],
    }


def test_required_visibility_and_archetype_ids_flow_to_opportunity(tmp_path: Path) -> None:
    """required_visibility 与 renderer archetype ID 必须贯穿到机会池（P0 修复）。"""
    run_dir = _contract_run(
        tmp_path,
        mathematical_object="probability_transition",
        archetype="probability_threshold_curve",
        required_data=["n", "successes", "trials", "wilson_low", "wilson_high", "threshold"],
        required_visibility=["wilson_interval", "threshold"],
        artifact=_probability_artifact(),
    )
    build_visual_requirements_from_paper(run_dir)
    pool = load_json(run_dir / "figures/visual-opportunities.json")
    item = pool["opportunities"][0]

    assert item["candidate_archetypes"] == ["probability_threshold_curve"]
    assert "probability curve with Wilson interval" not in " ".join(item["candidate_archetypes"])
    assert item["required_visibility"] == ["wilson_interval", "threshold"]
    assert item["required_data"] == [
        "n", "successes", "trials", "wilson_low", "wilson_high", "threshold",
    ]
    assert item["data_availability"]["decision"] == _DIRECT_RENDER


def test_required_visibility_carries_on_requirement(tmp_path: Path) -> None:
    """requirement 上必须保留 required_visibility，不因中途重建而丢失。"""
    run_dir = _contract_run(
        tmp_path,
        mathematical_object="probability_transition",
        archetype="probability_threshold_curve",
        required_data=["n", "successes", "trials", "wilson_low", "wilson_high", "threshold"],
        required_visibility=["wilson_interval", "threshold"],
        artifact=_probability_artifact(),
    )
    payload = build_visual_requirements_from_paper(run_dir)
    requirement = payload["requirements"][0]
    assert requirement["required_visibility"] == ["wilson_interval", "threshold"]


def test_resolver_can_render_when_production_artifact_complete(tmp_path: Path) -> None:
    """生产工件带齐必需语义字段时 can_render=True，决策为 direct_render。"""
    run_dir = _contract_run(
        tmp_path,
        mathematical_object="probability_transition",
        archetype="probability_threshold_curve",
        required_data=["n", "successes", "trials", "wilson_low", "wilson_high", "threshold"],
        required_visibility=["wilson_interval", "threshold"],
        artifact=_probability_artifact(),
    )
    result = resolve_visual_data_availability(
        run_dir,
        "Q1",
        ["result-current"],
        "probability_threshold_curve",
        mathematical_object="probability_transition",
    )
    assert result["can_render"] is True
    assert result["decision"] == _DIRECT_RENDER
    assert result["available_fields"] == ["x_values", "probability"]
    assert result["missing_fields"] == []


def test_resolver_data_missing_when_artifact_lacks_fields(tmp_path: Path) -> None:
    """生产工件缺少必需语义字段时 can_render=False，禁止 silent fallback。"""
    run_dir = _contract_run(
        tmp_path,
        mathematical_object="probability_transition",
        archetype="probability_threshold_curve",
        required_data=["n", "successes", "trials", "wilson_low", "wilson_high", "threshold"],
        required_visibility=["wilson_interval", "threshold"],
        artifact={"metrics": {"final_probability": 0.9}},
    )
    result = resolve_visual_data_availability(
        run_dir,
        "Q1",
        ["result-current"],
        "probability_threshold_curve",
        mathematical_object="probability_transition",
    )
    assert result["can_render"] is False
    assert result["decision"] == _DATA_MISSING
    assert set(result["missing_fields"]) >= {"x_values", "probability"}


def test_resolver_uses_visual_output_output_path_artifact(tmp_path: Path) -> None:
    """answer-map 主结果缺坐标时，visual_output output_path 工件可补足绘图原语。"""
    run_dir = _contract_run(
        tmp_path,
        mathematical_object="periodic_contact_network",
        archetype="spatial_contact_backbone_triptych",
        required_data=[
            "particles", "wrapped_fragments", "identity_map", "contact_edges",
            "electrodes", "conductive_backbone",
        ],
        required_visibility=["periodic_boundary", "contact_edges", "conductive_backbone"],
        artifact={
            "particles": [{"id": 1, "start": [0, 0, 0], "end": [1, 0, 0]}],
            "contact_edges": [{"first": 1, "second": 2}],
            "electrodes": [{"side": "left", "x": -1.0, "y": 0.0}],
            "conductive_backbone": [{"first": 1, "second": 2}],
            "identity_pairs": [{"first": 1, "second": 505, "axis": "x"}],
        },
        output_path="results/raw/q1_periodic_contact_scene.json",
        unit_kind="exact_oracle",
    )
    # answer-map 主结果工件不含坐标，但 visual_output output_path 工件有坐标。
    atomic_json(run_dir / "results/raw/result-current.json", {"metrics": {"conductive": 1}})
    payload = build_visual_requirements_from_paper(run_dir)
    requirement = payload["requirements"][0]
    assert requirement["source_artifact_paths"] == ["results/raw/q1_periodic_contact_scene.json"]
    availability = availability_for_requirement(run_dir, requirement)
    assert availability is not None
    assert availability["decision"] == _DIRECT_RENDER
    assert availability["available_fields"] == ["object_coordinates"]


def test_data_missing_is_exposed_on_opportunity_not_silently_faked(tmp_path: Path) -> None:
    """Q1 风格空间合同缺坐标时，机会池明确携带 data_missing 而非伪装已解决。"""
    run_dir = _contract_run(
        tmp_path,
        mathematical_object="periodic_contact_network",
        archetype="spatial_contact_backbone_triptych",
        required_data=["particles", "identity_map", "contact_edges", "conductive_backbone"],
        required_visibility=["periodic_boundary", "contact_edges"],
        artifact={"metrics": {"conductive_count": 1}},
        unit_kind="exact_oracle",
    )
    build_visual_requirements_from_paper(run_dir)
    pool = load_json(run_dir / "figures/visual-opportunities.json")
    item = pool["opportunities"][0]
    assert item["data_availability"]["decision"] == _DATA_MISSING
    assert "object_coordinates" in item["data_availability"]["missing_fields"]
    assert "不得用示意图冒充正式证据图" in item["data_availability"]["note"]


def test_decisive_evidence_with_renderer_routes_to_renderer_not_flowchart(
    tmp_path: Path,
) -> None:
    """有确定性 renderer 的 decisive_evidence 不再被误送 academic_flowchart。"""
    run_dir = _contract_run(
        tmp_path,
        mathematical_object="probability_transition",
        archetype="probability_threshold_curve",
        required_data=["n", "successes", "trials", "wilson_low", "wilson_high", "threshold"],
        required_visibility=["wilson_interval", "threshold"],
        artifact=_probability_artifact(),
    )
    payload = build_paper_image_prompts(run_dir, refresh_requirements=True)
    assert payload["renderer_handled_count"] >= 1
    handled_ids = {item["requirement_id"] for item in payload["renderer_handled"]}
    assert handled_ids
    planned_ids = {item["requirement_id"] for item in payload["planned"] if item.get("status") == "planned"}
    assert planned_ids.isdisjoint(handled_ids)
    assert all(
        item.get("renderer_archetype") == "probability_threshold_curve"
        for item in payload["renderer_handled"]
    )
    requirements = load_json(run_dir / VISUAL_REQUIREMENTS_PATH)
    opportunity = next(
        item["paper_image_opportunity"]
        for item in requirements["requirements"]
        if item["requirement_id"] in handled_ids
    )
    assert opportunity["production_status"] == "renderer_ready"
    assert opportunity["production_path"] == "deterministic_renderer"
    assert opportunity["recommended_visual_type"] is None


def test_ai_image_flowchart_only_when_no_deterministic_renderer(tmp_path: Path) -> None:
    """无确定性 renderer 的解释型需求仍走 academic_flowchart（保持既有行为）。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "ai-flowchart-only",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    # 无数学对象时路由到默认 mathematical_object_schematic（非确定性 renderer），
    # 因此该需求走 AI 解释图路径，而不是 renderer_ready。
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
                    "unit_kind": "coordination",
                    "core_question": True,
                    "visual_outputs": [
                        {
                            "visual_question": "资源如何经过分配和约束形成方案？",
                            "takeaway": "共享资源约束决定最终方案。",
                            "argument_unit_id": "u1-schedule",
                            "visual_archetype": "structure map",
                        }
                    ],
                }
            ],
        },
    )
    atomic_json(
        run_dir / "paper/answer-map.json",
        {
            "answers": {
                "Q1": {
                    "primary_result_id": "schedule-current",
                    "result_ids": ["schedule-current"],
                    "objective_answer": {"result_id": "schedule-current", "answer": "排班方案"},
                }
            }
        },
    )
    payload = build_visual_requirements_from_paper(run_dir)
    requirement = payload["requirements"][0]
    assert requirement["mathematical_object"] == ""
    opportunity = requirement["paper_image_opportunity"]
    assert opportunity["production_status"] == "planned"
    assert opportunity["recommended_visual_type"] == "academic_flowchart"
    assert opportunity["production_path"] == "ai_image"


def test_unknown_archetype_resolves_to_data_missing_not_crash(tmp_path: Path) -> None:
    """未登记 archetype 不崩溃，明确返回 data_missing。"""
    run_dir = _contract_run(
        tmp_path,
        mathematical_object="probability_transition",
        archetype="probability_threshold_curve",
        required_data=["n"],
        required_visibility=[],
        artifact=_probability_artifact(),
    )
    result = resolve_visual_data_availability(
        run_dir, "Q1", ["result-current"], "no_such_archetype"
    )
    assert result["can_render"] is False
    assert result["decision"] == _DATA_MISSING


def test_missing_results_index_is_data_missing_not_crash(tmp_path: Path) -> None:
    """无结果索引或工件时 resolver 不抛错，给出诚实 data_missing。"""
    run_dir = _contract_run(
        tmp_path,
        mathematical_object="probability_transition",
        archetype="probability_threshold_curve",
        required_data=["n", "successes", "trials"],
        required_visibility=[],
        artifact=_probability_artifact(),
    )
    (run_dir / "results/index.json").unlink()
    (run_dir / "results/raw/result-current.json").unlink(missing_ok=True)
    result = resolve_visual_data_availability(
        run_dir, "Q1", ["result-current"], "probability_threshold_curve"
    )
    assert result["can_render"] is False
    assert result["decision"] == _DATA_MISSING


def test_saturated_transition_data_is_flagged_not_faked(tmp_path: Path) -> None:
    """全饱和（点估计≈1）的数据字段齐全但必须被识别为不支持转变曲线。"""
    run_dir = _contract_run(
        tmp_path,
        mathematical_object="probability_transition",
        archetype="probability_threshold_curve",
        required_data=["n", "successes", "trials", "wilson_low", "wilson_high", "threshold"],
        required_visibility=["wilson_interval", "threshold"],
        artifact={
            "points": [
                {"n": 354, "p_estimate": 1.0, "ci_lower": 0.9997, "ci_upper": 1.0},
                {"n": 424, "p_estimate": 1.0, "ci_lower": 0.9997, "ci_upper": 1.0},
                {"n": 495, "p_estimate": 1.0, "ci_lower": 0.9997, "ci_upper": 1.0},
            ]
        },
    )
    result = resolve_visual_data_availability(
        run_dir, "Q1", ["result-current"], "probability_threshold_curve"
    )
    # 字段齐全仍 can_render，但必须携带饱和警告，禁止伪造转变。
    assert result["can_render"] is True
    assert any("probability_transition_saturated" in warning for warning in result["warnings"])
    assert "不得伪造 sigmoid" in result["warnings"][0]


def test_transition_data_spanning_region_has_no_saturation_warning(tmp_path: Path) -> None:
    """点估计覆盖 0.08–0.72 的真实转变数据不触发饱和警告。"""
    run_dir = _contract_run(
        tmp_path,
        mathematical_object="probability_transition",
        archetype="probability_threshold_curve",
        required_data=["n", "successes", "trials", "wilson_low", "wilson_high", "threshold"],
        required_visibility=["wilson_interval", "threshold"],
        artifact=_probability_artifact(),
    )
    result = resolve_visual_data_availability(
        run_dir, "Q1", ["result-current"], "probability_threshold_curve"
    )
    assert result["warnings"] == []
