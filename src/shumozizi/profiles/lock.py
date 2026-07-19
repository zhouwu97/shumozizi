"""创建并验证不可变运行配置锁。"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file, sha256_tree
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.core.schema import require_valid


def utc_now() -> str:
    """返回 RFC 3339 UTC 时间。"""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def create_run_config_lock(
    repo_root: Path,
    run_dir: Path,
    problem_source: Path,
    *,
    profile_id: str = "generic",
    language: str = "zh",
    anonymous: bool = True,
) -> dict[str, Any]:
    """在运行初始化时锁定 Profile、题面与排版配置。"""
    profile_path = repo_root / "profiles" / f"{profile_id}.json"
    if not profile_path.is_file():
        # 隔离测试仓库仍必须拥有自己的 Profile 副本，不能让运行锁指向外部文件。
        bundled = resolve_repo_root(Path(__file__)) / "profiles" / f"{profile_id}.json"
        if not bundled.is_file():
            raise ContractError(f"比赛 Profile 不存在: {profile_path}")
        atomic_json(profile_path, load_json(bundled))
    profile = load_json(profile_path)
    require_valid(profile, "competition_profile")
    if profile["profile_id"] != profile_id:
        raise ContractError("Profile 文件名与 profile_id 不一致")
    lock = {
        "schema_name": "run_config_lock",
        "schema_version": "2.0",
        "lock_version": 1,
        "run_id": run_dir.name,
        "competition_profile": {
            "profile_id": profile["profile_id"],
            "profile_version": profile["profile_version"],
            "profile_path": profile_path.relative_to(repo_root).as_posix(),
            "profile_sha256": sha256_file(profile_path),
        },
        "paper_engine": "typst",
        "language": language,
        "anonymous": anonymous,
        "problem_source_sha256": sha256_tree(problem_source),
        "locked_at": utc_now(),
    }
    require_valid(lock, "run_config_lock")
    lock_path = run_dir / "config" / "RUN_CONFIG_LOCK.json"
    atomic_json(lock_path, lock)
    atomic_json(
        run_dir / "config" / "RUN_CONFIG_LOCK.seal.json",
        {
            "schema_name": "run_config_lock_seal",
            "schema_version": "2.0",
            "canonicalization": "file-bytes-v1",
            "run_config_lock_sha256": sha256_file(lock_path),
            "sealed_at": utc_now(),
        },
    )
    return lock


def verify_run_config_lock(repo_root: Path, run_dir: Path) -> dict[str, Any]:
    """复验配置锁、锁封条与 Profile 内容哈希。"""
    lock_path = run_dir / "config" / "RUN_CONFIG_LOCK.json"
    lock = load_json(lock_path)
    require_valid(lock, "run_config_lock")
    if lock["run_id"] != run_dir.name:
        raise ContractError("RUN_CONFIG_LOCK.run_id 与运行目录不一致")
    seal = load_json(run_dir / "config" / "RUN_CONFIG_LOCK.seal.json")
    if seal.get("run_config_lock_sha256") != sha256_file(lock_path):
        raise ContractError("RUN_CONFIG_LOCK 哈希与封条不一致")
    profile_path = repo_root / lock["competition_profile"]["profile_path"]
    profile = load_json(profile_path)
    require_valid(profile, "competition_profile")
    if profile["profile_id"] != lock["competition_profile"]["profile_id"]:
        raise ContractError("锁定 Profile ID 与 Profile 文件不一致")
    if sha256_file(profile_path) != lock["competition_profile"]["profile_sha256"]:
        raise ContractError("锁定 Profile 的内容哈希已变化")
    return lock


def create_config_change_request(
    repo_root: Path,
    run_dir: Path,
    new_profile_id: str,
) -> Path:
    """创建绑定当前配置与目标 Profile 的变更批准请求。"""
    current_path = run_dir / "config" / "RUN_CONFIG_LOCK.json"
    current = verify_run_config_lock(repo_root, run_dir)
    profile_path = repo_root / "profiles" / f"{new_profile_id}.json"
    if not profile_path.is_file():
        raise ContractError(f"目标比赛 Profile 不存在: {profile_path}")
    require_valid(load_json(profile_path), "competition_profile")
    state = load_json(run_dir / "state.json")
    request = {
        "schema_name": "approval_request",
        "schema_version": "2.0",
        "request_id": f"{run_dir.name}-config-v{current['lock_version'] + 1}",
        "run_id": run_dir.name,
        "approval_kind": "config_change",
        "bindings": {
            "current_run_config_lock": sha256_file(current_path),
            "requested_profile": sha256_file(profile_path),
        },
        "state_revision": state["revision"],
        "warnings": ["配置变化会使旧路线锁、QA 和最终批准回执失效"],
        "requested_at": utc_now(),
    }
    require_valid(request, "approval_request")
    path = run_dir / "config" / "config_change_approval_request.json"
    atomic_json(path, request)
    return path


def materialize_config_change(
    repo_root: Path,
    run_dir: Path,
    new_profile_id: str,
    *,
    raw_user_response: str,
    approved_by: str = "human",
) -> Path:
    """依据明确人类回复创建新配置锁版本，保留旧锁且不覆盖历史回执。"""
    if not raw_user_response.strip():
        raise ContractError("原始用户批准回复不能为空")
    request_path = run_dir / "config" / "config_change_approval_request.json"
    request = load_json(request_path)
    require_valid(request, "approval_request")
    current_path = run_dir / "config" / "RUN_CONFIG_LOCK.json"
    current = verify_run_config_lock(repo_root, run_dir)
    profile_path = repo_root / "profiles" / f"{new_profile_id}.json"
    bindings = {
        "current_run_config_lock": sha256_file(current_path),
        "requested_profile": sha256_file(profile_path),
    }
    if request["approval_kind"] != "config_change" or request["bindings"] != bindings:
        raise ContractError("配置变更批准请求已失效")
    version = current["lock_version"] + 1
    receipt = {
        "schema_name": "approval_receipt",
        "schema_version": "2.0",
        "run_id": run_dir.name,
        "approval_kind": "config_change",
        "approval_request_sha256": sha256_file(request_path),
        "bindings": bindings,
        "raw_user_response": raw_user_response,
        "normalized_selection": new_profile_id,
        "delegated_items": [],
        "decision": "approved",
        "approved_by": approved_by,
        "approval_source": "codex-desktop-user-message",
        "approved_at": utc_now(),
    }
    require_valid(receipt, "approval_receipt")
    receipt_path = run_dir / "config" / f"config_change_approval_receipt.v{version}.json"
    atomic_json(receipt_path, receipt)
    archive_lock = run_dir / "config" / f"RUN_CONFIG_LOCK.v{current['lock_version']}.json"
    archive_seal = run_dir / "config" / f"RUN_CONFIG_LOCK.v{current['lock_version']}.seal.json"
    if archive_lock.exists() or archive_seal.exists():
        raise ContractError("配置锁历史版本已存在，拒绝覆盖")
    shutil.copy2(current_path, archive_lock)
    shutil.copy2(run_dir / "config" / "RUN_CONFIG_LOCK.seal.json", archive_seal)
    profile = load_json(profile_path)
    updated = {
        **current,
        "lock_version": version,
        "competition_profile": {
            "profile_id": profile["profile_id"],
            "profile_version": profile["profile_version"],
            "profile_path": profile_path.relative_to(repo_root).as_posix(),
            "profile_sha256": sha256_file(profile_path),
        },
        "locked_at": utc_now(),
    }
    require_valid(updated, "run_config_lock")
    atomic_json(current_path, updated)
    atomic_json(
        run_dir / "config" / "RUN_CONFIG_LOCK.seal.json",
        {
            "schema_name": "run_config_lock_seal",
            "schema_version": "2.0",
            "canonicalization": "file-bytes-v1",
            "run_config_lock_sha256": sha256_file(current_path),
            "sealed_at": utc_now(),
            "config_change_receipt_sha256": sha256_file(receipt_path),
        },
    )
    return receipt_path
