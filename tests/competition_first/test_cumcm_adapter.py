"""验证 CUMCM 轻量结构适配器的边界，不验证具体论文科学结论。"""

from __future__ import annotations

import copy
import subprocess
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, StreamObject

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.knowledge.retrieval import write_paper_knowledge_application
from shumozizi.paper import compiler as paper_compiler
from shumozizi.paper.cumcm_adapter import (
    CLASSIC_ROLE_BY_TARGET,
    SECTION_TARGETS,
    evaluate_presentation_contract,
    finalize_cumcm_layout_audit,
    probe_pdf_page_rhythm,
    require_cumcm_layout_audit,
    require_cumcm_paper_review_audit,
    write_cumcm_paper_review_audit,
    write_cumcm_structure_map,
)
from shumozizi.paper.readiness import check_paper_readiness
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.state import paper_revision_status, update_simple_state


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


def _write_adopted_knowledge_application(run_dir: Path) -> Path:
    """写入一项已采用且绑定当前题证据的论文卡模式。"""
    pattern_id = "paper-card:P1"
    pattern = "用共享数学对象贯穿问题链，并让验证紧跟对应结论"
    atomic_json(
        run_dir / "knowledge/analysis-retrieval.json",
        {
            "schema_name": "knowledge_retrieval",
            "schema_version": "1.0",
            "stage": "analysis",
            "run_id": run_dir.name,
            "status": "matched",
            "task_fingerprint": {
                "problem_type": "统计决策",
                "data_structure": "个体重复测量表",
                "task_types": ["分组验证"],
                "statistical_units": ["个体级"],
                "mathematical_difficulties": ["重复测量"],
                "objective_structures": ["评价到决策"],
                "constraint_types": ["可靠性约束"],
                "validation_risks": ["个体跨折泄漏"],
                "question_chain": ["Q1 到 Q2"],
                "structural_tags": ["问题继承"],
                "keywords": [],
            },
            "matched_cards": [
                {
                    "paper_id": "paper-card",
                    "title": "结构化竞赛论文案例",
                    "score": 7.0,
                    "structural_similarity": 0.7,
                    "domain_similarity": 0.0,
                    "matched_on": ["重复测量结构匹配"],
                    "candidate_patterns": [
                        {"pattern_id": pattern_id, "pattern": pattern}
                    ],
                }
            ],
            "accepted_patterns": [
                {
                    "pattern_id": pattern_id,
                    "reason": "该模式直接改善当前论文的跨问论证连续性。",
                    "route_application": "用当前题共享统计单位连接 Q1 与 Q2。",
                }
            ],
            "rejected_patterns": [],
            "forbidden_transfer": ["原题参数", "公式和代码", "数值结论", "奖项评价"],
            "no_match_reason": None,
            "unavailable_reason": None,
        },
    )
    path = write_paper_knowledge_application(run_dir)
    text = path.read_text(encoding="utf-8").replace(
        "- 写作决定：待判断\n- 理由：待填写\n- 应用位置：待填写\n"
        "- 当前题证据：待填写\n- 正文源码：待填写\n- 兑现锚点：待填写",
        "- 写作决定：采用\n"
        "- 理由：该模式直接服务当前论文的跨问论证连续性。\n"
        "- 应用位置：问题分析与 Q1 到 Q2 过渡段\n"
        "- 当前题证据：当前题 Q2 继承 Q1 的个体级统计单位。\n"
        "- 正文源码：paper/main.tex\n"
        "- 兑现锚点：Q2 继承 Q1 的个体级统计单位。",
    )
    path.write_text(text, encoding="utf-8")
    (run_dir / "paper/main.tex").write_text(
        "Q2 继承 Q1 的个体级统计单位。\n", encoding="utf-8"
    )
    return path


def _presentation_contract(
    *, mode: str = "advisory", opening_anchor: str = "当前测试事实来源。"
) -> dict[str, object]:
    """构造全部呈现图均有理由豁免的轻量合同。"""
    waived = {
        "status": "waived",
        "reason": "当前测试由短公式和直接答案表即可完整表达。",
        "figure_id": None,
    }
    return {
        "mode": mode,
        "opening_reading_route": {
            "target_pages": [1, 5],
            "must_reveal": ["全文主线", "必答问题"],
            "source_path": "paper/ARGUMENT_PLAN.md",
            "explanation_anchor": opening_anchor,
        },
        "cross_question_story": {
            "source": "ARGUMENT_PLAN",
            "must_be_visible": True,
            "source_path": "paper/STORYBOARD.md",
            "explanation_anchor": "当前测试事实来源。",
        },
        "answer_overview": {
            "required": False,
            "source_path": None,
            "explanation_anchor": None,
        },
        "data_portrait": dict(waived),
        "question_hero_figures": {"Q1": dict(waived), "Q2": dict(waived)},
    }


def _map_11_payload(run_dir: Path, template: Path, *, mode: str = "advisory") -> dict[str, object]:
    """把 classic 1.0 夹具提升为含呈现合同的 1.1。"""
    payload = _map_payload(run_dir, template)
    payload["schema_version"] = "1.1"
    payload["profile"] = "classic"
    for index, section in enumerate(payload["sections"], start=1):
        section["section_id"] = f"classic-{index}"
        section["role"] = CLASSIC_ROLE_BY_TARGET[section["target"]]
    payload["presentation_contract"] = _presentation_contract(mode=mode)
    return payload


def _write_map_11(run_dir: Path, *, mode: str = "advisory") -> Path:
    """写入测试用 1.1 classic 映射。"""
    template = _write_map_sources(run_dir)
    return write_cumcm_structure_map(run_dir, _map_11_payload(run_dir, template, mode=mode))


def _cold_read(*, q2_answer_found: bool = True) -> dict[str, object]:
    """构造严格 PDF-only 的两问冷读结果。"""
    return {
        "input_scope": "frozen_pdf_only",
        "direct_answers_found_within_3_minutes": {"Q1": True, "Q2": q2_answer_found},
        "one_sentence_contribution": "论文用统一统计单位串联两问并给出可核验的直接答案。",
        "cross_question_inheritance_understood": False,
        "first_five_pages_establish_data_intuition": False,
        "hero_figures_identified": {"Q1": False, "Q2": False},
        "report_like_pages": [6],
    }


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


def test_semantic_structure_requires_order_and_question_coverage(tmp_path: Path) -> None:
    """semantic 画像允许拆章，但角色顺序和逐问首次出现顺序必须确定。"""
    run_dir = _run(tmp_path)
    template = _write_map_sources(run_dir)
    payload = _map_11_payload(run_dir, template)
    payload["profile"] = "semantic"

    def section(
        section_id: str,
        role: str,
        *,
        question_ids: list[str] | None = None,
        forbidden: list[str] | None = None,
    ) -> dict[str, object]:
        """构造一个显式语义章节。"""
        sources = question_ids or ["argument_plan"]
        return {
            "section_id": section_id,
            "role": role,
            "question_ids": question_ids or [],
            "target": section_id,
            "sources": sources,
            "purpose": f"明确 {section_id} 在论文论证中的作用。",
            "required_claims": [],
            "forbidden_content": forbidden or [],
            "preserve_argument_order": True,
            "compression": "deduplicate_only",
            "scope": "local",
        }

    payload["sections"] = [
        section(
            "restatement",
            "problem_restatement",
            forbidden=["模型名称", "最终数值", "大段题面复制"],
        ),
        section("analysis", "problem_analysis"),
        section("assumptions", "assumptions"),
        section("symbols", "symbols_or_data_definition"),
        section("data", "data_processing"),
        section("q1", "question_solution", question_ids=["Q1"]),
        section("q1-check", "local_validation", question_ids=["Q1"]),
        section("q2", "question_solution", question_ids=["Q2"]),
        section("evaluation", "overall_evaluation"),
        section("references", "references"),
        section("appendix", "appendix"),
    ]
    assert write_cumcm_structure_map(run_dir, payload).is_file()

    missing_question = copy.deepcopy(payload)
    missing_question["sections"] = [
        item for item in missing_question["sections"] if item["section_id"] != "q2"
    ]
    with pytest.raises(ContractError, match="未覆盖必答问题"):
        write_cumcm_structure_map(run_dir, missing_question)

    wrong_order = copy.deepcopy(payload)
    references = wrong_order["sections"].pop(-2)
    wrong_order["sections"].insert(4, references)
    with pytest.raises(ContractError, match="顺序无效"):
        write_cumcm_structure_map(run_dir, wrong_order)


def test_presentation_contract_distinguishes_advisory_and_required(tmp_path: Path) -> None:
    """同一源码缺口只在合同显式 required 时阻断编译。"""
    run_dir = _run(tmp_path)
    template = _write_map_sources(run_dir)
    advisory = _map_11_payload(run_dir, template, mode="advisory")
    advisory["presentation_contract"] = _presentation_contract(
        mode="advisory", opening_anchor="正文尚未写入的阅读路线"
    )
    write_cumcm_structure_map(run_dir, advisory)
    result = evaluate_presentation_contract(run_dir)
    assert result is not None
    assert result["blockers"] == []
    assert result["warnings"] == ["opening_reading_route"]
    status = check_paper_readiness(run_dir)
    assert any("opening_reading_route" in item for item in status["warnings"])
    assert not any("opening_reading_route" in item for item in status["errors"])

    required = copy.deepcopy(advisory)
    required["presentation_contract"]["mode"] = "required"
    write_cumcm_structure_map(run_dir, required)
    status = check_paper_readiness(run_dir)
    assert any("opening_reading_route" in item for item in status["errors"])


def test_layout_audit_11_blocks_missing_answer_but_keeps_style_advisory(
    tmp_path: Path,
) -> None:
    """冷读找不到直接答案会阻断，数据直觉和工作报告感只进入建议。"""
    run_dir = _run(tmp_path)
    _write_map_11(run_dir)
    _write_pdf(run_dir, pages=8)
    _set_phase(run_dir, "paper_review")
    payload = _review_payload(run_dir)
    payload["schema_version"] = "1.1"
    payload["cold_read"] = _cold_read()
    path = write_cumcm_paper_review_audit(run_dir, payload)
    audit = load_json(path)
    assert audit["adjudication"]["status"] == "pass"
    assert audit["adjudication"]["blocking_findings"] == []
    assert any("数据直觉" in item for item in audit["adjudication"]["advisory_findings"])
    assert audit["presentation_probe"]["advisory_only"] is True

    blocked = _review_payload(run_dir, verdict="rework")
    blocked["schema_version"] = "1.1"
    blocked["cold_read"] = _cold_read(q2_answer_found=False)
    write_cumcm_paper_review_audit(run_dir, blocked)
    with pytest.raises(ContractError, match="三分钟内未找到 Q2"):
        require_cumcm_paper_review_audit(run_dir)


def test_layout_audit_12_checks_selected_learning_patterns_after_blind_read(
    tmp_path: Path,
) -> None:
    """学习兑现由本地审计检查，部分兑现只告警且计划漂移会使审计失效。"""
    run_dir = _run(tmp_path)
    _write_adopted_knowledge_application(run_dir)
    _write_map_11(run_dir)
    _write_pdf(run_dir, pages=8)
    _set_phase(run_dir, "paper_review")
    payload = _review_payload(run_dir)
    payload["cold_read"] = _cold_read()
    payload["learning_checks"] = [
        {
            "pattern_id": "paper-card:P1",
            "pdf_realization": "partial",
            "finding": "Q1 到 Q2 已共享统计单位，但过渡段尚未说明继承如何改变决策对象。",
        }
    ]

    path = write_cumcm_paper_review_audit(run_dir, payload)
    audit = load_json(path)
    assert audit["schema_version"] == "1.2"
    assert audit["learning_realization"]["selected_cards"] == ["paper-card"]
    assert audit["learning_realization"]["status"] == "partial"
    assert any(
        "paper-card:P1" in item
        for item in audit["adjudication"]["advisory_findings"]
    )
    assert audit["adjudication"]["blocking_findings"] == []
    assert require_cumcm_paper_review_audit(run_dir) == audit

    application = run_dir / "paper/KNOWLEDGE_APPLICATION.md"
    application.write_text(
        application.read_text(encoding="utf-8").replace(
            "问题分析与 Q1 到 Q2 过渡段", "问题二结果段与问题三开头"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="learning_realization"):
        require_cumcm_paper_review_audit(run_dir)


def test_page_rhythm_probe_counts_vector_form_xobject(tmp_path: Path) -> None:
    """矢量 PDF 常见的 Form XObject 必须计为视觉锚点。"""
    pdf = tmp_path / "vector-figure.pdf"
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    form = StreamObject()
    form.set_data(b"q Q")
    form.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Form"),
            NameObject("/BBox"): ArrayObject(
                [FloatObject(0), FloatObject(0), FloatObject(100), FloatObject(100)]
            ),
        }
    )
    form_ref = writer._add_object(form)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/XObject"): DictionaryObject(
                {NameObject("/FigureForm"): form_ref}
            )
        }
    )
    with pdf.open("wb") as stream:
        writer.write(stream)

    probe = probe_pdf_page_rhythm(pdf)
    assert probe["visual_anchor_pages"] == [1]
    assert probe["page_metrics"][0]["visual_xobjects"] == 1


def test_paper_revision_status_waits_for_cumcm_layout_only() -> None:
    """同一已盲评渲染仅在 CUMCM 中等待同修订版式闭环。"""
    base = {
        "paper_render_revision": 3,
        "paper_reviewed_revision": 3,
        "layout_audited_revision": 2,
    }
    assert paper_revision_status({**base, "competition": "cumcm"})["status"] == (
        "REVIEWED_LAYOUT_PENDING"
    )
    assert paper_revision_status({**base, "competition": "mcm"})["status"] == "REVIEWED"
    assert paper_revision_status(
        {**base, "competition": "cumcm", "paper_reviewed_revision": 2}
    )["status"] == "UNREVIEWED_DRAFT"
