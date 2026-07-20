"""审核任务交接、回执绑定和 R5 有界收敛规则。

审核任务只读生产目录，唯一允许写入的位置是 ``review/`` 下与请求绑定的报告和回执。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, resolve_inside, sha256_file
from shumozizi.core.schema import require_valid
from shumozizi.workflow.repair import (
    finding_requires_route_reapproval,
)
from shumozizi.workflow.review_inputs import (
    create_review_input_manifest,
    verify_review_input_manifest,
)
from shumozizi.workflow.review_policy import get_review_stage_policy
from shumozizi.workflow.review_sessions import verify_review_session
from shumozizi.workflow.source_package import SOURCE_MANIFEST_PATH, verify_source_manifest

REVIEW_STAGES = {
    "R1_MODELING": "mathmodel-review-r1-modeling",
    "R2_EXPERIMENT": "mathmodel-review-r2-experiment",
    "R3_PAPER_LOGIC": "mathmodel-review-r3-paper-logic",
    "R4_FORMAT_VISUAL": "mathmodel-review-r4-format-visual",
    "R5_COMPREHENSIVE": "mathmodel-review-r5-comprehensive",
    "J0_FINAL_BLIND_JUDGE": "fresh_context_unstructured",
}
VERDICTS = {
    "R1_MODELING": {
        "ACCEPT",
        "ACCEPT_WITH_MINOR_FIXES",
        "SPEC_REVISION_REQUIRED",
        "ROUTE_REAPPROVAL_REQUIRED",
        "BLOCKED_MISSING_INPUT",
    },
    "R2_EXPERIMENT": {"REPRODUCIBLE", "REPRODUCIBLE_WITH_WARNINGS", "BLOCKED"},
    "R3_PAPER_LOGIC": {"READY_FOR_COMPREHENSIVE_REVIEW", "MAJOR_REVISION", "NOT_READY"},
    "R4_FORMAT_VISUAL": {"COMPLIANT", "FIX_REQUIRED", "NOT_COMPLIANT"},
    "R5_COMPREHENSIVE": {"A", "B", "C", "D", "E"},
    "J0_FINAL_BLIND_JUDGE": {"PROCEED", "DO_NOT_PROCEED", "ADVISORY"},
}
PASSING_VERDICTS = {
    "R1_MODELING": {"ACCEPT", "ACCEPT_WITH_MINOR_FIXES"},
    "R2_EXPERIMENT": {"REPRODUCIBLE", "REPRODUCIBLE_WITH_WARNINGS"},
    "R3_PAPER_LOGIC": {"READY_FOR_COMPREHENSIVE_REVIEW"},
    "R4_FORMAT_VISUAL": {"COMPLIANT"},
    "J0_FINAL_BLIND_JUDGE": {"PROCEED", "ADVISORY"},
}
UNRESOLVED_ADJUDICATIONS = {
    "needs_probe",
    "needs_second_review",
    "needs_human_decision",
}
STRONG_RESOLUTION_EVIDENCE = {
    "deterministic_machine_evidence",
    "exact_oracle",
    "probe_result",
    "independent_second_review",
    "human_decision",
}

R1_COVERAGE_CHECKS = (
    "problem_interpretation",
    "question_output_mapping",
    "variable_completeness",
    "data_and_attachment_mapping",
    "unit_consistency",
    "equation_closure",
    "parameter_identifiability",
    "objective_definition",
    "constraint_completeness",
    "algorithm_executability",
    "stopping_rule",
    "baseline_design",
    "model_selection_criterion",
    "uncertainty_quantification",
    "robustness_and_ablation",
    "failure_boundary",
    "evidence_plan",
)
R1_REQUIRED_CHECK_IDS = frozenset(R1_COVERAGE_CHECKS)
if len(R1_COVERAGE_CHECKS) != 17 or len(R1_REQUIRED_CHECK_IDS) != 17:
    raise RuntimeError("R1 coverage 必须恰好包含 17 个唯一检查项")

R2_EXECUTION_CHECKS = frozenset(
    {
        "code_execution",
        "config_reproducibility",
        "hash_integrity",
        "random_seed_control",
        "result_figure_consistency",
        "accepted_result_seal",
    }
)
R2_SCIENTIFIC_CHECKS = frozenset(
    {
        "split_design",
        "leakage_control",
        "metric_suitability",
        "constraint_completeness",
        "solution_credibility",
        "parameter_stability",
        "conclusion_bounds",
        "robustness_discrimination",
    }
)


def utc_now() -> str:
    """返回 RFC 3339 UTC 时间。"""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _reviewer_severity(finding: dict[str, Any]) -> str:
    """读取 v2 严重度或 v3 reviewer 严重度建议。"""
    return str(finding.get("severity_recommendation", finding.get("severity", "")))


def _relative(run_dir: Path, path: Path) -> str:
    """校验路径位于运行目录内并返回 POSIX 相对路径。"""
    try:
        return path.resolve().relative_to(run_dir.resolve()).as_posix()
    except ValueError as exc:
        raise ContractError(f"审核路径越过运行目录边界: {path}") from exc


def _require_current_request_policy(request: dict[str, Any], run_dir: Path) -> None:
    """拒绝调用方削减固定审核材料或伪造源码包角色。"""
    policy = get_review_stage_policy(
        request["stage"], run_dir, question_id=request.get("question_id")
    )
    for key, expected in policy.items():
        if request.get(key) != expected:
            raise ContractError(f"审核请求策略字段已被修改: {key}")
    roles = set(request["bindings"])
    mandatory = set(policy["mandatory_inputs"])
    allowed = mandatory | set(policy["optional_inputs"])
    if not mandatory.issubset(roles) or not roles.issubset(allowed):
        raise ContractError("审核请求材料角色不符合当前阶段策略")
    manifest_path = resolve_inside(
        run_dir, request["input_manifest_path"], must_exist=True
    )
    if sha256_file(manifest_path) != request["input_manifest_sha256"]:
        raise ContractError("审核请求绑定的材料清单哈希不一致")
    manifest_report = verify_review_input_manifest(run_dir, manifest_path, request=request)
    if not manifest_report["valid"]:
        raise ContractError("审核材料清单复验失败: " + "; ".join(manifest_report["errors"]))
    if request["stage"] in {"R4_FORMAT_VISUAL", "R5_COMPREHENSIVE"}:
        source_report = verify_source_manifest(run_dir)
        if not source_report["valid"]:
            raise ContractError("源码包校验失败: " + "; ".join(source_report["errors"]))
        if request["binding_paths"].get("source_manifest") != SOURCE_MANIFEST_PATH:
            raise ContractError("审核请求未绑定权威 SOURCE_MANIFEST.json")
        if request["binding_paths"].get("format_audit") != "review/FORMAT_AUDIT.json":
            raise ContractError("审核请求未绑定权威 FORMAT_AUDIT.json")


def _validate_format_audit_verdict(
    request: dict[str, Any], report: dict[str, Any], run_dir: Path
) -> None:
    """机器格式硬失败不得被 R4/R5 的文字结论覆盖。"""
    if request["stage"] not in {"R4_FORMAT_VISUAL", "R5_COMPREHENSIVE"}:
        return
    audit_path = resolve_inside(
        run_dir, request["binding_paths"]["format_audit"], must_exist=True
    )
    audit = load_json(audit_path)
    require_valid(audit, "format_audit")
    hard_details = {
        item["check_id"]: item["details"]
        for item in audit["checks"]
        if item["check_id"] in audit["hard_failures"]
    }
    if request["stage"] == "R4_FORMAT_VISUAL":
        if report["verdict"] == "COMPLIANT" and audit["hard_failures"]:
            failures = "; ".join(
                f"{check_id}: {hard_details.get(check_id, '无详情')}"
                for check_id in audit["hard_failures"]
            )
            raise ContractError(
                f"FORMAT_AUDIT 存在机器硬失败，R4 不得判 COMPLIANT: {failures}"
            )
    elif report.get("joint_verdict") == "FINAL_CANDIDATE" and audit["hard_failures"]:
        failures = "; ".join(
            f"{check_id}: {hard_details.get(check_id, '无详情')}"
            for check_id in audit["hard_failures"]
        )
        raise ContractError(
            f"FORMAT_AUDIT 存在机器硬失败，R5 不得判 FINAL_CANDIDATE: {failures}"
        )


def create_review_request(
    run_dir: Path,
    stage: str,
    bindings: dict[str, Path],
    *,
    question_id: str | None = None,
    review_round_id: str | None = None,
    read_paths: list[Path] | None = None,
    max_minutes: int = 60,
    mode: str | None = None,
) -> Path:
    """冻结当前 revision 并创建供新桌面任务领取的只读审核请求。"""
    if stage not in REVIEW_STAGES:
        raise ContractError(f"未知审核阶段: {stage}")
    if stage == "J0_FINAL_BLIND_JUDGE" and any(
        (run_dir / "review" / stage.lower()).glob("*/review_request.json")
    ):
        raise ContractError("J0_FINAL_BLIND_JUDGE 只允许创建一次")
    state = load_json(run_dir / "state.json")
    effective_mode = state.get("mode", "competition")
    if mode is not None and mode != effective_mode:
        raise ContractError("审核轮次模式必须来自当前 state.json，调用方不能临时覆盖")
    r5_max_rounds = 5 if effective_mode == "training" else 3
    if stage == "R5_COMPREHENSIVE":
        existing_r5 = list(
            (run_dir / "review" / stage.lower()).glob("*/review_request.json")
        )
        if len(existing_r5) >= r5_max_rounds:
            raise ContractError(f"R5 完整审核已达到全局上限 {r5_max_rounds} 轮")
    if state.get("run_id") != run_dir.name:
        raise ContractError("审核请求 run_id 与运行目录不一致")
    if not bindings:
        raise ContractError("审核请求必须绑定至少一个当前产物")
    policy = get_review_stage_policy(stage, run_dir, question_id=question_id)
    binding_roles = set(bindings)
    mandatory_roles = set(policy["mandatory_inputs"])
    missing_roles = sorted(mandatory_roles - binding_roles)
    if missing_roles:
        raise ContractError("审核请求缺少阶段强制材料: " + ", ".join(missing_roles))
    allowed_roles = mandatory_roles | set(policy["optional_inputs"])
    unknown_roles = sorted(binding_roles - allowed_roles)
    if unknown_roles:
        raise ContractError("审核请求包含策略未声明的材料角色: " + ", ".join(unknown_roles))
    if stage in {"R4_FORMAT_VISUAL", "R5_COMPREHENSIVE"}:
        source_report = verify_source_manifest(run_dir)
        if not source_report["valid"]:
            raise ContractError("源码包校验失败: " + "; ".join(source_report["errors"]))
        source_path = bindings["source_manifest"].resolve()
        if source_path != (run_dir / SOURCE_MANIFEST_PATH).resolve():
            raise ContractError("source_manifest 必须绑定 source/SOURCE_MANIFEST.json")
        format_audit_path = bindings["format_audit"].resolve()
        if format_audit_path != (run_dir / "review/FORMAT_AUDIT.json").resolve():
            raise ContractError("format_audit 必须绑定 review/FORMAT_AUDIT.json")
        format_audit = load_json(format_audit_path)
        require_valid(format_audit, "format_audit")
    hashes: dict[str, str] = {}
    binding_paths: dict[str, str] = {}
    for name, path in bindings.items():
        resolved = path.resolve()
        _relative(run_dir, resolved)
        if not resolved.is_file():
            raise ContractError(f"审核绑定文件不存在: {path}")
        hashes[name] = sha256_file(resolved)
        binding_paths[name] = _relative(run_dir, resolved)
    paths = read_paths or [Path(path) for path in binding_paths.values()]
    if any(not (item if item.is_absolute() else run_dir / item).resolve().is_file() for item in paths):
        raise ContractError("审核允许读取的路径必须是当前存在的文件")
    normalized_paths = [_relative(run_dir, item if item.is_absolute() else run_dir / item) for item in paths]
    if not normalized_paths:
        raise ContractError("审核请求必须声明允许读取的路径")
    missing_read_paths = sorted(set(binding_paths.values()) - set(normalized_paths))
    if missing_read_paths:
        raise ContractError("审核 read_paths 未覆盖全部强制绑定: " + ", ".join(missing_read_paths))
    forbidden_hits = [
        path
        for path in normalized_paths
        if any(pattern.lower() in path.lower() for pattern in policy["forbidden_inputs"])
    ]
    if forbidden_hits:
        raise ContractError("审核请求包含禁止读取材料: " + ", ".join(forbidden_hits))
    round_id = review_round_id or f"{stage.lower()}-r{state['revision']}"
    request_id = f"{run_dir.name}-{stage.lower()}-{round_id}"
    request_dir = run_dir / "review" / stage.lower() / round_id
    if request_dir.exists():
        raise ContractError("审核 round_id 已存在，禁止覆盖历史请求")
    manifest_path = create_review_input_manifest(
        run_dir,
        request_id=request_id,
        stage=stage,
        question_id=question_id,
        review_round_id=round_id,
        state_revision=state["revision"],
        bindings=hashes,
        binding_paths=binding_paths,
        output_path=request_dir / "REVIEW_INPUT_MANIFEST.json",
    )
    request = {
        "schema_name": "review_request",
        "schema_version": "2.0",
        "request_id": request_id,
        "run_id": run_dir.name,
        "stage": stage,
        "question_id": question_id,
        "review_round_id": round_id,
        "state_revision": state["revision"],
        "bindings": hashes,
        "binding_paths": binding_paths,
        "read_paths": normalized_paths,
        "input_manifest_path": _relative(run_dir, manifest_path),
        "input_manifest_sha256": sha256_file(manifest_path),
        **policy,
        "output_path": f"review/{stage.lower()}/{round_id}/review_report.json",
        "skill": REVIEW_STAGES[stage],
        "read_only": True,
        "budget": {
            "max_minutes": max_minutes,
            "max_rounds": r5_max_rounds if stage == "R5_COMPREHENSIVE" else 1,
        },
        "requested_at": utc_now(),
    }
    require_valid(request, "review_request")
    request_path = request_dir / "review_request.json"
    atomic_json(request_path, request)
    return request_path


def write_review_report(request_path: Path, report: dict[str, Any]) -> Path:
    """校验并写入审核报告；报告不能写到请求声明之外。"""
    request = load_json(request_path)
    require_valid(request, "review_request")
    run_dir = request_path.parents[3]
    session_path = request_path.with_name("review_session.json")
    session_report = verify_review_session(
        run_dir, request_path, session_path, require_current_revision=True
    )
    if not session_report["valid"]:
        raise ContractError("审核 session 复验失败: " + "; ".join(session_report["errors"]))
    required = {"request_id": request["request_id"], "run_id": request["run_id"], "stage": request["stage"], "review_round_id": request["review_round_id"]}
    if any(report.get(key) != value for key, value in required.items()):
        raise ContractError("审核报告未匹配请求的身份字段")
    if report.get("verdict") not in VERDICTS[request["stage"]]:
        raise ContractError("审核结论不属于该阶段枚举")
    if report.get("request_sha256") != sha256_file(request_path):
        raise ContractError("审核报告未绑定当前 review_request.json")
    if report.get("input_manifest_sha256") != request["input_manifest_sha256"]:
        raise ContractError("审核报告未绑定当前 REVIEW_INPUT_MANIFEST.json")
    if report.get("session_sha256") != sha256_file(session_path):
        raise ContractError("审核报告未绑定当前 review_session.json")
    if request["stage"] == "R5_COMPREHENSIVE":
        report = _apply_r5_score_calibration(run_dir, report)
    require_valid(report, "review_report")
    if request["stage"] == "R1_MODELING":
        if report["schema_version"] == "3.0":
            phase_a_path = request["binding_paths"].get("phase_a")
            if not phase_a_path:
                raise ContractError("R1 v3 报告必须来自绑定 Phase A 的 Phase B 请求")
            phase_a = resolve_inside(run_dir, phase_a_path, must_exist=True)
            if report["phase_a_sha256"] != sha256_file(phase_a):
                raise ContractError("R1 v3 报告未绑定冻结的 Phase A")
        _validate_r1_semantics(report)
        _validate_r1_coverage_against_model_spec(report, request, run_dir)
    if request["stage"] == "R2_EXPERIMENT" and report["schema_version"] == "3.0":
        _validate_r2_semantics(report)
    if request["stage"] == "R5_COMPREHENSIVE":
        _validate_r5_axes(report)
    _validate_format_audit_verdict(request, report, run_dir)
    output = resolve_inside(request_path.parents[3], request["output_path"])
    if output.resolve() != request_path.parent / "review_report.json":
        raise ContractError("审核报告路径必须是请求声明的唯一输出路径")
    if output.exists():
        raise ContractError("一个审核 session 只能生成一个报告")
    atomic_json(output, report)
    return output


def _validate_adjudication_semantics(
    report: dict[str, Any], adjudication: dict[str, Any]
) -> None:
    """验证生产主 AI 对每条 finding 的独立裁决权限与冲突状态。"""
    findings = report["findings"]
    finding_map = {item["finding_id"]: item for item in findings}
    if len(finding_map) != len(findings):
        raise ContractError("审核报告 finding_id 必须唯一")
    decisions = adjudication["decisions"]
    decision_map = {item["finding_id"]: item for item in decisions}
    if len(decision_map) != len(decisions):
        raise ContractError("审核裁决 finding_id 必须唯一")
    if set(decision_map) != set(finding_map):
        raise ContractError("审核裁决必须逐条覆盖当前报告全部 finding")
    unresolved: set[str] = set()
    for finding_id, decision in decision_map.items():
        finding = finding_map[finding_id]
        severity = _reviewer_severity(finding)
        main_decision = decision["main_decision"]
        recommended_resolution = finding.get("recommended_resolution")
        if recommended_resolution and main_decision != recommended_resolution:
            raise ContractError(
                f"未验证 finding 必须先进入 {recommended_resolution}: {finding_id}"
            )
        if decision["reviewer_severity"] != severity:
            raise ContractError(f"裁决严重度与审核报告不一致: {finding_id}")
        if decision["effective_severity"] not in {"P0", "P1", "P2", "P3"}:
            raise ContractError(f"裁决有效严重度非法: {finding_id}")
        if main_decision == "accepted":
            if not decision["confirmation_evidence"]:
                raise ContractError("接受 finding 必须提供 confirmation_evidence")
            expected_effect = "block" if severity in {"P0", "P1"} else decision["gate_effect"]
            if decision["gate_effect"] != expected_effect:
                raise ContractError("接受 P0/P1 的 gate_effect 必须为 block")
        elif main_decision == "accepted_as_advisory":
            if decision["gate_effect"] != "warn":
                raise ContractError("accepted_as_advisory 的 gate_effect 必须为 warn")
            if severity in {"P0", "P1"} and (
                not decision["counter_evidence"]
                or decision["resolution_evidence_type"] not in STRONG_RESOLUTION_EVIDENCE
            ):
                raise ContractError(f"{severity} 降为建议必须绑定强反证")
        elif main_decision == "rejected":
            if not decision["counter_evidence"] or not decision["resolution_evidence_type"]:
                raise ContractError("驳回 finding 必须同时提供 counter_evidence 和 resolution_evidence_type")
            if severity in {"P0", "P1"} and decision["resolution_evidence_type"] not in STRONG_RESOLUTION_EVIDENCE:
                raise ContractError(f"{severity} 只有强反证类型才能驳回")
            if decision["gate_effect"] != "none":
                raise ContractError("rejected finding 的 gate_effect 必须为 none")
        elif main_decision in UNRESOLVED_ADJUDICATIONS:
            if decision["gate_effect"] != "block":
                raise ContractError("未解决 finding 的 gate_effect 必须为 block")
        else:
            raise ContractError(f"未知主 AI 裁决: {main_decision}")
        if (
            main_decision == "accepted"
            and decision["effective_change_level"] == "L5"
            and not decision["route_reapproval_required"]
        ):
            raise ContractError("接受的 L5 finding 必须重新批准路线")
        if main_decision in UNRESOLVED_ADJUDICATIONS:
            unresolved.add(finding_id)
    if set(adjudication["unresolved_conflicts"]) != unresolved:
        raise ContractError("unresolved_conflicts 与待复核/待人工决定 finding 不一致")


def write_review_adjudication(
    report_path: Path, adjudication: dict[str, Any]
) -> Path:
    """由生产主 AI 写入独立裁决；审核对话不得调用此函数。"""
    report_path = report_path.resolve()
    report = load_json(report_path)
    require_valid(report, "review_report")
    request_path = report_path.with_name("review_request.json")
    request = load_json(request_path)
    require_valid(request, "review_request")
    run_dir = report_path.parents[3]
    identity = {
        "run_id": report["run_id"],
        "request_id": report["request_id"],
        "stage": report["stage"],
        "state_revision": request["state_revision"],
        "review_report_sha256": sha256_file(report_path),
        "generated_by": "production_main_ai",
    }
    if any(adjudication.get(key) != value for key, value in identity.items()):
        raise ContractError("审核裁决未绑定当前请求、报告或生产主体")
    state = load_json(run_dir / "state.json")
    probe_continuation = (
        adjudication.get("adjudication_sequence") == 2
        and state["revision"] == request["state_revision"] + 1
        and report_path.with_name("REVIEW_ADJUDICATION.0001.json").is_file()
    )
    if state["revision"] != request["state_revision"] and not probe_continuation:
        raise ContractError("旧 revision 的审核报告不能生成生产裁决")
    require_valid(adjudication, "review_adjudication")
    _validate_adjudication_semantics(report, adjudication)
    output = _adjudication_output_path(report_path, adjudication)
    _validate_probe_adjudication_chain(report_path, adjudication, output)
    if output.exists():
        raise ContractError("一份审核报告只能生成一份不可变裁决")
    atomic_json(output, adjudication)
    return output


def _adjudication_output_path(
    report_path: Path, adjudication: dict[str, Any]
) -> Path:
    """普通裁决使用固定名，probe 链使用不可变编号文件。"""
    sequence = adjudication.get("adjudication_sequence")
    has_needs_probe = any(
        item["main_decision"] == "needs_probe"
        for item in adjudication["decisions"]
    )
    if has_needs_probe and sequence != 1:
        raise ContractError("needs_probe 初始裁决必须为 adjudication_sequence=1")
    if sequence is None:
        return report_path.with_name("REVIEW_ADJUDICATION.json")
    return report_path.with_name(f"REVIEW_ADJUDICATION.{sequence:04d}.json")


def _validate_probe_adjudication_chain(
    report_path: Path,
    adjudication: dict[str, Any],
    output_path: Path,
) -> None:
    """验证 probe 前后两份 adjudication 的哈希链与结论映射。"""
    sequence = adjudication.get("adjudication_sequence")
    if sequence is None:
        if adjudication.get("supersedes_adjudication_sha256") is not None:
            raise ContractError("非 probe 裁决不得声明 supersedes_adjudication_sha256")
        if adjudication.get("probe_result_sha256") is not None:
            raise ContractError("非 probe 裁决不得声明 probe_result_sha256")
        return
    if sequence == 1:
        if adjudication.get("supersedes_adjudication_sha256") is not None:
            raise ContractError("首份 probe 裁决不能 supersede 其他裁决")
        if adjudication.get("probe_result_sha256") is not None:
            raise ContractError("首份 probe 裁决不能提前绑定 probe result")
        return
    if sequence != 2:
        raise ContractError("当前 probe 生命周期只允许 .0001 和 .0002 两份裁决")
    initial_path = report_path.with_name("REVIEW_ADJUDICATION.0001.json")
    plan_path = report_path.with_name("PROBE_PLAN.json")
    result_path = report_path.with_name("PROBE_RESULT.json")
    initial = load_json(initial_path)
    plan = load_json(plan_path)
    result = load_json(result_path)
    require_valid(initial, "review_adjudication")
    require_valid(plan, "probe_plan")
    require_valid(result, "probe_result")
    if adjudication.get("supersedes_adjudication_sha256") != sha256_file(initial_path):
        raise ContractError("最终裁决未绑定初始 adjudication 哈希")
    if adjudication.get("probe_result_sha256") != sha256_file(result_path):
        raise ContractError("最终裁决未绑定当前 PROBE_RESULT.json")
    initial_probe_ids = {
        item["finding_id"]
        for item in initial["decisions"]
        if item["main_decision"] == "needs_probe"
    }
    if initial_probe_ids != {plan["finding_id"]} or result["finding_id"] != plan["finding_id"]:
        raise ContractError("probe 计划、结果和初始裁决 finding_id 不一致")
    final_decision = next(
        item for item in adjudication["decisions"] if item["finding_id"] == result["finding_id"]
    )
    allowed = {
        "confirmed": {"accepted"},
        "refuted": {"rejected"},
        "inconclusive": {"needs_second_review", "needs_human_decision"},
        "failed": {"needs_second_review", "needs_human_decision"},
    }[result["status"]]
    if final_decision["main_decision"] not in allowed:
        raise ContractError("最终裁决与 PROBE_RESULT status 不一致")
    if output_path.name != "REVIEW_ADJUDICATION.0002.json":
        raise ContractError("probe 最终裁决路径必须为 REVIEW_ADJUDICATION.0002.json")


def verify_review_adjudication(
    run_dir: Path,
    report_path: Path,
    adjudication_path: Path,
    *,
    require_current_revision: bool = True,
) -> dict[str, Any]:
    """复验裁决身份、报告哈希、逐 finding 权限和 revision。"""
    errors: list[str] = []
    try:
        report = load_json(report_path)
        adjudication = load_json(adjudication_path)
        request = load_json(report_path.with_name("review_request.json"))
        require_valid(report, "review_report")
        require_valid(adjudication, "review_adjudication")
        require_valid(request, "review_request")
        if adjudication_path.parent.resolve() != report_path.parent.resolve():
            raise ContractError("REVIEW_ADJUDICATION 必须与审核报告位于同一轮目录")
        if not adjudication_path.name.startswith("REVIEW_ADJUDICATION"):
            raise ContractError("审核裁决文件名非法")
        expected = {
            "run_id": report["run_id"],
            "request_id": report["request_id"],
            "stage": report["stage"],
            "state_revision": request["state_revision"],
            "review_report_sha256": sha256_file(report_path),
            "generated_by": "production_main_ai",
        }
        if any(adjudication.get(key) != value for key, value in expected.items()):
            raise ContractError("审核裁决绑定已失效")
        _validate_adjudication_semantics(report, adjudication)
        _validate_probe_adjudication_chain(report_path, adjudication, adjudication_path)
        if require_current_revision:
            state = load_json(run_dir / "state.json")
            if state["revision"] != adjudication["state_revision"]:
                raise ContractError("作者 revision 变化后审核裁决已失效")
    except (ContractError, OSError, KeyError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors, "adjudication_path": str(adjudication_path)}


def materialize_review_receipt(
    request_path: Path,
    report_path: Path,
) -> Path:
    """捕获不可变审核事实；回执不表达生产裁决或修复含义。"""
    request_path = request_path.resolve()
    report_path = report_path.resolve()
    request = load_json(request_path)
    report = load_json(report_path)
    require_valid(request, "review_request")
    require_valid(report, "review_report")
    run_dir = request_path.parents[3]
    _require_current_request_policy(request, run_dir)
    if report_path != request_path.with_name("review_report.json"):
        raise ContractError("review_receipt 只能捕获同一轮目录中的 review_report.json")
    if resolve_inside(run_dir, request["output_path"]).resolve() != report_path:
        raise ContractError("审核报告路径与 review_request.json 声明不一致")
    session_path = request_path.with_name("review_session.json")
    session_report = verify_review_session(
        run_dir, request_path, session_path, require_current_revision=True
    )
    if not session_report["valid"]:
        raise ContractError("审核 session 复验失败: " + "; ".join(session_report["errors"]))
    if report["verdict"] not in VERDICTS[request["stage"]]:
        raise ContractError("审核结论不属于该阶段枚举")
    if report["request_id"] != request["request_id"] or report["review_round_id"] != request["review_round_id"]:
        raise ContractError("审核报告与请求不匹配")
    if report["stage"] != request["stage"] or report["run_id"] != request["run_id"]:
        raise ContractError("审核报告身份与请求不匹配")
    if report["request_sha256"] != sha256_file(request_path):
        raise ContractError("审核报告绑定的请求哈希不一致")
    if report["input_manifest_sha256"] != request["input_manifest_sha256"]:
        raise ContractError("审核报告绑定的材料清单哈希不一致")
    if report["session_sha256"] != sha256_file(session_path):
        raise ContractError("审核报告绑定的 session 哈希不一致")
    actual_bindings = {}
    for name, _expected in request["bindings"].items():
        path = resolve_inside(run_dir, request["binding_paths"][name])
        if path.is_file():
            actual_bindings[name] = sha256_file(path)
        elif name == "state":
            actual_bindings[name] = sha256_file(run_dir / "state.json")
    if actual_bindings != request["bindings"]:
        raise ContractError("审核请求绑定事实已变化")
    receipt = {
        "schema_name": "review_receipt",
        "schema_version": "3.0",
        "receipt_kind": "capture",
        "run_id": request["run_id"],
        "request_id": request["request_id"],
        "request_sha256": sha256_file(request_path),
        "session_sha256": sha256_file(session_path),
        "report_sha256": sha256_file(report_path),
        "input_manifest_sha256": request["input_manifest_sha256"],
        "state_revision": request["state_revision"],
        "bindings": request["bindings"],
        "issued_at": utc_now(),
    }
    require_valid(receipt, "review_receipt")
    receipt_path = report_path.with_name("review_receipt.json")
    if receipt_path.exists():
        raise ContractError("一份审核报告只能生成一份不可变 capture receipt")
    atomic_json(receipt_path, receipt)
    return receipt_path


def verify_review_receipt(
    run_dir: Path, receipt_path: Path, *, require_current_revision: bool = True
) -> dict[str, Any]:
    """按版本复验回执；v2 仅保留历史只读兼容。"""
    try:
        receipt = load_json(receipt_path)
        require_valid(receipt, "review_receipt")
    except (ContractError, OSError) as exc:
        return {"valid": False, "errors": [str(exc)], "receipt_path": str(receipt_path)}
    if receipt.get("schema_version") == "2.0":
        return _verify_review_receipt_v2(
            run_dir, receipt_path, require_current_revision=require_current_revision
        )
    return _verify_review_receipt_v3(
        run_dir, receipt_path, require_current_revision=require_current_revision
    )


def _verify_review_receipt_v3(
    run_dir: Path, receipt_path: Path, *, require_current_revision: bool
) -> dict[str, Any]:
    """复验 v3 capture receipt 的请求、session、报告和输入事实。"""
    errors: list[str] = []
    try:
        receipt = load_json(receipt_path)
        require_valid(receipt, "review_receipt")
        request_path = receipt_path.with_name("review_request.json")
        report_path = receipt_path.with_name("review_report.json")
        session_path = receipt_path.with_name("review_session.json")
        request, report = load_json(request_path), load_json(report_path)
        require_valid(request, "review_request")
        require_valid(report, "review_report")
        _require_current_request_policy(request, run_dir)
        if resolve_inside(run_dir, request["output_path"]).resolve() != report_path.resolve():
            errors.append("审核报告路径与请求声明不一致")
        session_report = verify_review_session(
            run_dir,
            request_path,
            session_path,
            require_current_revision=require_current_revision,
        )
        if not session_report["valid"]:
            errors.extend(session_report["errors"])
        if receipt["request_sha256"] != sha256_file(request_path):
            errors.append("审核请求哈希不一致")
        if receipt["report_sha256"] != sha256_file(report_path):
            errors.append("审核报告哈希不一致")
        if report["request_sha256"] != receipt["request_sha256"]:
            errors.append("审核报告与回执的请求绑定不一致")
        if receipt["session_sha256"] != sha256_file(session_path):
            errors.append("审核 session 哈希不一致")
        if report["session_sha256"] != receipt["session_sha256"]:
            errors.append("审核报告与回执的 session 绑定不一致")
        manifest_path = resolve_inside(
            run_dir, request["input_manifest_path"], must_exist=True
        )
        if receipt["input_manifest_sha256"] != sha256_file(manifest_path):
            errors.append("审核回执的材料清单哈希不一致")
        if report["input_manifest_sha256"] != receipt["input_manifest_sha256"]:
            errors.append("审核报告与回执的材料清单绑定不一致")
        for name, expected in request["bindings"].items():
            bound_path = resolve_inside(run_dir, request["binding_paths"][name], must_exist=True)
            if sha256_file(bound_path) != expected:
                errors.append(f"审核绑定事实已变化: {name}")
        state = load_json(run_dir / "state.json")
        if require_current_revision and state["revision"] != receipt["state_revision"]:
            errors.append("作者修复后旧审核回执已失效")
        if request["bindings"] != receipt["bindings"]:
            errors.append("审核回执绑定与请求不一致")
        if receipt["request_id"] != request["request_id"] or report["request_id"] != request["request_id"]:
            errors.append("审核回执、报告和请求身份不一致")
        if receipt["run_id"] != request["run_id"] or report["run_id"] != request["run_id"]:
            errors.append("审核回执、报告和请求 run_id 不一致")
    except (ContractError, OSError, KeyError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors, "receipt_path": str(receipt_path)}


def _verify_review_receipt_v2(
    run_dir: Path, receipt_path: Path, *, require_current_revision: bool
) -> dict[str, Any]:
    """只读复验历史 v2 receipt，不用于生成新回执。"""
    errors: list[str] = []
    try:
        receipt = load_json(receipt_path)
        require_valid(receipt, "review_receipt")
        request_path = receipt_path.with_name("review_request.json")
        report_path = receipt_path.with_name("review_report.json")
        adjudication_path = receipt_path.with_name("REVIEW_ADJUDICATION.json")
        session_path = receipt_path.with_name("review_session.json")
        request, report, adjudication = (
            load_json(request_path),
            load_json(report_path),
            load_json(adjudication_path),
        )
        require_valid(request, "review_request")
        require_valid(report, "review_report")
        require_valid(adjudication, "review_adjudication")
        session_report = verify_review_session(
            run_dir,
            request_path,
            session_path,
            require_current_revision=require_current_revision,
        )
        if not session_report["valid"]:
            errors.extend(session_report["errors"])
        if receipt["request_sha256"] != sha256_file(request_path):
            errors.append("审核请求哈希不一致")
        if receipt["report_sha256"] != sha256_file(report_path):
            errors.append("审核报告哈希不一致")
        if receipt["session_sha256"] != sha256_file(session_path):
            errors.append("审核 session 哈希不一致")
        if receipt["adjudication_path"] != _relative(run_dir, adjudication_path):
            errors.append("审核回执的裁决路径不一致")
        if receipt["adjudication_sha256"] != sha256_file(adjudication_path):
            errors.append("审核裁决哈希不一致")
        manifest_path = resolve_inside(
            run_dir, request["input_manifest_path"], must_exist=True
        )
        if receipt["input_manifest_sha256"] != sha256_file(manifest_path):
            errors.append("审核回执的材料清单哈希不一致")
        for name, expected in request["bindings"].items():
            bound_path = resolve_inside(
                run_dir, request["binding_paths"][name], must_exist=True
            )
            if sha256_file(bound_path) != expected:
                errors.append(f"审核绑定事实已变化: {name}")
        state = load_json(run_dir / "state.json")
        if require_current_revision and state["revision"] != receipt["state_revision"]:
            errors.append("作者修复后旧审核回执已失效")
        if request["bindings"] != receipt["bindings"]:
            errors.append("审核回执绑定与请求不一致")
        repair_path = receipt.get("repair_plan_path")
        if repair_path:
            resolved_repair = resolve_inside(run_dir, repair_path, must_exist=True)
            if receipt.get("repair_plan_sha256") != sha256_file(resolved_repair):
                errors.append("定向修复计划哈希不一致")
    except (ContractError, OSError, KeyError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors, "receipt_path": str(receipt_path)}


def evaluate_r5_convergence(run_dir: Path, *, mode: str = "competition") -> dict[str, Any]:
    """按评级和 P0/P1 规则判断 R5 是否达到人工最终核包门槛。"""
    state = load_json(run_dir / "state.json")
    effective_mode = state.get("mode", "competition")
    if mode != "competition" and mode != effective_mode:
        raise ContractError("R5 收敛模式必须来自 state.json")
    reports = []
    for path in sorted((run_dir / "review").glob("r5_comprehensive/*/review_report.json")):
        try:
            report = load_json(path)
            require_valid(report, "review_report")
            if report["stage"] == "R5_COMPREHENSIVE":
                reports.append(report)
        except ContractError:
            continue
    requests = list(
        (run_dir / "review").glob("r5_comprehensive/*/review_request.json")
    )
    max_rounds = 5 if effective_mode == "training" else 3
    good = [
        item
        for item in reports
        if item.get("joint_verdict") == "FINAL_CANDIDATE"
        and item["rating"]["grade"] in {"A", "B"}
        and item.get("competition_claim_allowed") is True
        and item.get("calibrated_score", 0) >= 75
        and not any(_reviewer_severity(f) in {"P0", "P1"} for f in item["findings"])
    ]
    passed = bool(good and good[-1] is reports[-1])
    return {
        "status": "pass" if passed else ("not_ready_for_submission" if len(requests) >= max_rounds else "continue"),
        "rounds": len(requests),
        "reported_rounds": len(reports),
        "max_rounds": max_rounds,
        "passing_rounds": len(good),
        "consecutive_passing_rounds": 1 if passed else 0,
        "requires_human_final_package": passed,
    }


def _report_passed(report: dict[str, Any]) -> bool:
    """依据阶段语义而非 finding 是否为空判断审核是否通过。"""
    if any(_reviewer_severity(item) in {"P0", "P1"} for item in report["findings"]):
        return False
    if report["stage"] == "R5_COMPREHENSIVE":
        return report.get("joint_verdict") == "FINAL_CANDIDATE"
    if report["stage"] == "J0_FINAL_BLIND_JUDGE":
        severe = any(_reviewer_severity(item) in {"P0", "P1"} for item in report["findings"])
        return report["verdict"] in PASSING_VERDICTS[report["stage"]] and not severe
    return report["verdict"] in PASSING_VERDICTS[report["stage"]]


def _validate_r1_semantics(report: dict[str, Any]) -> None:
    """保证 R1 结论、严重度和路线影响分类互相一致。"""
    findings = report["findings"]
    verdict = report["verdict"]
    coverage = report["coverage"]
    if report.get("schema_version") == "3.0":
        _validate_r1_v3_coverage(report)
        return
    route_findings = [item for item in findings if finding_requires_route_reapproval(item)]
    severe = any(item["severity"] in {"P0", "P1"} for item in findings)

    if coverage["unchecked_items"]:
        raise ContractError("R1 coverage 不得包含 unchecked_items")
    failed_checks = {
        check_id for check_id in R1_COVERAGE_CHECKS if coverage[check_id] == "fail"
    }
    finding_checks = {finding.get("check_id") for finding in findings}
    missing_findings = sorted(failed_checks - finding_checks)
    if missing_findings:
        raise ContractError("R1 coverage fail 缺少对应 finding: " + ", ".join(missing_findings))
    mismatched_findings = sorted(
        finding["check_id"]
        for finding in findings
        if finding.get("check_id") and coverage.get(finding["check_id"]) != "fail"
    )
    if mismatched_findings:
        raise ContractError(
            "R1 finding 的 check_id 必须对应 coverage=fail: "
            + ", ".join(mismatched_findings)
        )

    if verdict == "ACCEPT" and failed_checks:
        raise ContractError("R1 ACCEPT 不能包含 coverage=fail")
    if verdict in {"SPEC_REVISION_REQUIRED", "ROUTE_REAPPROVAL_REQUIRED"} and not failed_checks:
        raise ContractError(f"R1 {verdict} 必须至少包含一个 coverage=fail")
    if verdict == "BLOCKED_MISSING_INPUT":
        if failed_checks:
            raise ContractError("缺少输入时不能把未执行检查标记为模型失败")
        if any(item.get("check_id") for item in findings):
            raise ContractError("缺少输入 finding 不得冒充 coverage 失败项")

    for finding in findings:
        material = finding_requires_route_reapproval(finding)
        changed_fields = finding["changed_route_core_fields"]
        if material and not changed_fields:
            raise ContractError("路线实质变化必须列出 changed_route_core_fields")
        if not material and changed_fields:
            raise ContractError("非路线变化不得声明 changed_route_core_fields")

    if route_findings and verdict != "ROUTE_REAPPROVAL_REQUIRED":
        raise ContractError("存在路线实质变化时 R1 必须要求重新批准路线")
    if verdict == "ROUTE_REAPPROVAL_REQUIRED" and not route_findings:
        raise ContractError("R1 要求重新批准路线时必须包含路线实质变化 finding")
    if verdict == "SPEC_REVISION_REQUIRED" and (not findings or route_findings):
        raise ContractError("规格修订结论必须包含不影响路线的 finding")
    if verdict == "BLOCKED_MISSING_INPUT" and (not findings or route_findings):
        raise ContractError("缺少输入结论不能携带路线实质变化")
    if verdict == "ACCEPT" and findings:
        raise ContractError("R1 ACCEPT 不得包含未关闭 finding")
    if verdict == "ACCEPT_WITH_MINOR_FIXES" and (not findings or severe or route_findings):
        raise ContractError("R1 小修通过仅允许非路线 P2/P3 finding")


def _validate_r1_v3_coverage(report: dict[str, Any]) -> None:
    """R1 v3 的四态 coverage 必须把未知项交给可追踪的后续裁决。"""
    coverage = report["coverage"]
    findings = report["findings"]
    if coverage["unchecked_items"]:
        raise ContractError("R1 coverage 不得包含 unchecked_items")
    invalid_statuses = sorted(
        {coverage[key] for key in R1_COVERAGE_CHECKS}
        - {"verified", "challenged", "unknown", "not_applicable"}
    )
    if invalid_statuses:
        raise ContractError("R1 v3 coverage 禁止使用旧 pass/fail 状态: " + ", ".join(invalid_statuses))
    finding_checks = {item.get("check_id") for item in findings if item.get("check_id")}
    challenged = {key for key in R1_COVERAGE_CHECKS if coverage[key] == "challenged"}
    unknown = {key for key in R1_COVERAGE_CHECKS if coverage[key] == "unknown"}
    missing = sorted((challenged | unknown) - finding_checks)
    if missing:
        raise ContractError("R1 challenged/unknown 必须有对应 finding: " + ", ".join(missing))
    for finding in findings:
        check_id = finding.get("check_id")
        if check_id is None:
            continue
        if check_id not in R1_REQUIRED_CHECK_IDS:
            raise ContractError(f"R1 finding 使用未知 check_id: {check_id}")
        state = coverage[check_id]
        if state == "challenged" and finding.get("recommended_resolution"):
            raise ContractError("R1 challenged finding 不应伪装为待探查")
        if state == "unknown" and finding.get("recommended_resolution") not in UNRESOLVED_ADJUDICATIONS:
            raise ContractError("R1 unknown 必须声明 needs_probe、needs_second_review 或 needs_human_decision")
        if state in {"verified", "not_applicable"}:
            raise ContractError(f"R1 finding 的 coverage 状态不能为 {state}: {check_id}")
    severe = any(_reviewer_severity(item) in {"P0", "P1"} for item in findings)
    if report["verdict"] == "ACCEPT" and (challenged or unknown or findings):
        raise ContractError("R1 v3 ACCEPT 必须所有检查 verified/not_applicable 且无 finding")
    checklist_external = any(finding.get("check_id") is None for finding in findings)
    if (
        report["verdict"] == "SPEC_REVISION_REQUIRED"
        and not challenged
        and not unknown
        and not checklist_external
    ):
        raise ContractError("R1 v3 规格修订必须有 challenged、unknown 或清单外 finding")
    if report["verdict"] == "BLOCKED_MISSING_INPUT" and not unknown:
        raise ContractError("R1 v3 缺少输入必须至少有 unknown 检查")
    if report["verdict"] == "ACCEPT_WITH_MINOR_FIXES" and (severe or challenged or unknown or not findings):
        raise ContractError("R1 v3 小修通过只允许已解决的非路线 P2/P3 finding")


def _validate_r2_semantics(report: dict[str, Any]) -> None:
    """R2 v3 同时覆盖可复现性、科学正确性和预注册 oracle。"""
    for axis_name, expected in (
        ("execution_reproducibility", R2_EXECUTION_CHECKS),
        ("scientific_correctness", R2_SCIENTIFIC_CHECKS),
    ):
        axis = report[axis_name]
        if set(axis["checks"]) != expected:
            raise ContractError(f"R2 {axis_name} 检查集合不完整")
        statuses = {item["status"] for item in axis["checks"].values()}
        expected_status = (
            "unknown"
            if "unknown" in statuses
            else (
                "challenged"
                if "challenged" in statuses
                else ("not_applicable" if statuses == {"not_applicable"} else "verified")
            )
        )
        if axis["status"] != expected_status:
            raise ContractError(f"R2 {axis_name} 汇总状态与逐项检查不一致")
    oracle_ids = [item["oracle_id"] for item in report["preregistered_oracles"]]
    if len(oracle_ids) != len(set(oracle_ids)):
        raise ContractError("R2 preregistered_oracles 的 oracle_id 必须唯一")
    findings_by_check = {
        item["check_id"]: item for item in report["findings"] if item.get("check_id")
    }
    for axis_name in ("execution_reproducibility", "scientific_correctness"):
        for check_id, check in report[axis_name]["checks"].items():
            finding = findings_by_check.get(check_id)
            if check["status"] in {"challenged", "unknown"} and finding is None:
                raise ContractError(f"R2 {check_id} 未验证但缺少对应 finding")
            if check["status"] == "unknown" and finding.get("recommended_resolution") not in UNRESOLVED_ADJUDICATIONS:
                raise ContractError(f"R2 {check_id}=unknown 必须进入 probe、二审或人工决定")


def _validate_r1_coverage_against_model_spec(
    report: dict[str, Any], request: dict[str, Any], run_dir: Path
) -> None:
    """检查已验证 coverage 是否具有最低结构证据。"""
    model_spec_path = resolve_inside(
        run_dir, request["binding_paths"]["model_spec"], must_exist=True
    )
    model_spec = load_json(model_spec_path)
    require_valid(model_spec, "model_spec")
    checks = {
        "data_and_attachment_mapping": _question_has_data_mapping_evidence,
        "equation_closure": _question_has_equation_closure_evidence,
        "parameter_identifiability": _question_has_identifiability_evidence,
        "stopping_rule": _question_has_stopping_rule_evidence,
        "baseline_design": _question_has_baseline_evidence,
        "model_selection_criterion": _question_has_selection_evidence,
        "uncertainty_quantification": _question_has_uncertainty_evidence,
    }
    for check_id, predicate in checks.items():
        expected_verified = (
            "verified" if report.get("schema_version") == "3.0" else "pass"
        )
        if report["coverage"][check_id] != expected_verified:
            continue
        missing = [
            question["question_id"]
            for question in model_spec["questions"]
            if not predicate(question)
        ]
        if missing:
            raise ContractError(
                f"R1 coverage={check_id}:{expected_verified} 缺少最低结构证据: "
                + ", ".join(missing)
            )
    expected_verified = "verified" if report.get("schema_version") == "3.0" else "pass"
    if report["coverage"]["evidence_plan"] == expected_verified:
        problem_manifest_path = resolve_inside(
            run_dir, request["binding_paths"]["problem_manifest"], must_exist=True
        )
        problem_manifest = load_json(problem_manifest_path)
        require_valid(problem_manifest, "problem_manifest")
        questions = {
            question["question_id"]: question for question in model_spec["questions"]
        }
        missing = []
        for required_question in problem_manifest["questions"]:
            if not required_question["required"]:
                continue
            question_id = required_question["question_id"]
            expected_outputs = {
                item["output_id"] for item in required_question["required_outputs"]
            }
            question = questions.get(question_id)
            if question is None or not _question_has_evidence_plan(
                question, expected_outputs
            ):
                missing.append(question_id)
        if missing:
            raise ContractError(
                f"R1 coverage=evidence_plan:{expected_verified} "
                "缺少必做输出的完整证据映射: "
                + ", ".join(missing)
            )


def _question_text(question: dict[str, Any]) -> str:
    """汇总模型规格中允许承载审核证据的文本字段。"""
    values = [question["objective"], question["algorithm"]]
    values.extend(question["constraints"])
    values.extend(question["validation_plan"])
    values.extend(question["assumptions"])
    return " ".join(values).casefold()


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    """判断文本是否包含任一中英文协议关键词。"""
    return any(term in text for term in terms)


def _r1_evidence(question: dict[str, Any], check_id: str) -> Any:
    """返回单问的结构化 R1 证据；缺失时由对应 coverage 预检拒绝。"""
    return question.get("r1_evidence", {}).get(check_id)


def _question_has_data_mapping_evidence(question: dict[str, Any]) -> bool:
    """源字段、派生公式、单位、来源和异常处理必须形成结构化映射。"""
    evidence = _r1_evidence(question, "data_and_attachment_mapping")
    if not isinstance(evidence, dict):
        return False
    declared = {item["name"] for item in question["variables"]}
    source_fields = evidence.get("source_fields", [])
    derived = evidence.get("derived_variables", [])
    mapped_names = {item.get("variable") for item in source_fields}
    derived_names = {item.get("name") for item in derived}
    has_derived_declaration = bool(derived) or bool(
        evidence.get("no_derived_variables_reason", "").strip()
    )
    return (
        bool(source_fields)
        and mapped_names.issubset(declared)
        and derived_names.issubset(declared)
        and has_derived_declaration
        and bool(evidence.get("missing_and_anomaly_handling", "").strip())
    )


def _question_has_equation_closure_evidence(question: dict[str, Any]) -> bool:
    """方程符号和输出必须闭合到变量表，并声明可计算输出。"""
    evidence = _r1_evidence(question, "equation_closure")
    if not isinstance(evidence, dict):
        return False
    variable_names = {item["name"] for item in question["variables"]}
    declared_symbols = set(evidence.get("declared_symbols", []))
    output_symbols = set(evidence.get("output_symbols", []))
    equations = evidence.get("equations", [])
    equation_text = " ".join(equations)
    return (
        bool(equations)
        and bool(declared_symbols)
        and declared_symbols.issubset(variable_names)
        and bool(output_symbols)
        and output_symbols.issubset(declared_symbols)
        and all(symbol in equation_text for symbol in output_symbols)
    )


def _question_has_stopping_rule_evidence(question: dict[str, Any]) -> bool:
    """停止规则必须区分迭代/解析，并声明失败处理和 fallback。"""
    evidence = _r1_evidence(question, "stopping_rule")
    if not isinstance(evidence, dict):
        return False
    common = bool(evidence.get("failure_handling", "").strip()) and bool(
        evidence.get("fallback", "").strip()
    )
    if evidence.get("mode") == "analytic":
        return common and bool(evidence.get("analytic_solution", "").strip())
    if evidence.get("mode") == "iterative":
        return (
            common
            and isinstance(evidence.get("max_iterations"), int)
            and evidence["max_iterations"] > 0
            and isinstance(evidence.get("tolerance"), (int, float))
            and evidence["tolerance"] > 0
            and bool(evidence.get("convergence_condition", "").strip())
        )
    return False


def _question_has_baseline_evidence(question: dict[str, Any]) -> bool:
    """baseline 必须具名，并固定相同输入、指标和比较口径。"""
    evidence = _r1_evidence(question, "baseline_design")
    if not isinstance(evidence, dict):
        return False
    return all(
        (
            bool(evidence.get("baseline_id", "").strip()),
            bool(evidence.get("input_equivalence", "").strip()),
            bool(evidence.get("metrics")),
            bool(evidence.get("comparison_rule", "").strip()),
        )
    )


def _question_has_evidence_plan(
    question: dict[str, Any], expected_outputs: set[str]
) -> bool:
    """每个必做输出必须唯一映射到实验、图表和论文章节。"""
    plan = _r1_evidence(question, "evidence_plan")
    if not isinstance(plan, list) or not plan:
        return False
    output_ids = [item.get("required_output_id") for item in plan]
    return len(output_ids) == len(set(output_ids)) and set(output_ids) == expected_outputs


def _question_has_identifiability_evidence(question: dict[str, Any]) -> bool:
    """参数、估计/来源、边界和可辨识说明必须同时出现。"""
    text = _question_text(question)
    variables_complete = bool(question["variables"]) and all(
        item.get("name") and item.get("role") and item.get("unit")
        for item in question["variables"]
    )
    return (
        variables_complete
        and _contains_any(text, ("可辨识", "identifi", "jacobian", "条件数"))
        and _contains_any(text, ("估计", "拟合", "优化", "固定", "来源", "estimate", "fit"))
        and _contains_any(text, ("边界", "范围", "约束", "bounded", "<=", ">=", "∈"))
    )


def _question_has_selection_evidence(question: dict[str, Any]) -> bool:
    """模型选择 pass 必须声明准则、比较对象和选择方向或阈值。"""
    text = _question_text(question)
    return (
        _contains_any(
            text,
            (
                "aic",
                "bic",
                "gcv",
                "交叉验证",
                "cross-validation",
                "cross validation",
                "留出",
            ),
        )
        and _contains_any(text, ("比较", "对照", "候选", "baseline", "vs", "versus"))
        and _contains_any(
            text,
            ("最小", "最大", "阈值", "排序", "优于", "改善", "minimum", "maximum", ">=", "<="),
        )
    )


def _question_has_uncertainty_evidence(question: dict[str, Any]) -> bool:
    """不确定性 pass 必须声明方法、输出口径和计算次数或区间口径。"""
    text = _question_text(question)
    return (
        _contains_any(
            text,
            (
                "bootstrap",
                "置信区间",
                "剖面区间",
                "敏感性",
                "误差传播",
                "概率分布",
                "profile interval",
            ),
        )
        and _contains_any(text, ("报告", "输出", "区间", "标准差", "方差", "report", "interval"))
        and (
            _contains_any(text, ("次数", "重采样", "分位数", "计算口径", "samples", "resampling"))
            or any(character.isdigit() for character in text)
        )
    )


def _validate_r5_axes(report: dict[str, Any]) -> None:
    """强制 A/B 双轴、评分阈值和联合结论相互一致。"""
    integrity_pass = report["integrity_axis"]["verdict"] == "A_PASS"
    quality = report["quality_axis"]
    dimensions = quality["dimensions"]
    threshold_pass = report["calibrated_score"] >= 75 and all(
        dimensions[name] >= 60
        for name in ("problem_coverage", "model_depth", "experiment_validation")
    )
    quality_pass = quality["verdict"] in {"B_STRONG", "B_PASS"} and threshold_pass
    expected = {
        (True, True): "FINAL_CANDIDATE",
        (True, False): "QUALITY_REPAIR",
        (False, True): "INTEGRITY_REPAIR",
        (False, False): "FULL_REPAIR",
    }[(integrity_pass, quality_pass)]
    if report["joint_verdict"] != expected:
        raise ContractError(f"R5 联合结论应为 {expected}")
    severe = any(_reviewer_severity(item) in {"P0", "P1"} for item in report["findings"])
    if report["joint_verdict"] == "FINAL_CANDIDATE" and severe:
        raise ContractError("R5 存在 P0/P1 时不能成为 FINAL_CANDIDATE")
    if report["joint_verdict"] == "FINAL_CANDIDATE" and not report["competition_claim_allowed"]:
        raise ContractError("机器校准禁止竞赛质量声明时不能成为 FINAL_CANDIDATE")
    if severe and report.get("competition_claim_allowed"):
        raise ContractError("存在 P0/P1 时不得宣称正式竞赛分数")


def _machine_score_caps(run_dir: Path) -> list[dict[str, Any]]:
    """从冻结问题、逐问验收和 sealed result 推导不可被评审意见覆盖的封顶条件。"""
    manifest_path = run_dir / "problem" / "PROBLEM_MANIFEST.json"
    if not manifest_path.is_file():
        return []
    manifest = load_json(manifest_path)
    required_questions = [item for item in manifest["questions"] if item["required"]]
    caps: list[dict[str, Any]] = []
    missing_questions: list[str] = []
    missing_outputs: list[str] = []
    missing_core: list[str] = []
    missing_baseline: list[str] = []
    missing_robustness: list[str] = []
    model_spec_path = run_dir / "brief" / "model_spec.json"
    model_spec = load_json(model_spec_path) if model_spec_path.is_file() else {"questions": []}
    model_by_question = {item["question_id"]: item for item in model_spec.get("questions", [])}
    registry_path = run_dir / "results" / "result_registry.json"
    registry = load_json(registry_path) if registry_path.is_file() else {"results": []}
    results_by_question: dict[str, list[dict[str, Any]]] = {}
    for item in registry.get("results", []):
        if item.get("status") == "accepted" and item.get("paper_allowed"):
            results_by_question.setdefault(item["question_id"], []).append(item)
    for question in required_questions:
        question_id = question["question_id"]
        acceptance_path = run_dir / "questions" / question_id / "QUESTION_ACCEPTANCE.json"
        if not acceptance_path.is_file():
            missing_questions.append(question_id)
            continue
        acceptance = load_json(acceptance_path)
        checks = acceptance.get("checks", {})
        if acceptance.get("status") != "accepted":
            missing_questions.append(question_id)
        if not checks.get("output_mapping", {}).get("passed", False):
            missing_outputs.extend(
                f"{question_id}:{output['output_id']}" for output in question["required_outputs"]
            )
        if not checks.get("model_output", {}).get("passed", False) or not checks.get("uncertainty", {}).get("passed", False):
            missing_core.append(question_id)
        accepted = results_by_question.get(question_id, [])
        cycles = {item.get("cycle") for item in accepted}
        primary_valid = False
        for result in accepted:
            if result.get("cycle") != "primary" or not result.get("sealed_result_path"):
                continue
            result_path = run_dir / result["sealed_result_path"]
            if not result_path.is_file():
                continue
            sealed = load_json(result_path)
            checks = sealed.get("validation_checks", [])
            if checks and all(item.get("passed", False) for item in checks if isinstance(item, dict)):
                primary_valid = True
        if "baseline" not in cycles or not primary_valid:
            missing_baseline.append(question_id)
        if not ({"robustness", "ablation"} & cycles):
            missing_robustness.append(question_id)
        spec_question = model_by_question.get(question_id, {})
        evidence_outputs = {
            item.get("required_output_id")
            for item in spec_question.get("r1_evidence", {}).get("evidence_plan", [])
        }
        missing_outputs.extend(
            f"{question_id}:{output['output_id']}"
            for output in question["required_outputs"]
            if output["output_id"] not in evidence_outputs
        )
    if missing_questions:
        caps.append({"cap_id": "missing_required_question", "reason": f"缺少必做问题: {', '.join(sorted(set(missing_questions)))}", "maximum_score": 59, "dimension": "problem_coverage", "maximum_dimension": 40})
    if missing_outputs:
        caps.append({"cap_id": "missing_required_output", "reason": f"缺少 required_output: {', '.join(sorted(set(missing_outputs)))}", "maximum_score": 59, "dimension": "problem_coverage", "maximum_dimension": 59})
    if missing_core:
        caps.append({"cap_id": "missing_core_parameter_or_interval", "reason": f"缺少核心参数/区间证据: {', '.join(sorted(set(missing_core)))}", "maximum_score": None, "dimension": "model_depth", "maximum_dimension": 59})
    if missing_baseline:
        caps.append({"cap_id": "missing_fair_baseline_or_validation", "reason": f"缺少公平 baseline 或 primary: {', '.join(sorted(set(missing_baseline)))}", "maximum_score": None, "dimension": "experiment_validation", "maximum_dimension": 59})
    if missing_robustness:
        caps.append({"cap_id": "missing_robustness", "reason": f"缺少 robustness/ablation: {', '.join(sorted(set(missing_robustness)))}", "maximum_score": None, "dimension": "experiment_validation", "maximum_dimension": 69})
    return caps


def _apply_r5_score_calibration(run_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    """保留评审原始分，并让机器封顶后的 calibrated_score 成为唯一正式分数。"""
    normalized = dict(report)
    quality = dict(normalized["quality_axis"])
    raw_dimensions = dict(quality.get("raw_dimensions") or quality.get("dimensions") or {})
    legacy_score = quality.pop("total_score", None)
    raw_score = normalized.get("raw_score", legacy_score)
    if raw_score is None:
        raw_score = sum(raw_dimensions.values()) / max(len(raw_dimensions), 1)
    normalized["score_type"] = "competition_quality"
    normalized["assessment_scope"] = "full_competition_submission"
    normalized["raw_score"] = float(raw_score)
    normalized["score_caps_applied"] = _machine_score_caps(run_dir)
    dimensions = {
        name: float(raw_dimensions.get(name, 0))
        for name in ("problem_coverage", "model_depth", "experiment_validation")
    }
    score_upper = 100.0
    for cap in normalized["score_caps_applied"]:
        if cap.get("dimension"):
            dimensions[cap["dimension"]] = min(dimensions[cap["dimension"]], cap["maximum_dimension"])
        if cap.get("maximum_score") is not None:
            score_upper = min(score_upper, float(cap["maximum_score"]))
    severe = any(
        _reviewer_severity(item) in {"P0", "P1"}
        for item in normalized.get("findings", [])
    )
    if severe:
        normalized["score_caps_applied"].append(
            {
                "cap_id": "unresolved_p0_p1",
                "reason": "存在 P0/P1，校准分不得用于宣称竞赛水平",
                "maximum_score": None,
            }
        )
    audit_path = run_dir / "review" / "FORMAT_AUDIT.json"
    format_blocked = False
    if audit_path.is_file():
        audit = load_json(audit_path)
        if audit.get("hard_failures"):
            format_blocked = True
            normalized["score_caps_applied"].append({"cap_id": "format_hard_failure", "reason": "FORMAT_AUDIT 存在机器硬失败", "maximum_score": None})
    normalized["calibrated_score"] = min(normalized["raw_score"], score_upper)
    normalized["competition_claim_allowed"] = not severe and not format_blocked
    quality["raw_dimensions"] = raw_dimensions
    quality["dimensions"] = dimensions
    if severe:
        quality["verdict"] = "B_WEAK"
    elif normalized["calibrated_score"] >= 85 and all(value >= 75 for value in dimensions.values()):
        quality["verdict"] = "B_STRONG"
    elif normalized["calibrated_score"] >= 75 and all(value >= 60 for value in dimensions.values()):
        quality["verdict"] = "B_PASS"
    elif normalized["calibrated_score"] >= 60:
        quality["verdict"] = "B_WEAK"
    else:
        quality["verdict"] = "B_REBUILD"
    quality["evidence"] = list(quality.get("evidence") or [])
    normalized["quality_axis"] = quality
    if format_blocked:
        integrity = dict(normalized["integrity_axis"])
        integrity["verdict"] = "A_BLOCKED"
        integrity["blockers"] = sorted(
            set([*integrity.get("blockers", []), "FORMAT_AUDIT 机器硬失败"])
        )
        normalized["integrity_axis"] = integrity
    return normalized
