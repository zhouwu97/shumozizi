"""验证 CUMCM 轻量结构适配器的边界，不验证具体论文科学结论。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pypdf import PdfWriter

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.paper import compiler as paper_compiler
from shumozizi.paper.cumcm_adapter import (
    SECTION_TARGETS,
    finalize_cumcm_layout_audit,
    require_cumcm_layout_audit,
    require_cumcm_paper_review_audit,
    write_cumcm_paper_review_audit,
    write_cumcm_structure_map,
)
from shumozizi.paper.readiness import check_paper_readiness
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.state import update_simple_state


def _run(tmp_path: Path, *, questions: list[str] | None = None) -> Path:
    """创建最小 CUMCM v3.2 运行。"""
    return initialize_simple_run(
        tmp_path,
        "cumcm-adapter",
        competition="cumcm",
        required_questions=questions or ["Q1", "Q2"],
        workflow_version="3.2",
    )


def _write_map_sources(run_dir: Path) -> Path:
    """创建结构映射所需事实来源和一个非空参考 Word。"""
    sources = {
        "argument_plan": "paper/ARGUMENT_PLAN.md",
        "storyboard": "paper/STORYBOARD.md",
        "figure_plan": "figures/FIGURE_PLAN.json",
        "results": "results/RESULT_REGISTRY.json",
        "modeling_units": "analysis/MODELING_UNITS.json",
    }
    for relative in sources.values():
        path = run_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("当前测试事实来源。\n", encoding="utf-8")
    template = run_dir.parent / "国赛参考模板.docx"
    template.write_bytes(b"PK\x03\x04minimal-reference-docx")
    return template


def _map_payload(run_dir: Path, template: Path) -> dict[str, object]:
    """构造覆盖十个国赛外层栏目的结构映射。"""
    source_of_truth = {
        "argument_plan": "paper/ARGUMENT_PLAN.md",
        "storyboard": "paper/STORYBOARD.md",
        "figure_plan": "figures/FIGURE_PLAN.json",
        "results": "results/RESULT_REGISTRY.json",
        "modeling_units": "analysis/MODELING_UNITS.json",
    }
    sections = []
    for target in SECTION_TARGETS:
        sources: list[str] = ["argument_plan"]
        scope = "local"
        if target == "五、模型的建立与求解":
            sources = ["Q1", "Q2"]
        elif target == "六、模型的综合分析与检验":
            sources = ["results"]
            scope = "cross_question_only"
        elif target == "四、符号说明与数据处理":
            sources = ["modeling_units"]
        sections.append(
            {
                "target": target,
                "sources": sources,
                "purpose": f"明确{target}在完整论证中的作用。",
                "required_claims": ["本节必须服务于当前论文论点"],
                "forbidden_content": (
                    ["模型名称", "最终数值", "大段题面复制"]
                    if target == "一、问题重述"
                    else []
                ),
                "preserve_argument_order": True,
                "compression": "deduplicate_only",
                "scope": scope,
            }
        )
    return {
        "template": {
            "reference_docx": str(template),
            "path_scope": "absolute",
            "usage": "styles_and_outer_structure_only",
            "placeholder_content_authoritative": False,
        },
        "source_of_truth": source_of_truth,
        "adaptation_rules": {
            "allowed": [
                "map_sections",
                "move_paragraphs",
                "rewrite_headings",
                "deduplicate_repetition",
                "reorder_figures",
                "repair_cross_references",
            ],
            "forbidden": [
                "change_model",
                "select_or_modify_numbers",
                "create_new_conclusions",
            ],
        },
        "sections": sections,
        "page_planning": {
            "recommended_body_pages": [24, 30],
            "inspect_below_pages": 18,
            "hard_gate": False,
        },
    }


def _write_map(run_dir: Path) -> Path:
    """写入测试用结构映射。"""
    template = _write_map_sources(run_dir)
    return write_cumcm_structure_map(run_dir, _map_payload(run_dir, template))


def _review_payload(run_dir: Path, *, verdict: str = "pass") -> dict[str, object]:
    """构造覆盖两个问题的论文论证审核。"""
    fields = {
        "mathematical_difficulty": True,
        "mathematical_object": True,
        "modeling_basis": True,
        "derivation": True,
        "solver": True,
        "main_result": True,
        "mechanism": True,
        "competing_route_or_counterexample": True,
        "claim_specific_validation": True,
        "direct_answer": True,
    }
    return {
        "structure": {name: "pass" for name in (
            "problem_restatement",
            "problem_analysis",
            "assumptions",
            "symbols_and_data",
            "four_questions",
            "model_evaluation",
        )},
        "argument_depth": {"Q1": dict(fields), "Q2": dict(fields)},
        "question_progression": {
            "status": "pass",
            "interchangeable_questions": False,
            "links": [
                {"from": "Q1", "to": "Q2", "inheritance": "Q2继承Q1的统计单位并新增决策对象。"}
            ],
            "summary": "各问共享统计单位，但后问在前问基础上引入新的数学困难。",
        },
        "narrative_risks": [],
        "paper_review_verdict": verdict,
        "review_summary": "当前审核同时覆盖结构、核心论证深度、问题继承和反工作报告风险。",
    }


def _set_phase(run_dir: Path, phase: str) -> None:
    """为只测试审计接口的夹具设置阶段。"""
    state_path = run_dir / "state/run.json"
    state = load_json(state_path)
    state["phase"] = phase
    atomic_json(state_path, state)


def _write_pdf(run_dir: Path, pages: int = 35) -> None:
    """写入可被页数审计读取的最小 PDF。"""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    with (run_dir / "paper/final.pdf").open("wb") as stream:
        writer.write(stream)


def test_structure_map_covers_all_template_sections_and_questions(tmp_path: Path) -> None:
    """结构映射必须覆盖所有外层栏目，并在第五章保留逐问内容。"""
    run_dir = _run(tmp_path)
    path = _write_map(run_dir)
    assert path.is_file()

    broken = _map_payload(run_dir, run_dir.parent / "国赛参考模板.docx")
    broken["sections"] = [item for item in broken["sections"] if item["target"] != "附录"]
    with pytest.raises(ContractError, match="sections"):
        write_cumcm_structure_map(run_dir, broken)


def test_structure_map_rejects_scientific_changes(tmp_path: Path) -> None:
    """适配器动作集合不能被扩展为改模型或改数字。"""
    run_dir = _run(tmp_path)
    _write_map(run_dir)
    payload = _map_payload(run_dir, run_dir.parent / "国赛参考模板.docx")
    payload["adaptation_rules"]["allowed"].append("change_model")
    with pytest.raises(ContractError, match="允许动作"):
        write_cumcm_structure_map(run_dir, payload)


def test_cumcm_map_is_required_by_formal_readiness(tmp_path: Path) -> None:
    """正式 CUMCM v3.2 就绪检查缺映射时必须明确阻断。"""
    run_dir = _run(tmp_path)
    status = check_paper_readiness(run_dir)
    assert any("CUMCM_STRUCTURE_MAP" in error for error in status["errors"])

    _write_map(run_dir)
    status = check_paper_readiness(run_dir)
    assert not any("CUMCM_STRUCTURE_MAP" in error for error in status["errors"])


def test_reference_docx_is_passed_to_pandoc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Word 模板只作为 Pandoc reference-doc，不替换论文科学正文。"""
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir()
    (paper_dir / "main.tex").write_text("\\section{正文}\n", encoding="utf-8")
    reference = tmp_path / "reference.docx"
    reference.write_bytes(b"reference")
    captured: list[str] = []

    monkeypatch.setattr(paper_compiler.shutil, "which", lambda _name: "pandoc")

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.extend(command)
        output = Path(command[command.index("-o") + 1])
        output.write_bytes(b"PK\\x03\\x04docx")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(paper_compiler.subprocess, "run", fake_run)
    output = paper_compiler.compile_docx(
        paper_dir, engine="latex", reference_docx=reference
    )
    assert output.is_file()
    assert f"--reference-doc={reference.resolve()}" in captured


def test_paper_review_audit_blocks_false_core_argument_depth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """核心问题缺少一项实质论证时不能进入 verify。"""
    run_dir = _run(tmp_path)
    _write_map(run_dir)
    (run_dir / "paper/final.pdf").write_bytes(b"%PDF-1.4\nfixture")
    _set_phase(run_dir, "paper_review")
    payload = _review_payload(run_dir, verdict="rework")
    payload["argument_depth"]["Q1"]["derivation"] = False
    write_cumcm_paper_review_audit(run_dir, payload)
    monkeypatch.setattr(
        "shumozizi.simple.review.require_paper_blind_review_allowed",
        lambda _run: None,
    )
    with pytest.raises(ContractError, match="论证不足"):
        update_simple_state(run_dir, phase="verify")


def test_interchangeable_questions_block_verify(tmp_path: Path) -> None:
    """四问可以任意交换顺序时，叙事审计必须阻断。"""
    run_dir = _run(tmp_path)
    _write_map(run_dir)
    (run_dir / "paper/final.pdf").write_bytes(b"%PDF-1.4\nfixture")
    _set_phase(run_dir, "paper_review")
    payload = _review_payload(run_dir, verdict="rework")
    payload["question_progression"]["status"] = "issue"
    payload["question_progression"]["interchangeable_questions"] = True
    write_cumcm_paper_review_audit(run_dir, payload)
    with pytest.raises(ContractError, match="不可任意交换"):
        require_cumcm_paper_review_audit(run_dir)


def test_page_range_is_soft_but_layout_issue_blocks_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """页数只形成条件结论，真实版面问题仍会要求返工。"""
    run_dir = _run(tmp_path)
    _write_map(run_dir)
    _write_pdf(run_dir)
    _set_phase(run_dir, "paper_review")
    write_cumcm_paper_review_audit(run_dir, _review_payload(run_dir))
    _set_phase(run_dir, "verify")
    monkeypatch.setattr(
        "shumozizi.simple.review.mechanical_qa_status",
        lambda _run: {"allowed": True},
    )
    audit = finalize_cumcm_layout_audit(
        run_dir,
        {
            "body_pages": 20,
            "page_review_note": "正文处于18至23页区间，已人工确认没有删除关键推导。",
            "docx_note": "测试夹具不生成 Word，仅验证 PDF 版面审计。",
        },
    )
    assert load_json(audit)["layout"]["page_assessment"] == "compression_review_required"
    assert require_cumcm_layout_audit(run_dir)["overall_verdict"] == "conditional_pass"

    blocked = finalize_cumcm_layout_audit(
        run_dir,
        {
            "body_pages": 20,
            "page_review_note": "正文处于18至23页区间，已人工确认没有删除关键推导。",
            "docx_note": "测试夹具不生成 Word，仅验证 PDF 版面审计。",
            "figures_too_small": ["图2文字无法在打印版中辨认。"],
        },
    )
    assert load_json(blocked)["overall_verdict"] == "rework"
    with pytest.raises(ContractError, match="要求返工"):
        require_cumcm_layout_audit(run_dir)


def test_non_cumcm_v32_does_not_require_adapter(tmp_path: Path) -> None:
    """非 CUMCM v3.2 运行不被国赛结构适配器影响。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "other-competition",
        competition="mcm",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    assert require_cumcm_layout_audit(run_dir) is None
