"""审核材料清单、独立 session 与 R1 结构证据的拒绝性测试。"""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.core.schema import schema_root
from shumozizi.workflow.probes import create_probe_plan, write_probe_result
from shumozizi.workflow.repair import create_repair_plan
from shumozizi.workflow.review_sessions import claim_review_request, verify_review_session
from shumozizi.workflow.reviews import (
    R1_COVERAGE_CHECKS,
    R1_REQUIRED_CHECK_IDS,
    create_review_request,
    materialize_review_receipt,
    verify_review_receipt,
    write_review_adjudication,
    write_review_report,
)
from shumozizi.workflow.state_service import Actor, StateService, collect_machine_blockers
from tests.review_contract_helpers import (
    adjudicate_report,
    complete_stage_bindings,
    rich_model_spec,
    rich_problem_manifest,
)


def _state(run_dir: Path, revision: int = 3) -> None:
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
            "revision": revision,
            "completed_stages": ["ROUTE_LOCKED"],
            "active_stage": "review",
            "route_locked": True,
            "paper_ready": False,
            "question_progress": {},
            "review_gates": {},
            "artifacts": {},
            "last_updated_by": "test",
            "updated_at": "2026-07-20T00:00:00Z",
            "history": [],
        },
    )


def _r1_request(
    tmp_path: Path,
    *,
    run_id: str = "review-contract",
    round_id: str = "r1-r3",
    rich_spec: bool = True,
) -> tuple[Path, Path]:
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if not (run_dir / "state.json").exists():
        _state(run_dir)
    model_spec = run_dir / "brief/model_spec.json"
    if rich_spec:
        rich_model_spec(run_dir, model_spec)
    else:
        atomic_json(
            model_spec,
            {
                "schema_name": "model_spec",
                "schema_version": "2.0",
                "run_id": run_dir.name,
                "route_lock_sha256": "0" * 64,
                "questions": [
                    {
                        "question_id": "q1",
                        "model_family": "statistical",
                        "target_role": "target",
                        "feature_roles": ["x"],
                        "variables": [
                            {"name": "y", "role": "target", "unit": "dimensionless"}
                        ],
                        "assumptions": [],
                        "objective": "最小化误差",
                        "constraints": ["参数非负"],
                        "algorithm": "最小二乘",
                        "validation_plan": ["检查残差"],
                    }
                ],
            },
        )
    bindings = complete_stage_bindings(
        run_dir, "R1_MODELING", {"model_spec": model_spec}
    )
    rich_problem_manifest(run_dir, bindings["problem_manifest"])
    request = create_review_request(
        run_dir, "R1_MODELING", bindings, review_round_id=round_id
    )
    return run_dir, request


def _accept_report(request: Path, session_sha256: str) -> dict:
    request_doc = load_json(request)
    return {
        "schema_name": "review_report",
        "schema_version": "2.0",
        "request_id": request_doc["request_id"],
        "run_id": request_doc["run_id"],
        "stage": "R1_MODELING",
        "review_round_id": request_doc["review_round_id"],
        "request_sha256": sha256_file(request),
        "input_manifest_sha256": request_doc["input_manifest_sha256"],
        "session_sha256": session_sha256,
        "verdict": "ACCEPT",
        "coverage": {
            **{check_id: "pass" for check_id in R1_COVERAGE_CHECKS},
            "unchecked_items": [],
        },
        "findings": [],
        "read_only_confirmed": True,
        "generated_at": "2026-07-20T00:00:00Z",
    }


def _finding_report(
    request: Path,
    session_sha256: str,
    *,
    severity: str = "P1",
    count: int = 1,
) -> dict:
    """生成具有合法 R1 coverage 绑定的未通过报告。"""
    report = _accept_report(request, session_sha256)
    report["verdict"] = "SPEC_REVISION_REQUIRED"
    report["coverage"]["baseline_design"] = "fail"
    report["findings"] = [
        {
            "finding_id": f"finding-{index}",
            "severity": severity,
            "title": "基线证据不足",
            "evidence": ["brief/model_spec.json"],
            "remediation": "补齐公平基线证据",
            "status": "open",
            "check_id": "baseline_design" if index == 1 else None,
            "change_level": "L3",
            "affected_questions": ["q1"],
            "change_class": "EXPERIMENT_DESIGN_CHANGE",
            "affected_stage": "R1_MODELING",
            "affected_files": ["brief/model_spec.json"],
            "expected_improvement": "恢复实验可比性",
            "route_impact": "none",
            "changed_route_core_fields": [],
        }
        for index in range(1, count + 1)
    ]
    for finding in report["findings"]:
        if finding["check_id"] is None:
            finding.pop("check_id")
    return report


def _adjudication(
    report_path: Path,
    decisions: list[dict],
    *,
    unresolved: list[str] | None = None,
) -> dict:
    """生成绑定当前 R1 报告的生产主 AI 裁决。"""
    report = load_json(report_path)
    request = load_json(report_path.with_name("review_request.json"))
    return {
        "schema_name": "review_adjudication",
        "schema_version": "2.0",
        "run_id": report["run_id"],
        "request_id": report["request_id"],
        "stage": report["stage"],
        "state_revision": request["state_revision"],
        "review_report_sha256": sha256_file(report_path),
        "decisions": decisions,
        "unresolved_conflicts": unresolved or [],
        "generated_by": "production_main_ai",
        "generated_at": "2026-07-20T00:00:00Z",
    }


def _decision(
    finding_id: str,
    severity: str,
    main_decision: str,
    *,
    counter_evidence: list[str] | None = None,
    confirmation_evidence: list[str] | None = None,
    resolution_evidence_type: str | None = None,
    gate_effect: str | None = None,
) -> dict:
    """生成最小逐 finding 裁决。"""
    return {
        "finding_id": finding_id,
        "reviewer_severity": severity,
        "main_decision": main_decision,
        "effective_severity": severity,
        "gate_effect": gate_effect
        or (
            {
                "accepted": "block",
                "accepted_as_advisory": "warn",
                "needs_second_review": "block",
                "needs_human_decision": "block",
            }.get(main_decision, "none")
        ),
        "decision_reason": "生产主 AI 独立核验",
        "confirmation_evidence": (
            ["test:confirmation"]
            if confirmation_evidence is None and main_decision == "accepted"
            else (confirmation_evidence or [])
        ),
        "counter_evidence": counter_evidence or [],
        "resolution_evidence_type": resolution_evidence_type,
        "effective_change_level": "L3",
        "affected_questions": ["q1"],
        "required_retests": ["R2_EXPERIMENT_q1"],
        "route_reapproval_required": False,
    }


def test_review_request_freezes_complete_input_manifest(tmp_path: Path) -> None:
    """请求必须绑定阶段完整材料清单及逐文件哈希。"""
    run_dir, request = _r1_request(tmp_path)
    request_doc = load_json(request)
    manifest = load_json(run_dir / request_doc["input_manifest_path"])

    assert sha256_file(run_dir / request_doc["input_manifest_path"]) == request_doc[
        "input_manifest_sha256"
    ]
    assert {item["role"] for item in manifest["materials"]} == set(
        request_doc["mandatory_inputs"]
    )
    assert all(item["required"] for item in manifest["materials"])


def test_r1_coverage_exact_set_matches_schema_and_skill() -> None:
    """Python、Schema 与 Skill 必须共享同一组 17 个检查 ID。"""
    schema = load_json(schema_root() / "review_report.schema.json")
    schema_ids = set(schema["properties"]["coverage"]["properties"]) - {
        "unchecked_items"
    }
    skill = Path(
        ".agents/skills/mathmodel-review-r1-modeling/SKILL.md"
    ).read_text(encoding="utf-8")
    block = re.search(
        r"R1_REQUIRED_CHECK_IDS_START.*?```text\n(.*?)\n```.*?R1_REQUIRED_CHECK_IDS_END",
        skill,
        flags=re.DOTALL,
    )

    assert block is not None
    skill_ids = set(block.group(1).splitlines())
    assert len(R1_COVERAGE_CHECKS) == 17
    assert len(R1_REQUIRED_CHECK_IDS) == 17
    assert set(R1_COVERAGE_CHECKS) == R1_REQUIRED_CHECK_IDS == schema_ids == skill_ids


def test_review_input_manifest_rejects_hash_change(tmp_path: Path) -> None:
    """请求冻结后任一审核材料变化都必须阻止领取。"""
    run_dir, request = _r1_request(tmp_path)
    material = run_dir / load_json(request)["binding_paths"]["data_profile"]
    material.write_text("changed\n", encoding="utf-8")

    with pytest.raises(ContractError, match="材料清单复验失败|哈希已变化"):
        claim_review_request(request, thread_id="thread-hash-change")


def test_review_input_manifest_rejects_path_alias(tmp_path: Path) -> None:
    """同一文件也不能通过包含 ``..`` 的别名路径绕过禁止规则。"""
    run_dir, request = _r1_request(tmp_path)
    request_doc = load_json(request)
    manifest_path = run_dir / request_doc["input_manifest_path"]
    manifest = load_json(manifest_path)
    item = next(entry for entry in manifest["materials"] if entry["role"] == "data_profile")
    parent, name = item["path"].rsplit("/", 1)
    item["path"] = f"{parent}/../{Path(parent).name}/{name}"
    atomic_json(manifest_path, manifest)
    request_doc["input_manifest_sha256"] = sha256_file(manifest_path)
    atomic_json(request, request_doc)

    with pytest.raises(ContractError, match="规范相对路径"):
        claim_review_request(request, thread_id="thread-path-alias")


def test_review_report_requires_session(tmp_path: Path) -> None:
    """未由顶层任务领取的请求不能直接生成报告。"""
    _, request = _r1_request(tmp_path)

    with pytest.raises(ContractError, match="session"):
        write_review_report(request, _accept_report(request, "a" * 64))


def test_same_request_and_thread_cannot_be_reused(tmp_path: Path) -> None:
    """一个请求只能领取一次，同一线程在同一 run 中也只能使用一次。"""
    _, first = _r1_request(tmp_path, round_id="r1-first")
    claim_review_request(first, thread_id="thread-unique")
    with pytest.raises(ContractError, match="只能被一个 session"):
        claim_review_request(first, thread_id="thread-other")

    _, second = _r1_request(tmp_path, round_id="r1-second")
    with pytest.raises(ContractError, match="同一仓库中 thread_id"):
        claim_review_request(second, thread_id="thread-unique")


def test_thread_id_cannot_be_reused_across_runs(tmp_path: Path) -> None:
    """同一对话不能先后审核仓库内两个不同 run。"""
    _, first = _r1_request(tmp_path, run_id="run-a")
    claim_review_request(first, thread_id="thread-cross-run")
    _, second = _r1_request(tmp_path, run_id="run-b")

    with pytest.raises(ContractError, match="同一仓库中 thread_id"):
        claim_review_request(second, thread_id="thread-cross-run")


def test_concurrent_claim_allows_exactly_one_winner(tmp_path: Path) -> None:
    """两个任务同时领取同一请求时恰好一个成功，session 不被覆盖。"""
    _, request = _r1_request(tmp_path)
    barrier = threading.Barrier(2)

    def attempt(thread_id: str) -> tuple[str, str]:
        barrier.wait(timeout=5)
        try:
            session = claim_review_request(request, thread_id=thread_id)
            return "success", load_json(session)["executor"]["thread_id"]
        except ContractError as exc:
            return "rejected", str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(attempt, ("thread-concurrent-a", "thread-concurrent-b"))
        )

    assert [status for status, _ in results].count("success") == 1
    assert [status for status, _ in results].count("rejected") == 1
    winner = next(detail for status, detail in results if status == "success")
    assert load_json(request.with_name("review_session.json"))["executor"][
        "thread_id"
    ] == winner
    claims = list((tmp_path / ".review_registry/thread_claims").glob("*.json"))
    assert len(claims) == 1


def test_claim_cannot_self_assert_verified_attestation(tmp_path: Path) -> None:
    """没有平台可信元数据时，领取方不能自行提升证明等级。"""
    _, request = _r1_request(tmp_path)

    with pytest.raises(ContractError, match="只能生成 self_declared"):
        claim_review_request(
            request,
            thread_id="thread-false-attestation",
            attestation_level="platform_verified",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("subagent", True), ("context_inherited", True), ("forked", True)],
)
def test_non_independent_session_is_rejected(
    tmp_path: Path, field: str, value: bool
) -> None:
    """子 agent、fork 或继承上下文的自声明均不能通过 session Schema。"""
    run_dir, request = _r1_request(tmp_path)
    session = claim_review_request(request, thread_id=f"thread-{field}")
    payload = load_json(session)
    payload["execution_policy"][field] = value
    atomic_json(session, payload)

    result = verify_review_session(run_dir, request, session)

    assert result["valid"] is False


def test_report_and_receipt_bind_immutable_session(tmp_path: Path) -> None:
    """报告与回执必须绑定同一不可变 session 哈希。"""
    run_dir, request = _r1_request(tmp_path)
    session = claim_review_request(request, thread_id="thread-bindings")
    report = write_review_report(request, _accept_report(request, sha256_file(session)))
    adjudicate_report(report)
    receipt = materialize_review_receipt(request, report)
    receipt_doc = load_json(receipt)

    assert receipt_doc["session_sha256"] == sha256_file(session)
    assert receipt_doc["input_manifest_sha256"] == load_json(request)[
        "input_manifest_sha256"
    ]
    payload = load_json(session)
    payload["started_at"] = "2026-07-20T01:00:00Z"
    atomic_json(session, payload)
    assert verify_review_receipt(run_dir, receipt)["valid"] is False


def test_receipt_is_capture_only_and_does_not_require_adjudication(
    tmp_path: Path,
) -> None:
    """v3 回执只捕获审核事实，不承载生产裁决或修复计划。"""
    run_dir, request = _r1_request(tmp_path)
    session = claim_review_request(request, thread_id="thread-no-adjudication")
    report = write_review_report(request, _accept_report(request, sha256_file(session)))
    receipt_path = materialize_review_receipt(request, report)
    receipt = load_json(receipt_path)

    assert receipt["schema_version"] == "3.0"
    assert receipt["receipt_kind"] == "capture"
    assert verify_review_receipt(run_dir, receipt_path)["valid"] is True
    assert {
        "decision",
        "adjudication_path",
        "adjudication_sha256",
        "repair_plan_path",
        "repair_plan_sha256",
    }.isdisjoint(receipt)
    with pytest.raises(ContractError, match="审核裁决复验失败"):
        StateService(tmp_path).record_review_gate(
            run_dir.name, "R1_MODELING", receipt_path, Actor("gate-recorder")
        )


def test_historical_v2_receipt_is_read_only_compatible(tmp_path: Path) -> None:
    """历史 v2 回执可复验，但不能作为新审核门登记或迁移。"""
    run_dir, request = _r1_request(tmp_path, run_id="review-v2-history")
    session = claim_review_request(request, thread_id="thread-v2-history")
    report = write_review_report(request, _accept_report(request, sha256_file(session)))
    adjudication = adjudicate_report(report)
    receipt_path = materialize_review_receipt(request, report)
    capture = load_json(receipt_path)
    atomic_json(
        receipt_path,
        {
            "schema_name": "review_receipt",
            "schema_version": "2.0",
            "run_id": capture["run_id"],
            "request_id": capture["request_id"],
            "report_sha256": capture["report_sha256"],
            "request_sha256": capture["request_sha256"],
            "session_sha256": capture["session_sha256"],
            "input_manifest_sha256": capture["input_manifest_sha256"],
            "adjudication_path": adjudication.relative_to(run_dir).as_posix(),
            "adjudication_sha256": sha256_file(adjudication),
            "state_revision": capture["state_revision"],
            "bindings": capture["bindings"],
            "decision": "accepted",
            "issued_at": capture["issued_at"],
        },
    )

    assert verify_review_receipt(run_dir, receipt_path)["valid"] is True
    with pytest.raises(ContractError, match="仅允许历史只读验证"):
        StateService(tmp_path).record_review_gate(
            run_dir.name, "R1_MODELING", receipt_path, Actor("gate-recorder")
        )


def test_p1_cannot_be_rejected_without_independent_counter_evidence(tmp_path: Path) -> None:
    """P1 不允许主 AI 无反证单方面驳回。"""
    _, request = _r1_request(tmp_path)
    session = claim_review_request(request, thread_id="thread-p1-reject")
    report = write_review_report(
        request, _finding_report(request, sha256_file(session), severity="P1")
    )
    adjudication = _adjudication(
        report, [_decision("finding-1", "P1", "rejected")]
    )
    with pytest.raises(ContractError, match="counter_evidence|P1"):
        write_review_adjudication(report, adjudication)


def test_p1_can_be_rejected_with_exact_oracle_and_gate_passes(tmp_path: Path) -> None:
    """强 oracle 驳回误报 P1 后，状态门只按最终裁决通过。"""
    run_dir, request = _r1_request(tmp_path, run_id="review-p1-oracle")
    session = claim_review_request(request, thread_id="thread-p1-oracle")
    report = write_review_report(
        request, _finding_report(request, sha256_file(session), severity="P1")
    )
    receipt = materialize_review_receipt(request, report)
    adjudication = _adjudication(
        report,
        [
            _decision(
                "finding-1",
                "P1",
                "rejected",
                counter_evidence=["oracle:exact-solution-q1"],
                resolution_evidence_type="exact_oracle",
            )
        ],
    )
    write_review_adjudication(report, adjudication)

    state = StateService(tmp_path).record_review_gate(
        run_dir.name, "R1_MODELING", receipt, Actor("gate-recorder")
    )

    gate = state["review_gates"]["R1_MODELING"]
    assert gate["status"] == "passed"
    assert gate["accepted_blocking_finding_count"] == 0
    assert not (report.parent / "REPAIR_PLAN.json").exists()


def test_accepted_p1_blocks_and_repair_is_explicit(tmp_path: Path) -> None:
    """主 AI 接受 P1 后审核门阻断，显式 repair 才生成计划。"""
    run_dir, request = _r1_request(tmp_path, run_id="review-p1-accepted")
    session = claim_review_request(request, thread_id="thread-p1-accepted")
    report = write_review_report(
        request, _finding_report(request, sha256_file(session), severity="P1")
    )
    receipt = materialize_review_receipt(request, report)
    adjudication = _adjudication(
        report,
        [
            _decision(
                "finding-1",
                "P1",
                "accepted",
                confirmation_evidence=["brief/model_spec.json:line-1"],
                gate_effect="block",
            )
        ],
    )
    adjudication_path = write_review_adjudication(report, adjudication)

    state = StateService(tmp_path).record_review_gate(
        run_dir.name, "R1_MODELING", receipt, Actor("gate-recorder")
    )

    gate = state["review_gates"]["R1_MODELING"]
    assert gate["status"] == "failed"
    assert gate["accepted_blocking_finding_count"] == 1
    assert not (report.parent / "REPAIR_PLAN.json").exists()

    plan = create_repair_plan(run_dir, report, adjudication_path)
    assert load_json(plan)["repair_scope"][0]["finding_id"] == "finding-1"


def test_invalid_sealed_result_is_machine_blocker(tmp_path: Path) -> None:
    """accepted result 的 seal 失效时，机器 blocker 独立于 adjudication。"""
    run_dir, _ = _r1_request(tmp_path, run_id="review-sealed-blocker")
    atomic_json(
        run_dir / "results/result_registry.json",
        {
            "schema_name": "result_registry",
            "schema_version": "2.0",
            "run_id": run_dir.name,
            "results": [
                {
                    "result_id": "q1-invalid",
                    "question_id": "q1",
                    "cycle": "primary",
                    "status": "accepted",
                    "paper_allowed": True,
                    "execution_record_id": "missing",
                    "metric_spec_ids": [],
                    "sealed_result_path": "results/sealed/q1-invalid.result.json",
                    "result_seal_path": "results/sealed/q1-invalid.seal.json",
                    "supersedes_result_id": None,
                }
            ],
        },
    )
    blockers = collect_machine_blockers(
        run_dir, "R2_EXPERIMENT_q1", load_json(run_dir / "state.json")
    )

    assert any(item.blocker_id == "sealed-result-invalid:q1-invalid" for item in blockers)
    assert all(item.override_allowed is False for item in blockers)


def test_probe_lifecycle_preserves_initial_adjudication_and_resolves_gate(
    tmp_path: Path,
) -> None:
    """needs_probe 经受限 probe 后以新裁决解决，初始裁决保持不可变。"""
    run_dir, request = _r1_request(tmp_path, run_id="review-probe-lifecycle")
    session = claim_review_request(request, thread_id="thread-probe-lifecycle")
    report = write_review_report(
        request, _finding_report(request, sha256_file(session), severity="P2")
    )
    receipt = materialize_review_receipt(request, report)
    initial_doc = _adjudication(
        report,
        [_decision("finding-1", "P2", "needs_probe", gate_effect="block")],
        unresolved=["finding-1"],
    )
    initial_doc.update(
        {
            "adjudication_sequence": 1,
            "supersedes_adjudication_sha256": None,
            "probe_result_sha256": None,
        }
    )
    initial_path = write_review_adjudication(report, initial_doc)
    initial_sha256 = sha256_file(initial_path)

    pending = StateService(tmp_path).record_review_gate(
        run_dir.name, "R1_MODELING", receipt, Actor("gate-recorder")
    )
    assert pending["review_gates"]["R1_MODELING"]["status"] == "failed"
    assert not (report.parent / "REPAIR_PLAN.json").exists()

    output_relative = (
        report.parent / "probe-output.json"
    ).relative_to(run_dir).as_posix()
    command = "python -m pytest probe"
    plan_path = create_probe_plan(
        run_dir,
        report,
        initial_path,
        {
            "schema_name": "probe_plan",
            "schema_version": "2.0",
            "run_id": run_dir.name,
            "request_id": load_json(request)["request_id"],
            "finding_id": "finding-1",
            "source_report_sha256": sha256_file(report),
            "source_adjudication_sha256": initial_sha256,
            "question": "该 finding 是否可由确定性 oracle 复现？",
            "hypothesis": "精确 oracle 将确认审核 finding。",
            "probe_type": "exact_oracle",
            "allowed_files": ["brief/model_spec.json"],
            "allowed_commands": [command],
            "budget": {
                "max_minutes": 5,
                "max_commands": 1,
                "max_output_bytes": 1024,
            },
            "success_condition": "oracle 复现 finding",
            "failure_condition": "oracle 反驳 finding",
            "inconclusive_condition": "输入不足以运行 oracle",
            "expected_outputs": [output_relative],
            "generated_at": "2026-07-20T00:00:00Z",
        },
    )
    (run_dir / output_relative).write_text("confirmed\n", encoding="utf-8")
    result_path = write_probe_result(
        plan_path,
        {
            "schema_name": "probe_result",
            "schema_version": "2.0",
            "run_id": run_dir.name,
            "request_id": load_json(request)["request_id"],
            "finding_id": "finding-1",
            "probe_plan_sha256": sha256_file(plan_path),
            "status": "confirmed",
            "evidence": ["probe-output.json:confirmed"],
            "executed_commands": [command],
            "outputs": [output_relative],
            "started_at": "2026-07-20T00:01:00Z",
            "finished_at": "2026-07-20T00:02:00Z",
        },
    )
    final_doc = _adjudication(
        report,
        [
            _decision(
                "finding-1",
                "P2",
                "accepted",
                confirmation_evidence=["probe-output.json:confirmed"],
                gate_effect="warn",
            )
        ],
    )
    final_doc.update(
        {
            "adjudication_sequence": 2,
            "supersedes_adjudication_sha256": initial_sha256,
            "probe_result_sha256": sha256_file(result_path),
        }
    )
    final_path = write_review_adjudication(report, final_doc)

    resolved = StateService(tmp_path).record_review_gate(
        run_dir.name, "R1_MODELING", receipt, Actor("gate-recorder")
    )
    assert final_path.name == "REVIEW_ADJUDICATION.0002.json"
    assert sha256_file(initial_path) == initial_sha256
    assert resolved["review_gates"]["R1_MODELING"]["status"] == "passed"


def test_p0_accept_requires_confirmation_evidence(tmp_path: Path) -> None:
    """接受 P0 必须绑定支持 finding 成立的确认性证据。"""
    _, request = _r1_request(tmp_path)
    session = claim_review_request(request, thread_id="thread-p0-accept")
    report_doc = _finding_report(request, sha256_file(session), severity="P0")
    report_doc["verdict"] = "ROUTE_REAPPROVAL_REQUIRED"
    report_doc["findings"][0]["change_level"] = "L5"
    report_doc["findings"][0]["change_class"] = "ROUTE_CORE_CHANGE"
    report_doc["findings"][0]["route_impact"] = "material"
    report_doc["findings"][0]["changed_route_core_fields"] = ["primary_model"]
    report = write_review_report(request, report_doc)
    adjudication = _adjudication(
        report,
        [_decision("finding-1", "P0", "accepted", confirmation_evidence=[])],
    )
    adjudication["decisions"][0]["effective_change_level"] = "L5"
    adjudication["decisions"][0]["route_reapproval_required"] = True
    with pytest.raises(ContractError, match="confirmation_evidence"):
        write_review_adjudication(report, adjudication)


def test_unresolved_conflict_blocks_gate_but_not_capture_receipt(tmp_path: Path) -> None:
    """待二次复核冲突阻断状态门，但不阻止事实捕获回执。"""
    run_dir, request = _r1_request(tmp_path)
    session = claim_review_request(request, thread_id="thread-unresolved")
    report = write_review_report(
        request, _finding_report(request, sha256_file(session), severity="P2")
    )
    adjudication = _adjudication(
        report,
        [_decision("finding-1", "P2", "needs_second_review")],
        unresolved=["finding-1"],
    )
    write_review_adjudication(report, adjudication)
    receipt = materialize_review_receipt(request, report)
    state = StateService(tmp_path).record_review_gate(
        run_dir.name, "R1_MODELING", receipt, Actor("gate-recorder")
    )

    assert state["review_gates"]["R1_MODELING"]["status"] == "failed"
    assert not (report.parent / "REPAIR_PLAN.json").exists()


def test_repair_plan_contains_only_accepted_findings(tmp_path: Path) -> None:
    """修复计划只接收主 AI 明确接受的 finding。"""
    run_dir, request = _r1_request(tmp_path)
    session = claim_review_request(request, thread_id="thread-repair-filter")
    report = write_review_report(
        request, _finding_report(request, sha256_file(session), severity="P2", count=2)
    )
    adjudication = _adjudication(
        report,
        [
            _decision("finding-1", "P2", "accepted"),
            _decision("finding-2", "P2", "accepted_as_advisory"),
        ],
    )
    adjudication_path = write_review_adjudication(report, adjudication)
    plan = load_json(create_repair_plan(run_dir, report, adjudication_path))
    assert [item["finding_id"] for item in plan["repair_scope"]] == ["finding-1"]


def test_adjudication_is_not_part_of_capture_receipt(tmp_path: Path) -> None:
    """裁决变化不影响此前的事实捕获回执。"""
    run_dir, request = _r1_request(tmp_path)
    session = claim_review_request(request, thread_id="thread-adjudication-tamper")
    report = write_review_report(request, _accept_report(request, sha256_file(session)))
    adjudication_report = adjudicate_report(report)
    receipt = materialize_review_receipt(request, report)
    payload = load_json(adjudication_report)
    payload["generated_at"] = "2026-07-20T02:00:00Z"
    atomic_json(adjudication_report, payload)
    assert verify_review_receipt(run_dir, receipt)["valid"] is True


@pytest.mark.parametrize("target", ["manifest", "session", "request", "report"])
def test_record_review_gate_rejects_each_hash_layer_tamper(
    tmp_path: Path, target: str
) -> None:
    """登记审核门时必须重新计算四层哈希及全部材料哈希。"""
    run_dir, request = _r1_request(tmp_path)
    session = claim_review_request(request, thread_id=f"thread-tamper-{target}")
    report = write_review_report(request, _accept_report(request, sha256_file(session)))
    adjudicate_report(report)
    receipt = materialize_review_receipt(request, report)
    request_doc = load_json(request)
    paths = {
        "manifest": run_dir / request_doc["input_manifest_path"],
        "session": session,
        "request": request,
        "report": report,
    }
    path = paths[target]
    payload = load_json(path)
    if target == "request":
        payload["budget"]["max_minutes"] += 1
    else:
        time_field = {
            "manifest": "generated_at",
            "session": "started_at",
            "report": "generated_at",
        }[target]
        payload[time_field] = "2026-07-20T02:00:00Z"
    atomic_json(path, payload)

    with pytest.raises(ContractError, match="审核回执复验失败"):
        StateService(tmp_path).record_review_gate(
            run_dir.name, "R1_MODELING", receipt, Actor("gate-recorder")
        )


def test_old_revision_session_is_stale(tmp_path: Path) -> None:
    """作者 revision 变化后，已领取但未出报告的 session 必须失效。"""
    run_dir, request = _r1_request(tmp_path)
    session = claim_review_request(request, thread_id="thread-stale")
    state = load_json(run_dir / "state.json")
    state["revision"] += 1
    atomic_json(run_dir / "state.json", state)

    with pytest.raises(ContractError, match="旧 revision"):
        write_review_report(request, _accept_report(request, sha256_file(session)))


def test_coverage_pass_requires_minimum_structural_evidence(tmp_path: Path) -> None:
    """审核器不能在模型规格缺少必要证据时把关键项目全部填 pass。"""
    _, request = _r1_request(tmp_path, rich_spec=False)
    session = claim_review_request(request, thread_id="thread-weak-spec")

    with pytest.raises(ContractError, match="最低结构证据"):
        write_review_report(request, _accept_report(request, sha256_file(session)))


@pytest.mark.parametrize(
    "check_id",
    [
        "data_and_attachment_mapping",
        "equation_closure",
        "stopping_rule",
        "baseline_design",
        "evidence_plan",
    ],
)
def test_each_new_r1_structural_precheck_rejects_missing_evidence(
    tmp_path: Path, check_id: str
) -> None:
    """五项新增 coverage 不能在结构证据缺失时单独伪报 pass。"""
    run_dir, request = _r1_request(tmp_path)
    model_spec_path = run_dir / load_json(request)["binding_paths"]["model_spec"]
    model_spec = load_json(model_spec_path)
    model_spec["questions"][0].pop("r1_evidence")
    atomic_json(model_spec_path, model_spec)
    request_doc = load_json(request)
    request_doc["bindings"]["model_spec"] = sha256_file(model_spec_path)
    atomic_json(request, request_doc)
    manifest_path = run_dir / request_doc["input_manifest_path"]
    manifest = load_json(manifest_path)
    next(item for item in manifest["materials"] if item["role"] == "model_spec")[
        "sha256"
    ] = sha256_file(model_spec_path)
    atomic_json(manifest_path, manifest)
    request_doc["input_manifest_sha256"] = sha256_file(manifest_path)
    atomic_json(request, request_doc)

    session = claim_review_request(request, thread_id=f"thread-{check_id}")
    report = _accept_report(request, sha256_file(session))
    new_checks = {
        "data_and_attachment_mapping",
        "equation_closure",
        "stopping_rule",
        "baseline_design",
        "evidence_plan",
    }
    failed_checks = new_checks - {check_id}
    for failed_check in failed_checks:
        report["coverage"][failed_check] = "fail"
    report["verdict"] = "SPEC_REVISION_REQUIRED"
    report["findings"] = [
        {
            "finding_id": f"missing-{failed_check}",
            "severity": "P2",
            "title": f"{failed_check} 缺少结构证据",
            "evidence": ["brief/model_spec.json"],
            "remediation": "补充结构化 R1 证据",
            "status": "open",
            "check_id": failed_check,
            "change_level": "L4",
            "affected_questions": ["q1"],
            "change_class": "SPEC_COMPLETION",
            "affected_stage": "R1_MODELING",
            "route_impact": "none",
            "changed_route_core_fields": [],
        }
        for failed_check in sorted(failed_checks)
    ]

    expected = "完整证据映射" if check_id == "evidence_plan" else "最低结构证据"
    with pytest.raises(ContractError, match=expected):
        write_review_report(request, report)
