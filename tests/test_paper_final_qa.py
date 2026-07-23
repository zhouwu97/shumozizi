"""验证终检复验论文参考收据与贡献账本。"""

from __future__ import annotations

import io
from pathlib import Path

import scripts.qa.run_final_checks as final_checks
from scripts.qa.check_numeric_consistency import check_numeric_consistency
from scripts.qa.check_result_references import check_result_references
from shumozizi.paper.sufficiency import build_content_blueprint
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.quality import assess_result_quality
from tests.quality_protocol_helpers import (
    adapter_backed_assessment,
    record_passing_scientific_review,
    run_synthetic_verification_protocol,
)


def _passing_check() -> dict[str, object]:
    """返回终检无关依赖的最小通过结果。"""
    return {"success": True, "checks": [{"id": "pdf-open", "passed": True}], "warnings": []}


def test_final_qa_blocks_invalid_written_paper_receipts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """运行目录已有论文收据或账本时，终检必须复验而非静默忽略。"""
    run_dir = initialize_simple_run(tmp_path, "paper-qa")
    (run_dir / "paper" / "paper_references.json").write_text("{}", encoding="utf-8")
    (run_dir / "paper" / "contribution_ledger.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(final_checks, "audit_pdf", lambda *_args, **_kwargs: _passing_check())
    monkeypatch.setattr(
        final_checks,
        "run_paper_sufficiency_check",
        lambda *_args, **_kwargs: {"status": "pass", "warnings": []},
    )
    monkeypatch.setattr(final_checks, "check_placeholders", lambda *_args: {"success": True})
    monkeypatch.setattr(final_checks, "check_result_references", lambda *_args: {"success": True})
    monkeypatch.setattr(final_checks, "check_numeric_consistency", lambda *_args: {"success": True})
    monkeypatch.setattr(
        final_checks, "verify_current_result_files", lambda *_args: {"success": True}
    )
    monkeypatch.setattr(
        final_checks, "verify_current_figure_files", lambda *_args: {"success": True}
    )
    monkeypatch.setattr(final_checks, "make_contact_sheet", lambda *_args: None)
    monkeypatch.setattr(
        final_checks,
        "verify_paper_references",
        lambda *_args, **_kwargs: {"valid": False, "errors": ["收据哈希已漂移"]},
        raising=False,
    )
    monkeypatch.setattr(
        final_checks,
        "verify_contribution_ledger",
        lambda *_args, **_kwargs: {"valid": False, "errors": ["创新证据已失效"]},
        raising=False,
    )

    report = final_checks.run_final_checks(run_dir)
    checks = {item["id"]: item for item in report["checks"]}

    assert report["status"] == "blocked"
    assert not checks["paper-references"]["passed"]
    assert not checks["paper-contribution-ledger"]["passed"]


def test_final_qa_cli_summary_reconfigures_gbk_stdout(monkeypatch) -> None:
    """终检摘要在 Windows 默认 GBK 流上也必须保留不可见追溯字符。"""
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="gbk")
    monkeypatch.setattr(final_checks.sys, "stdout", stream)

    final_checks._print_cli_payload({"marker": "\u2060"})
    stream.flush()

    assert "\u2060" in buffer.getvalue().decode("utf-8")


def test_production_paper_requires_question_result_and_numeric_markers(tmp_path: Path) -> None:
    """生产蓝图有本问数值证据时，零追溯标记不能通过终检。"""
    run_dir = initialize_simple_run(tmp_path, "marker-coverage", required_questions=["Q1"])
    protocol = run_synthetic_verification_protocol(
        run_dir,
        result_id="q1_accepted",
        question_id="Q1",
        objective=2.0,
    )
    assess_result_quality(
        run_dir,
        result_id="q1_accepted",
        assessment=adapter_backed_assessment(protocol),
    )
    # 论文证据只能在独立科学审查放行后进入内容蓝图。
    record_passing_scientific_review(run_dir)
    build_content_blueprint(run_dir, evidence_by_question={"Q1": ["q1_accepted"]})
    source = run_dir / "paper" / "sections" / "q1.typ"
    source.write_text(
        """Q1
直接答案：已完成。
""",
        encoding="utf-8",
    )

    result_report = check_result_references(run_dir)
    numeric_report = check_numeric_consistency(run_dir)

    assert not result_report["success"]
    assert result_report["missing_question_references"] == ["Q1"]
    assert not numeric_report["success"]
    assert numeric_report["missing_question_metrics"] == ["Q1"]

    source.write_text(
        """Q1
直接答案：2.0。
// @result q1_accepted
// @metric q1_accepted.objective 2.0
""",
        encoding="utf-8",
    )

    assert check_result_references(run_dir)["success"]
    assert check_numeric_consistency(run_dir)["success"]
