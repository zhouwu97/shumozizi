"""读取外部 Author 交付物并汇总外部写作状态。

外部 Author 的交付物固定位于 ``paper/external-author/``：

- ``draft.tex``：正文草稿，即使材料有缺口也必须返回；
- ``AUTHOR_NOTE.md``：可选写作说明；
- ``AUTHOR_REQUESTS.json``：可选的上游材料请求。

本模块负责读取、校验与请求决策；Import Audit 在 ``import_audit`` 中完成。
请求决策遵循硬原则：作者请求不会自动变成实验任务。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, relative_inside, sha256_file
from shumozizi.core.schema import require_valid
from shumozizi.simple.authoring import read_authoring
from shumozizi.simple.state import utc_now

EXTERNAL_DIR = Path("paper/external-author")
DRAFT_PATH = EXTERNAL_DIR / "draft.tex"
AUTHOR_NOTE_PATH = EXTERNAL_DIR / "AUTHOR_NOTE.md"
AUTHOR_REQUESTS_PATH = EXTERNAL_DIR / "AUTHOR_REQUESTS.json"
INTERNAL_AUTHOR_REQUESTS_PATH = Path("paper/AUTHOR_REQUESTS.json")
AUTHOR_REQUEST_DECISIONS_PATH = Path("review/author-request-decisions.json")

AUTHOR_REQUEST_KINDS = ("argument_material", "visual", "evidence", "citation", "clarification")
REQUEST_DECISIONS = ("fulfill", "substitute", "waive", "reject")
REQUEST_ROUTES = ("author", "visual", "experiment", "analysis")


def read_external_draft(run_dir: Path) -> dict[str, Any]:
    """读取外部 Author 交付物，并校验其位于运行目录内。

    Args:
        run_dir: 当前运行目录。

    Returns:
        含 ``draft_path``、``draft_text`` 与可选 note/requests 的读取结果。

    Raises:
        ContractError: 缺少 ``draft.tex``，或路径越界。
    """
    root = run_dir.resolve()
    draft = relative_inside(root, root / DRAFT_PATH)
    if not (root / DRAFT_PATH).is_file():
        raise ContractError("外部 Author 尚未返回 draft.tex")
    payload: dict[str, Any] = {
        "draft_path": draft.as_posix(),
        "draft_sha256": sha256_file(root / DRAFT_PATH),
        "draft_text": (root / DRAFT_PATH).read_text(encoding="utf-8"),
    }
    note = root / AUTHOR_NOTE_PATH
    if note.is_file():
        payload["author_note_path"] = relative_inside(root, note).as_posix()
        payload["author_note_sha256"] = sha256_file(note)
        payload["author_note_text"] = note.read_text(encoding="utf-8")
    requests = root / AUTHOR_REQUESTS_PATH
    if requests.is_file():
        payload["author_requests_path"] = relative_inside(root, requests).as_posix()
        payload["author_requests"] = load_json(requests)
    return payload


def external_author_status(run_dir: Path) -> dict[str, Any]:
    """汇总外部 Author 流程的当前状态（authoring + 草稿 + audit 存在性）。"""
    root = run_dir.resolve()
    authoring = read_authoring(root)
    status: dict[str, Any] = {
        "authoring_mode": authoring["authoring_mode"],
        "authoring_status": authoring["authoring_status"],
        "handoff_revision": authoring["handoff_revision"],
        "draft_present": (root / DRAFT_PATH).is_file(),
        "author_note_present": (root / AUTHOR_NOTE_PATH).is_file(),
        "author_requests_present": (root / AUTHOR_REQUESTS_PATH).is_file(),
        "import_audit_present": (root / "review/import-audit.json").is_file(),
        "confirmed_fact_failures_present": (
            root / "review/confirmed-scientific-fact-failures.json"
        ).is_file(),
    }
    audit_path = root / "review/import-audit.json"
    if audit_path.is_file():
        try:
            status["import_audit"] = load_json(audit_path)
        except ContractError:
            status["import_audit"] = None
    return status


def read_author_requests(run_dir: Path) -> list[dict[str, Any]]:
    """读取并校验 ``paper/external-author/AUTHOR_REQUESTS.json`` 的请求清单。

    Args:
        run_dir: 当前运行目录。

    Returns:
        请求对象列表；文件不存在时返回空数组（作者无请求）。

    Raises:
        ContractError: 请求 kind 不在五类范围内。
    """
    root = run_dir.resolve()
    candidates = (root / AUTHOR_REQUESTS_PATH, root / INTERNAL_AUTHOR_REQUESTS_PATH)
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        return []
    payload = load_json(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("requests"), list):
        raise ContractError("AUTHOR_REQUESTS.json 必须是包含 requests 数组的对象")
    for item in payload["requests"]:
        if not isinstance(item, dict) or item.get("kind") not in AUTHOR_REQUEST_KINDS:
            raise ContractError(f"外部作者请求 kind 必须属于 {AUTHOR_REQUEST_KINDS}")
    return payload["requests"]


def _has_scientific_value(request: dict[str, Any], decision: dict[str, Any]) -> bool:
    """判断 evidence/argument 请求是否具有科学价值，决定能否返回实验。

    返回实验的硬前提是：请求能改变科学理解、检验重要机制或解决核心证据缺口。
    visual/citation/clarification 请求永远不能直接变成实验任务。
    """
    if request.get("kind") not in {"evidence", "argument_material"}:
        return False
    return decision.get("scientific_value") in {
        "changes_understanding",
        "tests_mechanism",
        "closes_evidence_gap",
    }


def decide_author_request(
    run_dir: Path,
    decisions_input: list[dict[str, Any]],
) -> dict[str, Any]:
    """对作者请求做出 fulfill/substitute/waive/reject 决策并记录台账。

    硬原则（§16）：``route=experiment`` 不能由作者请求自动触发；只有明确具有
    科学价值（能改变科学理解 / 检验重要机制 / 解决核心证据缺口）才允许返回
    experiment，否则强制回到 author/visual/analysis 或降级处理。

    Args:
        run_dir: 当前运行目录。
        decisions_input: ``[{gap_id, decision, route, reason, scientific_value?}]``。

    Returns:
        已写入的 ``review/author-request-decisions.json`` 台账。

    Raises:
        ContractError: 请求未知、决策非法，或非法路由到 experiment。
    """
    root = run_dir.resolve()
    requests = read_author_requests(root)
    by_gap = {str(item["gap_id"]): item for item in requests}
    if not by_gap:
        raise ContractError("没有待裁决的作者请求")
    resolved: list[dict[str, Any]] = []
    for raw in decisions_input:
        if not isinstance(raw, dict):
            raise ContractError("decisions 每项必须是对象")
        gap_id = str(raw.get("gap_id", ""))
        request = by_gap.get(gap_id)
        if request is None:
            raise ContractError(f"找不到作者请求: {gap_id}")
        decision = raw.get("decision")
        route = raw.get("route", "author")
        reason = raw.get("reason")
        if decision not in REQUEST_DECISIONS:
            raise ContractError(f"{gap_id} 决策不合法: {decision}")
        if route not in REQUEST_ROUTES:
            raise ContractError(f"{gap_id} 路由不合法: {route}")
        if not isinstance(reason, str) or not reason.strip():
            raise ContractError(f"{gap_id} 决策必须记录具体原因")
        if route == "experiment" and not _has_scientific_value(request, raw):
            raise ContractError(
                f"{gap_id}: 请求不能直接返回实验，除非能改变科学理解、检验重要机制"
                "或解决核心证据缺口（需声明 scientific_value）"
            )
        if route == "experiment" and decision != "fulfill":
            raise ContractError(f"{gap_id}: 只有 fulfill 才能返回 experiment")
        resolved.append(
            {
                "gap_id": gap_id,
                "decision": decision,
                "route": route,
                "reason": reason,
                "scientific_value": raw.get("scientific_value"),
            }
        )
    decision_ids = {str(item["gap_id"]) for item in resolved}
    if len(decision_ids) != len(resolved):
        raise ContractError("decisions 中存在重复 gap_id")
    missing = sorted(set(by_gap) - decision_ids)
    unknown = sorted(decision_ids - set(by_gap))
    if missing or unknown:
        detail = []
        if missing:
            detail.append("缺少: " + ", ".join(missing))
        if unknown:
            detail.append("未知: " + ", ".join(unknown))
        raise ContractError("裁决必须覆盖全部作者请求; " + "; ".join(detail))
    document = {
        "schema_name": "author_request_decisions",
        "schema_version": "1.0",
        "run_id": root.name,
        "decisions": resolved,
        "generated_at": utc_now(),
    }
    require_valid(document, "author_request_decisions")
    atomic_json(root / AUTHOR_REQUEST_DECISIONS_PATH, document)
    _advance_authoring_for_requests(root, resolved)
    return document


def _advance_authoring_for_requests(root: Path, decisions: list[dict[str, Any]]) -> None:
    """根据请求裁决推进 authoring_status。

    需要上游新资产（visual/experiment/analysis）时把草稿标为 ``rework_requested``，
    让 Author 知道还有补图/补实验需要消化；纯替代/豁免/驳回不改变状态。
    """
    from shumozizi.simple.authoring import mark_authoring_status, read_authoring

    current = read_authoring(root)["authoring_status"]
    needs_upstream = any(
        item.get("route") in {"visual", "experiment", "analysis"} for item in decisions
    )
    if needs_upstream and current == "draft_imported":
        mark_authoring_status(root, "rework_requested")
