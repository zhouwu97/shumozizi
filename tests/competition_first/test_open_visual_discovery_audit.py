"""开放式视觉发现与正文问题归属的回归测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfWriter

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.paper.argument_extraction import extract_paper_argument_units
from shumozizi.paper.readiness import validate_candidate_visual_assessment
from shumozizi.paper.visual_discovery import (
    build_visual_discovery_prompt,
    record_visual_discovery,
    validate_visual_discovery_closure,
)
from shumozizi.paper.visual_requirements import build_visual_requirements_from_paper
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.visual_opportunities import record_visual_critic


def _run_with_visual_requirement(tmp_path: Path) -> Path:
    """构造一个已有视觉需求但尚未完成开放式审查的运行。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "open-visual-discovery",
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
                    "unit_id": "q1",
                    "question_id": "Q1",
                    "core_question": True,
                    "unit_kind": "evaluation",
                    "visual_outputs": [
                        {
                            "argument_unit_id": "q1-evidence",
                            "visual_question": "结果为什么成立？",
                            "takeaway": "需要展示决定性证据。",
                            "visual_archetype": "active-constraint plot",
                        }
                    ],
                }
            ],
        },
    )
    atomic_json(
        run_dir / "paper/answer-map.json",
        {"answers": {"Q1": {"primary_result_id": "result-q1", "result_ids": ["result-q1"]}}},
    )
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with (run_dir / "paper/final.pdf").open("wb") as stream:
        writer.write(stream)
    build_visual_requirements_from_paper(run_dir)
    return run_dir


def _drop_all_existing_requirements(run_dir: Path) -> None:
    """模拟旧流程用逐条 DROP 把清单全部关闭。"""
    pool = load_json(run_dir / "figures/visual-opportunities.json")
    for item in list(pool["opportunities"]):
        record_visual_critic(
            run_dir,
            item["opportunity_id"],
            verdict="DROP",
            reviewer_context_id=f"legacy-drop-{item['opportunity_id']}",
            review={
                "observed": "旧清单中存在对应论证。",
                "mechanism": "已有正文推导可以解释。",
                "boundary": "当前结论边界已写入正文。",
                "action": "不新增图。",
            },
        )


def test_drop_every_requirement_still_requires_open_world_discovery(tmp_path: Path) -> None:
    """逐条 DROP 不能证明整篇 PDF 没有未登记缺图。"""
    run_dir = _run_with_visual_requirement(tmp_path)
    _drop_all_existing_requirements(run_dir)

    errors = validate_candidate_visual_assessment(run_dir)

    assert any("VISUAL_DISCOVERY" in error for error in errors)


def test_discovery_prompt_is_blind_to_requirement_inventory(tmp_path: Path) -> None:
    """开放式审查提示不得把现有需求清单泄露给审核者。"""
    run_dir = _run_with_visual_requirement(tmp_path)
    prompt = build_visual_discovery_prompt(run_dir)

    assert "VISUAL_REQUIREMENTS" not in prompt
    assert "VR-Q1" not in prompt
    assert "只读取冻结 PDF" in prompt


def test_discovery_requires_all_six_dimensions_and_binds_pdf(tmp_path: Path) -> None:
    """发现记录必须覆盖六个维度，并绑定审核时的 PDF。"""
    run_dir = _run_with_visual_requirement(tmp_path)
    with pytest.raises(ContractError):
        record_visual_discovery(
            run_dir,
            {"dimensions": {"model_object_visibility": {"status": "sufficient", "rationale": "够"}}},
            reviewer_context_id="fresh-visual-reviewer",
        )

    record = record_visual_discovery(
        run_dir,
        {
            "dimensions": {
                key: {"status": "sufficient", "rationale": f"{key} 已在 PDF 中可读。"}
                for key in (
                    "model_object_visibility",
                    "decisive_evidence_visibility",
                    "mechanism_visibility",
                    "boundary_uncertainty_visibility",
                    "paper_size_legibility",
                    "whole_paper_visual_rhythm",
                )
            },
            "findings": [],
        },
        reviewer_context_id="fresh-visual-reviewer",
    )

    assert record["blind_to_requirements"] is True
    assert record["inputs"]["pdf_sha256"]
    assert validate_visual_discovery_closure(run_dir) == []


def test_p1_discovery_finding_creates_blocking_opportunity(tmp_path: Path) -> None:
    """P1 缺口必须进入机会池，不能被旧需求 DROP 抵消。"""
    run_dir = _run_with_visual_requirement(tmp_path)
    _drop_all_existing_requirements(run_dir)
    record_visual_discovery(
        run_dir,
        {
            "dimensions": {
                key: {"status": "gap" if key == "mechanism_visibility" else "sufficient", "rationale": f"{key} 审查结论。"}
                for key in (
                    "model_object_visibility",
                    "decisive_evidence_visibility",
                    "mechanism_visibility",
                    "boundary_uncertainty_visibility",
                    "paper_size_legibility",
                    "whole_paper_visual_rhythm",
                )
            },
            "findings": [
                {
                    "finding_id": "VD-001",
                    "severity": "P1",
                    "action": "ADD_FIGURE",
                    "title": "缺少机制证据",
                    "evidence": "PDF 中只有结果表，没有显示活动约束如何产生结果。",
                    "required_change": "增加当前数据驱动的活动约束图。",
                    "question_id": "Q1",
                }
            ],
        },
        reviewer_context_id="fresh-visual-reviewer",
    )

    errors = validate_candidate_visual_assessment(run_dir)

    assert any("VD-001" in error for error in errors)
    assert any("VISUAL_DISCOVERY" in error for error in errors)


def test_current_figure_can_close_p1_discovery_finding(tmp_path: Path) -> None:
    """只有明确绑定 finding 的 current 正式图才能关闭高影响缺图。"""
    run_dir = _run_with_visual_requirement(tmp_path)
    record_visual_discovery(
        run_dir,
        {
            "dimensions": {
                key: {"status": "gap" if key == "decisive_evidence_visibility" else "sufficient", "rationale": f"{key} 审查结论充分。"}
                for key in (
                    "model_object_visibility",
                    "decisive_evidence_visibility",
                    "mechanism_visibility",
                    "boundary_uncertainty_visibility",
                    "paper_size_legibility",
                    "whole_paper_visual_rhythm",
                )
            },
            "findings": [
                {
                    "finding_id": "VD-002",
                    "severity": "P1",
                    "action": "REPLACE_FIGURE",
                    "title": "主图不能承担结论",
                    "evidence": "现图无法辨认正式答案与可行边界。",
                    "required_change": "用当前结果重绘答案点和活动边界。",
                    "question_id": "Q1",
                }
            ],
        },
        reviewer_context_id="fresh-current-reviewer",
    )
    index = load_json(run_dir / "figures/index.json")
    index["figures"].append(
        {
            "figure_id": "q1-discovery-resolution",
            "question_id": "Q1",
            "role": "decisive_evidence",
            "status": "current",
            "paper_allowed": True,
            "visual_opportunity_id": "visual-discovery-VD-002",
            "outputs": [],
        }
    )
    atomic_json(run_dir / "figures/index.json", index)

    assert validate_visual_discovery_closure(run_dir) == []


def test_changed_pdf_invalidates_visual_discovery(tmp_path: Path) -> None:
    """渲染稿变化后不能继续复用旧 PDF 的开放式审查。"""
    run_dir = _run_with_visual_requirement(tmp_path)
    record_visual_discovery(
        run_dir,
        {
            "dimensions": {
                key: {"status": "sufficient", "rationale": f"{key} 在当前 PDF 中清楚可读。"}
                for key in (
                    "model_object_visibility",
                    "decisive_evidence_visibility",
                    "mechanism_visibility",
                    "boundary_uncertainty_visibility",
                    "paper_size_legibility",
                    "whole_paper_visual_rhythm",
                )
            },
            "findings": [],
        },
        reviewer_context_id="fresh-before-render-change",
    )
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_blank_page(width=595, height=842)
    with (run_dir / "paper/final.pdf").open("wb") as stream:
        writer.write(stream)

    errors = validate_visual_discovery_closure(run_dir)

    assert any("PDF 已变化" in error for error in errors)


def test_body_q4_mention_does_not_switch_q3_owner(tmp_path: Path) -> None:
    """普通正文提到 Q4 时，不得把当前 Q3 论证迁移到 Q4。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "question-attribution",
        required_questions=["Q3", "Q4"],
        workflow_version="3.2",
    )
    (run_dir / "paper/longform-source.tex").write_text(
        "\\section{问题三}\n\n"
        "Q3 的阈值由活动约束决定，本文同时比较 Q4 的候选方案。\n\n"
        "该阈值在边界附近保持稳定，并且这一机制仍属于问题三的可靠性判断。\n\n"
        "\\section{问题四}\n\n"
        "Q4 的成本前沿由价格约束决定。\n",
        encoding="utf-8",
    )

    arguments = extract_paper_argument_units(run_dir, write=False)["arguments"]

    q3_claims = [item["claim"] for item in arguments if item["question_id"] == "Q3"]
    q4_claims = [item["claim"] for item in arguments if item["question_id"] == "Q4"]
    assert any("边界附近" in claim for claim in q3_claims)
    assert not any("边界附近" in claim for claim in q4_claims)


def test_semantic_heading_uses_question_contract_for_owner(tmp_path: Path) -> None:
    """不写 Q 编号的语义标题应按问题合同归属，而不是按正文偶然字样归属。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "semantic-heading-attribution",
        required_questions=["Q3", "Q4"],
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
                    "unit_id": "q3-threshold",
                    "question_id": "Q3",
                    "answer_contract": {
                        "required_output": "给出90%可靠性下的最低A填充量。",
                        "decision_scope": "纯A介质填充。",
                        "primary_endpoint": {"name": "可靠阈值", "definition": "概率首达90%的最低填充量。"},
                    },
                },
                {
                    "unit_id": "q4-cost",
                    "question_id": "Q4",
                    "answer_contract": {
                        "required_output": "给出A-B混合填充的最低成本配比。",
                        "decision_scope": "A与B的整数配比。",
                        "primary_endpoint": {"name": "最低成本", "definition": "可靠域内成本最低的混合配比。"},
                    },
                },
            ],
        },
    )
    (run_dir / "paper/longform-source.tex").write_text(
        "\\section{90\\%可靠性下的最低 A 填充量}\n\n"
        "临界点附近的活动约束决定最低填充量，并需报告边界稳定性。\n\n"
        "\\section{A--B 混合填充的最低成本配比}\n\n"
        "成本前沿与可靠边界共同决定最终整数配比，并形成问题四的最低成本答案。\n",
        encoding="utf-8",
    )

    arguments = extract_paper_argument_units(run_dir, write=False)["arguments"]

    assert any(item["question_id"] == "Q3" and "最低填充量" in item["claim"] for item in arguments)
    assert any(item["question_id"] == "Q4" and "成本前沿" in item["claim"] for item in arguments)
