"""验证全面审核后的查漏门禁不能被 Competition-First 放行链绕过。"""

from __future__ import annotations

from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, sha256_file
from shumozizi.simple.review_gaps import verify_review_gap_completion
from shumozizi.simple.review_tasks import (
    create_review_task_receipt,
    persist_review_task_creation_event,
    validate_review_task_receipt,
)


def test_missing_gap_report_blocks_release(tmp_path: Path) -> None:
    """即使全面报告存在，未生成 gap 报告时也不得放行。"""
    run_dir = tmp_path / "gap-missing"
    report = run_dir / "review" / "SCIENTIFIC_CHALLENGE.md"
    report.parent.mkdir(parents=True)
    report.write_text("# 全面科学审核\n\n已执行独立攻击。\n", encoding="utf-8")

    status = verify_review_gap_completion(
        run_dir,
        scope="scientific",
        review_report={"report": {"file": "review/SCIENTIFIC_CHALLENGE.md"}},
    )

    assert not status["allowed"]
    assert "gap" in status["reason"]


def test_manual_thread_id_cannot_satisfy_fresh_thread_gate(tmp_path: Path) -> None:
    """仅向回执生成器传入 thread_id 不能证明它来自 create_thread。"""
    run_dir = tmp_path / "manual-thread"
    report = run_dir / "review" / "followup.md"
    report.parent.mkdir(parents=True)
    report.write_text("# 专项审核\n\n已复验。\n", encoding="utf-8")
    receipt = create_review_task_receipt(
        run_dir,
        task_id="manual",
        task_type="scientific_follow_up",
        thread_id="caller-supplied-id",
        model_id="fixture-model",
        prompt_sha256="1" * 64,
        input_bindings={"risk_id": "example"},
        report_file="review/followup.md",
        parent_task_id="primary",
    )

    with pytest.raises(ContractError, match="create_thread"):
        validate_review_task_receipt(
            run_dir,
            receipt.relative_to(run_dir).as_posix(),
            expected_type="scientific_follow_up",
            expected_report="review/followup.md",
            expected_input_bindings={"risk_id": "example"},
            expected_parent_task_id="primary",
            require_fresh_thread=True,
        )


def test_negative_keyword_mention_is_not_an_attack(tmp_path: Path) -> None:
    """“尚未检查 proxy/exact”这类否定提及不能把风险标为已攻击。"""
    run_dir = tmp_path / "negative-mention"
    report = run_dir / "review" / "SCIENTIFIC_CHALLENGE.md"
    report.parent.mkdir(parents=True)
    report.write_text(
        "# 代理与精确排序\n\n代理与精确排序反转尚未检查。\n",
        encoding="utf-8",
    )
    method_facts = run_dir / "analysis" / "method_facts.json"
    atomic_json(
        method_facts,
        {
            "schema_version": "1.1",
            "run_id": run_dir.name,
            "facts": {
                "uses_continuous_time": False,
                "uses_discrete_approximation": False,
                "uses_proxy_objective": True,
                "uses_heuristic_optimization": False,
                "candidate_search_limited": False,
                "uses_temporal_split": False,
                "has_shared_downstream_dependency": False,
            },
        },
    )
    strong_claims = run_dir / "review" / "strong_claims" / "scientific.json"
    atomic_json(
        strong_claims,
        {
            "schema_name": "review_strong_claims",
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "scope": "scientific",
            "review_file": "review/SCIENTIFIC_CHALLENGE.md",
            "review_sha256": sha256_file(report),
            "claims": [],
        },
    )
    atomic_json(
        run_dir / "review" / "gaps" / "round-1.json",
        {
            "schema_name": "review_gap_report",
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "scope": "scientific",
            "review_file": "review/SCIENTIFIC_CHALLENGE.md",
            "review_sha256": sha256_file(report),
            "method_facts_file": "analysis/method_facts.json",
            "method_facts_sha256": sha256_file(method_facts),
            "strong_claims_file": "review/strong_claims/scientific.json",
            "strong_claims_sha256": sha256_file(strong_claims),
            "risks": [
                {
                    "risk_id": "proxy-exact-reversal",
                    "coverage_status": "attacked",
                    "evidence_locations": [
                        "review/SCIENTIFIC_CHALLENGE.md#代理与精确排序"
                    ],
                    "conclusion": "报告提到了排序反转。",
                }
            ],
            "findings": [],
            "closures": [],
        },
    )

    status = verify_review_gap_completion(
        run_dir,
        scope="scientific",
        review_report={
            "report": {"file": "review/SCIENTIFIC_CHALLENGE.md"},
            "task_receipt": {"task_id": "primary"},
            "reviewer": {"thread_id": "primary-thread"},
        },
    )

    assert not status["allowed"]
    assert any("attack_performed" in error or "evidence_files" in error for error in status["errors"])


def test_every_blocking_p2_needs_its_own_closure(tmp_path: Path) -> None:
    """只关闭三个 P2 中的一个时，整轮全面审核不得放行。"""
    run_dir = tmp_path / "p2-set"
    report = run_dir / "review" / "SCIENTIFIC_CHALLENGE.md"
    report.parent.mkdir(parents=True)
    report.write_text("# 全面审核\n\n发现两个 P2。\n", encoding="utf-8")
    method_facts = run_dir / "analysis" / "method_facts.json"
    atomic_json(
        method_facts,
        {
            "schema_version": "1.1",
            "run_id": run_dir.name,
            "facts": {
                "uses_continuous_time": False,
                "uses_discrete_approximation": False,
                "uses_proxy_objective": False,
                "uses_heuristic_optimization": False,
                "candidate_search_limited": False,
                "uses_temporal_split": False,
                "has_shared_downstream_dependency": False,
            },
        },
    )
    strong_claims = run_dir / "review" / "strong_claims" / "scientific.json"
    atomic_json(
        strong_claims,
        {
            "schema_name": "review_strong_claims",
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "scope": "scientific",
            "review_file": "review/SCIENTIFIC_CHALLENGE.md",
            "review_sha256": sha256_file(report),
            "claims": [],
        },
    )
    repair = run_dir / "results" / "evidence" / "p2-01.json"
    repair.parent.mkdir(parents=True)
    repair.write_text("{}", encoding="utf-8")
    followup = run_dir / "review" / "followups" / "p2-01.md"
    followup.parent.mkdir(parents=True)
    followup.write_text("# P2-01 专项\n\n已验证恢复条件。\n", encoding="utf-8")
    event = persist_review_task_creation_event(
        run_dir,
        event_file="review/tasks/creation-events/p2-01.json",
        raw_event={
            "schema_name": "review_task_creation_event",
            "schema_version": "1.0",
            "provider": "codex",
            "raw_task_id": "fresh-p2-01-task",
            "raw_thread_id": "fresh-p2-01-thread",
            "creation_mode": "create_thread",
            "parent_context_inherited": False,
            "created_at": "2026-07-25T00:00:00Z",
        },
    )
    receipt = create_review_task_receipt(
        run_dir,
        task_id="p2-01-followup",
        task_type="scientific_follow_up",
        model_id="fixture-model",
        prompt_sha256="1" * 64,
        input_bindings={
            "review_report": {
                "file": "review/SCIENTIFIC_CHALLENGE.md",
                "sha256": sha256_file(report),
            },
            "finding_id": "P2-01",
        },
        report_file="review/followups/p2-01.md",
        parent_task_id="primary",
        creation_event_file=event.relative_to(run_dir).as_posix(),
    )
    atomic_json(
        run_dir / "review" / "gaps" / "round-1.json",
        {
            "schema_name": "review_gap_report",
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "scope": "scientific",
            "review_file": "review/SCIENTIFIC_CHALLENGE.md",
            "review_sha256": sha256_file(report),
            "method_facts_file": "analysis/method_facts.json",
            "method_facts_sha256": sha256_file(method_facts),
            "strong_claims_file": "review/strong_claims/scientific.json",
            "strong_claims_sha256": sha256_file(strong_claims),
            "risks": [],
            "findings": [
                {
                    "finding_id": "P2-01",
                    "severity": "P2",
                    "blocking": True,
                    "recovery_condition": "补充 P2-01 的独立证据。",
                },
                {
                    "finding_id": "P2-02",
                    "severity": "P2",
                    "blocking": True,
                    "recovery_condition": "补充 P2-02 的独立证据。",
                },
            ],
            "closures": [
                {
                    "finding_id": "P2-01",
                    "status": "closed",
                    "recovery_condition": "补充 P2-01 的独立证据。",
                    "repaired_files": ["results/evidence/p2-01.json"],
                    "task_receipt": receipt.relative_to(run_dir).as_posix(),
                    "report_file": "review/followups/p2-01.md",
                    "report_sha256": sha256_file(followup),
                }
            ],
        },
    )

    status = verify_review_gap_completion(
        run_dir,
        scope="scientific",
        review_report={
            "report": {"file": "review/SCIENTIFIC_CHALLENGE.md"},
            "task_receipt": {"task_id": "primary"},
            "reviewer": {"thread_id": "primary-thread"},
        },
    )

    assert not status["allowed"]
    assert any("P2-02" in error for error in status["errors"])
