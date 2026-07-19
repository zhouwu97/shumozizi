"""创建并复验路线确认时冻结的权威问题全集。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file, sha256_tree
from shumozizi.core.schema import require_valid


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def create_problem_manifest(run_dir: Path, questions: list[dict[str, Any]]) -> Path:
    """依据当前题面与配置锁创建问题全集，供路线批准一并冻结。"""
    state = load_json(run_dir / "state.json")
    source = Path(state["problem_source"])
    repo_root = run_dir.resolve().parents[1]
    source_path = source if source.is_absolute() else repo_root / source
    if not source_path.exists():
        raise ContractError(f"题面来源不存在: {source_path}")
    document = {
        "schema_name": "problem_manifest",
        "schema_version": "2.0",
        "run_id": run_dir.name,
        "run_config_lock_sha256": sha256_file(run_dir / "config/RUN_CONFIG_LOCK.json"),
        "problem_source": {
            "path": state["problem_source"],
            "sha256": sha256_tree(source_path),
        },
        "questions": questions,
        "frozen_at": _utc_now(),
    }
    require_valid(document, "problem_manifest")
    _validate_question_graph(document)
    path = run_dir / "problem" / "PROBLEM_MANIFEST.json"
    atomic_json(path, document)
    return path


def verify_problem_manifest(run_dir: Path) -> dict[str, Any]:
    """复验问题全集、题面、配置锁、题号和依赖关系。"""
    errors: list[str] = []
    path = run_dir / "problem" / "PROBLEM_MANIFEST.json"
    try:
        manifest = load_json(path)
        require_valid(manifest, "problem_manifest")
        if manifest["run_id"] != run_dir.name:
            errors.append("PROBLEM_MANIFEST.run_id 与运行目录不一致")
        if manifest["run_config_lock_sha256"] != sha256_file(
            run_dir / "config/RUN_CONFIG_LOCK.json"
        ):
            errors.append("PROBLEM_MANIFEST 绑定的 RUN_CONFIG_LOCK 已变化")
        source = Path(manifest["problem_source"]["path"])
        repo_root = run_dir.resolve().parents[1]
        source_path = source if source.is_absolute() else repo_root / source
        if not source_path.exists():
            errors.append(f"题面来源不存在: {source_path}")
        elif sha256_tree(source_path) != manifest["problem_source"]["sha256"]:
            errors.append("题面来源与 PROBLEM_MANIFEST 哈希不一致")
        _validate_question_graph(manifest)
    except (ContractError, KeyError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors, "path": str(path)}


def _validate_question_graph(manifest: dict[str, Any]) -> None:
    """拒绝重复题号、未知依赖和依赖环。"""
    questions = manifest["questions"]
    ids = [item["question_id"] for item in questions]
    if len(ids) != len(set(ids)):
        raise ContractError("PROBLEM_MANIFEST.question_id 重复")
    known = set(ids)
    dependencies = {item["question_id"]: set(item["depends_on"]) for item in questions}
    for question_id, required in dependencies.items():
        unknown = required - known
        if unknown:
            raise ContractError(f"{question_id} 引用了未知依赖: {', '.join(sorted(unknown))}")
        if question_id in required:
            raise ContractError(f"{question_id} 不能依赖自身")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(question_id: str) -> None:
        if question_id in visiting:
            raise ContractError("PROBLEM_MANIFEST 问题依赖存在环")
        if question_id in visited:
            return
        visiting.add(question_id)
        for dependency in dependencies[question_id]:
            visit(dependency)
        visiting.remove(question_id)
        visited.add(question_id)

    for question_id in ids:
        visit(question_id)
