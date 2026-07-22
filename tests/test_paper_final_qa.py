"""验证终检复验论文参考收据与贡献账本。"""

from __future__ import annotations

from pathlib import Path

import scripts.qa.run_final_checks as final_checks
from shumozizi.simple.initialization import initialize_simple_run


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
    monkeypatch.setattr(final_checks, "verify_current_result_files", lambda *_args: {"success": True})
    monkeypatch.setattr(final_checks, "verify_current_figure_files", lambda *_args: {"success": True})
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
