"""审核任务交接、回执绑定和 R5 有界收敛规则。

审核任务只读生产目录，唯一允许写入的位置是 ``review/`` 下与请求绑定的报告和回执。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, resolve_inside, sha256_file
from shumozizi.core.schema import require_valid
from shumozizi.workflow.repair import create_repair_plan
from shumozizi.workflow.review_policy import get_review_stage_policy
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
    "R1_MODELING": {"ACCEPT", "ACCEPT_WITH_FIXES", "REBUILD"},
    "R2_EXPERIMENT": {"REPRODUCIBLE", "REPRODUCIBLE_WITH_WARNINGS", "BLOCKED"},
    "R3_PAPER_LOGIC": {"READY_FOR_COMPREHENSIVE_REVIEW", "MAJOR_REVISION", "NOT_READY"},
    "R4_FORMAT_VISUAL": {"COMPLIANT", "FIX_REQUIRED", "NOT_COMPLIANT"},
    "R5_COMPREHENSIVE": {"A", "B", "C", "D", "E"},
    "J0_FINAL_BLIND_JUDGE": {"PROCEED", "DO_NOT_PROCEED", "ADVISORY"},
}
PASSING_VERDICTS = {
    "R1_MODELING": {"ACCEPT", "ACCEPT_WITH_FIXES"},
    "R2_EXPERIMENT": {"REPRODUCIBLE", "REPRODUCIBLE_WITH_WARNINGS"},
    "R3_PAPER_LOGIC": {"READY_FOR_COMPREHENSIVE_REVIEW"},
    "R4_FORMAT_VISUAL": {"COMPLIANT"},
    "J0_FINAL_BLIND_JUDGE": {"PROCEED", "ADVISORY"},
}


def utc_now() -> str:
    """返回 RFC 3339 UTC 时间。"""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _relative(run_dir: Path, path: Path) -> str:
    """校验路径位于运行目录内并返回 POSIX 相对路径。"""
    try:
        return path.resolve().relative_to(run_dir.resolve()).as_posix()
    except ValueError as exc:
        raise ContractError(f"审核路径越过运行目录边界: {path}") from exc


def _require_current_request_policy(request: dict[str, Any], run_dir: Path) -> None:
    """拒绝调用方削减固定审核材料或伪造源码包角色。"""
    policy = get_review_stage_policy(request["stage"])
    for key, expected in policy.items():
        if request.get(key) != expected:
            raise ContractError(f"审核请求策略字段已被修改: {key}")
    roles = set(request["bindings"])
    mandatory = set(policy["mandatory_inputs"])
    allowed = mandatory | set(policy["optional_inputs"])
    if not mandatory.issubset(roles) or not roles.issubset(allowed):
        raise ContractError("审核请求材料角色不符合当前阶段策略")
    if request["stage"] in {
        "R4_FORMAT_VISUAL",
        "R5_COMPREHENSIVE",
        "J0_FINAL_BLIND_JUDGE",
    }:
        source_report = verify_source_manifest(run_dir)
        if not source_report["valid"]:
            raise ContractError("源码包校验失败: " + "; ".join(source_report["errors"]))
        if request["binding_paths"].get("source_manifest") != SOURCE_MANIFEST_PATH:
            raise ContractError("审核请求未绑定权威 SOURCE_MANIFEST.json")


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
    codex_thread_id: str | None = None,
) -> Path:
    """冻结当前 revision 并创建供新桌面任务领取的只读审核请求。"""
    if stage not in REVIEW_STAGES:
        raise ContractError(f"未知审核阶段: {stage}")
    if stage == "J0_FINAL_BLIND_JUDGE" and any(
        (run_dir / "review" / stage.lower()).glob("*/review_request.json")
    ):
        raise ContractError("J0_FINAL_BLIND_JUDGE 只允许创建一次")
    state = load_json(run_dir / "state.json")
    if state.get("run_id") != run_dir.name:
        raise ContractError("审核请求 run_id 与运行目录不一致")
    if not bindings:
        raise ContractError("审核请求必须绑定至少一个当前产物")
    policy = get_review_stage_policy(stage)
    binding_roles = set(bindings)
    mandatory_roles = set(policy["mandatory_inputs"])
    missing_roles = sorted(mandatory_roles - binding_roles)
    if missing_roles:
        raise ContractError("审核请求缺少阶段强制材料: " + ", ".join(missing_roles))
    allowed_roles = mandatory_roles | set(policy["optional_inputs"])
    unknown_roles = sorted(binding_roles - allowed_roles)
    if unknown_roles:
        raise ContractError("审核请求包含策略未声明的材料角色: " + ", ".join(unknown_roles))
    if stage in {"R4_FORMAT_VISUAL", "R5_COMPREHENSIVE", "J0_FINAL_BLIND_JUDGE"}:
        source_report = verify_source_manifest(run_dir)
        if not source_report["valid"]:
            raise ContractError("源码包校验失败: " + "; ".join(source_report["errors"]))
        source_path = bindings["source_manifest"].resolve()
        if source_path != (run_dir / SOURCE_MANIFEST_PATH).resolve():
            raise ContractError("source_manifest 必须绑定 source/SOURCE_MANIFEST.json")
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
    request = {
        "schema_name": "review_request",
        "schema_version": "2.0",
        "request_id": f"{run_dir.name}-{stage.lower()}-{round_id}",
        "run_id": run_dir.name,
        "stage": stage,
        "question_id": question_id,
        "review_round_id": round_id,
        "state_revision": state["revision"],
        "bindings": hashes,
        "binding_paths": binding_paths,
        "read_paths": normalized_paths,
        **policy,
        "output_path": f"review/{stage.lower()}/{round_id}/review_report.json",
        "skill": REVIEW_STAGES[stage],
        "read_only": True,
        "budget": {
            "max_minutes": max_minutes,
            "max_rounds": 1 if stage == "J0_FINAL_BLIND_JUDGE" else (5 if mode == "training" else 2),
        },
        "requested_at": utc_now(),
    }
    if codex_thread_id is not None:
        if not codex_thread_id.strip():
            raise ContractError("Codex 审核任务 ID 不能为空")
        request["codex_thread_id"] = codex_thread_id.strip()
        request["execution_policy"] = {
            "new_codex_thread": True,
            "subagents_forbidden": True,
            "context_inheritance": False,
        }
    require_valid(request, "review_request")
    request_path = run_dir / "review" / stage.lower() / round_id / "review_request.json"
    atomic_json(request_path, request)
    return request_path


def write_review_report(request_path: Path, report: dict[str, Any]) -> Path:
    """校验并写入审核报告；报告不能写到请求声明之外。"""
    request = load_json(request_path)
    require_valid(request, "review_request")
    required = {"request_id": request["request_id"], "run_id": request["run_id"], "stage": request["stage"], "review_round_id": request["review_round_id"]}
    if any(report.get(key) != value for key, value in required.items()):
        raise ContractError("审核报告未匹配请求的身份字段")
    if report.get("verdict") not in VERDICTS[request["stage"]]:
        raise ContractError("审核结论不属于该阶段枚举")
    require_valid(report, "review_report")
    if request["stage"] == "R5_COMPREHENSIVE":
        _validate_r5_axes(report)
    output = resolve_inside(request_path.parents[3], request["output_path"])
    if output.resolve() != request_path.parent / "review_report.json":
        raise ContractError("审核报告路径必须是请求声明的唯一输出路径")
    atomic_json(output, report)
    return output


def materialize_review_receipt(request_path: Path, report_path: Path, *, decision: str | None = None) -> Path:
    """以请求、报告和当前绑定哈希生成审核回执。"""
    request = load_json(request_path)
    report = load_json(report_path)
    require_valid(request, "review_request")
    require_valid(report, "review_report")
    run_dir = request_path.parents[3]
    _require_current_request_policy(request, run_dir)
    if report["verdict"] not in VERDICTS[request["stage"]]:
        raise ContractError("审核结论不属于该阶段枚举")
    if report["request_id"] != request["request_id"] or report["review_round_id"] != request["review_round_id"]:
        raise ContractError("审核报告与请求不匹配")
    if report["stage"] != request["stage"] or report["run_id"] != request["run_id"]:
        raise ContractError("审核报告身份与请求不匹配")
    if request["stage"] == "R5_COMPREHENSIVE":
        _validate_r5_axes(report)
    actual_bindings = {}
    for name, _expected in request["bindings"].items():
        path = resolve_inside(run_dir, request["binding_paths"][name])
        if path.is_file():
            actual_bindings[name] = sha256_file(path)
        elif name == "state":
            actual_bindings[name] = sha256_file(run_dir / "state.json")
    if actual_bindings != request["bindings"]:
        raise ContractError("审核请求绑定事实已变化")
    passed = _report_passed(report)
    expected_decision = "accepted_with_warnings" if passed and report["findings"] else (
        "accepted" if passed else "rejected"
    )
    if decision is not None and decision != expected_decision:
        raise ContractError("审核 decision 与报告结论不一致")
    repair_plan = None if passed else create_repair_plan(run_dir, report_path)
    receipt = {
        "schema_name": "review_receipt",
        "schema_version": "2.0",
        "run_id": request["run_id"],
        "request_id": request["request_id"],
        "report_sha256": sha256_file(report_path),
        "request_sha256": sha256_file(request_path),
        "state_revision": request["state_revision"],
        "bindings": request["bindings"],
        "decision": decision
        or expected_decision,
        "issued_at": utc_now(),
    }
    if repair_plan is not None:
        receipt["repair_plan_path"] = _relative(run_dir, repair_plan)
        receipt["repair_plan_sha256"] = sha256_file(repair_plan)
    require_valid(receipt, "review_receipt")
    receipt_path = report_path.with_name("review_receipt.json")
    atomic_json(receipt_path, receipt)
    return receipt_path


def verify_review_receipt(
    run_dir: Path, receipt_path: Path, *, require_current_revision: bool = True
) -> dict[str, Any]:
    """验证审核回执、报告、请求和当前 revision 是否仍匹配。"""
    errors: list[str] = []
    try:
        receipt = load_json(receipt_path)
        require_valid(receipt, "review_receipt")
        request_path = receipt_path.with_name("review_request.json")
        report_path = receipt_path.with_name("review_report.json")
        request, report = load_json(request_path), load_json(report_path)
        require_valid(request, "review_request")
        require_valid(report, "review_report")
        _require_current_request_policy(request, run_dir)
        if report["verdict"] not in VERDICTS[request["stage"]]:
            errors.append("审核结论不属于该阶段枚举")
        if request["stage"] == "R5_COMPREHENSIVE":
            _validate_r5_axes(report)
        if receipt["request_sha256"] != sha256_file(request_path):
            errors.append("审核请求哈希不一致")
        if receipt["report_sha256"] != sha256_file(report_path):
            errors.append("审核报告哈希不一致")
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
        if receipt["decision"] != (
            "accepted_with_warnings"
            if _report_passed(report) and report["findings"]
            else ("accepted" if _report_passed(report) else "rejected")
        ):
            errors.append("审核回执 decision 与报告结论不一致")
        if receipt["decision"] == "rejected" and not receipt.get("repair_plan_path"):
            errors.append("审核失败回执缺少 REPAIR_PLAN.json")
        if receipt["decision"] != "rejected" and receipt.get("repair_plan_path"):
            errors.append("通过审核回执不应携带 REPAIR_PLAN.json")
        repair_path = receipt.get("repair_plan_path")
        if repair_path:
            resolved_repair = resolve_inside(run_dir, repair_path, must_exist=True)
            repair = load_json(resolved_repair)
            require_valid(repair, "repair_plan")
            if repair.get("source_report_path") != _relative(run_dir, report_path):
                errors.append("定向修复计划未指向当前审核报告")
            if repair.get("source_report_sha256") != sha256_file(report_path):
                errors.append("定向修复计划来源哈希不一致")
            if receipt.get("repair_plan_sha256") != sha256_file(resolved_repair):
                errors.append("定向修复计划哈希不一致")
    except (ContractError, OSError, KeyError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors, "receipt_path": str(receipt_path)}


def evaluate_r5_convergence(run_dir: Path, *, mode: str = "competition") -> dict[str, Any]:
    """按评级和 P0/P1 规则判断 R5 是否达到人工最终核包门槛。"""
    reports = []
    for path in sorted((run_dir / "review").glob("r5_comprehensive/*/review_report.json")):
        try:
            report = load_json(path)
            require_valid(report, "review_report")
            if report["stage"] == "R5_COMPREHENSIVE":
                reports.append(report)
        except ContractError:
            continue
    max_rounds = 5 if mode == "training" else 2
    good = [
        item
        for item in reports
        if item.get("joint_verdict") == "FINAL_CANDIDATE"
        and item["rating"]["grade"] in {"A", "B"}
        and not any(f["severity"] in {"P0", "P1"} for f in item["findings"])
    ]
    passed = bool(good and good[-1] is reports[-1])
    return {
        "status": "pass" if passed else ("not_ready_for_submission" if len(reports) >= max_rounds else "continue"),
        "rounds": len(reports),
        "max_rounds": max_rounds,
        "passing_rounds": len(good),
        "consecutive_passing_rounds": 1 if passed else 0,
        "requires_human_final_package": passed,
    }


def _report_passed(report: dict[str, Any]) -> bool:
    """依据阶段语义而非 finding 是否为空判断审核是否通过。"""
    if any(item["severity"] in {"P0", "P1"} for item in report["findings"]):
        return False
    if report["stage"] == "R5_COMPREHENSIVE":
        return report.get("joint_verdict") == "FINAL_CANDIDATE"
    if report["stage"] == "J0_FINAL_BLIND_JUDGE":
        severe = any(item["severity"] in {"P0", "P1"} for item in report["findings"])
        return report["verdict"] in PASSING_VERDICTS[report["stage"]] and not severe
    return report["verdict"] in PASSING_VERDICTS[report["stage"]]


def _validate_r5_axes(report: dict[str, Any]) -> None:
    """强制 A/B 双轴、评分阈值和联合结论相互一致。"""
    integrity_pass = report["integrity_axis"]["verdict"] == "A_PASS"
    quality = report["quality_axis"]
    dimensions = quality["dimensions"]
    threshold_pass = quality["total_score"] >= 75 and all(
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
    severe = any(item["severity"] in {"P0", "P1"} for item in report["findings"])
    if report["joint_verdict"] == "FINAL_CANDIDATE" and severe:
        raise ContractError("R5 存在 P0/P1 时不能成为 FINAL_CANDIDATE")
