"""完整审核根、scoped closure 来源链与 deferred obligation 攻击测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.workflow.r1_phases import create_r1_phase_a, create_r1_phase_b_request
from shumozizi.workflow.review_sessions import claim_review_request
from shumozizi.workflow.reviews import (
    R1_COVERAGE_CHECKS,
    _validate_review_mode_report,
    create_review_request,
    materialize_review_receipt,
    write_review_adjudication,
    write_review_report,
)
from shumozizi.workflow.state_service import Actor, StateService, WorkflowEvent
from tests.review_contract_helpers import complete_stage_bindings
from tests.test_production_closure import _review_run
from tests.test_r1_r2_scientific_contracts import _phase_a_outputs
from tests.test_review_contracts import (
    _accept_report,
    _finding_report,
    _r1_request,
)
from tests.test_review_contracts import (
    _adjudication as _full_adjudication,
)
from tests.test_review_contracts import (
    _decision as _full_decision,
)
from tests.test_review_modes import (
    _adjudication as _scoped_adjudication,
)
from tests.test_review_modes import (
    _decision as _scoped_decision,
)
from tests.test_review_modes import (
    _finding as _v3_finding,
)
from tests.test_review_modes import (
    _report as _scoped_report,
)
from tests.test_review_modes import (
    _write_state,
    _write_text,
)


def _registered_full_r1(
    tmp_path: Path,
    run_id: str,
    *,
    count: int = 1,
    domain: str = "machine",
    verification_mode: str = "machine_check",
) -> tuple[Path, Path, Path, Path, dict]:
    """登记一个包含 open blocking finding 的完整 R1 根审核。"""
    run_dir, request = _r1_request(tmp_path, run_id=run_id, round_id="base-full")
    session = claim_review_request(request, thread_id=f"thread-{run_id}-full")
    report = write_review_report(
        request,
        _finding_report(request, sha256_file(session), severity="P1", count=count),
    )
    decisions = []
    for index in range(1, count + 1):
        decision = _full_decision(f"finding-{index}", "P1", "accepted")
        decision.update(
            {
                "domain": domain,
                "verification_mode": verification_mode,
                "scientific_semantic_change": False,
                "reopen_justification": None,
            }
        )
        decisions.append(decision)
    adjudication = write_review_adjudication(
        report, _full_adjudication(report, decisions)
    )
    receipt = materialize_review_receipt(request, report)
    state = StateService(tmp_path).record_review_gate(
        run_dir.name, "R1_MODELING", receipt, Actor("full-review")
    )
    assert state["review_gates"]["R1_MODELING"]["status"] == "failed"
    return run_dir, report, adjudication, receipt, state


def _scoped_bindings(
    run_dir: Path,
    report_path: Path,
    adjudication_path: Path,
    *,
    target_finding_id: str,
    review_mode: str,
) -> dict[str, Path]:
    report = load_json(report_path)
    finding = next(
        item for item in report["findings"] if item["finding_id"] == target_finding_id
    )
    root = run_dir / f"review/recheck_inputs/{review_mode}-{target_finding_id}"
    original = root / "original_finding.json"
    atomic_json(original, finding)
    common = {
        "original_finding": original,
        "source_adjudication": adjudication_path,
    }
    if review_mode == "machine_check":
        return {
            **common,
            "machine_evidence": _write_text(root / "machine_evidence.json", "{}\n"),
        }
    if review_mode == "diff_check":
        return {
            **common,
            "before_after_diff": _write_text(root / "before_after.diff"),
            "repair_evidence": _write_text(root / "repair_evidence.json", "{}\n"),
        }
    return {
        **common,
        "before_after_diff": _write_text(root / "before_after.diff"),
        "repair_evidence": _write_text(root / "repair_evidence.json", "{}\n"),
        "direct_dependencies": _write_text(root / "direct_dependencies.json", "[]\n"),
    }


def _scoped_receipt(
    tmp_path: Path,
    run_dir: Path,
    report_path: Path,
    adjudication_path: Path,
    *,
    target_finding_id: str = "finding-1",
    review_mode: str = "machine_check",
) -> tuple[Path, Path]:
    request = create_review_request(
        run_dir,
        "R1_MODELING",
        _scoped_bindings(
            run_dir,
            report_path,
            adjudication_path,
            target_finding_id=target_finding_id,
            review_mode=review_mode,
        ),
        review_mode=review_mode,
        target_finding_id=target_finding_id,
        source_gate_id="R1_MODELING",
        review_round_id=f"{review_mode}-{target_finding_id}",
    )
    scoped_report = write_review_report(request, _scoped_report(request, []))
    write_review_adjudication(
        scoped_report, _scoped_adjudication(scoped_report, [])
    )
    return request, materialize_review_receipt(request, scoped_report)


def _replacement_full_r1(
    tmp_path: Path, run_dir: Path, *, round_id: str
) -> tuple[Path, dict]:
    """为 stale R1 创建并登记新的通过态完整根。"""
    _, request = _r1_request(tmp_path, run_id=run_dir.name, round_id=round_id)
    session = claim_review_request(
        request, thread_id=f"thread-{run_dir.name}-{round_id}"
    )
    report = write_review_report(
        request, _accept_report(request, sha256_file(session))
    )
    write_review_adjudication(report, _full_adjudication(report, []))
    receipt = materialize_review_receipt(request, report)
    state = StateService(tmp_path).record_review_gate(
        run_dir.name, "R1_MODELING", receipt, Actor("replacement-full")
    )
    return receipt, state


def _registered_deferred_r1(
    tmp_path: Path, run_id: str
) -> tuple[Path, Path, Path, dict]:
    """登记一个在 model_selection 前关闭的 R1 deferred finding。"""
    run_dir, seed_request = _r1_request(
        tmp_path, run_id=run_id, round_id="phase-a-seed"
    )
    seed = load_json(seed_request)
    bindings = {
        role: run_dir / relative
        for role, relative in seed["binding_paths"].items()
    }
    phase_a = create_r1_phase_a(
        run_dir,
        "deferred-full",
        {"problem_source": bindings["problem_source"]},
        _phase_a_outputs(),
    )
    request = create_r1_phase_b_request(
        run_dir,
        phase_a,
        bindings,
        review_round_id="deferred-full",
    )
    session = claim_review_request(
        request, thread_id=f"thread-{run_id}-deferred-full"
    )
    finding = _v3_finding("F-DEFERRED", "P1", status="deferred_empirical")
    finding.update(
        {
            "block_before": "model_selection",
            "closure_condition": "完成预注册稳健性实验并达到阈值",
            "failure_action": "退回已确认 baseline",
        }
    )
    request_doc = load_json(request)
    report_doc = {
        "schema_name": "review_report",
        "schema_version": "3.0",
        "request_id": request_doc["request_id"],
        "run_id": run_dir.name,
        "stage": "R1_MODELING",
        "review_round_id": request_doc["review_round_id"],
        "review_mode": "full_scientific",
        "request_sha256": sha256_file(request),
        "input_manifest_sha256": request_doc["input_manifest_sha256"],
        "session_sha256": sha256_file(session),
        "phase_a_sha256": sha256_file(phase_a),
        "verdict": "SPEC_REVISION_REQUIRED",
        "coverage": {
            **{check_id: "verified" for check_id in R1_COVERAGE_CHECKS},
            "unchecked_items": [],
        },
        "findings": [finding],
        "read_only_confirmed": True,
        "generated_at": "2026-07-21T00:00:00Z",
    }
    report = write_review_report(request, report_doc)
    decision = _scoped_decision(
        finding,
        main_decision="deferred_empirical",
        domain="scientific",
        verification_mode="targeted_recheck",
    )
    adjudication = write_review_adjudication(
        report, _scoped_adjudication(report, [decision])
    )
    receipt = materialize_review_receipt(request, report)
    state = StateService(tmp_path).record_review_gate(
        run_dir.name, "R1_MODELING", receipt, Actor("deferred-full")
    )
    assert state["review_gates"]["R1_MODELING"]["status"] == "passed"
    return run_dir, report, adjudication, state


def test_scoped_review_cannot_bootstrap_full_gate(tmp_path: Path) -> None:
    """没有 full root 时 scoped request 必须在创建阶段失败。"""
    run_dir = tmp_path / "runs/scoped-bootstrap"
    run_dir.mkdir(parents=True)
    _write_state(run_dir)
    root = run_dir / "review/recheck_inputs/forged"
    bindings = {
        "original_finding": _write_text(root / "original_finding.json", "{}\n"),
        "source_adjudication": _write_text(root / "REVIEW_ADJUDICATION.json", "{}\n"),
        "machine_evidence": _write_text(root / "machine_evidence.json", "{}\n"),
    }

    with pytest.raises(ContractError, match="完整审核根|full_scientific"):
        create_review_request(
            run_dir,
            "R1_MODELING",
            bindings,
            review_mode="machine_check",
            target_finding_id="F-FORGED",
            source_gate_id="R1_MODELING",
        )


def test_scoped_receipt_cannot_replace_base_gate_receipt(tmp_path: Path) -> None:
    """record_review_gate 只登记 full root，拒绝合法 scoped receipt。"""
    run_dir, report, adjudication, base_receipt, _ = _registered_full_r1(
        tmp_path, "scoped-cannot-replace"
    )
    _, scoped_receipt = _scoped_receipt(
        tmp_path, run_dir, report, adjudication
    )

    with pytest.raises(ContractError, match="scoped review|full_scientific"):
        StateService(tmp_path).record_review_gate(
            run_dir.name, "R1_MODELING", scoped_receipt, Actor("scoped")
        )
    assert load_json(run_dir / "state.json")["review_gates"]["R1_MODELING"][
        "receipt"
    ] == base_receipt.relative_to(run_dir).as_posix()


def test_scoped_closure_preserves_full_review_receipt(tmp_path: Path) -> None:
    """closure 追加历史并关闭目标，不覆盖完整审核根回执。"""
    run_dir, report, adjudication, base_receipt, _ = _registered_full_r1(
        tmp_path, "closure-preserves-root"
    )
    _, scoped_receipt = _scoped_receipt(
        tmp_path, run_dir, report, adjudication
    )

    state = StateService(tmp_path).record_review_closure(
        run_dir.name, "R1_MODELING", scoped_receipt, Actor("scoped")
    )
    gate = state["review_gates"]["R1_MODELING"]

    assert gate["status"] == "passed"
    assert gate["receipt"] == base_receipt.relative_to(run_dir).as_posix()
    assert gate["receipt_sha256"] == sha256_file(base_receipt)
    assert gate["open_blocking_findings"] == []
    assert gate["closures"][0]["target_finding_id"] == "finding-1"
    assert gate["closures"][0]["receipt_sha256"] == sha256_file(scoped_receipt)


def test_scoped_closure_updates_only_target_finding(tmp_path: Path) -> None:
    """关闭 finding-1 后 finding-2 必须继续阻断完整审核门。"""
    run_dir, report, adjudication, base_receipt, _ = _registered_full_r1(
        tmp_path, "closure-one-target", count=2
    )
    _, scoped_receipt = _scoped_receipt(
        tmp_path, run_dir, report, adjudication
    )

    state = StateService(tmp_path).record_review_closure(
        run_dir.name, "R1_MODELING", scoped_receipt, Actor("scoped")
    )
    gate = state["review_gates"]["R1_MODELING"]

    assert gate["status"] == "failed"
    assert gate["receipt"] == base_receipt.relative_to(run_dir).as_posix()
    assert gate["open_blocking_findings"] == ["finding-2"]


def test_stale_gate_cannot_accept_scoped_closure(tmp_path: Path) -> None:
    """stale 根既不能创建新 scoped request，也不能登记已冻结 closure。"""
    run_dir, report, adjudication, _, _ = _registered_full_r1(
        tmp_path, "stale-rejects-scoped"
    )
    _, scoped_receipt = _scoped_receipt(
        tmp_path, run_dir, report, adjudication
    )
    state = StateService(tmp_path).record_change_impact(
        run_dir.name, "L4", [], Actor("semantic-change")
    )
    assert state["review_gates"]["R1_MODELING"]["status"] == "stale"

    with pytest.raises(ContractError, match="stale 完整根"):
        StateService(tmp_path).record_review_closure(
            run_dir.name, "R1_MODELING", scoped_receipt, Actor("scoped")
        )
    with pytest.raises(ContractError, match="stale 完整根"):
        create_review_request(
            run_dir,
            "R1_MODELING",
            _scoped_bindings(
                run_dir,
                report,
                adjudication,
                target_finding_id="finding-1",
                review_mode="machine_check",
            ),
            review_mode="machine_check",
            target_finding_id="finding-1",
            source_gate_id="R1_MODELING",
            review_round_id="stale-machine-check",
        )


def test_stale_gate_can_be_replaced_by_new_full_root(
    tmp_path: Path,
) -> None:
    """已有 closure 的 stale 根必须允许新的完整审核解除死锁。"""
    run_dir, report, adjudication, old_receipt, _ = _registered_full_r1(
        tmp_path, "stale-replacement", count=2
    )
    _, scoped_receipt = _scoped_receipt(
        tmp_path, run_dir, report, adjudication
    )
    StateService(tmp_path).record_review_closure(
        run_dir.name, "R1_MODELING", scoped_receipt, Actor("scoped")
    )
    StateService(tmp_path).record_change_impact(
        run_dir.name, "L4", [], Actor("semantic-change")
    )

    new_receipt, state = _replacement_full_r1(
        tmp_path, run_dir, round_id="replacement-full"
    )

    assert new_receipt != old_receipt
    assert state["review_gates"]["R1_MODELING"]["status"] == "passed"
    assert state["review_gates"]["R1_MODELING"]["receipt_sha256"] == sha256_file(
        new_receipt
    )


def test_new_root_does_not_inherit_old_closures(tmp_path: Path) -> None:
    """新完整根只继承历史事件，不继承旧根的 closure 权限。"""
    run_dir, report, adjudication, _, _ = _registered_full_r1(
        tmp_path, "replacement-drops-closures", count=2
    )
    _, scoped_receipt = _scoped_receipt(
        tmp_path, run_dir, report, adjudication
    )
    closed = StateService(tmp_path).record_review_closure(
        run_dir.name, "R1_MODELING", scoped_receipt, Actor("scoped")
    )
    old_closure_hash = closed["review_gates"]["R1_MODELING"]["closures"][0][
        "receipt_sha256"
    ]
    StateService(tmp_path).record_change_impact(
        run_dir.name, "L4", [], Actor("semantic-change")
    )

    _, state = _replacement_full_r1(
        tmp_path, run_dir, round_id="fresh-full-root"
    )

    gate = state["review_gates"]["R1_MODELING"]
    assert gate["closures"] == []
    assert old_closure_hash not in {
        item.get("receipt_sha256") for item in gate["closures"]
    }


def test_old_deferred_obligation_does_not_follow_new_root(tmp_path: Path) -> None:
    """替换 stale 完整根时必须丢弃仅属于旧根的 deferred obligation。"""
    run_dir, _, _, state = _registered_deferred_r1(
        tmp_path, "replacement-drops-deferred"
    )
    old_source_hash = state["deferred_obligations"][0]["source_receipt_sha256"]
    StateService(tmp_path).record_change_impact(
        run_dir.name, "L4", [], Actor("semantic-change")
    )

    _, replaced = _replacement_full_r1(
        tmp_path, run_dir, round_id="fresh-root-without-deferred"
    )

    assert replaced["deferred_obligations"] == []
    assert replaced["review_gates"]["R1_MODELING"]["receipt_sha256"] != old_source_hash


def test_passed_gate_reconstructs_open_findings_from_full_root(tmp_path: Path) -> None:
    """清空 state 中的 open 列表不能隐藏完整根裁决里的 blocker。"""
    run_dir, _, _, _, state = _registered_full_r1(
        tmp_path, "reconstruct-open-findings"
    )
    gate = state["review_gates"]["R1_MODELING"]
    gate["status"] = "passed"
    gate["open_blocking_findings"] = []

    with pytest.raises(ContractError, match="未关闭 finding"):
        StateService._require_passed_review_gates(
            run_dir, state, ("R1_MODELING",)
        )


def test_passed_gate_revalidates_closure_mode(tmp_path: Path) -> None:
    """state 中的 closure 模式必须与已签请求保持一致。"""
    run_dir, report, adjudication, _, _ = _registered_full_r1(
        tmp_path, "revalidate-closure-mode"
    )
    _, scoped_receipt = _scoped_receipt(
        tmp_path, run_dir, report, adjudication
    )
    state = StateService(tmp_path).record_review_closure(
        run_dir.name, "R1_MODELING", scoped_receipt, Actor("scoped")
    )
    state["review_gates"]["R1_MODELING"]["closures"][0][
        "review_mode"
    ] = "diff_check"

    with pytest.raises(ContractError, match="closure 模式"):
        StateService._require_passed_review_gates(
            run_dir, state, ("R1_MODELING",)
        )


def test_forged_empty_source_chain_is_rejected(tmp_path: Path) -> None:
    """空 original finding 和伪造 adjudication 不能通过来源链验证。"""
    run_dir, report, adjudication, _, _ = _registered_full_r1(
        tmp_path, "forged-source-chain"
    )
    bindings = _scoped_bindings(
        run_dir,
        report,
        adjudication,
        target_finding_id="finding-1",
        review_mode="machine_check",
    )
    atomic_json(bindings["original_finding"], {})
    fake_adjudication = bindings["original_finding"].with_name("FAKE_ADJUDICATION.json")
    atomic_json(fake_adjudication, {})
    bindings["source_adjudication"] = fake_adjudication

    with pytest.raises(ContractError, match="来源|original_finding|adjudication"):
        create_review_request(
            run_dir,
            "R1_MODELING",
            bindings,
            review_mode="machine_check",
            target_finding_id="finding-1",
            source_gate_id="R1_MODELING",
        )


def test_target_finding_must_exist_in_source_report(tmp_path: Path) -> None:
    """target_finding_id 不能由调用方凭空声明。"""
    run_dir, report, adjudication, _, _ = _registered_full_r1(
        tmp_path, "missing-target"
    )
    bindings = _scoped_bindings(
        run_dir,
        report,
        adjudication,
        target_finding_id="finding-1",
        review_mode="machine_check",
    )

    with pytest.raises(ContractError, match="target_finding_id|不存在"):
        create_review_request(
            run_dir,
            "R1_MODELING",
            bindings,
            review_mode="machine_check",
            target_finding_id="F-MISSING",
            source_gate_id="R1_MODELING",
        )


def test_closure_mode_must_match_source_decision(tmp_path: Path) -> None:
    """科学 targeted finding 不能改用 machine_check 关闭。"""
    run_dir, report, adjudication, _, _ = _registered_full_r1(
        tmp_path,
        "closure-mode-mismatch",
        domain="scientific",
        verification_mode="targeted_recheck",
    )
    bindings = _scoped_bindings(
        run_dir,
        report,
        adjudication,
        target_finding_id="finding-1",
        review_mode="machine_check",
    )

    with pytest.raises(ContractError, match="verification_mode|关闭模式"):
        create_review_request(
            run_dir,
            "R1_MODELING",
            bindings,
            review_mode="machine_check",
            target_finding_id="finding-1",
            source_gate_id="R1_MODELING",
        )


@pytest.mark.parametrize(
    ("gate_id", "review_mode"),
    [
        ("R1_MODELING", "machine_check"),
        ("R5_STANDARD_FINAL", "targeted_recheck"),
    ],
)
def test_passed_gate_requires_full_scientific_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_id: str,
    review_mode: str,
) -> None:
    """状态推进不能接受 scoped receipt 冒充完整 R1/R5 根门。"""
    run_dir = tmp_path / "runs/root-mode-check"
    run_dir.mkdir(parents=True)
    receipt = _write_text(run_dir / "review/scoped-receipt.json", "{}\n")
    state = {
        "review_gates": {
            gate_id: {
                "status": "passed",
                "receipt": receipt.relative_to(run_dir).as_posix(),
                "receipt_sha256": sha256_file(receipt),
                "review_mode": review_mode,
            }
        }
    }
    monkeypatch.setattr(
        "shumozizi.workflow.state_service.verify_review_receipt",
        lambda *_args, **_kwargs: {"valid": True, "errors": []},
    )

    with pytest.raises(ContractError, match="full_scientific|完整审核根"):
        StateService._require_passed_review_gates(run_dir, state, (gate_id,))


def test_experiment_start_requires_full_scientific_r1_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EXPERIMENT_STARTED 复用同一根类型硬门。"""
    run_dir = tmp_path / "runs/experiment-root"
    run_dir.mkdir(parents=True)
    receipt = _write_text(run_dir / "review/machine-receipt.json", "{}\n")
    state = {
        "review_gates": {
            "R1_MODELING": {
                "status": "passed",
                "receipt": receipt.relative_to(run_dir).as_posix(),
                "receipt_sha256": sha256_file(receipt),
                "review_mode": "machine_check",
            }
        }
    }
    monkeypatch.setattr(
        "shumozizi.workflow.state_service.verify_review_receipt",
        lambda *_args, **_kwargs: {"valid": True, "errors": []},
    )

    with pytest.raises(ContractError, match="full_scientific|完整审核根"):
        StateService(tmp_path)._check_event_invariants(
            run_dir, state, WorkflowEvent.EXPERIMENT_STARTED, []
        )


def test_deferred_empirical_blocks_at_declared_boundary(tmp_path: Path) -> None:
    """开放 deferred obligation 必须在 paper_claim 边界阻断状态推进。"""
    run_dir = tmp_path / "runs/deferred-boundary"
    run_dir.mkdir(parents=True)
    _write_state(run_dir)
    state = load_json(run_dir / "state.json")
    state["status"] = "PAPER_DRAFTED"
    state["active_stage"] = "qa"
    atomic_json(run_dir / "state.json", state)
    bindings = complete_stage_bindings(run_dir, "R3_PAPER_LOGIC")
    request = create_review_request(
        run_dir,
        "R3_PAPER_LOGIC",
        bindings,
        review_round_id="deferred-full",
    )
    session = claim_review_request(request, thread_id="thread-deferred-full")
    finding = _v3_finding("F-DEFERRED", "P1", status="deferred_empirical")
    finding.update(
        {
            "block_before": "paper_claim",
            "closure_condition": "完成预注册稳健性实验",
            "failure_action": "退回已确认 baseline",
        }
    )
    request_doc = load_json(request)
    report_doc = {
        "schema_name": "review_report",
        "schema_version": "3.0",
        "request_id": request_doc["request_id"],
        "run_id": run_dir.name,
        "stage": "R3_PAPER_LOGIC",
        "review_round_id": request_doc["review_round_id"],
        "review_mode": "full_scientific",
        "request_sha256": sha256_file(request),
        "input_manifest_sha256": request_doc["input_manifest_sha256"],
        "session_sha256": sha256_file(session),
        "verdict": "MAJOR_REVISION",
        "findings": [finding],
        "read_only_confirmed": True,
        "generated_at": "2026-07-21T00:00:00Z",
    }
    report = write_review_report(request, report_doc)
    decision = _scoped_decision(
        finding,
        main_decision="deferred_empirical",
        domain="scientific",
        verification_mode="targeted_recheck",
    )
    write_review_adjudication(report, _scoped_adjudication(report, [decision]))
    receipt = materialize_review_receipt(request, report)
    recorded = StateService(tmp_path).record_review_gate(
        run_dir.name, "R3_PAPER_LOGIC", receipt, Actor("full-review")
    )

    assert recorded["deferred_obligations"][0]["status"] == "open"
    with pytest.raises(ContractError, match="deferred_empirical|paper_claim"):
        StateService(tmp_path)._check_event_invariants(
            run_dir, recorded, WorkflowEvent.PAPER_COMPLETED, []
        )


def test_r1_deferred_model_selection_can_close_after_experiment(
    tmp_path: Path,
) -> None:
    """R1 model_selection obligation 可在实验启动后由 targeted reviewer 关闭。"""
    run_dir, report, adjudication, _ = _registered_deferred_r1(
        tmp_path, "deferred-close-after-experiment"
    )
    progressed = StateService(tmp_path).transition(
        run_dir.name, WorkflowEvent.EXPERIMENT_STARTED, Actor("experiment"), []
    )
    assert progressed["status"] == "EXPERIMENTING"
    _, scoped_receipt = _scoped_receipt(
        tmp_path,
        run_dir,
        report,
        adjudication,
        target_finding_id="F-DEFERRED",
        review_mode="targeted_recheck",
    )

    state = StateService(tmp_path).record_review_closure(
        run_dir.name, "R1_MODELING", scoped_receipt, Actor("targeted-review")
    )

    assert state["status"] == "EXPERIMENTING"
    assert state["deferred_obligations"][0]["status"] == "closed"
    assert state["deferred_obligations"][0][
        "closed_by_receipt_sha256"
    ] == sha256_file(scoped_receipt)


def test_tampered_deferred_closed_status_is_rejected(tmp_path: Path) -> None:
    """只改 state.status 不能伪造 deferred finding 已关闭。"""
    run_dir, _, _, state = _registered_deferred_r1(
        tmp_path, "tampered-deferred-status"
    )
    obligation = state["deferred_obligations"][0]
    obligation["status"] = "closed"
    obligation["closed_by_receipt_sha256"] = "0" * 64
    obligation["closed_revision"] = state["revision"]

    with pytest.raises(ContractError, match="缺少真实 scoped closure"):
        StateService._require_passed_review_gates(
            run_dir, state, ("R1_MODELING",)
        )


def test_deferred_close_matches_source_receipt_sha256(tmp_path: Path) -> None:
    """closed_by 哈希必须精确指向同根同 finding 的真实 closure。"""
    run_dir, report, adjudication, _ = _registered_deferred_r1(
        tmp_path, "tampered-deferred-hash"
    )
    StateService(tmp_path).transition(
        run_dir.name, WorkflowEvent.EXPERIMENT_STARTED, Actor("experiment"), []
    )
    _, scoped_receipt = _scoped_receipt(
        tmp_path,
        run_dir,
        report,
        adjudication,
        target_finding_id="F-DEFERRED",
        review_mode="targeted_recheck",
    )
    state = StateService(tmp_path).record_review_closure(
        run_dir.name, "R1_MODELING", scoped_receipt, Actor("targeted-review")
    )
    state["deferred_obligations"][0]["closed_by_receipt_sha256"] = "0" * 64

    with pytest.raises(ContractError, match="未绑定真实 closure receipt"):
        StateService._require_passed_review_gates(
            run_dir, state, ("R1_MODELING",)
        )


def test_scoped_r5_does_not_consume_full_quota(tmp_path: Path) -> None:
    """scoped R5 请求不占用 competition 模式的三轮完整审核配额。"""
    run_dir, first_full = _review_run(tmp_path, "R5_COMPREHENSIVE")
    for index in (1, 2):
        atomic_json(
            run_dir
            / "review"
            / "r5_comprehensive"
            / f"scoped-{index}"
            / "review_request.json",
            {"review_mode": "targeted_recheck"},
        )
    first_request = load_json(first_full)
    bindings = {
        role: run_dir / relative
        for role, relative in first_request["binding_paths"].items()
    }

    second_full = create_review_request(
        run_dir,
        "R5_COMPREHENSIVE",
        bindings,
        review_round_id="full-after-scoped",
    )

    assert load_json(second_full)["review_mode"] == "full_scientific"


def test_scoped_r5_cannot_emit_full_competition_score() -> None:
    """scoped R5 只能关闭目标 finding，不能产出完整投稿评分。"""
    request = {
        "review_mode": "targeted_recheck",
        "target_finding_id": "R5-P1",
    }
    report = {
        "schema_version": "3.0",
        "findings": [],
        "raw_score": 90,
        "calibrated_score": 90,
        "competition_claim_allowed": True,
    }

    with pytest.raises(ContractError, match="不得生成完整竞赛评分"):
        _validate_review_mode_report(request, report)
