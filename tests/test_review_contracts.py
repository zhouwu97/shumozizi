"""审核材料清单、独立 session 与 R1 结构证据的拒绝性测试。"""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.core.schema import schema_root
from shumozizi.workflow.review_sessions import claim_review_request, verify_review_session
from shumozizi.workflow.reviews import (
    R1_COVERAGE_CHECKS,
    R1_REQUIRED_CHECK_IDS,
    create_review_request,
    materialize_review_receipt,
    verify_review_receipt,
    write_review_report,
)
from shumozizi.workflow.state_service import Actor, StateService
from tests.review_contract_helpers import (
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


@pytest.mark.parametrize("target", ["manifest", "session", "request", "report"])
def test_record_review_gate_rejects_each_hash_layer_tamper(
    tmp_path: Path, target: str
) -> None:
    """登记审核门时必须重新计算四层哈希及全部材料哈希。"""
    run_dir, request = _r1_request(tmp_path)
    session = claim_review_request(request, thread_id=f"thread-tamper-{target}")
    report = write_review_report(request, _accept_report(request, sha256_file(session)))
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
