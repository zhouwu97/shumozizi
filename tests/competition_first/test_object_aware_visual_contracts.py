"""验证 v3.4 对象感知视觉数据合同：exact_oracle 纳入、数学对象最低字段与 waiver。"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_competition_first_v32 import _record_fixture_knowledge_retrieval, _v14_non_search_plan

from shumozizi.core.io import ContractError
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.modeling_units import require_v32_modeling_plan, write_modeling_units
from shumozizi.simple.visual_requirements import validate_object_visual_data


def _write_plan(run_dir: Path, unit_kind: str, mutate) -> dict[str, object]:
    """构造 v1.4 单元并写入运行目录，返回写好的 plan。"""
    plan = _v14_non_search_plan(run_dir, unit_kind)
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    mutate(unit)
    _record_fixture_knowledge_retrieval(run_dir)
    write_modeling_units(run_dir, plan)
    return plan


def test_spatial_exact_oracle_requires_visual_output_contract(tmp_path: Path) -> None:
    """空间几何 exact oracle 无结构化输出时必须拒绝进入实验（7.3）。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "spatial-exact-oracle-contract",
        workflow_version="3.2",
        required_questions=["Q1"],
    )

    def mutate(unit: dict) -> None:
        unit["mathematical_objects"] = ["periodic_contact_network"]

    _write_plan(run_dir, "exact_oracle", mutate)
    with pytest.raises(ContractError, match="visual_outputs"):
        require_v32_modeling_plan(run_dir)


def test_scalar_exact_oracle_with_waiver_runs(tmp_path: Path) -> None:
    """纯标量 exact oracle 给出具体 waiver 后仍可进入实验（7.3）。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "scalar-exact-oracle-waiver",
        workflow_version="3.2",
        required_questions=["Q1"],
    )

    def mutate(unit: dict) -> None:
        unit["visual_output_waiver"] = {
            "reason": "本问只解析题面给定的一个标量评价指标，没有可绘制的空间、"
            "网络、集合或可行域结构；结构图只能表达不存在的对象。"
        }

    _write_plan(run_dir, "exact_oracle", mutate)
    require_v32_modeling_plan(run_dir)


def test_waiver_rejected_when_spatial_object_declared(tmp_path: Path) -> None:
    """声明空间/网络对象的 exact oracle 不能用标量 waiver 豁免。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "waiver-with-spatial-object",
        workflow_version="3.2",
        required_questions=["Q1"],
    )

    def mutate(unit: dict) -> None:
        unit["mathematical_objects"] = ["contact_network"]
        unit["visual_output_waiver"] = {"reason": "试图用标量理由豁免网络结构。"}

    _write_plan(run_dir, "exact_oracle", mutate)
    with pytest.raises(ContractError, match="visual_outputs"):
        require_v32_modeling_plan(run_dir)


def test_periodic_network_missing_identity_map_rejected(tmp_path: Path) -> None:
    """周期接触网络缺少 identity_map 或 contact edges 时拒绝（7.4 表格）。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "periodic-network-fields",
        workflow_version="3.2",
        required_questions=["Q1"],
    )

    def mutate(unit: dict) -> None:
        unit["visual_outputs"] = [
            {
                "visual_question": "回绕片段如何合并为同一物理粒子？",
                "takeaway": "回绕片段必须合并身份，否则产生伪接触边。",
                "argument_unit_id": "Q1-periodic-scene",
                "mathematical_object": "periodic_contact_network",
                "argument_role": "model_understanding",
                "candidate_archetypes": ["periodic_spatial_contact_scene"],
                "required_visibility": ["periodic_boundary", "contact_edges"],
                "required_data": [
                    "particles",
                    "wrapped_fragments",
                    "contact_edges",
                    "electrodes",
                    "conductive_backbone",
                ],
                "output_path": "results/raw/q1_periodic_contact_scene.json",
            }
        ]

    _write_plan(run_dir, "exact_oracle", mutate)
    with pytest.raises(ContractError, match="identity_map"):
        require_v32_modeling_plan(run_dir)


def test_probability_transition_missing_successes_rejected(tmp_path: Path) -> None:
    """概率转变缺 successes/trials/interval 时拒绝（7.4 表格）。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "probability-transition-fields",
        workflow_version="3.2",
        required_questions=["Q1"],
    )

    def mutate(unit: dict) -> None:
        unit["visual_outputs"] = [
            {
                "visual_question": "导通概率如何随 A 数量越过 90%？",
                "takeaway": "只有同时保存成功次数与样本量才能画出区间。",
                "argument_unit_id": "Q1-probability",
                "mathematical_object": "probability_transition",
                "argument_role": "decisive_evidence",
                "candidate_archetypes": ["probability_threshold_curve"],
                "required_visibility": ["wilson_interval", "threshold"],
                "required_data": ["n", "wilson_low", "wilson_high", "threshold"],
                "output_path": "results/raw/q1_probability_transition.json",
            }
        ]

    _write_plan(run_dir, "exact_oracle", mutate)
    with pytest.raises(ContractError, match="successes"):
        require_v32_modeling_plan(run_dir)


def test_unknown_mathematical_object_rejected(tmp_path: Path) -> None:
    """visual_output 的数学对象必须在登记枚举内。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "unknown-object",
        workflow_version="3.2",
        required_questions=["Q1"],
    )

    def mutate(unit: dict) -> None:
        unit["visual_outputs"] = [
            {
                "visual_question": "如何在同一张图中展示周期边界内的粒子身份与贯通路径？",
                "argument_unit_id": "Q1-unknown",
                "mathematical_object": "quantum_teleportation",
                "required_data": ["anything"],
                "output_path": "results/raw/q1_unknown.json",
            }
        ]

    with pytest.raises(ContractError, match="mathematical_object 未登记"):
        _write_plan(run_dir, "exact_oracle", mutate)


def test_unknown_argument_role_rejected(tmp_path: Path) -> None:
    """visual_output 的论证角色必须在登记枚举内。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "unknown-role",
        workflow_version="3.2",
        required_questions=["Q1"],
    )

    def mutate(unit: dict) -> None:
        unit["visual_outputs"] = [
            {
                "visual_question": "如何在同一张图中展示周期边界内的粒子身份与贯通路径？",
                "argument_unit_id": "Q1-role",
                "argument_role": "prestige",
                "required_data": ["anything"],
                "output_path": "results/raw/q1_role.json",
            }
        ]

    with pytest.raises(ContractError, match="argument_role"):
        _write_plan(run_dir, "exact_oracle", mutate)


def test_object_validation_passes_with_complete_fields() -> None:
    """完整字段的周期接触网络通过对象级最低结构检查。"""
    unit = {
        "question_id": "Q1",
        "unit_id": "Q1-ok",
        "visual_outputs": [
            {
                "visual_question": "周期接触网络如何决定导通？",
                "argument_unit_id": "Q1-ok",
                "mathematical_object": "periodic_contact_network",
                "argument_role": "decisive_evidence",
                "required_data": [
                    "particles",
                    "wrapped_fragments",
                    "identity_map",
                    "contact_edges",
                    "electrodes",
                    "conductive_backbone",
                ],
                "output_path": "results/raw/q1_ok.json",
            }
        ],
    }
    assert validate_object_visual_data(unit) == []


def test_object_validation_reports_missing_edge_group() -> None:
    """接触网络缺接触边语义组时给出可定位错误。"""
    unit = {
        "question_id": "Q1",
        "unit_id": "Q1-bad",
        "visual_outputs": [
            {
                "visual_question": "网络如何决定导通？",
                "argument_unit_id": "Q1-bad",
                "mathematical_object": "contact_network",
                "argument_role": "decisive_evidence",
                "required_data": ["particles", "electrodes", "conductive_backbone"],
                "output_path": "results/raw/q1_bad.json",
            }
        ],
    }
    errors = validate_object_visual_data(unit)
    assert any("edges" in error for error in errors)
