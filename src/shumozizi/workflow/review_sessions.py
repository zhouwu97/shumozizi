"""独立审核任务的领取协议与会话绑定复验。"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
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
from shumozizi.core.schema import require_valid
from shumozizi.workflow.review_inputs import verify_review_input_manifest


def utc_now() -> str:
    """返回 RFC 3339 UTC 时间。"""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _repo_root(run_dir: Path) -> Path:
    """从 ``<repo>/runs/<run_id>`` 得到仓库根目录。"""
    if run_dir.parent.name != "runs":
        raise ContractError("审核运行目录必须位于仓库 runs/ 下")
    return run_dir.parent.parent


def _thread_claim_path(repo_root: Path, thread_id: str) -> Path:
    """用线程 ID 摘要得到不泄露原始 ID 的全局 claim 路径。"""
    digest = sha256_bytes(thread_id.encode("utf-8"))
    return repo_root / ".review_registry" / "thread_claims" / f"{digest}.json"


def _exclusive_json(path: Path, payload: dict[str, Any]) -> None:
    """使用 O_EXCL 独占创建 JSON，禁止并发覆盖已存在文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise ContractError(f"独占文件已存在: {path}") from exc


@contextmanager
def _repository_claim_lock(repo_root: Path, *, timeout_seconds: float = 10.0):
    """用原子 mkdir 串行化整个仓库的 request/thread 领取临界区。"""
    registry = repo_root / ".review_registry"
    registry.mkdir(parents=True, exist_ok=True)
    lock_dir = registry / "claim.lock"
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            lock_dir.mkdir()
            break
        except FileExistsError as exc:
            if time.monotonic() >= deadline:
                raise ContractError("等待仓库级审核领取锁超时") from exc
            time.sleep(0.01)
    try:
        yield
    finally:
        lock_dir.rmdir()


def _repository_thread_sessions(repo_root: Path, thread_id: str) -> list[Path]:
    """返回整个仓库内使用指定 thread_id 的所有 session。"""
    matches: list[Path] = []
    for existing in (repo_root / "runs").glob("*/review/**/review_session.json"):
        session = load_json(existing)
        if session.get("executor", {}).get("thread_id") == thread_id:
            matches.append(existing)
    return matches


def claim_review_request(
    request_path: Path,
    *,
    thread_id: str,
    attestation_level: str = "self_declared",
) -> Path:
    """由全新顶层 Codex 任务领取请求，并冻结不可变会话声明。"""
    request = load_json(request_path)
    require_valid(request, "review_request")
    run_dir = request_path.parents[3]
    state = load_json(run_dir / "state.json")
    if state["revision"] != request["state_revision"]:
        raise ContractError("旧 revision 的审核请求不能被领取")
    normalized_thread_id = thread_id.strip()
    if not normalized_thread_id:
        raise ContractError("Codex 顶层任务 ID 不能为空")
    if attestation_level != "self_declared":
        raise ContractError(
            "当前领取接口没有平台可信元数据，只能生成 self_declared attestation"
        )
    repo_root = _repo_root(run_dir)
    session_path = request_path.with_name("review_session.json")
    manifest_path = resolve_inside(
        run_dir, request["input_manifest_path"], must_exist=True
    )
    manifest_report = verify_review_input_manifest(run_dir, manifest_path, request=request)
    if not manifest_report["valid"]:
        raise ContractError("审核材料清单复验失败: " + "; ".join(manifest_report["errors"]))
    if sha256_file(manifest_path) != request["input_manifest_sha256"]:
        raise ContractError("审核请求绑定的材料清单哈希不一致")
    timestamp = utc_now()
    session = {
        "schema_name": "review_session",
        "schema_version": "2.0",
        "run_id": request["run_id"],
        "request_id": request["request_id"],
        "review_round_id": request["review_round_id"],
        "stage": request["stage"],
        "state_revision": request["state_revision"],
        "executor": {
            "platform": "codex_desktop",
            "thread_id": normalized_thread_id,
            "task_kind": "top_level",
            "parent_thread_id": None,
        },
        "execution_policy": {
            "new_thread": True,
            "subagent": False,
            "forked": False,
            "context_inherited": False,
        },
        "attestation_level": attestation_level,
        "request_sha256": sha256_file(request_path),
        "input_manifest_sha256": request["input_manifest_sha256"],
        "claimed_at": timestamp,
        "started_at": timestamp,
    }
    require_valid(session, "review_session")
    claim_path = _thread_claim_path(repo_root, normalized_thread_id)
    with _repository_claim_lock(repo_root):
        if session_path.exists():
            raise ContractError("一个审核请求只能被一个 session 领取")
        if request_path.with_name("review_report.json").exists():
            raise ContractError("已生成报告的请求不能补写 session")
        if claim_path.exists() or _repository_thread_sessions(
            repo_root, normalized_thread_id
        ):
            raise ContractError("同一仓库中 thread_id 只能领取一个审核请求")
        _exclusive_json(session_path, session)
        claim = {
            "schema_name": "review_thread_claim",
            "schema_version": "2.0",
            "thread_id": normalized_thread_id,
            "run_id": request["run_id"],
            "request_id": request["request_id"],
            "request_path": relative_inside(repo_root, request_path).as_posix(),
            "request_sha256": sha256_file(request_path),
            "session_path": relative_inside(repo_root, session_path).as_posix(),
            "session_sha256": sha256_file(session_path),
            "claimed_at": timestamp,
        }
        require_valid(claim, "review_thread_claim")
        try:
            _exclusive_json(claim_path, claim)
        except ContractError:
            session_path.unlink()
            raise
    return session_path


def verify_review_session(
    run_dir: Path,
    request_path: Path,
    session_path: Path,
    *,
    require_current_revision: bool = True,
) -> dict[str, Any]:
    """复验 session 身份、请求/材料哈希、线程唯一性和 revision。"""
    errors: list[str] = []
    try:
        request = load_json(request_path)
        session = load_json(session_path)
        require_valid(request, "review_request")
        require_valid(session, "review_session")
        if session_path.resolve() != request_path.with_name("review_session.json").resolve():
            raise ContractError("review_session.json 必须与请求位于同一轮目录")
        identity = ("request_id", "run_id", "stage", "review_round_id", "state_revision")
        if any(session[key] != request[key] for key in identity):
            raise ContractError("审核 session 与请求身份不一致")
        if session["request_sha256"] != sha256_file(request_path):
            raise ContractError("审核 session 绑定的请求哈希不一致")
        manifest_path = resolve_inside(
            run_dir, request["input_manifest_path"], must_exist=True
        )
        manifest_report = verify_review_input_manifest(run_dir, manifest_path, request=request)
        if not manifest_report["valid"]:
            raise ContractError(
                "审核材料清单复验失败: " + "; ".join(manifest_report["errors"])
            )
        manifest_hash = sha256_file(manifest_path)
        if request["input_manifest_sha256"] != manifest_hash:
            raise ContractError("审核请求绑定的材料清单哈希不一致")
        if session["input_manifest_sha256"] != manifest_hash:
            raise ContractError("审核 session 绑定的材料清单哈希不一致")
        repo_root = _repo_root(run_dir)
        thread_id = session["executor"]["thread_id"]
        matches = _repository_thread_sessions(repo_root, thread_id)
        if len(matches) != 1 or matches[0].resolve() != session_path.resolve():
            raise ContractError("同一仓库中 thread_id 必须唯一")
        claim_path = _thread_claim_path(repo_root, thread_id)
        claim = load_json(claim_path)
        require_valid(claim, "review_thread_claim")
        expected_claim = {
            "thread_id": thread_id,
            "run_id": request["run_id"],
            "request_id": request["request_id"],
            "request_path": relative_inside(repo_root, request_path).as_posix(),
            "request_sha256": sha256_file(request_path),
            "session_path": relative_inside(repo_root, session_path).as_posix(),
            "session_sha256": sha256_file(session_path),
        }
        if any(claim[key] != value for key, value in expected_claim.items()):
            raise ContractError("仓库级 thread claim 与审核 session 不一致")
        if require_current_revision:
            state = load_json(run_dir / "state.json")
            if state["revision"] != session["state_revision"]:
                raise ContractError("旧 revision 的审核 session 已失效")
    except (ContractError, OSError, KeyError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors, "session_path": str(session_path)}
