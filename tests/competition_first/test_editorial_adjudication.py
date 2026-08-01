"""验证 v3.4 Editorial Adjudication：严重性确认、权限边界与路由。

Test H/I/J（设计文档 §43）：
- Test H：Reviewer 报数字错，但 machine binding 证明正文正确 → 不升级；
- Test I：confirmed scientific fact failure → Adjudicator 不可降级；
- Test J：Reviewer P1 → Adjudicator 可降 P2 + substitute。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json
from shumozizi.paper.adjudication import (
    load_confirmed_fact_failures,
    record_adjudication,
    require_paper_editorial_adjudication,
)
from shumozizi.paper.import_audit import classify_fact_candidates
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.state import utc_now


def _run(tmp_path: Path, name: str = "adjudication") -> Path:
    """创建最小 v3.2 运行。"""
    return initialize_simple_run(
        tmp_path,
        name,
        required_questions=["Q1", "Q2", "Q3"],
        workflow_version="3.2",
    )


def _write_reviewer(
    run_dir: Path,
    findings: list[dict[str, object]],
    *,
    source_pdf: str = "paper/external-author/draft.pdf",
) -> None:
    """写入 Fresh Reviewer finding 文档。"""
    document = {
        "schema_name": "paper_reviewer_findings",
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "source_pdf": source_pdf,
        "reviewer_context_id": "fresh-thread-01",
        "findings": findings,
        "generated_at": utc_now(),
    }
    atomic_json(run_dir / "review/paper-reviewer-findings.json", document)


def _write_audit(
    run_dir: Path, *, objective: tuple[str, ...] = (), fact_candidates: tuple[dict, ...] = ()
) -> None:
    """写入最小 import audit（含客观失败与事实候选）。"""
    document = {
        "schema_name": "import_audit",
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "handoff_revision": 1,
        "draft_path": "paper/external-author/draft.tex",
        "compiled": True,
        "compile_errors": [],
        "findings": [],
        "objective_failures": list(objective),
        "fact_candidates": list(fact_candidates),
        "generated_at": utc_now(),
    }
    atomic_json(run_dir / "review/import-audit.json", document)


def _finding(
    finding_id: str, finding_class: str = "argument", severity: str = "P1"
) -> dict[str, object]:
    """构造一条 Reviewer finding。"""
    return {
        "finding_id": finding_id,
        "finding_class": finding_class,
        "severity_recommendation": severity,
        "location": "Q3.4",
        "observation": "该问题影响论证完整性。",
        "why_it_matters": "读者无法判断结论边界。",
        "suggested_route": "author",
        "minimum_fix": "补充机制解释。",
        "acceptance_test": "重新盲读后机制可定位。",
    }


def _decision(finding_id: str, **overrides: object) -> dict[str, object]:
    """构造一条裁决输入。"""
    base: dict[str, object] = {
        "finding_id": finding_id,
        "confirmed": True,
        "confirmed_severity": "P2",
        "route": "author",
        "decision": "rework",
        "reason": "补充机制解释后重审。",
    }
    base.update(overrides)
    return base


def test_reviewer_fact_candidate_not_escalated_when_machine_binding_matches(
    tmp_path: Path,
) -> None:
    """Test H：machine binding 证明正文数字正确 → finding 不升级为事实失败。"""
    run_dir = _run(tmp_path, "machine-match")
    _write_audit(
        run_dir,
        fact_candidates=(
            {"finding_id": "AUD-Q3-NUM-01", "formal_value": "581", "draft_value": "581"},
        ),
    )
    confirmed = classify_fact_candidates(run_dir, _load_audit(run_dir))
    assert confirmed["failures"] == []

    _write_reviewer(
        run_dir,
        [
            _finding(
                "REV-Q3-02",
                finding_class="scientific_fact_candidate",
                severity="P1",
            )
        ],
    )
    document = record_adjudication(
        run_dir,
        [
            _decision(
                "REV-Q3-02",
                confirmed=False,
                confirmed_severity="P3",
                decision="reject",
                reason="machine binding 证明正文数字与正式结果一致，属于误报。",
            )
        ],
    )
    assert document["decisions"][0]["confirmed"] is False
    assert load_confirmed_fact_failures(run_dir) == []
    require_paper_editorial_adjudication(run_dir)  # 可通过


def test_confirmed_fact_failure_cannot_be_downgraded(tmp_path: Path) -> None:
    """Test I：confirmed fact failure → Adjudicator 尝试接受/降级被拒绝。"""
    run_dir = _run(tmp_path, "confirmed-fact")
    _write_audit(run_dir)
    confirmed = {
        "schema_name": "confirmed_scientific_fact_failure",
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "failures": [
            {
                "finding_id": "REV-Q3-02",
                "claim": "正式答案数字应为 581，草稿写为 582",
                "formal_value": "581",
                "draft_value": "582",
                "method": "machine_binding",
                "confirmation_evidence": "正文 582 != 正式结果 581",
                "confirmed_at": utc_now(),
            }
        ],
        "generated_at": utc_now(),
    }
    atomic_json(run_dir / "review/confirmed-scientific-fact-failures.json", confirmed)
    _write_reviewer(
        run_dir,
        [
            _finding(
                "REV-Q3-02",
                finding_class="scientific_fact_candidate",
                severity="P1",
            )
        ],
    )
    with pytest.raises(ContractError, match="不可降级或主观接受"):
        record_adjudication(
            run_dir,
            [
                _decision(
                    "REV-Q3-02",
                    confirmed_severity="P2",
                    decision="accept",
                    reason="虽然是事实错误但影响不大。",
                )
            ],
        )
    with pytest.raises(ContractError, match="不可降级或主观接受"):
        record_adjudication(
            run_dir,
            [
                _decision(
                    "REV-Q3-02",
                    confirmed_severity="P1",
                    decision="waive",
                    reason="时间不够，放弃修复。",
                )
            ],
        )


def test_reviewer_p1_downgraded_to_p2_substitute(tmp_path: Path) -> None:
    """Test J：Reviewer P1 缺机制图 → Adjudicator 降 P2 + substitute 合法。"""
    run_dir = _run(tmp_path, "downgrade")
    _write_audit(run_dir)
    _write_reviewer(
        run_dir,
        [
            _finding("REV-Q3-05", finding_class="visual", severity="P1"),
        ],
    )
    document = record_adjudication(
        run_dir,
        [
            _decision(
                "REV-Q3-05",
                confirmed=True,
                confirmed_severity="P2",
                route="author",
                decision="substitute",
                reason="现有约束余量表和公式足以解释，无需新增图。",
            )
        ],
    )
    assert document["decisions"][0]["confirmed_severity"] == "P2"
    assert document["decisions"][0]["decision"] == "substitute"
    require_paper_editorial_adjudication(run_dir)


def test_audit_objective_failure_cannot_be_accepted(tmp_path: Path) -> None:
    """import audit 客观失败（未知图）不可被 Adjudicator 判为可接受。"""
    run_dir = _run(tmp_path, "objective")
    _write_audit(run_dir, objective=("AUD-FIG-01",))
    _write_reviewer(run_dir, [_finding("AUD-FIG-01", finding_class="visual", severity="P2")])
    with pytest.raises(ContractError, match="客观失败不可主观判为可接受"):
        record_adjudication(
            run_dir,
            [
                _decision(
                    "AUD-FIG-01",
                    confirmed_severity="P3",
                    decision="accept",
                    reason="图其实不太重要。",
                )
            ],
        )


def test_gate_blocks_unadjudicated_findings(tmp_path: Path) -> None:
    """Reviewer finding 未全部裁决时，adjudication 门禁阻断。"""
    run_dir = _run(tmp_path, "unadjudicated")
    _write_audit(run_dir)
    _write_reviewer(run_dir, [_finding("REV-Q3-01", severity="P2")])
    with pytest.raises(ContractError, match="尚未被 Editorial Adjudicator 裁决"):
        require_paper_editorial_adjudication(run_dir)


def test_gate_blocks_unclosed_confirmed_p1(tmp_path: Path) -> None:
    """confirmed P1 未闭合时，adjudication 门禁阻断。"""
    run_dir = _run(tmp_path, "unclosed-p1")
    _write_audit(run_dir)
    _write_reviewer(run_dir, [_finding("REV-Q3-09", finding_class="argument", severity="P1")])
    record_adjudication(
        run_dir,
        [
            _decision(
                "REV-Q3-09",
                confirmed=True,
                confirmed_severity="P1",
                route="author",
                decision="rework",
                reason="论证确实存在缺口。",
            )
        ],
    )
    with pytest.raises(ContractError, match="未闭合 confirmed P1"):
        require_paper_editorial_adjudication(run_dir)
    # confirmed P0/P1 应同步进 PAPER_REVIEW 返修闭环。
    review_md = (run_dir / "paper/PAPER_REVIEW.md").read_text(encoding="utf-8")
    assert "REV-Q3-09" in review_md


def test_adjudication_requires_coverage_of_all_findings(tmp_path: Path) -> None:
    """裁决必须覆盖全部 Reviewer finding，缺一个即报错。"""
    run_dir = _run(tmp_path, "coverage")
    _write_audit(run_dir)
    _write_reviewer(
        run_dir,
        [_finding("REV-Q3-01", severity="P2"), _finding("REV-Q3-02", severity="P3")],
    )
    with pytest.raises(ContractError, match="必须覆盖全部"):
        record_adjudication(
            run_dir,
            [_decision("REV-Q3-01", confirmed_severity="P2", decision="accept")],
        )


def _load_audit(run_dir: Path) -> dict:
    """读取已写入的 import audit 供 classify 使用。"""
    from shumozizi.core.io import load_json

    return load_json(run_dir / "review/import-audit.json")
