"""完整审核根、scoped closure 来源链与 deferred obligation 攻击测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.workflow.review_sessions import claim_review_request
from shumozizi.workflow.reviews import (
    create_review_request,
    materialize_review_receipt,
    write_review_adjudication,
    write_review_report,
)
from shumozizi.workflow.state_service import Actor, StateService, WorkflowEvent
from tests.review_contract_helpers import complete_stage_bindings
from tests.test_review_contracts import (
    _adjudication as _full_adjudication,
)
from tests.test_review_contracts import (
    _decision as _full_decision,
)
from tests.test_review_contracts import (
    _finding_report,
    _r1_request,
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
