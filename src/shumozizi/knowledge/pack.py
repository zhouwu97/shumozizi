"""知识包导入、泄漏检查和运行配置绑定。"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.core.schema import require_valid
from shumozizi.profiles.lock import verify_run_config_lock


def _pack_schema(repo_root: Path) -> dict[str, Any]:
    return json.loads((repo_root / "schemas" / "knowledge_pack.schema.json").read_text(encoding="utf-8"))


def validate_knowledge_pack(repo_root: Path, pack: dict[str, Any]) -> None:
    """校验知识包自己的 0.1.0 合同，不把它伪装成工作流状态 Schema。"""
    errors = sorted(Draft202012Validator(_pack_schema(repo_root), format_checker=FormatChecker()).iter_errors(pack), key=lambda error: list(error.path))
    if errors:
        raise ContractError("知识包格式错误: " + "; ".join(error.message for error in errors))
    card_ids = [card["card_id"] for card in pack["cards"]]
    if len(card_ids) != len(set(card_ids)):
        raise ContractError("知识包 card_id 重复")


def load_knowledge_pack(repo_root: Path, path: Path) -> dict[str, Any]:
    pack = load_json(path)
    validate_knowledge_pack(repo_root, pack)
    return pack


def _problem_files(problem_source: Path) -> list[Path]:
    if problem_source.is_symlink():
        target = problem_source.resolve()
        if problem_source.parent.resolve() not in target.parents:
            raise ContractError(f"题面符号链接越过工作区边界: {problem_source}")
    root = problem_source.resolve()
    if root.is_file():
        paths = [root]
    elif root.is_dir():
        # 先检查所有目录项，再收集文件；否则 rglob 不遍历目录符号链接，
        # 越界目录可能在未被读取的情况下绕过泄漏检查。
        entries = sorted(problem_source.rglob("*"))
        for path in entries:
            if path.is_symlink() and root not in path.resolve().parents:
                raise ContractError(f"题面目录包含越界符号链接: {path}")
        paths = sorted(path for path in entries if path.is_file())
    else:
        raise ContractError(f"题面路径不存在: {problem_source}")
    return paths


def _problem_text(problem_source: Path) -> tuple[str, list[Path]]:
    paths = _problem_files(problem_source)
    chunks = [" ".join(path.name for path in paths)]
    for path in paths:
        if path.suffix.lower() in {".md", ".txt", ".json", ".csv", ".tex", ".typ"}:
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks).casefold(), paths


def check_knowledge_leakage(pack: dict[str, Any], problem_source: Path) -> None:
    """拒绝题面或附件名称中出现知识包来源题号/题名的同题资产。"""
    text, paths = _problem_text(problem_source)
    source_hashes = {
        value
        for summary in pack["source_summary"]
        for value in (summary["sha256"], summary.get("source_asset_sha256"))
        if value
    }
    for path in paths:
        if hashlib.sha256(path.read_bytes()).hexdigest() in source_hashes:
            raise ContractError("检测到知识包同题资产泄漏: 文件哈希匹配")
    for exclusion in pack["leakage_exclusions"]:
        for token in exclusion["forbidden_tokens"]:
            if token.casefold() in text:
                raise ContractError(f"检测到知识包同题资产泄漏: {exclusion['paper_id']}")


def install_knowledge_pack(repo_root: Path, pack_path: Path) -> tuple[Path, dict[str, Any]]:
    """把知识包安装到 knowledge/packs，并拒绝覆盖不同内容。"""
    pack = load_knowledge_pack(repo_root, pack_path)
    destination = repo_root / "knowledge" / "packs" / f"{pack['pack_id']}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_bytes = pack_path.read_bytes()
    if destination.exists() and destination.read_bytes() != source_bytes:
        raise ContractError(f"已存在不同内容的知识包: {destination}")
    if not destination.exists():
        shutil.copyfile(pack_path, destination)
    return destination, pack


def bind_knowledge_pack(
    repo_root: Path,
    run_dir: Path,
    pack_path: Path,
    *,
    problem_source: Path | None = None,
) -> dict[str, Any]:
    """在路线锁定前将知识包哈希写入现有 RUN_CONFIG_LOCK。"""
    lock = verify_run_config_lock(repo_root, run_dir)
    state = load_json(run_dir / "state.json")
    if state.get("route_locked") or state.get("status") not in {"NEW", "WAITING_HUMAN_ROUTE"}:
        raise ContractError("知识包只能在路线锁定前绑定")
    destination, pack = install_knowledge_pack(repo_root, pack_path)
    if problem_source is not None:
        check_knowledge_leakage(pack, problem_source)
    metadata = {
        "pack_id": pack["pack_id"],
        "pack_version": pack["pack_version"],
        "path": destination.relative_to(repo_root).as_posix(),
        "sha256": sha256_file(destination),
        "source_commit": pack["source_commit"],
    }
    existing = lock.get("knowledge_pack")
    if existing is not None and existing != metadata:
        raise ContractError("RUN_CONFIG_LOCK 已绑定不同知识包")
    if existing == metadata:
        return lock
    updated = {**lock, "knowledge_pack": metadata}
    require_valid(updated, "run_config_lock")
    lock_path = run_dir / "config" / "RUN_CONFIG_LOCK.json"
    atomic_json(lock_path, updated)
    seal = load_json(run_dir / "config" / "RUN_CONFIG_LOCK.seal.json")
    seal["run_config_lock_sha256"] = sha256_file(lock_path)
    atomic_json(run_dir / "config" / "RUN_CONFIG_LOCK.seal.json", seal)
    return updated


def verify_bound_knowledge_pack(repo_root: Path, lock: dict[str, Any]) -> dict[str, Any] | None:
    """复验锁中知识包的路径、字节哈希和内容合同。"""
    metadata = lock.get("knowledge_pack")
    if metadata is None:
        return None
    path = repo_root / metadata["path"]
    if sha256_file(path) != metadata["sha256"]:
        raise ContractError("RUN_CONFIG_LOCK 绑定的知识包哈希已变化")
    pack = load_knowledge_pack(repo_root, path)
    if pack["pack_id"] != metadata["pack_id"] or pack["pack_version"] != metadata["pack_version"]:
        raise ContractError("RUN_CONFIG_LOCK 绑定的知识包版本不一致")
    return pack
