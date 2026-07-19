"""以 staging、完整校验和备份实现 v1 到 v2 的事务式迁移。"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file, sha256_tree
from shumozizi.core.schema import require_valid
from shumozizi.profiles.lock import create_run_config_lock


def utc_now() -> str:
    """返回 RFC 3339 UTC 时间。"""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def classify_v1_run(run_dir: Path) -> str:
    """按是否执行、accepted 或论文产物分类 A/B/C。"""
    registry = load_json(run_dir / "results" / "result_registry.json")
    results = registry.get("results", [])
    has_accepted = any(
        item.get("status") == "accepted" for item in results if isinstance(item, dict)
    )
    paper_dir = run_dir / "paper"
    has_paper = paper_dir.is_dir() and any(path.is_file() for path in paper_dir.rglob("*"))
    if has_accepted or has_paper:
        return "C"
    has_execution = (run_dir / "executions").is_dir() and any(
        (run_dir / "executions").glob("*/execution_record.json")
    )
    return "B" if has_execution or results else "A"


def migrate_run(repo_root: Path, run_dir: Path) -> dict[str, Any]:
    """事务式迁移允许升级的 v1 运行。

    C 类运行直接拒绝且不改写历史事实。迁移失败时，目标文件只存在于 staging。
    """
    root, source = repo_root.resolve(), run_dir.resolve()
    state_path = source / "state.json"
    original_state = load_json(state_path)
    if original_state.get("schema_version") != "1.0":
        raise ContractError("只允许迁移显式 Schema v1 运行")
    classification = classify_v1_run(source)
    if classification == "C":
        raise ContractError("C 类 v1 运行含 accepted 结果或论文，只能只读归档或新建 v2 run")
    staging = source / ".migration-v2-staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = source / ".migration-backups" / timestamp
    try:
        now = utc_now()
        migrated_state = {
            "schema_name": "workflow_state",
            "schema_version": "2.0",
            "run_schema_version": "2.0",
            "run_id": source.name,
            "problem_source": original_state["problem_source"],
            "mode": original_state.get("mode", "competition"),
            "status": "NEW",
            "revision": 0,
            "completed_stages": [],
            "active_stage": "ingest",
            "route_locked": False,
            "paper_ready": False,
            "question_progress": original_state.get("question_progress", {}),
            "artifacts": {},
            "last_updated_by": "migrate_run_v1_to_v2.py",
            "updated_at": now,
            "history": [
                {
                    "from_status": None,
                    "status": "NEW",
                    "event": "MIGRATED_FROM_V1",
                    "timestamp": now,
                    "actor": {"actor_id": "migrate_run_v1_to_v2.py", "actor_type": "system"},
                    "artifact_refs": [],
                    "note": f"v1 {classification} 类运行已迁移；既有未接受实验不提升为权威事实",
                }
            ],
        }
        require_valid(migrated_state, "workflow_state")
        atomic_json(staging / "state.json", migrated_state)
        registry = {
            "schema_name": "result_registry",
            "schema_version": "2.0",
            "run_id": source.name,
            "results": [],
        }
        require_valid(registry, "result_registry")
        atomic_json(staging / "results" / "result_registry.json", registry)
        problem = Path(original_state["problem_source"])
        if not problem.is_absolute():
            problem = root / problem
        create_run_config_lock(root, staging, problem)
        # staging 名与真实 run_id 不同，物化后再将锁内 ID 修正为真实运行 ID。
        lock_path = staging / "config" / "RUN_CONFIG_LOCK.json"
        lock = load_json(lock_path)
        lock["run_id"] = source.name
        atomic_json(lock_path, lock)
        seal_path = staging / "config" / "RUN_CONFIG_LOCK.seal.json"
        seal = load_json(seal_path)
        seal["run_config_lock_sha256"] = sha256_file(lock_path)
        atomic_json(seal_path, seal)
        generated = []
        for path in sorted(item for item in staging.rglob("*") if item.is_file()):
            generated.append(
                {"path": path.relative_to(staging).as_posix(), "sha256": sha256_file(path)}
            )
        manifest = {
            "schema_name": "migration_manifest",
            "schema_version": "2.0",
            "run_id": source.name,
            "from_version": "1.0",
            "to_version": "2.0",
            "classification": classification,
            "source_tree_sha256": sha256_tree(source),
            "generated_files": generated,
            "backup_path": backup.relative_to(source).as_posix(),
            "migrated_at": now,
        }
        require_valid(manifest, "migration_manifest")
        atomic_json(staging / "migration_manifest.json", manifest)
        backup.mkdir(parents=True)
        target_files = (
            "state.json",
            "results/result_registry.json",
            "config/RUN_CONFIG_LOCK.json",
            "config/RUN_CONFIG_LOCK.seal.json",
            "migration_manifest.json",
        )
        for relative in target_files:
            old = source / relative
            if old.is_file():
                target = backup / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(old, target)
        for relative in target_files:
            staged = staging / relative
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            staged.replace(target)
        (source / "MIGRATED_TO_V2").write_text(now + "\n", encoding="utf-8")
        shutil.rmtree(staging)
        for path in (item for item in backup.rglob("*") if item.is_file()):
            path.chmod(0o444)
        return {"migrated": True, "classification": classification, "backup": str(backup)}
    except Exception as exc:
        if backup.is_dir():
            for relative in (
                "state.json",
                "results/result_registry.json",
                "config/RUN_CONFIG_LOCK.json",
                "config/RUN_CONFIG_LOCK.seal.json",
                "migration_manifest.json",
            ):
                saved = backup / relative
                target = source / relative
                if saved.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(saved, target)
                elif target.exists() and relative not in {
                    "state.json",
                    "results/result_registry.json",
                }:
                    target.unlink()
        atomic_json(
            source / "migration_failure.json",
            {
                "schema_name": "migration_failure",
                "schema_version": "2.0",
                "error": str(exc),
                "failed_at": utc_now(),
                "staging": str(staging),
            },
        )
        raise
