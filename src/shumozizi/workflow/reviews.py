"""审核任务交接、回执绑定和 R5 有界收敛规则。

审核任务只读生产目录，唯一允许写入的位置是 ``review/`` 下与请求绑定的报告和回执。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, resolve_inside, sha256_file
from shumozizi.core.schema import require_valid

REVIEW_STAGES = {
    "R1_MODELING": "mathmodel-review/r1-modeling",
    "R2_EXPERIMENT": "mathmodel-review/r2-experiment",
    "R3_PAPER_LOGIC": "mathmodel-review/r3-paper-logic",
    "R4_FORMAT_VISUAL": "mathmodel-review/r4-format-visual",
    "R5_COMPREHENSIVE": "mathmodel-review/r5-comprehensive",
}
VERDICTS = {
    "R1_MODELING": {"ACCEPT", "ACCEPT_WITH_FIXES", "REBUILD"},
    "R2_EXPERIMENT": {"REPRODUCIBLE", "REPRODUCIBLE_WITH_WARNINGS", "BLOCKED"},
    "R3_PAPER_LOGIC": {"READY_FOR_COMPREHENSIVE_REVIEW", "MAJOR_REVISION", "NOT_READY"},
    "R4_FORMAT_VISUAL": {"COMPLIANT", "FIX_REQUIRED", "NOT_COMPLIANT"},
    "R5_COMPREHENSIVE": {"A", "B", "C", "D", "E"},
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
    state = load_json(run_dir / "state.json")
    if state.get("run_id") != run_dir.name:
        raise ContractError("审核请求 run_id 与运行目录不一致")
    if not bindings:
        raise ContractError("审核请求必须绑定至少一个当前产物")
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
        "output_path": f"review/{stage.lower()}/{round_id}/review_report.json",
        "skill": REVIEW_STAGES[stage],
        "read_only": True,
        "budget": {"max_minutes": max_minutes, "max_rounds": 5 if mode == "training" else 3},
        "requested_at": utc_now(),
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
    if report["request_id"] != request["request_id"] or report["review_round_id"] != request["review_round_id"]:
        raise ContractError("审核报告与请求不匹配")
    actual_bindings = {}
    run_dir = request_path.parents[3]
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
        "schema_version": "2.0",
        "run_id": request["run_id"],
        "request_id": request["request_id"],
        "report_sha256": sha256_file(report_path),
        "request_sha256": sha256_file(request_path),
        "state_revision": request["state_revision"],
        "bindings": request["bindings"],
        "decision": decision or ("accepted_with_warnings" if report["findings"] else "accepted"),
        "issued_at": utc_now(),
    }
    require_valid(receipt, "review_receipt")
    receipt_path = report_path.with_name("review_receipt.json")
    atomic_json(receipt_path, receipt)
    return receipt_path


def verify_review_receipt(run_dir: Path, receipt_path: Path) -> dict[str, Any]:
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
        if receipt["request_sha256"] != sha256_file(request_path):
            errors.append("审核请求哈希不一致")
        if receipt["report_sha256"] != sha256_file(report_path):
            errors.append("审核报告哈希不一致")
        for name, expected in request["bindings"].items():
            bound_path = resolve_inside(run_dir, request["binding_paths"][name], must_exist=True)
            if sha256_file(bound_path) != expected:
                errors.append(f"审核绑定事实已变化: {name}")
        state = load_json(run_dir / "state.json")
        if state["revision"] != receipt["state_revision"]:
            errors.append("作者修复后旧审核回执已失效")
        if request["bindings"] != receipt["bindings"]:
            errors.append("审核回执绑定与请求不一致")
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
    max_rounds = 5 if mode == "training" else 3
    good = [item for item in reports if item["rating"]["grade"] in {"A", "B"} and not any(f["severity"] in {"P0", "P1"} for f in item["findings"])]
    consecutive = len(good) >= 2 and all(item in good for item in reports[-2:]) if len(reports) >= 2 else False
    return {
        "status": "pass" if consecutive else ("not_ready_for_submission" if len(reports) >= max_rounds else "continue"),
        "rounds": len(reports),
        "max_rounds": max_rounds,
        "passing_rounds": len(good),
        "consecutive_passing_rounds": 2 if consecutive else 0,
        "requires_human_final_package": consecutive,
    }
