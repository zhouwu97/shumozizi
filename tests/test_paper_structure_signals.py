"""验证论文内容蓝图和 PDF 结构信号检查的能力边界。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from shumozizi.core.io import atomic_json
from shumozizi.core.schema import validate_document
from shumozizi.paper.sufficiency import (
    assess_paper_structure_signals,
    build_content_blueprint,
)


def _write_production_state(run_dir: Path, questions: list[str]) -> None:
    """写入内容蓝图测试所需的最小生产状态。"""
    atomic_json(
        run_dir / "state" / "run.json",
        {
            "schema_version": "3.0",
            "run_id": run_dir.name,
            "workflow": "capability-first-v3",
            "phase": "paper",
            "execution_mode": "production",
            "revision": 3,
            "competition": "synthetic",
            "problem_id": "paper-structure-signals",
            "required_questions": questions,
            "current_question": questions[-1],
            "completed_questions": questions,
            "selected_route": "route-a",
            "fallback_route": None,
            "artifacts": {},
            "time_budget": {"total_hours": 1, "remaining_hours": 0.5},
            "token_budget": {"soft_cap": 1000, "used_estimate": 100},
            "updated_at": "2026-07-22T00:00:00Z",
        },
    )


def _blueprint(question_ids: list[str]) -> dict:
    """构造只包含必答内容要求的合成论文蓝图。"""
    sections = [
        {
            "section_id": "abstract",
            "kind": "global",
            "required": True,
            "draft_allowed": True,
            "evidence_result_ids": question_ids,
            "required_elements": ["abstract"],
        },
        {
            "section_id": "problem_restatement_assumptions",
            "kind": "global",
            "required": True,
            "draft_allowed": True,
            "evidence_result_ids": [],
            "required_elements": ["problem_restatement", "assumptions"],
        },
        {
            "section_id": "shared_model",
            "kind": "global",
            "required": True,
            "draft_allowed": True,
            "evidence_result_ids": question_ids,
            "required_elements": ["shared_model"],
        },
        {
            "section_id": "global_robustness_or_missing_reason",
            "kind": "global",
            "required": True,
            "draft_allowed": True,
            "evidence_result_ids": question_ids,
            "required_elements": ["robustness_or_missing_reason"],
        },
        {
            "section_id": "conclusion",
            "kind": "global",
            "required": True,
            "draft_allowed": True,
            "evidence_result_ids": question_ids,
            "required_elements": ["conclusion"],
        },
        {
            "section_id": "references",
            "kind": "global",
            "required": True,
            "draft_allowed": True,
            "evidence_result_ids": [],
            "required_elements": ["references"],
        },
    ]
    sections.extend(
        {
            "section_id": f"question_{question_id}",
            "kind": "question",
            "question_id": question_id,
            "required": True,
            "draft_allowed": True,
            "evidence_result_ids": [question_id],
            "required_elements": [
                "direct_answer",
                "model_algorithm",
                "key_results",
                "verification_boundary",
            ],
        }
        for question_id in question_ids
    )
    return {
        "schema_name": "paper_content_blueprint",
        "schema_version": "2.0",
        "run_id": "five-question-run",
        "state_revision": 1,
        "execution_mode": "production",
        "required_questions": question_ids,
        "data_processing_applicable": False,
        "sections": sections,
        "generated_at": "2026-07-22T00:00:00Z",
    }


def test_five_question_paper_with_only_abstract_and_results_table_is_blocked() -> None:
    """摘要和结果表不能替代五个必答问题的直接回答与验证。"""
    report = assess_paper_structure_signals(
        _blueprint(["Q1", "Q2", "Q3", "Q4", "Q5"]),
        pdf_text="""
        摘要
        本文给出汇总结果。
        表 1：五问结果汇总
        """,
        page_count=1,
    )

    assert report["status"] == "missing_required_signals"
    assert not report["mechanical_gate_passed"]
    assert any("question:Q1" in item for item in report["missing_required_signals"])
    assert any("异常短" in item for item in report["warnings"])


def test_complete_short_paper_is_not_blocked_by_page_count_alone() -> None:
    """内容完整的短论文可以通过，页数只作为报告信息而非硬阈值。"""
    question_text = "\n".join(
        (
            f"Q{number}\n直接答案：本问采用实体时长求和作为目标。"
            "模型与算法：令 J=sum_i T_i，并在硬约束满足后用精确评分器复算候选。"
            f"关键结果：第 {number} 问的当前结果为 {10 + number}.25 s，表 1 给出参数与结果。"
            "该数值高于基线，因此表明局部搜索确实改善了题目目标，而非只改善代理值。"
            "验证与边界：独立实现复算误差低于 0.01 s；结论仅适用于题面给定参数，"
            "若边界条件变化仍需重新做敏感性分析。"
        )
        for number in range(1, 6)
    )
    report = assess_paper_structure_signals(
        _blueprint(["Q1", "Q2", "Q3", "Q4", "Q5"]),
        pdf_text=f"""
        摘要
        问题重述与假设
        共享模型
        {question_text}
        全局稳健性：未进行额外敏感性分析，原因是样本固定。
        结论
        参考文献
        """,
        page_count=1,
    )

    assert report["status"] == "signals_present"
    assert report["mechanical_gate_passed"]
    assert report["page_count"] == 1
    assert not report["missing_required_signals"]
    assert report["assesses_mathematical_correctness"] is False
    assert report["assesses_argument_quality"] is False
    assert report["independent_pdf_review_required"] is True


def test_question_coverage_uses_body_after_incomplete_contents_entries() -> None:
    """目录重复题号时，应继续定位包含全部元素的正文段。"""
    question_ids = ["Q1", "Q2", "Q3", "Q4", "Q5"]
    contents = "\n".join(
        f"{question_id}\n直接答案\n模型与算法\n验证与边界" for question_id in question_ids
    )
    body = "\n".join(
        (
            f"{question_id}\n直接答案：采用各实体有效时长求和。"
            "模型与算法：令 J=sum_i T_i，并用独立精确评分器计算每个可行候选。"
            "关键结果：最优值为 21.25 s，表 1 同时列出约束余量和基线结果。"
            "该结果比基线提高 8.2%，因此表明改进来自可行区域内的目标提升。"
            "验证与边界：第二实现的差值小于 0.01 s，但该结论不外推到不同题面参数。"
        )
        for question_id in question_ids
    )
    report = assess_paper_structure_signals(
        _blueprint(question_ids),
        pdf_text=f"""
        摘要
        问题重述与假设
        共享模型
        目录
        {contents}
        {body}
        全局稳健性：已说明。
        结论
        参考文献
        """,
        page_count=2,
    )

    assert report["status"] == "signals_present"
    assert all(item["structure_signals_complete"] for item in report["question_coverage"])


def test_question_labels_without_argument_are_blocked() -> None:
    """标题、标签和结论口号齐全也不能替代逐问论证。"""
    report = assess_paper_structure_signals(
        _blueprint(["Q1"]),
        pdf_text="""
        摘要
        问题重述与假设
        共享模型
        Q1
        直接答案：完成。模型与算法：优化。关键结果：很好。验证与边界：通过。
        全局稳健性：已说明。
        结论
        参考文献
        """,
        page_count=8,
    )

    coverage = report["question_coverage"][0]
    assert report["status"] == "missing_required_signals"
    assert not coverage["content_signals"]["minimum_body_signal"]
    assert not coverage["content_signals"]["technical_content_signal"]
    assert not coverage["content_signals"]["explanation_marker_present"]


def test_question_section_needs_its_own_current_production_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Q1 不能仅凭 Q2 的有效结果获得题目事实写作权限。"""
    run_dir = tmp_path / "cross-question-evidence"
    _write_production_state(run_dir, ["Q1", "Q2"])
    monkeypatch.setattr(
        "shumozizi.paper.sufficiency.quality_allows_paper",
        lambda _run_dir, result_id: result_id == "Q2-R1",
    )
    monkeypatch.setattr(
        "shumozizi.paper.sufficiency.read_result_index",
        lambda _run_dir: {
            "results": [
                {"result_id": "Q2-R1", "question_id": "Q2"},
            ]
        },
        raising=False,
    )

    blueprint = build_content_blueprint(
        run_dir,
        evidence_by_question={"Q1": ["Q2-R1"], "Q2": ["Q2-R1"]},
    )
    q1 = next(
        section for section in blueprint["sections"] if section["section_id"] == "question_Q1"
    )

    assert not q1["draft_allowed"]
    assert "本问" in q1["blocked_reason"]


def test_blueprint_materializes_full_python_and_matlab_source(tmp_path: Path, monkeypatch) -> None:
    """论文蓝图必须冻结实际源码文本副本，而不是只登记路径。"""
    run_dir = tmp_path / "source-appendix"
    _write_production_state(run_dir, ["Q1"])
    (run_dir / "code").mkdir(parents=True)
    (run_dir / "code" / "solve.py").write_text("print('solve')\n", encoding="utf-8")
    (run_dir / "code" / "proof.m").write_text("disp('proof');\n", encoding="utf-8")
    monkeypatch.setattr(
        "shumozizi.paper.sufficiency.quality_allows_paper",
        lambda _run_dir, result_id: result_id == "Q1-R1",
    )
    monkeypatch.setattr(
        "shumozizi.paper.sufficiency.read_result_index",
        lambda _run_dir: {"results": [{"result_id": "Q1-R1", "question_id": "Q1"}]},
    )

    blueprint = build_content_blueprint(
        run_dir,
        evidence_by_question={"Q1": ["Q1-R1"]},
    )

    assert {item["source_path"] for item in blueprint["source_code_appendix"]} == {
        "code/proof.m",
        "code/solve.py",
    }
    for item in blueprint["source_code_appendix"]:
        assert (run_dir / item["appendix_path"]).read_bytes() == (
            run_dir / item["source_path"]
        ).read_bytes()
        assert item["source_text"] == (run_dir / item["source_path"]).read_text(encoding="utf-8")


def test_keyword_stuffing_can_only_satisfy_mechanical_signals() -> None:
    """关键词堆砌即使命中结构信号，也不能产生论证质量结论或跳过盲审。"""
    report = assess_paper_structure_signals(
        _blueprint(["Q1"]),
        pdf_text="""
        摘要
        问题重述与假设
        共享模型
        Q1
        直接答案：目标函数为 12.3 s。模型与算法、关键结果和验证与边界全部存在。
        模型选择理由、证明义务、生产结果、基线、因此、表明、局限只是重复标签；
        目标函数、模型选择理由、证明义务、生产结果、基线、因此、表明、局限继续重复。
        这些词超过一百二十个字符并出现三个句子标记，但文本不保证任何数学结论正确。
        全局稳健性：已说明。
        结论
        参考文献
        """,
        page_count=2,
    )

    assert report["status"] == "signals_present"
    assert report["mechanical_gate_passed"] is True
    assert report["assesses_mathematical_correctness"] is False
    assert report["assesses_argument_quality"] is False
    assert report["independent_pdf_review_required"] is True
    assert "argument_quality_passed" not in report


def test_structure_signal_schema_rejects_forged_gate_consistency() -> None:
    """Schema 必须拒绝通过状态、门禁布尔值和阻断事实互相矛盾的报告。"""
    report = assess_paper_structure_signals(
        _blueprint(["Q1"]),
        pdf_text="""
        摘要 问题重述与假设 共享模型 Q1
        直接答案：结果为 12.3 s。模型与算法采用精确评分。关键结果见表 1。
        该结果用于当前问题，因此包含最低解释标记。验证与边界说明不能外推；
        当前 production 结果还包含约束余量、单位和误差记录，用来确认这里不是空章节。
        第二句话补足最低正文信号并重复说明当前结果仅适用于题面参数。
        第三句话补足最低正文信号并明确不同参数仍然需要重新验证。
        全局稳健性：已说明。结论 参考文献
        """,
        page_count=2,
    )
    assert not validate_document(report, "paper_structure_signal_report")
    assert report["status"] == "signals_present"

    forged_boolean = deepcopy(report)
    forged_boolean["mechanical_gate_passed"] = False
    assert validate_document(forged_boolean, "paper_structure_signal_report")

    forged_blocker = deepcopy(report)
    forged_blocker["evidence_blockers"] = ["当前证据已失效"]
    assert validate_document(forged_blocker, "paper_structure_signal_report")
