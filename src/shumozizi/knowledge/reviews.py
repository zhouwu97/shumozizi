"""Paper Card 知识审核请求、独立会话领取与线程唯一性复验。"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shumozizi.core.io import (
    ContractError,
    load_json,
    relative_inside,
    resolve_inside,
    sha256_bytes,
    sha256_file,
)
from shumozizi.knowledge.papers import read_paper_card


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} 必须是非空字符串")
    return value


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ContractError(f"{field} 不是有效 SHA-256")
    return value


def _exclusive_json(path: Path, payload: dict[str, Any]) -> None:
    """独占创建审核身份产物，禁止并发领取覆盖。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise ContractError(f"独占文件已存在: {path}") from exc


def _request_root(request_path: Path) -> Path:
    resolved = request_path.resolve()
    if len(resolved.parents) < 5:
        raise ContractError("knowledge review request 路径层级无效")
    root = resolved.parents[4]
    expected = root / "knowledge/reviews/requests" / resolved.parent.name / resolved.name
    if resolved != expected.resolve() or resolved.name != "knowledge_review_request.json":
        raise ContractError("knowledge_review_request.json 路径无效")
    return root


def _thread_claim_path(repo_root: Path, thread_id: str) -> Path:
    digest = sha256_bytes(thread_id.encode("utf-8"))
    return repo_root / "knowledge/reviews/claims" / f"{digest}.json"


def _validate_request(document: dict[str, Any]) -> None:
    if document.get("schema_name") != "knowledge_review_request" or document.get(
        "schema_version"
    ) != "1.0":
        raise ContractError("无效 knowledge_review_request")
    for field in (
        "request_id",
        "paper_id",
        "authoring_session_id",
        "card_path",
        "evidence_map_path",
        "output_path",
        "requested_at",
    ):
        _require_string(document.get(field), field)
    for field in ("card_sha256", "evidence_map_sha256", "source_asset_sha256"):
        _require_sha256(document.get(field), field)
    expected_policy = {
        "new_thread": True,
        "subagent": False,
        "forked": False,
        "context_inherited": False,
    }
    if document.get("required_execution_policy") != expected_policy:
        raise ContractError("知识审核请求未强制全新顶层独立任务")
    if document.get("read_only") is not True:
        raise ContractError("知识审核请求必须只读")


def _validate_session(document: dict[str, Any]) -> None:
    if document.get("schema_name") != "knowledge_review_session" or document.get(
        "schema_version"
    ) != "1.0":
        raise ContractError("无效 knowledge_review_session")
    for field in (
        "session_id",
        "request_id",
        "paper_id",
        "authoring_session_id",
        "reviewer_identity",
        "attestation_level",
        "claimed_at",
        "started_at",
    ):
        _require_string(document.get(field), field)
    for field in ("request_sha256", "card_sha256", "evidence_map_sha256"):
        _require_sha256(document.get(field), field)
    executor = document.get("executor")
    if not isinstance(executor, dict):
        raise ContractError("knowledge review executor 无效")
    if executor != {
        "platform": "codex_desktop",
        "thread_id": executor.get("thread_id"),
        "task_kind": "top_level",
        "parent_thread_id": None,
    }:
        raise ContractError("知识审核 executor 必须是独立顶层 Codex 任务")
    _require_string(executor.get("thread_id"), "thread_id")
    expected_policy = {
        "new_thread": True,
        "subagent": False,
        "forked": False,
        "context_inherited": False,
    }
    if document.get("execution_policy") != expected_policy:
        raise ContractError("知识审核 session 未满足独立上下文策略")


def create_knowledge_review_request(repo_root: Path, paper_id: str) -> Path:
    """为一张 Card v2 冻结只读知识审核请求。"""
    root = repo_root.resolve()
    card_path = resolve_inside(
        root, f"knowledge/cards/papers/{paper_id}.md", must_exist=True
    )
    evidence_path = resolve_inside(
        root, f"knowledge/reviews/evidence_maps/{paper_id}.json", must_exist=True
    )
    card = read_paper_card(card_path)
    metadata = card["metadata"]
    if metadata.get("paper_id") != paper_id or str(metadata.get("card_version")) != "2.0":
        raise ContractError("知识审核请求只接受指定 Paper Card v2")
    authoring_session_id = _require_string(
        metadata.get("authoring_session_id"), "authoring_session_id"
    )
    source_asset_sha256 = _require_sha256(
        metadata.get("source_asset_sha256"), "source_asset_sha256"
    )
    card_sha256 = sha256_file(card_path)
    evidence_sha256 = sha256_file(evidence_path)
    request = {
        "schema_name": "knowledge_review_request",
        "schema_version": "1.0",
        "request_id": f"knowledge-{paper_id}-{card_sha256[:12]}",
        "paper_id": paper_id,
        "authoring_session_id": authoring_session_id,
        "card_path": relative_inside(root, card_path).as_posix(),
        "card_sha256": card_sha256,
        "evidence_map_path": relative_inside(root, evidence_path).as_posix(),
        "evidence_map_sha256": evidence_sha256,
        "source_asset_sha256": source_asset_sha256,
        "required_execution_policy": {
            "new_thread": True,
            "subagent": False,
            "forked": False,
            "context_inherited": False,
        },
        "output_path": f"knowledge/reviews/reports/{paper_id}.json",
        "read_only": True,
        "requested_at": _utc_now(),
    }
    _validate_request(request)
    path = root / f"knowledge/reviews/requests/{paper_id}/knowledge_review_request.json"
    _exclusive_json(path, request)
    return path


def claim_knowledge_review_request(
    request_path: Path,
    *,
    thread_id: str,
    reviewer_identity: str,
    attestation_level: str = "self_declared",
) -> Path:
    """由全新顶层任务独占领取一份知识审核请求。"""
    root = _request_root(request_path)
    request = load_json(request_path)
    _validate_request(request)
    normalized_thread = _require_string(thread_id, "thread_id").strip()
    reviewer = _require_string(reviewer_identity, "reviewer_identity").strip()
    if attestation_level != "self_declared":
        raise ContractError("当前接口只能生成 self_declared attestation")
    if normalized_thread == request["authoring_session_id"]:
        raise ContractError("论文卡制作与知识审核必须使用不同顶层任务")
    session_path = request_path.with_name("knowledge_review_session.json")
    if session_path.exists():
        raise ContractError("同一 knowledge review request 只能领取一次")
    report_path = resolve_inside(root, request["output_path"])
    if report_path.exists():
        raise ContractError("已有审核报告的 request 不能补领 session")
    claim_path = _thread_claim_path(root, normalized_thread)
    if claim_path.exists():
        raise ContractError("同一 thread_id 只能领取一个知识审核请求")
    for existing in (root / "knowledge/reviews/requests").glob(
        "*/knowledge_review_session.json"
    ):
        if load_json(existing).get("executor", {}).get("thread_id") == normalized_thread:
            raise ContractError("同一 thread_id 只能领取一个知识审核请求")
    timestamp = _utc_now()
    session = {
        "schema_name": "knowledge_review_session",
        "schema_version": "1.0",
        "session_id": f"{request['request_id']}-{sha256_bytes(normalized_thread.encode('utf-8'))[:12]}",
        "request_id": request["request_id"],
        "paper_id": request["paper_id"],
        "authoring_session_id": request["authoring_session_id"],
        "reviewer_identity": reviewer,
        "executor": {
            "platform": "codex_desktop",
            "thread_id": normalized_thread,
            "task_kind": "top_level",
            "parent_thread_id": None,
        },
        "execution_policy": dict(request["required_execution_policy"]),
        "attestation_level": attestation_level,
        "request_sha256": sha256_file(request_path),
        "card_sha256": request["card_sha256"],
        "evidence_map_sha256": request["evidence_map_sha256"],
        "claimed_at": timestamp,
        "started_at": timestamp,
    }
    _validate_session(session)
    _exclusive_json(session_path, session)
    claim = {
        "schema_name": "knowledge_review_thread_claim",
        "schema_version": "1.0",
        "thread_id": normalized_thread,
        "paper_id": request["paper_id"],
        "request_id": request["request_id"],
        "request_path": relative_inside(root, request_path).as_posix(),
        "request_sha256": sha256_file(request_path),
        "session_path": relative_inside(root, session_path).as_posix(),
        "session_sha256": sha256_file(session_path),
        "claimed_at": timestamp,
    }
    try:
        _exclusive_json(claim_path, claim)
    except ContractError:
        session_path.unlink()
        raise
    return session_path


def verify_knowledge_review_session(
    repo_root: Path, request_path: Path, session_path: Path
) -> dict[str, Any]:
    """复验请求、session、线程 claim 和当前卡片证据绑定。"""
    root = repo_root.resolve()
    errors: list[str] = []
    try:
        if _request_root(request_path) != root:
            raise ContractError("knowledge review request 不属于当前仓库")
        request = load_json(request_path)
        session = load_json(session_path)
        _validate_request(request)
        _validate_session(session)
        if session_path.resolve() != request_path.with_name(
            "knowledge_review_session.json"
        ).resolve():
            raise ContractError("knowledge_review_session.json 必须与请求同目录")
        for field in ("request_id", "paper_id", "authoring_session_id"):
            if session[field] != request[field]:
                raise ContractError(f"知识审核 session 未绑定 {field}")
        if session["request_sha256"] != sha256_file(request_path):
            raise ContractError("知识审核 session 未绑定当前 request")
        if session["execution_policy"] != request["required_execution_policy"]:
            raise ContractError("知识审核 session 修改了执行隔离策略")
        thread_id = session["executor"]["thread_id"]
        if thread_id == request["authoring_session_id"]:
            raise ContractError("论文卡制作与知识审核任务未隔离")
        card_path = resolve_inside(root, request["card_path"], must_exist=True)
        evidence_path = resolve_inside(root, request["evidence_map_path"], must_exist=True)
        if sha256_file(card_path) != request["card_sha256"]:
            raise ContractError("知识审核请求绑定的 Card v2 已变化")
        if sha256_file(evidence_path) != request["evidence_map_sha256"]:
            raise ContractError("知识审核请求绑定的 evidence map 已变化")
        if session["card_sha256"] != request["card_sha256"] or session[
            "evidence_map_sha256"
        ] != request["evidence_map_sha256"]:
            raise ContractError("知识审核 session 未绑定当前卡片和证据图")
        matches = [
            path
            for path in (root / "knowledge/reviews/requests").glob(
                "*/knowledge_review_session.json"
            )
            if load_json(path).get("executor", {}).get("thread_id") == thread_id
        ]
        if len(matches) != 1 or matches[0].resolve() != session_path.resolve():
            raise ContractError("同一 thread_id 必须只绑定一个知识审核 session")
        claim_path = _thread_claim_path(root, thread_id)
        claim = load_json(claim_path)
        expected_claim = {
            "schema_name": "knowledge_review_thread_claim",
            "schema_version": "1.0",
            "thread_id": thread_id,
            "paper_id": request["paper_id"],
            "request_id": request["request_id"],
            "request_path": relative_inside(root, request_path).as_posix(),
            "request_sha256": sha256_file(request_path),
            "session_path": relative_inside(root, session_path).as_posix(),
            "session_sha256": sha256_file(session_path),
            "claimed_at": session["claimed_at"],
        }
        if claim != expected_claim:
            raise ContractError("knowledge review thread claim 与 session 不一致")
    except (ContractError, KeyError, OSError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors}
