"""生产闭环新增契约的定向回归测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.questions.acceptance import verify_question_acceptance
from shumozizi.questions.manifest import create_problem_manifest
from shumozizi.workflow.approval import (
    create_approval_request,
    materialize_route_approval,
    verify_route_approval,
)
from shumozizi.workflow.initialization import initialize_run
from shumozizi.workflow.repair import create_repair_plan
from shumozizi.workflow.reviews import (
    create_review_request,
    materialize_review_receipt,
    write_review_report,
)
from shumozizi.workflow.state_service import Actor, ArtifactRef, StateService, WorkflowEvent
from tests.review_contract_helpers import (
    adjudicate_report,
    claim_and_hash,
    complete_stage_bindings,
    rich_model_spec,
    rich_problem_manifest,
    write_passing_format_audit,
)
from tests.source_package_helpers import write_source_package


def _candidate(route_id: str) -> dict[str, object]:
    return {
        "route_id": route_id,
        "name": f"路线 {route_id}",
        "problem_interpretation": "对固定输入执行可复验的确定性标量计算。",
        "mathematical_nature": "确定性计算",
        "baseline": "直接计算",
        "primary_model": f"模型 {route_id}",
        "innovation": "结构化输出",
        "validation": "精确值复验",
        "computational_cost": "低成本",
        "risks": ["无统计推广性"],
        "fallback": "直接计算",
    }


def _route_run(tmp_path: Path, *, manifest: bool = True) -> Path:
    problem = tmp_path / "problems/sample/problem.md"
    problem.parent.mkdir(parents=True)
    problem.write_text("输出一个可复验标量。\n", encoding="utf-8")
    run_dir = initialize_run(tmp_path, problem, "closure-route")
    candidates = {
        "schema_name": "route_candidates",
        "schema_version": "2.0",
        "run_id": run_dir.name,
        "run_config_lock_sha256": sha256_file(run_dir / "config/RUN_CONFIG_LOCK.json"),
        "problem_summary": "对固定输入执行确定性计算并输出可复验的结构化标量结果。",
        "ambiguities": [],
        "recommended_route_id": "route_a",
        "recommendation_reason": "直接计算足以验证执行、指标和论文证据闭环。",
        "candidates": [_candidate("route_a"), _candidate("route_b")],
    }
    candidates_path = run_dir / "brief/route_candidates.json"
    atomic_json(candidates_path, candidates)
    if manifest:
        create_problem_manifest(
            run_dir,
            [
                {
                    "question_id": "q1",
                    "title": "输出可复验标量",
                    "required": True,
                    "required_outputs": [
                        {"output_id": "value", "description": "确定性标量结果", "unit": None}
                    ],
                    "depends_on": [],
                    "source_refs": ["题面第 1 行"],
                }
            ],
        )
    return run_dir


def test_route_approval_requires_manifest(tmp_path: Path) -> None:
    run_dir = _route_run(tmp_path, manifest=False)
    with pytest.raises(ContractError, match="PROBLEM_MANIFEST"):
        create_approval_request(
            run_dir,
            "route",
            {
                "run_config_lock": run_dir / "config/RUN_CONFIG_LOCK.json",
                "route_candidates": run_dir / "brief/route_candidates.json",
            },
        )


@pytest.mark.parametrize(
    ("approved_by", "raw_response"),
    [("codex", "批准 route_a"), ("human-reviewer", "拒绝 route_a")],
)
def test_route_approval_rejects_non_human_or_negative_reply(
    tmp_path: Path, approved_by: str, raw_response: str
) -> None:
    run_dir = _route_run(tmp_path)
    candidates_path = run_dir / "brief/route_candidates.json"
    create_approval_request(
        run_dir,
        "route",
        {
            "run_config_lock": run_dir / "config/RUN_CONFIG_LOCK.json",
            "route_candidates": candidates_path,
        },
    )
    with pytest.raises(ContractError):
        materialize_route_approval(
            run_dir,
            raw_user_response=raw_response,
            selected_route_id="route_a",
            approved_by=approved_by,
        )


def test_route_lock_candidate_semantics_are_rechecked(tmp_path: Path) -> None:
    run_dir = _route_run(tmp_path)
    candidates_path = run_dir / "brief/route_candidates.json"
    create_approval_request(
        run_dir,
        "route",
        {
            "run_config_lock": run_dir / "config/RUN_CONFIG_LOCK.json",
            "route_candidates": candidates_path,
        },
    )
    materialize_route_approval(
        run_dir,
        raw_user_response="明确批准 route_a",
        selected_route_id="route_a",
        approved_by="human-reviewer",
    )
    lock_path = run_dir / "brief/ROUTE_LOCK.json"
    lock = load_json(lock_path)
    lock["primary_route"] = "被篡改路线"
    atomic_json(lock_path, lock)
    report = verify_route_approval(run_dir)
    assert not report["valid"]
    assert any("primary_route" in error for error in report["errors"])


def test_plain_text_route_artifacts_cannot_advance_state(tmp_path: Path) -> None:
    run_dir = _route_run(tmp_path)
    candidates_path = run_dir / "brief/route_candidates.json"
    create_approval_request(
        run_dir,
        "route",
        {
            "run_config_lock": run_dir / "config/RUN_CONFIG_LOCK.json",
            "route_candidates": candidates_path,
        },
    )
    service = StateService(tmp_path)
    service.transition(
        run_dir.name,
        WorkflowEvent.ROUTES_PROPOSED,
        Actor("route-author"),
        [ArtifactRef("route_candidates", "brief/route_candidates.json", sha256_file(candidates_path))],
    )
    (run_dir / "brief/route_approval_receipt.json").write_text("approved", encoding="utf-8")
    (run_dir / "brief/ROUTE_LOCK.json").write_text("approved", encoding="utf-8")
    receipt = run_dir / "brief/route_approval_receipt.json"
    lock = run_dir / "brief/ROUTE_LOCK.json"
    with pytest.raises(ContractError):
        service.transition(
            run_dir.name,
            WorkflowEvent.ROUTE_APPROVED,
            Actor("route-author"),
            [
                ArtifactRef("route_approval_receipt", receipt.relative_to(run_dir).as_posix(), sha256_file(receipt)),
                ArtifactRef("route_lock", lock.relative_to(run_dir).as_posix(), sha256_file(lock)),
            ],
        )


def test_manifest_required_questions_cannot_be_replaced_by_subset(tmp_path: Path) -> None:
    run_dir = _route_run(tmp_path)
    create_problem_manifest(
        run_dir,
        [
            {
                "question_id": "q1",
                "title": "第一问",
                "required": True,
                "required_outputs": [{"output_id": "a", "description": "结果", "unit": None}],
                "depends_on": [],
                "source_refs": ["题面第 1 行"],
            },
            {
                "question_id": "q2",
                "title": "第二问",
                "required": True,
                "required_outputs": [{"output_id": "b", "description": "结果", "unit": None}],
                "depends_on": [],
                "source_refs": ["题面第 2 行"],
            },
        ],
    )
    state_path = run_dir / "state.json"
    state = load_json(state_path)
    state["question_progress"] = {"q1": {"experiment": "accepted"}}
    atomic_json(state_path, state)
    report = verify_question_acceptance(run_dir)
    assert not report["valid"]
    assert any("q2" in error for error in report["errors"])


def _review_run(tmp_path: Path, stage: str) -> tuple[Path, Path]:
    problem = tmp_path / "problems/sample/problem.md"
    problem.parent.mkdir(parents=True)
    problem.write_text("固定题面\n", encoding="utf-8")
    run_dir = initialize_run(tmp_path, problem, f"review-{stage.lower()}")
    if stage == "R5_COMPREHENSIVE":
        create_problem_manifest(
            run_dir,
            [
                {
                    "question_id": "q1",
                    "title": "测试问题",
                    "required": True,
                    "required_outputs": [
                        {"output_id": "value", "description": "测试输出", "unit": None}
                    ],
                    "depends_on": [],
                    "source_refs": ["题面"],
                }
            ],
        )
        atomic_json(
            run_dir / "results/result_registry.json",
            {
                "schema_name": "result_registry",
                "schema_version": "2.0",
                "run_id": run_dir.name,
                "results": [
                    {
                        "result_id": "source-fixture",
                        "question_id": "q1",
                        "cycle": "baseline",
                        "status": "accepted",
                        "paper_allowed": True,
                        "execution_record_id": "source-fixture",
                        "metric_spec_ids": [],
                        "sealed_result_path": None,
                        "result_seal_path": None,
                        "supersedes_result_id": None,
                    }
                ],
            },
        )
        (run_dir / "paper/final.pdf").write_bytes(b"PDF")
        write_passing_format_audit(run_dir, run_dir / "paper/final.pdf")
        file_ref = {"path": "fixture", "sha256": "0" * 64}
        atomic_json(
            run_dir / "paper/paper_plan.json",
            {
                "schema_name": "paper_plan",
                "schema_version": "2.0",
                "run_id": run_dir.name,
                "referenced_result_ids": ["source-fixture"],
                "bindings": {
                    "mathmodel_paper": file_ref,
                    "writing_skill": file_ref,
                    "typst_author": file_ref,
                    "figure_templates": file_ref,
                    "coding_visual": file_ref,
                    "competition_template": file_ref,
                    "model_spec": file_ref,
                    "result_registry": {
                        "path": "results/result_registry.json",
                        "sha256": sha256_file(run_dir / "results/result_registry.json"),
                    },
                    "claim_gate": file_ref,
                    "section_files": [file_ref],
                    "figures_used": [],
                },
                "final_pdf_path": "paper/final.pdf",
            },
        )
        write_source_package(run_dir, question_id="q1", result_id="source-fixture")
    overrides: dict[str, Path] = {}
    if stage == "R1_MODELING":
        problem_manifest = rich_problem_manifest(
            run_dir, run_dir / "problem/PROBLEM_MANIFEST.json"
        )
        model_spec = rich_model_spec(
            run_dir, run_dir / "review-inputs/model_spec.json"
        )
        overrides.update(
            {"model_spec": model_spec, "problem_manifest": problem_manifest}
        )
    else:
        overrides.update(
            {
                "problem_manifest": run_dir / "problem/PROBLEM_MANIFEST.json",
                "run_config_lock": run_dir / "review-inputs/run_config_lock.json",
                "result_registry": run_dir / "results/result_registry.json",
                "paper_plan": run_dir / "paper/paper_plan.json",
                "final_pdf": run_dir / "paper/final.pdf",
                "qa_report": run_dir / "review-inputs/qa_report.json",
                "evidence_report": run_dir / "review-inputs/evidence_report.json",
                "source_manifest": run_dir / "source/SOURCE_MANIFEST.json",
            }
        )
    bindings = complete_stage_bindings(run_dir, stage, overrides)
    for path in bindings.values():
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
    request = create_review_request(run_dir, stage, bindings)
    claim_and_hash(request, f"thread-{stage.lower()}-{run_dir.name}")
    return run_dir, request


def test_review_request_requires_policy_materials(tmp_path: Path) -> None:
    run_dir = _review_run(tmp_path, "R1_MODELING")[0]
    path = run_dir / "review-inputs/only-model-spec.json"
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ContractError, match="强制材料"):
        create_review_request(run_dir, "R1_MODELING", {"model_spec": path})


def test_r5_joint_verdict_must_match_b_axis_threshold(tmp_path: Path) -> None:
    run_dir, request = _review_run(tmp_path, "R5_COMPREHENSIVE")
    request_doc = load_json(request)
    report = {
        "schema_name": "review_report",
        "schema_version": "2.0",
        "request_id": request_doc["request_id"],
        "run_id": run_dir.name,
        "stage": "R5_COMPREHENSIVE",
        "review_round_id": request_doc["review_round_id"],
        "request_sha256": sha256_file(request),
        "input_manifest_sha256": request_doc["input_manifest_sha256"],
        "session_sha256": sha256_file(request.with_name("review_session.json")),
        "verdict": "B",
        "findings": [],
        "rating": {
            "grade": "B",
            "confidence": "medium",
            "basis": ["冻结提交包"],
            "downgrade_reasons": [],
            "expert_estimate": True,
        },
        "integrity_axis": {"verdict": "A_PASS", "checks": ["通过"], "blockers": []},
        "quality_axis": {
            "verdict": "B_WEAK",
            "total_score": 50,
            "dimensions": {"problem_coverage": 50, "model_depth": 50, "experiment_validation": 50},
            "evidence": ["质量不足"],
        },
        "joint_verdict": "FINAL_CANDIDATE",
        "repair_scope": [],
        "required_retests": [],
        "read_only_confirmed": True,
        "generated_at": "2026-07-19T00:00:00Z",
    }
    with pytest.raises(ContractError, match="联合结论"):
        write_review_report(request, report)


def test_failed_review_requires_explicit_hashed_repair_plan(tmp_path: Path) -> None:
    run_dir, request = _review_run(tmp_path, "R1_MODELING")
    request_doc = load_json(request)
    report = {
        "schema_name": "review_report",
        "schema_version": "2.0",
        "request_id": request_doc["request_id"],
        "run_id": run_dir.name,
        "stage": "R1_MODELING",
        "review_round_id": request_doc["review_round_id"],
        "request_sha256": sha256_file(request),
        "input_manifest_sha256": request_doc["input_manifest_sha256"],
        "session_sha256": sha256_file(request.with_name("review_session.json")),
        "verdict": "SPEC_REVISION_REQUIRED",
        "coverage": {
            "problem_interpretation": "pass", "question_output_mapping": "pass",
            "variable_completeness": "pass", "data_and_attachment_mapping": "pass", "unit_consistency": "pass",
            "equation_closure": "pass", "parameter_identifiability": "pass",
            "objective_definition": "pass", "constraint_completeness": "pass",
            "algorithm_executability": "pass", "stopping_rule": "pass",
            "baseline_design": "pass", "model_selection_criterion": "fail",
            "uncertainty_quantification": "pass", "robustness_and_ablation": "pass",
            "failure_boundary": "pass", "evidence_plan": "pass", "unchecked_items": [],
        },
        "findings": [
            {
                "finding_id": "R1-001",
                "check_id": "model_selection_criterion",
                "severity": "P1",
                "title": "路线不可证伪",
                "evidence": ["review-inputs/model-spec.json"],
                "remediation": "补充可证伪验证",
                "axis": "quality",
                "affected_stage": "R1_MODELING",
                "affected_files": ["reports/model_spec.md"],
                "required_retests": ["R1_MODELING"],
                "expected_improvement": "提高模型可证伪性",
                "change_level": "L3",
                "affected_questions": ["q1"],
                "change_class": "VALIDATION_DETAIL",
                "route_impact": "none",
                "changed_route_core_fields": [],
            }
        ],
        "read_only_confirmed": True,
        "generated_at": "2026-07-19T00:00:00Z",
    }
    report_path = write_review_report(request, report)
    adjudication_path = adjudicate_report(report_path)
    receipt_path = materialize_review_receipt(request, report_path)
    receipt = load_json(receipt_path)
    assert "repair_plan_path" not in receipt
    repair_path = create_repair_plan(run_dir, report_path, adjudication_path)
    assert repair_path.name == "REPAIR_PLAN.json"
    assert load_json(repair_path)["route_reapproval_required"] is False


@pytest.mark.parametrize("change_class", ["SPEC_COMPLETION", "VALIDATION_DETAIL"])
def test_r1_spec_fixes_do_not_require_route_reapproval(
    tmp_path: Path, change_class: str
) -> None:
    """R1 规格补全和验证细化只能触发规格修订，不能返回路线审批。"""
    run_dir, request = _review_run(tmp_path, "R1_MODELING")
    request_doc = load_json(request)
    report = {
        "schema_name": "review_report",
        "schema_version": "2.0",
        "request_id": request_doc["request_id"],
        "run_id": run_dir.name,
        "stage": "R1_MODELING",
        "review_round_id": request_doc["review_round_id"],
        "request_sha256": sha256_file(request),
        "input_manifest_sha256": request_doc["input_manifest_sha256"],
        "session_sha256": sha256_file(request.with_name("review_session.json")),
        "verdict": "SPEC_REVISION_REQUIRED",
        "coverage": {
            "problem_interpretation": "pass", "question_output_mapping": "pass",
            "variable_completeness": "pass", "data_and_attachment_mapping": "pass", "unit_consistency": "pass",
            "equation_closure": "pass", "parameter_identifiability": "pass",
            "objective_definition": "pass", "constraint_completeness": "pass",
            "algorithm_executability": "pass", "stopping_rule": "pass",
            "baseline_design": "pass", "model_selection_criterion": "fail",
            "uncertainty_quantification": "pass", "robustness_and_ablation": "pass",
            "failure_boundary": "pass", "evidence_plan": "pass", "unchecked_items": [],
        },
        "findings": [
            {
                "finding_id": "R1-SPEC-001",
                "check_id": "model_selection_criterion",
                "severity": "P1",
                "title": "模型规格需要补全",
                "evidence": ["review-inputs/model_spec.json"],
                "remediation": "补全定义后重新执行 R1",
                "affected_stage": "R1_MODELING",
                "change_level": "L4" if change_class == "SPEC_COMPLETION" else "L3",
                "affected_questions": ["q1"],
                "change_class": change_class,
                "route_impact": "none",
                "changed_route_core_fields": [],
            }
        ],
        "read_only_confirmed": True,
        "generated_at": "2026-07-19T00:00:00Z",
    }

    report_path = write_review_report(request, report)
    adjudication_path = adjudicate_report(report_path)
    materialize_review_receipt(request, report_path)
    repair = load_json(create_repair_plan(run_dir, report_path, adjudication_path))

    assert repair["route_reapproval_required"] is False


@pytest.mark.parametrize(
    ("change_class", "changed_field"),
    [
        ("ROUTE_CORE_CHANGE", "model_family"),
        ("PROBLEM_INTERPRETATION_CHANGE", "problem_interpretation"),
    ],
)
def test_r1_route_core_changes_require_route_reapproval(
    tmp_path: Path, change_class: str, changed_field: str
) -> None:
    """模型大类或题意解释变化必须显式返回路线人工确认。"""
    run_dir, request = _review_run(tmp_path, "R1_MODELING")
    request_doc = load_json(request)
    report = {
        "schema_name": "review_report",
        "schema_version": "2.0",
        "request_id": request_doc["request_id"],
        "run_id": run_dir.name,
        "stage": "R1_MODELING",
        "review_round_id": request_doc["review_round_id"],
        "request_sha256": sha256_file(request),
        "input_manifest_sha256": request_doc["input_manifest_sha256"],
        "session_sha256": sha256_file(request.with_name("review_session.json")),
        "verdict": "ROUTE_REAPPROVAL_REQUIRED",
        "coverage": {
            "problem_interpretation": "fail", "question_output_mapping": "pass", "data_and_attachment_mapping": "pass",
            "variable_completeness": "pass", "unit_consistency": "pass",
            "equation_closure": "pass", "parameter_identifiability": "pass",
            "objective_definition": "pass", "constraint_completeness": "pass",
            "algorithm_executability": "pass", "stopping_rule": "pass",
            "baseline_design": "pass", "model_selection_criterion": "pass",
            "uncertainty_quantification": "pass", "robustness_and_ablation": "pass",
            "failure_boundary": "pass", "evidence_plan": "pass", "unchecked_items": [],
        },
        "findings": [
            {
                "finding_id": "R1-ROUTE-001",
                "check_id": "problem_interpretation",
                "severity": "P1",
                "title": "路线核心发生变化",
                "evidence": ["review-inputs/model_spec.json"],
                "remediation": "返回路线审批并说明变化",
                "affected_stage": "R1_MODELING",
                "change_level": "L5",
                "affected_questions": ["q1"],
                "change_class": change_class,
                "route_impact": "material",
                "changed_route_core_fields": [changed_field],
            }
        ],
        "read_only_confirmed": True,
        "generated_at": "2026-07-19T00:00:00Z",
    }

    report_path = write_review_report(request, report)
    adjudication_path = adjudicate_report(report_path)
    materialize_review_receipt(request, report_path)
    repair = load_json(create_repair_plan(run_dir, report_path, adjudication_path))

    assert repair["route_reapproval_required"] is True
