"""A4 的 R1 两阶段隔离、四态覆盖和 R2 双轴契约测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.core.schema import require_valid
from shumozizi.workflow.r1_phases import (
    create_r1_phase_a,
    create_r1_phase_b_request,
    verify_r1_phase_a,
)
from shumozizi.workflow.review_sessions import claim_review_request
from shumozizi.workflow.reviews import (
    R1_COVERAGE_CHECKS,
    R2_EXECUTION_CHECKS,
    R2_SCIENTIFIC_CHECKS,
    _validate_r1_semantics,
    _validate_r2_semantics,
    write_review_report,
)
from tests.review_contract_helpers import (
    complete_stage_bindings,
    rich_model_spec,
    rich_problem_manifest,
)


def _phase_a_outputs() -> dict[str, list[str]]:
    return {
        "required_outputs": ["q1 的最优决策与不确定性区间"],
        "decision_variables": ["x: 决策量"],
        "observable_variables": ["demand: 已观测需求"],
        "latent_variables": ["future_demand: 潜在未来需求"],
        "units": ["x=件", "demand=件/日"],
        "hard_constraints": ["x >= 0"],
        "boundary_conditions": ["demand = 0 时 x = 0"],
        "plausible_model_families": ["带约束随机优化"],
        "identifiability_risks": ["单一时间窗不能分离趋势与季节项"],
        "minimum_validation_requirements": ["小实例穷举与约束可行性 oracle"],
        "possible_failure_modes": ["未来信息泄漏导致收益高估"],
    }


def test_phase_a_rejects_author_material_and_freezes_inputs(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "a4-phase"
    source = run_dir / "problem" / "source.md"
    source.parent.mkdir(parents=True)
    source.write_text("原始题面", encoding="utf-8")
    phase_a = create_r1_phase_a(
        run_dir,
        "round-1",
        {"problem_source": source},
        _phase_a_outputs(),
    )
    assert verify_r1_phase_a(run_dir, phase_a)["required_outputs"]

    model_spec = run_dir / "brief" / "model_spec.json"
    model_spec.parent.mkdir(parents=True)
    model_spec.write_text("{}", encoding="utf-8")
    with pytest.raises(ContractError, match="作者侧或未授权"):
        create_r1_phase_a(
            run_dir,
            "round-2",
            {"problem_source": source, "model_spec": model_spec},
            _phase_a_outputs(),
        )

    source.write_text("被修改的题面", encoding="utf-8")
    with pytest.raises(ContractError, match="输入冻结后发生变化"):
        verify_r1_phase_a(run_dir, phase_a)


def test_phase_b_report_binds_frozen_phase_a(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "a4-phase-b"
    run_dir.mkdir(parents=True)
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
            "review_gates": {},
            "artifacts": {},
            "last_updated_by": "test",
            "updated_at": "2026-07-20T00:00:00Z",
            "history": [],
        },
    )
    model_spec = run_dir / "brief" / "model_spec.json"
    rich_model_spec(run_dir, model_spec)
    bindings = complete_stage_bindings(
        run_dir, "R1_MODELING", {"model_spec": model_spec}
    )
    rich_problem_manifest(run_dir, bindings["problem_manifest"])
    phase_roles = {
        role: bindings[role]
        for role in (
            "problem_source",
            "problem_attachments_manifest",
            "problem_manifest",
            "data_dictionary",
            "data_profile",
        )
    }
    phase_a = create_r1_phase_a(run_dir, "round-1", phase_roles, _phase_a_outputs())
    request = create_r1_phase_b_request(
        run_dir,
        phase_a,
        bindings,
        review_round_id="round-1",
    )
    session = claim_review_request(request, thread_id="fresh-r1-phase-b")
    request_doc = load_json(request)
    report = _base_report("R1_MODELING")
    report.update(
        {
            "request_id": request_doc["request_id"],
            "run_id": run_dir.name,
            "review_round_id": request_doc["review_round_id"],
            "request_sha256": sha256_file(request),
            "input_manifest_sha256": request_doc["input_manifest_sha256"],
            "session_sha256": sha256_file(session),
            "phase_a_sha256": sha256_file(phase_a),
            "coverage": {
                **{check_id: "verified" for check_id in R1_COVERAGE_CHECKS},
                "unchecked_items": [],
            },
        }
    )
    report_path = write_review_report(request, report)
    assert load_json(report_path)["phase_a_sha256"] == sha256_file(phase_a)


def _base_report(stage: str) -> dict:
    return {
        "schema_name": "review_report",
        "schema_version": "3.0",
        "request_id": "request-1",
        "run_id": "run-1",
        "stage": stage,
        "review_round_id": "round-1",
        "request_sha256": "1" * 64,
        "input_manifest_sha256": "2" * 64,
        "session_sha256": "3" * 64,
        "verdict": "ACCEPT" if stage == "R1_MODELING" else "REPRODUCIBLE",
        "findings": [],
        "read_only_confirmed": True,
        "generated_at": "2026-07-20T00:00:00Z",
    }


def test_r1_v3_uses_four_states_and_unknown_cannot_pass() -> None:
    report = _base_report("R1_MODELING")
    report["phase_a_sha256"] = "4" * 64
    report["coverage"] = {
        **{check_id: "verified" for check_id in R1_COVERAGE_CHECKS},
        "unchecked_items": [],
    }
    require_valid(report, "review_report")
    _validate_r1_semantics(report)

    report["coverage"]["parameter_identifiability"] = "unknown"
    with pytest.raises(ContractError, match="对应 finding"):
        _validate_r1_semantics(report)

    report["coverage"]["parameter_identifiability"] = "pass"
    with pytest.raises(ContractError, match="review_report.schema.json"):
        require_valid(report, "review_report")
    with pytest.raises(ContractError, match="旧 pass/fail"):
        _validate_r1_semantics(report)


def _verified_axis(check_ids: set[str] | frozenset[str]) -> dict:
    return {
        "status": "verified",
        "checks": {
            check_id: {"status": "verified", "evidence": [f"evidence:{check_id}"]}
            for check_id in check_ids
        },
    }


def test_r2_v3_requires_both_axes_and_preregistered_oracle() -> None:
    report = _base_report("R2_EXPERIMENT")
    report["execution_reproducibility"] = _verified_axis(R2_EXECUTION_CHECKS)
    report["scientific_correctness"] = _verified_axis(R2_SCIENTIFIC_CHECKS)
    report["preregistered_oracles"] = [
        {
            "oracle_id": "oracle-small-instance",
            "oracle_type": "small_instance_exhaustive_solution",
            "question": "小实例的优化解是否正确",
            "registered_before_primary": True,
            "success_condition": "目标值与穷举最优值一致",
            "evidence_path": "experiments/q1/oracles/small-instance.json",
        }
    ]
    require_valid(report, "review_report")
    _validate_r2_semantics(report)

    report["scientific_correctness"]["checks"]["leakage_control"]["status"] = "unknown"
    report["scientific_correctness"]["status"] = "unknown"
    with pytest.raises(ContractError, match="leakage_control"):
        _validate_r2_semantics(report)
