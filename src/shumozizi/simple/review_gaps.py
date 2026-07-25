"""把全面审核后的风险查漏接入不可绕过的放行门。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, load_json, relative_inside, resolve_inside, sha256_file
from shumozizi.simple.review_tasks import validate_review_task_receipt

_GAPS_DIRECTORY = Path("review/gaps")
_SCOPES = {"scientific", "paper"}
_FOLLOW_UP_TYPES = {
    "scientific": "scientific_follow_up",
    "paper": "paper_follow_up",
}


def _required_central_risks(
    run_dir: Path,
    payload: dict[str, Any],
    *,
    scope: str,
    report_file: str,
    report_sha256: str,
    errors: list[str],
) -> set[str]:
    """从显式方法事实和冻结后的强断言推导本轮中央风险。

    未知事实不会伪装成某个具体算法风险，而会成为可见的
    ``method-facts-unknown`` 查漏项；因此它不能在没有专项核验的情况下静默
    让离散近似、代理排序或有限搜索从风险集中消失。
    """
    expected: set[str] = set()
    facts_file = payload.get("method_facts_file")
    facts_sha = payload.get("method_facts_sha256")
    if not isinstance(facts_file, str) or not isinstance(facts_sha, str):
        errors.append("gap 报告必须绑定当前 method_facts 文件及其 SHA")
        return expected
    try:
        facts_path = resolve_inside(run_dir, facts_file, must_exist=True)
        if sha256_file(facts_path) != facts_sha:
            raise ContractError("method_facts SHA 已变化")
        method_facts = load_json(facts_path)
        facts = method_facts.get("facts")
        if method_facts.get("run_id") != run_dir.name or not isinstance(facts, dict):
            raise ContractError("method_facts run_id 或 facts 无效")
    except (ContractError, OSError, TypeError, ValueError) as exc:
        errors.append(f"method_facts 无效: {exc}")
        return expected
    required_names = {
        "uses_continuous_time",
        "uses_discrete_approximation",
        "uses_proxy_objective",
        "uses_heuristic_optimization",
        "candidate_search_limited",
        "uses_temporal_split",
        "has_shared_downstream_dependency",
    }
    for name in sorted(required_names):
        if facts.get(name) not in {True, False, "unknown"}:
            errors.append(f"method_facts 未显式登记 {name}")
        elif facts[name] == "unknown":
            expected.add(f"method-facts-unknown.{name}")
    if facts.get("uses_continuous_time") is True and facts.get("uses_discrete_approximation") is True:
        expected.add("continuous-domain-certificate")
    if facts.get("uses_proxy_objective") is True:
        expected.add("proxy-exact-reversal")
    if facts.get("uses_heuristic_optimization") is True or facts.get("candidate_search_limited") is True:
        expected.add("search-sufficiency")
    if facts.get("uses_temporal_split") is True:
        expected.add("time-leakage")
    if facts.get("has_shared_downstream_dependency") is True:
        expected.add("downstream-inheritance")

    claims_file = payload.get("strong_claims_file")
    claims_sha = payload.get("strong_claims_sha256")
    if not isinstance(claims_file, str) or not isinstance(claims_sha, str):
        errors.append("全面报告冻结后必须提取并绑定 strong_claims，不能省略")
        return expected
    try:
        claims_path = resolve_inside(run_dir, claims_file, must_exist=True)
        if sha256_file(claims_path) != claims_sha:
            raise ContractError("strong_claims SHA 已变化")
        claims_payload = load_json(claims_path)
        if (
            claims_payload.get("schema_name") != "review_strong_claims"
            or claims_payload.get("run_id") != run_dir.name
            or claims_payload.get("scope") != scope
            or claims_payload.get("review_file") != report_file
            or claims_payload.get("review_sha256") != report_sha256
            or not isinstance(claims_payload.get("claims"), list)
        ):
            raise ContractError("strong_claims 未绑定当前全面审核报告")
        if scope == "paper":
            pdf = run_dir / "paper" / "final.pdf"
            if (
                claims_payload.get("paper_pdf_file") != "paper/final.pdf"
                or not pdf.is_file()
                or claims_payload.get("paper_pdf_sha256") != sha256_file(pdf)
            ):
                raise ContractError("paper strong_claims 未绑定当前 final.pdf")
        claims = claims_payload["claims"]
    except (ContractError, OSError, TypeError, ValueError) as exc:
        errors.append(f"strong_claims 无效: {exc}")
        return expected
    claim_to_risk = {
        "continuous_conservative_bound": "continuous-domain-certificate",
        "competitive_search": "search-sufficiency",
        "proxy_exact_equivalence": "proxy-exact-reversal",
        "all_actions_material": "action-activation",
        "shared_downstream_validity": "downstream-inheritance",
        "temporal_generalization": "time-leakage",
    }
    for claim in claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("claim_type"), str):
            errors.append("strong_claims 含未结构化 claim_type")
            continue
        risk = claim_to_risk.get(claim["claim_type"])
        if risk is not None:
            expected.add(risk)
    return expected


def _report_reference(run_dir: Path, review_report: dict[str, Any]) -> tuple[str, str]:
    """返回全面审核报告的规范路径及当前哈希。

    Args:
        run_dir: 当前运行目录。
        review_report: 审核摘要中的 ``report`` 引用，或等价的最小引用。

    Returns:
        报告相对路径和当前 SHA-256。

    Raises:
        ContractError: 审核报告缺失、越界或结构不合法。
    """
    report = review_report.get("report", review_report)
    if not isinstance(report, dict) or not isinstance(report.get("file"), str):
        raise ContractError("全面审核缺少结构化 report.file")
    path = resolve_inside(run_dir, report["file"], must_exist=True)
    return relative_inside(run_dir, path).as_posix(), sha256_file(path)


def _matching_gap_reports(
    run_dir: Path, *, scope: str, report_file: str, report_sha256: str
) -> list[tuple[Path, dict[str, Any]]]:
    """找出绑定当前报告内容的 gap 报告，禁止复用旧轮次。"""
    directory = run_dir / _GAPS_DIRECTORY
    if not directory.is_dir():
        return []
    matches: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(directory.glob("round-*.json")):
        try:
            payload = load_json(path)
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        if (
            payload.get("scope") == scope
            and payload.get("review_file") == report_file
            and payload.get("review_sha256") == report_sha256
        ):
            matches.append((path, payload))
    return matches


def _require_text(item: dict[str, Any], key: str, *, label: str, errors: list[str]) -> str | None:
    """要求非空文本字段，并把协议错误累积到当前验证结果。"""
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} 缺少 {key}")
        return None
    return value


def _validate_attacked_risk(
    run_dir: Path,
    item: dict[str, Any],
    *,
    report_file: str,
    errors: list[str],
) -> None:
    """验证风险确有执行攻击，而非仅在报告里出现关键词。"""
    risk_id = item.get("risk_id", "<unknown>")
    _require_text(item, "attack_performed", label=str(risk_id), errors=errors)
    _require_text(item, "conclusion", label=str(risk_id), errors=errors)
    locations = item.get("evidence_locations")
    if not isinstance(locations, list) or not locations or not all(
        isinstance(value, str) and value.startswith(report_file) for value in locations
    ):
        errors.append(f"{risk_id} 的 evidence_locations 必须定位到当前全面审核报告")
    evidence_files = item.get("evidence_files")
    if not isinstance(evidence_files, list) or not evidence_files:
        errors.append(f"{risk_id} 缺少实际执行 evidence_files")
        return
    for evidence_file in evidence_files:
        if not isinstance(evidence_file, str):
            errors.append(f"{risk_id} 的 evidence_files 含非路径值")
            continue
        try:
            path = resolve_inside(run_dir, evidence_file, must_exist=True)
            if not path.is_file() or path.stat().st_size == 0:
                raise ContractError("证据文件为空")
        except (ContractError, OSError, ValueError) as exc:
            errors.append(f"{risk_id} 的执行证据无效: {exc}")


def _primary_task_context(
    review_report: dict[str, Any], errors: list[str]
) -> tuple[str | None, str | None]:
    """返回主审核任务 ID 与线程，用于专项任务的父子及 fresh 校验。"""
    reference = review_report.get("task_receipt")
    reviewer = review_report.get("reviewer")
    task_id = reference.get("task_id") if isinstance(reference, dict) else None
    thread_id = reviewer.get("thread_id") if isinstance(reviewer, dict) else None
    if not isinstance(task_id, str) or not task_id:
        errors.append("全面审核摘要缺少 task_receipt.task_id")
        task_id = None
    if not isinstance(thread_id, str) or not thread_id:
        errors.append("全面审核摘要缺少 reviewer.thread_id")
        thread_id = None
    return task_id, thread_id


def _validate_special_task(
    run_dir: Path,
    special: dict[str, Any],
    *,
    scope: str,
    parent_task_id: str | None,
    primary_thread_id: str | None,
    report_file: str,
    report_sha256: str,
    input_key: str,
    input_id: str,
    seen_threads: set[str],
    errors: list[str],
) -> None:
    """验证一个针对风险或 finding 的独立专项审核及其修复证据。"""
    label = f"专项 {input_key}={input_id}"
    receipt_file = _require_text(special, "task_receipt", label=label, errors=errors)
    target_report = _require_text(special, "report_file", label=label, errors=errors)
    target_sha = _require_text(special, "report_sha256", label=label, errors=errors)
    if not receipt_file or not target_report or not target_sha or parent_task_id is None:
        return
    try:
        target = resolve_inside(run_dir, target_report, must_exist=True)
        if sha256_file(target) != target_sha:
            raise ContractError("专项报告哈希不匹配")
        receipt = validate_review_task_receipt(
            run_dir,
            receipt_file,
            expected_type=_FOLLOW_UP_TYPES[scope],
            expected_report=target_report,
            expected_input_bindings={
                "review_report": {"file": report_file, "sha256": report_sha256},
                input_key: input_id,
            },
            expected_parent_task_id=parent_task_id,
            require_fresh_thread=True,
        )
        thread_id = receipt["thread_id"]
        if thread_id == primary_thread_id or thread_id in seen_threads:
            raise ContractError("专项审核未使用不同的 fresh thread")
        seen_threads.add(thread_id)
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        errors.append(f"{label} 无效: {exc}")


def _validate_findings(
    run_dir: Path,
    payload: dict[str, Any],
    *,
    scope: str,
    parent_task_id: str | None,
    primary_thread_id: str | None,
    report_file: str,
    report_sha256: str,
    seen_threads: set[str],
    errors: list[str],
) -> None:
    """要求所有阻断 P2 都逐项绑定恢复条件与独立闭合证据。"""
    findings = payload.get("findings", [])
    closures = payload.get("closures", [])
    if not isinstance(findings, list) or not isinstance(closures, list):
        errors.append("gap 报告的 findings 或 closures 不是数组")
        return
    blocking: dict[str, dict[str, Any]] = {}
    for finding in findings:
        if not isinstance(finding, dict):
            errors.append("findings 含非对象")
            continue
        finding_id = finding.get("finding_id")
        if not isinstance(finding_id, str) or not finding_id:
            errors.append("finding 缺少 finding_id")
            continue
        if finding.get("severity") in {"P0", "P1"} and finding.get("blocking") is True:
            errors.append(f"{finding_id} 是未解决的 blocking {finding.get('severity')}")
        if finding.get("severity") == "P2" and finding.get("blocking") is True:
            if not isinstance(finding.get("recovery_condition"), str) or not finding["recovery_condition"].strip():
                errors.append(f"{finding_id} 缺少 recovery_condition")
            blocking[finding_id] = finding
    closure_by_id: dict[str, dict[str, Any]] = {}
    for closure in closures:
        if not isinstance(closure, dict) or not isinstance(closure.get("finding_id"), str):
            errors.append("closure 缺少 finding_id")
            continue
        finding_id = closure["finding_id"]
        if finding_id in closure_by_id:
            errors.append(f"finding {finding_id} 有重复 closure")
        closure_by_id[finding_id] = closure
        if finding_id not in blocking:
            errors.append(f"closure 试图关闭不存在或非 blocking 的 finding: {finding_id}")
            continue
        finding = blocking[finding_id]
        if closure.get("status") != "closed":
            errors.append(f"{finding_id} 尚未 closed")
            continue
        if closure.get("recovery_condition") != finding.get("recovery_condition"):
            errors.append(f"{finding_id} 的 closure 未绑定原恢复条件")
        repaired_files = closure.get("repaired_files")
        if not isinstance(repaired_files, list) or not repaired_files:
            errors.append(f"{finding_id} 缺少 repaired_files")
        else:
            for repaired_file in repaired_files:
                try:
                    resolve_inside(run_dir, repaired_file, must_exist=True)
                except (ContractError, OSError, TypeError, ValueError) as exc:
                    errors.append(f"{finding_id} 的 repaired_file 无效: {exc}")
        _validate_special_task(
            run_dir,
            closure,
            scope=scope,
            parent_task_id=parent_task_id,
            primary_thread_id=primary_thread_id,
            report_file=report_file,
            report_sha256=report_sha256,
            input_key="finding_id",
            input_id=finding_id,
            seen_threads=seen_threads,
            errors=errors,
        )
    missing = sorted(set(blocking) - set(closure_by_id))
    if missing:
        errors.append("所有 blocking P2 必须逐项关闭: " + ", ".join(missing))


def verify_review_gap_completion(
    run_dir: Path,
    *,
    scope: str,
    review_report: dict[str, Any],
) -> dict[str, Any]:
    """验证当前全面审核后的查漏、专项复审与逐项 P2 闭合。

    该函数只接受结构化 ``attacked`` 记录：关键词出现、否定性提及或报告中的
    泛泛结论都不能把风险视作已覆盖。它在科学审核、PDF 盲审和最终完成状态中
    复用，从而避免导入后再绕开查漏门。

    Args:
        run_dir: 当前运行目录。
        scope: ``scientific`` 或 ``paper``。
        review_report: 已导入或待导入的全面审核摘要。

    Returns:
        含 ``allowed``、``reason``、``errors`` 和已绑定 gap 文件的结果。
    """
    if scope not in _SCOPES:
        return {"allowed": False, "reason": f"未知 gap scope: {scope}", "errors": []}
    try:
        report_file, report_sha256 = _report_reference(run_dir, review_report)
    except (ContractError, OSError, TypeError, ValueError) as exc:
        return {"allowed": False, "reason": str(exc), "errors": [str(exc)]}
    matches = _matching_gap_reports(
        run_dir,
        scope=scope,
        report_file=report_file,
        report_sha256=report_sha256,
    )
    if not matches:
        reason = "缺少绑定当前全面审核报告的 review/gaps/round-N.json"
        return {"allowed": False, "reason": reason, "errors": [reason]}
    if len(matches) > 1:
        reason = "同一全面审核报告存在多个 gap 轮次，必须明确清理并重新生成"
        return {"allowed": False, "reason": reason, "errors": [reason]}
    gap_path, payload = matches[0]
    errors: list[str] = []
    if payload.get("schema_name") != "review_gap_report" or payload.get("schema_version") != "1.0":
        errors.append("gap 报告 schema_name 或 schema_version 不合法")
    if payload.get("run_id") != run_dir.name:
        errors.append("gap 报告 run_id 不匹配")
    expected_central = _required_central_risks(
        run_dir,
        payload,
        scope=scope,
        report_file=report_file,
        report_sha256=report_sha256,
        errors=errors,
    )
    risks = payload.get("risks")
    if not isinstance(risks, list):
        errors.append("gap 报告缺少 risks 数组")
        risks = []
    seen_risks: set[str] = set()
    parent_task_id, primary_thread_id = _primary_task_context(review_report, errors)
    seen_threads: set[str] = set()
    if primary_thread_id is not None:
        seen_threads.add(primary_thread_id)
    for item in risks:
        if not isinstance(item, dict):
            errors.append("risks 含非对象")
            continue
        risk_id = item.get("risk_id")
        if not isinstance(risk_id, str) or not risk_id:
            errors.append("风险缺少 risk_id")
            continue
        if risk_id in seen_risks:
            errors.append(f"风险重复: {risk_id}")
            continue
        seen_risks.add(risk_id)
        status = item.get("coverage_status")
        if status == "attacked":
            _validate_attacked_risk(
                run_dir, item, report_file=report_file, errors=errors
            )
        elif status == "uncovered":
            special = item.get("special_review")
            if not isinstance(special, dict):
                errors.append(f"{risk_id} 未覆盖且缺少专项审核")
            else:
                _validate_special_task(
                    run_dir,
                    special,
                    scope=scope,
                    parent_task_id=parent_task_id,
                    primary_thread_id=primary_thread_id,
                    report_file=report_file,
                    report_sha256=report_sha256,
                    input_key="risk_id",
                    input_id=risk_id,
                    seen_threads=seen_threads,
                    errors=errors,
                )
                if special.get("resolution") == "blocked":
                    errors.append(f"{risk_id} 的专项审核明确阻断，不能放行")
                elif special.get("resolution") != "repaired":
                    errors.append(f"{risk_id} 的专项审核未给出 repaired 或 blocked 结论")
                else:
                    repaired_files = special.get("repaired_files")
                    if not isinstance(repaired_files, list) or not repaired_files:
                        errors.append(f"{risk_id} 的 repaired 专项审核缺少 repaired_files")
                    else:
                        for repaired_file in repaired_files:
                            try:
                                resolve_inside(run_dir, repaired_file, must_exist=True)
                            except (ContractError, OSError, TypeError, ValueError) as exc:
                                errors.append(f"{risk_id} 的 repaired_file 无效: {exc}")
        else:
            errors.append(f"{risk_id} 的 coverage_status 必须是 attacked 或 uncovered")
    missing_central = sorted(expected_central - seen_risks)
    if missing_central:
        errors.append("以下中央风险未进入 gap 查漏: " + ", ".join(missing_central))
    _validate_findings(
        run_dir,
        payload,
        scope=scope,
        parent_task_id=parent_task_id,
        primary_thread_id=primary_thread_id,
        report_file=report_file,
        report_sha256=report_sha256,
        seen_threads=seen_threads,
        errors=errors,
    )
    return {
        "allowed": not errors,
        "reason": "；".join(errors),
        "errors": errors,
        "gap_file": relative_inside(run_dir, gap_path).as_posix(),
        "gap_sha256": sha256_file(gap_path),
    }


def record_targeted_closure(
    run_dir: Path,
    *,
    scope: str,
    review_report: dict[str, Any],
    finding_id: str,
    closure: dict[str, Any],
) -> Path:
    """记录一个已存在 blocking P2 的逐项闭合，拒绝虚构或重复 ID。

    写入后不会把整轮自动标记为通过；调用方仍必须通过
    :func:`verify_review_gap_completion`，因此同一报告中的其他 blocking P2
    仍会继续阻断放行。

    Args:
        run_dir: 当前运行目录。
        scope: ``scientific`` 或 ``paper``。
        review_report: 当前全面审核摘要。
        finding_id: 原全面审核中已登记的 blocking P2 ID。
        closure: 此 finding 独有的修复、专项报告和回执绑定。

    Returns:
        被更新的 gap 报告路径。

    Raises:
        ContractError: finding 不存在、非阻断 P2、重复闭合或恢复条件漂移。
    """
    report_file, report_sha256 = _report_reference(run_dir, review_report)
    matches = _matching_gap_reports(
        run_dir, scope=scope, report_file=report_file, report_sha256=report_sha256
    )
    if len(matches) != 1:
        raise ContractError("记录 P2 闭合前必须恰有一个绑定当前全面审核的 gap 报告")
    path, payload = matches[0]
    findings = {
        item.get("finding_id"): item
        for item in payload.get("findings", [])
        if isinstance(item, dict) and isinstance(item.get("finding_id"), str)
    }
    finding = findings.get(finding_id)
    if not isinstance(finding, dict):
        raise ContractError(f"不能关闭不存在的 finding ID: {finding_id}")
    if finding.get("severity") != "P2" or finding.get("blocking") is not True:
        raise ContractError(f"finding {finding_id} 不是 blocking P2")
    if not isinstance(closure, dict) or closure.get("finding_id") != finding_id:
        raise ContractError("closure 必须绑定目标 finding_id")
    if closure.get("recovery_condition") != finding.get("recovery_condition"):
        raise ContractError("closure 的 recovery_condition 必须与原 finding 逐字一致")
    if any(
        isinstance(item, dict) and item.get("finding_id") == finding_id
        for item in payload.get("closures", [])
    ):
        raise ContractError(f"finding {finding_id} 已有闭合记录，不能覆盖旧证据")
    payload.setdefault("closures", []).append(closure)
    from shumozizi.core.io import atomic_json

    atomic_json(path, payload)
    return path
