"""验证论文内容充分性蓝图和 PDF 异常短文检查。"""

from __future__ import annotations

from pathlib import Path

from shumozizi.core.io import atomic_json
from shumozizi.paper.sufficiency import assess_paper_sufficiency, build_content_blueprint


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
            "problem_id": "paper-sufficiency",
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
    report = assess_paper_sufficiency(
        _blueprint(["Q1", "Q2", "Q3", "Q4", "Q5"]),
        pdf_text="""
        摘要
        本文给出汇总结果。
        表 1：五问结果汇总
        """,
        page_count=1,
    )

    assert report["status"] == "blocked"
    assert any("question:Q1" in item for item in report["hard_failures"])
    assert any("异常短" in item for item in report["warnings"])


def test_complete_short_paper_is_not_blocked_by_page_count_alone() -> None:
    """内容完整的短论文可以通过，页数只作为报告信息而非硬阈值。"""
    question_text = "\n".join(
        f"Q{number}\n直接答案：已回答。模型与算法：共享模型。关键结果：结果稳定。验证与边界：已说明。"
        for number in range(1, 6)
    )
    report = assess_paper_sufficiency(
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

    assert report["status"] == "pass"
    assert report["page_count"] == 1
    assert not report["hard_failures"]


def test_question_coverage_uses_body_after_incomplete_contents_entries() -> None:
    """目录重复题号时，应继续定位包含全部元素的正文段。"""
    question_ids = ["Q1", "Q2", "Q3", "Q4", "Q5"]
    contents = "\n".join(
        f"{question_id}\n直接答案\n模型与算法\n验证与边界" for question_id in question_ids
    )
    body = "\n".join(
        (
            f"{question_id}\n直接答案：已回答。模型与算法：已说明。"
            "关键结果：已复算。验证与边界：已说明。"
        )
        for question_id in question_ids
    )
    report = assess_paper_sufficiency(
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

    assert report["status"] == "pass"
    assert all(item["complete"] for item in report["question_coverage"])


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
