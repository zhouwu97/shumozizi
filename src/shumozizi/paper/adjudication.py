"""对外部稿 PDF 的 Reviewer finding 做独立编辑裁决。

Reviewer 只给出 ``severity_recommendation``；Editorial Adjudicator 确认
``confirmed_severity`` 并决定返修路由。只有 confirmed P0/P1 进入硬阻断。

权限边界（设计文档 §24）：

- 可裁决：argument / visual / writing / layout / citation presentation /
  scientific_support；
- 不可覆盖：``confirmed_scientific_fact_failure``（machine binding 已确认的
  客观事实错误）；
- 不可把 import audit 的客观失败（missing figure file、unknown citation key、
  stale result、wrong formal answer）主观判成"可接受"。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.core.schema import require_valid
from shumozizi.paper.import_audit import AUDIT_PATH, CONFIRMED_FAILURE_PATH

REVIEWER_FINDINGS_PATH = Path("review/paper-reviewer-findings.json")
ADJUDICATION_PATH = Path("review/paper-editorial-adjudication.json")

# Reviewer 的 finding_class 中，只有这些允许 Adjudicator 自由裁决严重性。
ADJUDICABLE_CLASSES = {
    "scientific_support",
    "argument",
    "visual",
    "writing",
    "layout",
    "citation",
}
# 客观失败类别：Adjudicator 不能把它们主观判成可接受。
OBJECTIVE_FINDING_CLASSES = {
    "unknown_figure",
    "unknown_citation",
    "compile_failure",
    "formula_environment",
}


def load_reviewer_findings(run_dir: Path) -> dict[str, Any]:
    """读取并校验 Fresh Reviewer 的 finding 文档。"""
    root = run_dir.resolve()
    path = root / REVIEWER_FINDINGS_PATH
    if not path.is_file():
        raise ContractError("缺少 Fresh Reviewer findings: " + REVIEWER_FINDINGS_PATH.as_posix())
    payload = load_json(path)
    require_valid(payload, "paper_reviewer_findings")
    return payload


def load_confirmed_fact_failures(run_dir: Path) -> list[dict[str, Any]]:
    """读取已确认的科学事实错误（不可申诉类别）。"""
    root = run_dir.resolve()
    path = root / CONFIRMED_FAILURE_PATH
    if not path.is_file():
        return []
    return load_json(path).get("failures", [])


def _audit_objective_failures(run_dir: Path) -> set[str]:
    """返回 import audit 的客观失败 finding_id 集合。"""
    root = run_dir.resolve()
    if not (root / AUDIT_PATH).is_file():
        return set()
    audit = load_json(root / AUDIT_PATH)
    return set(audit.get("objective_failures", []))


def _find_reviewer_finding(findings: list[dict[str, Any]], finding_id: str) -> dict[str, Any]:
    """按 finding_id 在 Reviewer finding 列表中查找。"""
    for item in findings:
        if item.get("finding_id") == finding_id:
            return item
    raise ContractError(f"Reviewer findings 中不存在: {finding_id}")


def _verify_reviewer_freshness(root: Path, reviewer: dict[str, Any]) -> None:
    """复验 Reviewer 当时所读 PDF、论文政策与外部草稿是否仍是当前版本。

    PDF 或草稿变化后，旧 Reviewer findings 不能继续裁决；政策变化同样使
    findings stale。这防止"Reviewer 看 v1、Adjudicator 对 v2 使用 v1 意见"。
    """
    errors: list[str] = []
    pdf_rel = reviewer.get("source_pdf")
    pdf = root / pdf_rel if pdf_rel else None
    if pdf is None or not pdf.is_file() or sha256_file(pdf) != reviewer.get("source_pdf_sha256"):
        errors.append("Reviewer 所读 PDF 已变化或缺失，findings 已 stale")
    from shumozizi.core.repo_root import resolve_repo_root
    from shumozizi.paper.policy import policy_fingerprint

    expected_policy = policy_fingerprint(resolve_repo_root(Path(__file__)), "paper")
    if reviewer.get("paper_policy_fingerprint") != expected_policy:
        errors.append("论文政策指纹已变化，Reviewer findings 已 stale")
    draft_sha = reviewer.get("external_draft_sha256")
    draft = root / "paper/external-author/draft.tex"
    if draft_sha and draft.is_file() and sha256_file(draft) != draft_sha:
        errors.append("外部草稿已变化，Reviewer findings 已 stale")
    if errors:
        raise ContractError("; ".join(errors))


def _validate_decision_bounds(
    reviewer_finding: dict[str, Any],
    raw: dict[str, Any],
    *,
    confirmed_fact_ids: set[str],
    audit_objective_failures: set[str],
) -> str:
    """校验一个裁决是否越过 Adjudicator 的权限边界，返回拒绝原因。"""
    finding_id = str(raw.get("finding_id", ""))
    finding_class = reviewer_finding.get("finding_class")
    decision = raw.get("decision")
    severity = raw.get("confirmed_severity")

    if finding_id in confirmed_fact_ids:
        if decision in {"accept", "waive", "substitute"} or severity not in {"P0", "P1"}:
            return "confirmed scientific fact failure 不可降级或主观接受"
    if finding_id in audit_objective_failures:
        if decision == "accept":
            return "import audit 客观失败不可主观判为可接受"
    if finding_class == "scientific_fact_candidate" and raw.get("confirmed") is True:
        if finding_id not in confirmed_fact_ids:
            return (
                "scientific fact candidate 的确认必须来自 machine binding 或独立复算"
                "（confirmed-scientific-fact-failures.json），不能由 Adjudicator 主观确认"
            )
        if severity not in {"P0", "P1"}:
            return "已确认的科学事实错误只能为 P0/P1"
    if finding_class not in ADJUDICABLE_CLASSES and finding_class != "scientific_fact_candidate":
        return f"finding_class={finding_class} 不可由 Adjudicator 自由裁决"
    return ""


def record_adjudication(
    run_dir: Path,
    decisions_input: list[dict[str, Any]],
) -> dict[str, Any]:
    """记录对全部 Reviewer finding 的编辑裁决。

    Args:
        run_dir: 当前运行目录。
        decisions_input: ``[{finding_id, confirmed, confirmed_severity, route,
            decision, reason}]``。

    Returns:
        已写入的 ``review/paper-editorial-adjudication.json``。

    Raises:
        ContractError: Reviewer findings 缺失、裁决越过权限边界或信息不完整。
    """
    root = run_dir.resolve()
    reviewer = load_reviewer_findings(root)
    _verify_reviewer_freshness(root, reviewer)
    findings = reviewer.get("findings", [])
    if not findings:
        raise ContractError("没有待裁决的 Reviewer finding")
    confirmed_fact_ids = {
        str(item.get("finding_id")) for item in load_confirmed_fact_failures(root)
    }
    audit_objective_failures = _audit_objective_failures(root)

    by_id = {str(item.get("finding_id")): item for item in findings}
    if set(by_id) != {str(raw.get("finding_id", "")) for raw in decisions_input}:
        raise ContractError("裁决必须覆盖全部 Reviewer finding")
    decisions: list[dict[str, Any]] = []
    for raw in decisions_input:
        finding_id = str(raw.get("finding_id", ""))
        reviewer_finding = _find_reviewer_finding(findings, finding_id)
        confirmed = raw.get("confirmed") is True
        severity = raw.get("confirmed_severity")
        route = raw.get("route")
        decision = raw.get("decision")
        reason = raw.get("reason")
        if severity not in {"P0", "P1", "P2", "P3"}:
            raise ContractError(f"{finding_id} confirmed_severity 不合法")
        if route not in {"author", "visual", "experiment", "analysis", "render"}:
            raise ContractError(f"{finding_id} route 不合法")
        if decision not in {"accept", "rework", "substitute", "reject", "waive"}:
            raise ContractError(f"{finding_id} decision 不合法")
        if not isinstance(reason, str) or not reason.strip():
            raise ContractError(f"{finding_id} 裁决必须记录原因")
        rejected = _validate_decision_bounds(
            reviewer_finding,
            raw,
            confirmed_fact_ids=confirmed_fact_ids,
            audit_objective_failures=audit_objective_failures,
        )
        if rejected:
            raise ContractError(f"{finding_id}: {rejected}")
        decisions.append(
            {
                "finding_id": finding_id,
                "confirmed": confirmed,
                "confirmed_severity": severity,
                "route": route,
                "decision": decision,
                "reason": reason,
            }
        )
    document = {
        "schema_name": "paper_editorial_adjudication",
        "schema_version": "1.0",
        "run_id": root.name,
        "source_pdf": reviewer.get("source_pdf", ""),
        "reviewer_findings_sha256": sha256_file(root / REVIEWER_FINDINGS_PATH),
        "decisions": decisions,
        "generated_at": _utc_now(),
    }
    require_valid(document, "paper_editorial_adjudication")
    atomic_json(root / ADJUDICATION_PATH, document)
    _sync_confirmed_p0_p1_to_paper_review(root, reviewer, decisions)
    _advance_authoring_for_adjudication(root, decisions)
    return document


def _advance_authoring_for_adjudication(root: Path, decisions: list[dict[str, Any]]) -> None:
    """根据裁决结果推进 authoring_status。

    存在 confirmed P0/P1 或需要返修的 finding 时标记 ``rework_requested``；
    全部通过则标记 ``author_pass_accepted``，允许进入正式最终编译。
    """
    from shumozizi.simple.authoring import mark_authoring_status, read_authoring

    if read_authoring(root)["authoring_status"] != "draft_imported":
        return
    has_confirmed_p0_p1 = any(
        item.get("confirmed") is True and item.get("confirmed_severity") in {"P0", "P1"}
        for item in decisions
    )
    needs_rework = any(
        item.get("confirmed") is True and item.get("decision") == "rework" for item in decisions
    )
    if has_confirmed_p0_p1 or needs_rework:
        mark_authoring_status(root, "rework_requested")
    else:
        mark_authoring_status(root, "author_pass_accepted")


def _repair_type_for_route(route: str) -> str:
    """把裁决路由映射为 PAPER_REVIEW 的 repair_type。"""
    return {
        "author": "argument",
        "visual": "figure",
        "experiment": "science",
        "analysis": "science",
        "render": "render",
    }[route]


def _sync_confirmed_p0_p1_to_paper_review(
    root: Path,
    reviewer: dict[str, Any],
    decisions: list[dict[str, Any]],
) -> None:
    """把 confirmed P0/P1 裁决合入 PAPER_REVIEW，使现有返修闭环生效。"""
    from shumozizi.paper.paper_review import merge_paper_review_findings

    by_id = {str(item.get("finding_id")): item for item in reviewer.get("findings", [])}
    high_priority = [
        decision
        for decision in decisions
        if decision["confirmed"] and decision["confirmed_severity"] in {"P0", "P1"}
    ]
    if not high_priority:
        return
    review_dir = root / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    findings: list[dict[str, Any]] = []
    for decision in high_priority:
        reviewer_finding = by_id.get(decision["finding_id"], {})
        findings.append(
            {
                "finding_id": decision["finding_id"],
                "severity": decision["confirmed_severity"],
                "finding": reviewer_finding.get("observation", decision["reason"]),
                "impact": reviewer_finding.get("why_it_matters", ""),
                "affected_argument_units": [str(reviewer_finding.get("location", ""))],
                "repair_type": _repair_type_for_route(decision["route"]),
                "target_files": ["paper/external-author/draft.tex"],
                "expected_benefit": reviewer_finding.get("minimum_fix", ""),
                "estimated_cost": "low",
                "acceptance_test": reviewer_finding.get("acceptance_test", ""),
                "stop_condition": "accepted after rework",
                "status": "open",
                "evidence_of_closure": [],
            }
        )
    sync_path = review_dir / "adjudication-p0-p1-sync.json"
    atomic_json(
        sync_path,
        {
            "schema_name": "paper_reviewer_findings_sync",
            "schema_version": "1.0",
            "findings": findings,
        },
    )
    merge_paper_review_findings(
        root,
        input_path="review/adjudication-p0-p1-sync.json",
        source="editorial_adjudication",
    )


def _utc_now() -> str:
    """返回 RFC 3339 UTC 时间。"""
    from shumozizi.simple.state import utc_now

    return utc_now()


def require_paper_editorial_adjudication(run_dir: Path) -> None:
    """要求外部稿的 Reviewer finding 已全部裁决且无未闭合 confirmed P0/P1。

    外部流程门：import audit 无客观失败、无已确认事实错误、Reviewer 全部
    finding 都有裁决记录，且不存在 confirmed P0/P1 未闭合。
    """
    root = run_dir.resolve()
    reviewer = load_reviewer_findings(root)
    findings = reviewer.get("findings", [])
    if not findings:
        return
    adjudication_path = root / ADJUDICATION_PATH
    if not adjudication_path.is_file():
        raise ContractError("Reviewer finding 尚未被 Editorial Adjudicator 裁决")
    adjudication = load_json(adjudication_path)
    adjudicated = {str(item.get("finding_id")) for item in adjudication.get("decisions", [])}
    missing = sorted({str(item.get("finding_id")) for item in findings} - adjudicated)
    if missing:
        raise ContractError("未裁决的 Reviewer finding: " + ", ".join(missing))
    confirmed_fact_ids = {
        str(item.get("finding_id")) for item in load_confirmed_fact_failures(root)
    }
    if confirmed_fact_ids:
        raise ContractError("存在已确认科学事实错误: " + ", ".join(sorted(confirmed_fact_ids)))
    audit_objective_failures = _audit_objective_failures(root)
    if audit_objective_failures:
        raise ContractError(
            "import audit 存在客观失败: " + ", ".join(sorted(audit_objective_failures))
        )
    for decision in adjudication.get("decisions", []):
        if decision.get("confirmed") is True and decision.get("confirmed_severity") in {"P0", "P1"}:
            raise ContractError(
                f"存在未闭合 confirmed {decision['confirmed_severity']} finding: "
                f"{decision['finding_id']}"
            )
