"""阶段 1A/1B 审核模式、输入隔离和关闭路径测试。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.core.schema import schema_root
from shumozizi.workflow.review_policy import (
    DEFERRED_BLOCK_POINTS,
    FINDING_CONFIDENCE_LEVELS,
    FINDING_DOMAINS,
    FINDING_STATUSES,
    REVIEW_MODES,
    VERIFICATION_MODES,
)
from shumozizi.workflow.review_sessions import claim_review_request
from shumozizi.workflow.reviews import (
    create_review_request,
    materialize_review_receipt,
    write_review_adjudication,
    write_review_report,
)
from shumozizi.workflow.state_service import Actor, StateService


def _write_state(run_dir: Path, *, with_passed_gates: bool = False) -> None:
    review_gates = (
        {
            "R1_MODELING": {"status": "passed", "receipt": "review/r1.json"},
            "R2_EXPERIMENT_q1": {
                "status": "passed",
                "receipt": "review/r2-q1.json",
            },
        }
        if with_passed_gates
        else {}
    )
    atomic_json(
        run_dir / "state.json",
        {
            "schema_name": "workflow_state",
            "schema_version": "2.0",
            "run_schema_version": "2.0",
            "run_id": run_dir.name,
            "problem_source": "problems/sample.md",
            "mode": "competition",
            "status": "MODEL_SPEC_READY",
            "revision": 3,
            "completed_stages": ["ROUTE_LOCKED"],
            "active_stage": "review",
            "route_locked": True,
            "paper_ready": False,
            "question_progress": {},
            "review_gates": review_gates,
            "artifacts": {},
            "last_updated_by": "test",
            "updated_at": "2026-07-21T00:00:00Z",
            "history": [],
        },
    )


def _write_text(path: Path, content: str = "fixture\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _finding(
    finding_id: str,
    severity: str,
    *,
    status: str = "open",
    reopen_context: dict | None = None,
) -> dict:
    finding = {
        "finding_id": finding_id,
        "severity_recommendation": severity,
        "title": "审核发现",
        "claim": "当前证据可能不足以支持结论",
        "evidence": ["repair_evidence.json:1"],
        "why_it_may_be_wrong": "证据与结论之间仍有可验证缺口",
        "confidence": "high",
        "status": status,
    }
    if reopen_context is not None:
        finding["reopen_context"] = reopen_context
    return finding


def _reopen_context() -> dict:
    return {
        "relation_to_change": "本次修改改变了原 finding 的直接依赖",
        "previously_undiscoverable_reason": "旧版本中该依赖尚未存在",
        "reopen_evidence": ["before_after.diff:12"],
        "reopen_justification": "新证据足以重新打开科学 P1",
    }


def _mode_bindings(run_dir: Path, review_mode: str) -> dict[str, Path]:
    root = run_dir / "review/recheck_inputs/case-1"
    common = {
        "original_finding": _write_text(root / "original_finding.json", "{}\n"),
        "source_adjudication": _write_text(
            run_dir / "review/r1_modeling/source/REVIEW_ADJUDICATION.json", "{}\n"
        ),
        "repair_evidence": _write_text(root / "repair_evidence.json", "{}\n"),
    }
    if review_mode == "targeted_recheck":
        return {
            **common,
            "before_after_diff": _write_text(root / "before_after.diff"),
            "direct_dependencies": _write_text(root / "direct_dependencies.json", "[]\n"),
        }
    if review_mode == "diff_check":
        return {
            "before_after_diff": _write_text(root / "before_after.diff"),
            "repair_evidence": common["repair_evidence"],
        }
    if review_mode == "machine_check":
        return {
            "original_finding": common["original_finding"],
            "source_adjudication": common["source_adjudication"],
            "machine_evidence": _write_text(root / "machine_evidence.json", "{}\n"),
        }
    raise AssertionError(review_mode)


def _request(
    tmp_path: Path,
    review_mode: str,
    *,
    run_id: str,
    stage: str = "R1_MODELING",
    with_passed_gates: bool = False,
) -> tuple[Path, Path]:
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    _write_state(run_dir, with_passed_gates=with_passed_gates)
    request = create_review_request(
        run_dir,
        stage,
        _mode_bindings(run_dir, review_mode),
        review_mode=review_mode,
        target_finding_id="F-ORIGINAL",
        review_round_id="round-1",
    )
    return run_dir, request


def _report(
    request_path: Path,
    findings: list[dict],
    *,
    review_mode: str | None = None,
) -> dict:
    request = load_json(request_path)
    session = claim_review_request(
        request_path, thread_id=f"thread-{request['run_id']}-{request['review_mode']}"
    )
    verdicts = {
        "R1_MODELING": ("SPEC_REVISION_REQUIRED", "ACCEPT"),
        "R2_EXPERIMENT": ("BLOCKED", "REPRODUCIBLE"),
        "R3_PAPER_LOGIC": ("MAJOR_REVISION", "READY_FOR_COMPREHENSIVE_REVIEW"),
        "R4_FORMAT_VISUAL": ("FIX_REQUIRED", "COMPLIANT"),
        "R5_COMPREHENSIVE": ("E", "B"),
        "J0_FINAL_BLIND_JUDGE": ("DO_NOT_PROCEED", "PROCEED"),
    }
    failing_verdict, passing_verdict = verdicts[request["stage"]]
    return {
        "schema_name": "review_report",
        "schema_version": "3.0",
        "request_id": request["request_id"],
        "run_id": request["run_id"],
        "stage": request["stage"],
        "review_round_id": request["review_round_id"],
        "review_mode": review_mode or request["review_mode"],
        "target_finding_id": request.get("target_finding_id"),
        "request_sha256": sha256_file(request_path),
        "input_manifest_sha256": request["input_manifest_sha256"],
        "session_sha256": sha256_file(session),
        "verdict": failing_verdict if findings else passing_verdict,
        "findings": findings,
        "read_only_confirmed": True,
        "generated_at": "2026-07-21T00:00:00Z",
    }


def _decision(
    finding: dict,
    *,
    main_decision: str,
    domain: str,
    verification_mode: str,
    effective_severity: str | None = None,
    semantic_change: bool = False,
    reopen_justification: str | None = None,
) -> dict:
    severity = finding["severity_recommendation"]
    return {
        "finding_id": finding["finding_id"],
        "reviewer_severity": severity,
        "main_decision": main_decision,
        "effective_severity": effective_severity or severity,
        "domain": domain,
        "verification_mode": verification_mode,
        "scientific_semantic_change": semantic_change,
        "gate_effect": {
            "accepted": "block" if (effective_severity or severity) in {"P0", "P1"} else "warn",
            "accepted_as_advisory": "warn",
            "rejected": "none",
            "deferred_empirical": "warn",
        }[main_decision],
        "decision_reason": "生产主 AI 独立核验",
        "confirmation_evidence": ["test:confirmed"] if main_decision == "accepted" else [],
        "counter_evidence": ["machine:test"] if main_decision == "rejected" else [],
        "resolution_evidence_type": (
            "deterministic_machine_evidence" if main_decision == "rejected" else None
        ),
        "effective_change_level": "L3",
        "affected_questions": ["q1"],
        "required_retests": ["R2_EXPERIMENT_q1"],
        "route_reapproval_required": False,
        "reopen_justification": reopen_justification,
    }


def _adjudication(report_path: Path, decisions: list[dict]) -> dict:
    report = load_json(report_path)
    request = load_json(report_path.with_name("review_request.json"))
    return {
        "schema_name": "review_adjudication",
        "schema_version": "2.0",
        "run_id": report["run_id"],
        "request_id": report["request_id"],
        "stage": report["stage"],
        "review_mode": report["review_mode"],
        "state_revision": request["state_revision"],
        "review_report_sha256": sha256_file(report_path),
        "decisions": decisions,
        "unresolved_conflicts": [],
        "generated_by": "production_main_ai",
        "generated_at": "2026-07-21T00:00:00Z",
    }


def test_review_mode_enums_match_schema_and_skill() -> None:
    """Python、三个 Schema 与审核 Skill 必须使用同一枚举。"""
    expected = set(REVIEW_MODES)
    for filename in (
        "review_request.schema.json",
        "review_input_manifest.schema.json",
        "review_report.schema.json",
        "review_adjudication.schema.json",
    ):
        schema = load_json(schema_root() / filename)
        assert set(schema["properties"]["review_mode"]["enum"]) == expected
    report_schema = load_json(schema_root() / "review_report.schema.json")
    finding = report_schema["$defs"]["reviewer_finding_v3"]
    assert set(finding["properties"]["confidence"]["enum"]) == set(
        FINDING_CONFIDENCE_LEVELS
    )
    assert set(finding["properties"]["status"]["enum"]) == set(FINDING_STATUSES)
    assert set(finding["properties"]["block_before"]["enum"]) == set(
        DEFERRED_BLOCK_POINTS
    )
    adjudication_schema = load_json(schema_root() / "review_adjudication.schema.json")
    decision = adjudication_schema["properties"]["decisions"]["items"]
    assert set(decision["properties"]["domain"]["enum"]) == set(FINDING_DOMAINS)
    assert set(decision["properties"]["verification_mode"]["enum"]) == set(
        VERIFICATION_MODES
    )
    state_schema = load_json(schema_root() / "workflow_state.schema.json")
    gate = state_schema["properties"]["review_gates"]["additionalProperties"]
    assert set(gate["properties"]["review_mode"]["enum"]) == expected
    skill = Path(".agents/skills/mathmodel-review/SKILL.md").read_text(encoding="utf-8")
    block = re.search(
        r"REVIEW_MODES_START.*?```text\n(.*?)\n```.*?REVIEW_MODES_END",
        skill,
        flags=re.DOTALL,
    )
    assert block is not None
    assert set(block.group(1).splitlines()) == expected


def test_targeted_review_receives_only_scoped_inputs(tmp_path: Path) -> None:
    """targeted reviewer 不能通过额外 read path 读取完整题面。"""
    run_dir = tmp_path / "runs/targeted-inputs"
    run_dir.mkdir(parents=True)
    _write_state(run_dir)
    bindings = _mode_bindings(run_dir, "targeted_recheck")
    problem = _write_text(run_dir / "problems/full-problem.md", "完整题面\n")

    with pytest.raises(ContractError, match="限定输入|策略未声明|禁止读取"):
        create_review_request(
            run_dir,
            "R1_MODELING",
            bindings,
            review_mode="targeted_recheck",
            target_finding_id="F-ORIGINAL",
            read_paths=[*bindings.values(), problem],
        )


@pytest.mark.parametrize(
    "forbidden_path",
    [
        "problems/full-problem.md",
        "review/other-round/review_report.json",
        "results/unrelated-result.json",
    ],
)
def test_targeted_review_rejects_relabelled_forbidden_material(
    tmp_path: Path, forbidden_path: str
) -> None:
    """策略角色不能把题面、其他报告或无关产物伪装成修复证据。"""
    run_dir = tmp_path / f"runs/targeted-alias-{Path(forbidden_path).stem}"
    run_dir.mkdir(parents=True)
    _write_state(run_dir)
    bindings = _mode_bindings(run_dir, "targeted_recheck")
    bindings["repair_evidence"] = _write_text(
        run_dir / forbidden_path, "禁止材料\n"
    )

    with pytest.raises(ContractError, match="禁止读取"):
        create_review_request(
            run_dir,
            "R1_MODELING",
            bindings,
            review_mode="targeted_recheck",
            target_finding_id="F-ORIGINAL",
        )


def test_targeted_review_rejects_unrelated_p2(tmp_path: Path) -> None:
    """targeted recheck 不得新增与原 finding 无关的 P2/P3。"""
    _, request = _request(
        tmp_path, "targeted_recheck", run_id="targeted-unrelated-p2"
    )
    report = _report(request, [_finding("F-UNRELATED", "P2")])

    with pytest.raises(ContractError, match="无关 P2/P3"):
        write_review_report(request, report)


@pytest.mark.parametrize("severity", ["P0", "P1"])
def test_new_p0_p1_requires_reopen_context(tmp_path: Path, severity: str) -> None:
    """targeted recheck 新增 P0/P1 必须提供完整 reopening 证据。"""
    _, request = _request(
        tmp_path, "targeted_recheck", run_id=f"targeted-new-{severity.lower()}"
    )
    report = _report(request, [_finding("F-NEW", severity)])

    with pytest.raises(ContractError, match="reopen_context|重新打开"):
        write_review_report(request, report)


def test_new_p1_adjudication_requires_reopen_justification(tmp_path: Path) -> None:
    """即使 reviewer 提供证据，生产裁决仍必须独立说明为何重新打开。"""
    _, request = _request(
        tmp_path, "targeted_recheck", run_id="targeted-new-p1-adjudication"
    )
    finding = _finding("F-NEW", "P1", reopen_context=_reopen_context())
    report_path = write_review_report(request, _report(request, [finding]))
    decision = _decision(
        finding,
        main_decision="accepted",
        domain="scientific",
        verification_mode="targeted_recheck",
    )

    with pytest.raises(ContractError, match="reopen_justification"):
        write_review_adjudication(report_path, _adjudication(report_path, [decision]))
    decision["reopen_justification"] = "生产主 AI 确认新证据与修改直接相关"
    assert write_review_adjudication(
        report_path, _adjudication(report_path, [decision])
    ).is_file()


def test_full_and_targeted_modes_cannot_impersonate_each_other(tmp_path: Path) -> None:
    """报告声明的模式必须与冻结请求完全一致。"""
    _, request = _request(
        tmp_path, "targeted_recheck", run_id="targeted-impersonation"
    )
    report = _report(
        request,
        [_finding("F-ORIGINAL", "P1")],
        review_mode="full_scientific",
    )

    with pytest.raises(ContractError, match="review_mode"):
        write_review_report(request, report)


def test_targeted_r5_does_not_require_or_emit_full_scoring(tmp_path: Path) -> None:
    """局部 R5 复核不能被 Schema 强迫伪装成完整竞赛评分。"""
    _, request = _request(
        tmp_path,
        "targeted_recheck",
        run_id="targeted-r5",
        stage="R5_COMPREHENSIVE",
    )
    report_path = write_review_report(
        request, _report(request, [_finding("F-ORIGINAL", "P1")])
    )
    report = load_json(report_path)

    assert report["review_mode"] == "targeted_recheck"
    assert "quality_axis" not in report
    assert "raw_score" not in report


def test_machine_p1_closes_with_machine_check(tmp_path: Path) -> None:
    """确定性 machine P1 可由 machine_check 证据关闭，无需 reviewer 复核。"""
    run_dir, request = _request(
        tmp_path, "machine_check", run_id="machine-p1-close"
    )
    finding = _finding("F-ORIGINAL", "P1")
    report_path = write_review_report(request, _report(request, [finding]))
    decision = _decision(
        finding,
        main_decision="rejected",
        domain="machine",
        verification_mode="machine_check",
    )
    adjudication = write_review_adjudication(
        report_path, _adjudication(report_path, [decision])
    )
    receipt = materialize_review_receipt(request, report_path)
    state = StateService(tmp_path).record_review_gate(
        run_dir.name, "R1_MODELING", receipt, Actor("machine-check")
    )

    assert adjudication.is_file()
    assert state["review_gates"]["R1_MODELING"]["status"] == "passed"


def test_scientific_p1_requires_targeted_reviewer(tmp_path: Path) -> None:
    """科学 P1 不能伪装成 machine_check 直接关闭。"""
    _, request = _request(
        tmp_path, "targeted_recheck", run_id="scientific-p1-machine"
    )
    finding = _finding("F-ORIGINAL", "P1")
    report_path = write_review_report(request, _report(request, [finding]))
    decision = _decision(
        finding,
        main_decision="accepted",
        domain="scientific",
        verification_mode="machine_check",
    )

    with pytest.raises(ContractError, match="targeted_recheck"):
        write_review_adjudication(report_path, _adjudication(report_path, [decision]))


def test_scientific_p1_closure_binds_independent_reviewer_evidence(
    tmp_path: Path,
) -> None:
    """科学 P1 的关闭证据必须来自独立 targeted reviewer。"""
    _, request = _request(
        tmp_path, "targeted_recheck", run_id="scientific-p1-independent"
    )
    finding = _finding("F-ORIGINAL", "P1")
    report_path = write_review_report(request, _report(request, [finding]))
    decision = _decision(
        finding,
        main_decision="rejected",
        domain="scientific",
        verification_mode="targeted_recheck",
    )

    with pytest.raises(ContractError, match="独立复核证据"):
        write_review_adjudication(report_path, _adjudication(report_path, [decision]))
    decision["resolution_evidence_type"] = "independent_second_review"
    decision["counter_evidence"] = ["targeted-review:confirmed-closure"]
    assert write_review_adjudication(
        report_path, _adjudication(report_path, [decision])
    ).is_file()


def test_p2_semantic_change_is_reclassified(tmp_path: Path) -> None:
    """P2 修复触及科学语义时必须升级为科学 P1 并定向复核。"""
    _, request = _request(
        tmp_path, "targeted_recheck", run_id="p2-semantic-reclass"
    )
    finding = _finding("F-ORIGINAL", "P2")
    report_path = write_review_report(request, _report(request, [finding]))
    decision = _decision(
        finding,
        main_decision="accepted",
        domain="scientific",
        verification_mode="diff_check",
        semantic_change=True,
    )

    with pytest.raises(ContractError, match="重新分类|P1"):
        write_review_adjudication(report_path, _adjudication(report_path, [decision]))
    upgraded = _decision(
        finding,
        main_decision="accepted",
        domain="scientific",
        verification_mode="targeted_recheck",
        effective_severity="P1",
        semantic_change=True,
    )
    assert write_review_adjudication(
        report_path, _adjudication(report_path, [upgraded])
    ).is_file()


def test_deferred_empirical_requires_bounded_closure_contract(tmp_path: Path) -> None:
    """deferred_empirical 必须声明阻断点、关闭条件和失败动作。"""
    _, request = _request(
        tmp_path, "targeted_recheck", run_id="deferred-empirical"
    )
    finding = _finding("F-ORIGINAL", "P1", status="deferred_empirical")
    report = _report(request, [finding])

    with pytest.raises(ContractError, match="closure_condition|关闭条件"):
        write_review_report(request, report)
    report["findings"][0].update(
        {
            "block_before": "model_selection",
            "closure_condition": "完成预注册稳健性实验并达到阈值",
            "failure_action": "退回已确认 baseline",
        }
    )
    report_path = write_review_report(request, report)
    decision = _decision(
        report["findings"][0],
        main_decision="deferred_empirical",
        domain="scientific",
        verification_mode="targeted_recheck",
    )
    assert write_review_adjudication(
        report_path, _adjudication(report_path, [decision])
    ).is_file()


@pytest.mark.parametrize(
    ("severity", "verification_mode"),
    [("P2", "diff_check"), ("P3", "none")],
)
def test_p2_p3_have_nonreviewer_closure_paths(
    tmp_path: Path, severity: str, verification_mode: str
) -> None:
    """非语义 P2 走差异检查，P3 可直接作为不阻断建议关闭。"""
    _, request = _request(
        tmp_path,
        "targeted_recheck",
        run_id=f"{severity.lower()}-closure",
    )
    finding = _finding("F-ORIGINAL", severity)
    report_path = write_review_report(request, _report(request, [finding]))
    decision = _decision(
        finding,
        main_decision="accepted_as_advisory",
        domain="scientific",
        verification_mode=verification_mode,
    )

    path = write_review_adjudication(
        report_path, _adjudication(report_path, [decision])
    )
    assert path.is_file()


def test_diff_check_does_not_stale_unrelated_r1_r2(tmp_path: Path) -> None:
    """创建和执行 diff_check 不得修改无关 R1/R2 gate 状态。"""
    run_dir, request = _request(
        tmp_path,
        "diff_check",
        run_id="diff-no-stale",
        stage="R3_PAPER_LOGIC",
        with_passed_gates=True,
    )
    before = load_json(run_dir / "state.json")["review_gates"]
    report_path = write_review_report(request, _report(request, []))
    write_review_adjudication(report_path, _adjudication(report_path, []))
    after = load_json(run_dir / "state.json")["review_gates"]

    assert before == after
    assert after["R1_MODELING"]["status"] == "passed"
    assert after["R2_EXPERIMENT_q1"]["status"] == "passed"
