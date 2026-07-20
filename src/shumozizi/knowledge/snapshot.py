"""路线前知识检索快照的生成、结构校验与当前环境差异审计。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_bytes, sha256_file

RETRIEVAL_POLICY = {
    "policy_id": "paper-verified-structural-domain-v1",
    "index_kind": "verified",
    "structural_weights": {
        "problem_type": 0.35,
        "data_structure": 0.20,
        "task_types": 0.30,
        "structural_tags": 0.15,
    },
    "score_weights": {"structural": 0.70, "domain": 0.30},
    "same_problem_exclusion_fields": ["canonical_problem_id", "problem_asset_sha256"],
    "provisional_fallback_allowed": False,
}


def _policy_sha256(policy: dict[str, Any]) -> str:
    encoded = json.dumps(
        policy, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256_bytes(encoded)


def _repo_relative(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise ContractError(f"知识文件不在仓库内: {path}") from exc


def write_retrieval_snapshot(
    run_dir: Path,
    index_path: Path,
    fingerprint_path: Path,
    fingerprint: dict[str, Any],
    index: dict[str, Any],
    matches: list[dict[str, Any]],
) -> Path:
    """冻结一次路线检索的输入、策略、排除与选卡集合。"""
    repo_root = index_path.resolve().parents[2]
    canonical_id = fingerprint.get("canonical_problem_id")
    problem_sha256 = fingerprint.get("problem_asset_sha256")
    exclusions: list[dict[str, str]] = []
    for entry in index["papers"]:
        reason: str | None = None
        if canonical_id and entry.get("canonical_problem_id") == canonical_id:
            reason = "canonical_problem_id"
        elif problem_sha256 and entry.get("problem_asset_sha256") == problem_sha256:
            reason = "problem_asset_sha256"
        if reason:
            exclusions.append({"paper_id": entry["paper_id"], "reason": reason})

    selected_cards = [
        {
            "paper_id": item["paper_id"],
            "card_version": item["card_version"],
            "card_sha256": item["card_sha256"],
            "promotion_receipt_sha256": item["promotion_receipt_sha256"],
        }
        for item in matches
    ]
    document = {
        "schema_name": "retrieval_snapshot",
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "current_problem_identity": {
            "canonical_problem_id": canonical_id,
            "problem_asset_sha256": problem_sha256,
        },
        "verified_index_path": _repo_relative(repo_root, index_path),
        "verified_index_sha256": sha256_file(index_path),
        "retrieval_policy": RETRIEVAL_POLICY,
        "retrieval_policy_sha256": _policy_sha256(RETRIEVAL_POLICY),
        "task_fingerprint_path": fingerprint_path.relative_to(run_dir).as_posix(),
        "task_fingerprint_sha256": sha256_file(fingerprint_path),
        "retrieval_input": {
            field: fingerprint[field]
            for field in (
                "problem_type",
                "data_structure",
                "task_types",
                "keywords",
                "structural_tags",
                "canonical_problem_id",
                "problem_asset_sha256",
            )
        },
        "selected_cards": selected_cards,
        "same_problem_exclusions": exclusions,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    errors = validate_retrieval_snapshot_document(document, run_id=run_dir.name)
    if errors:
        raise ContractError("检索快照无效: " + "; ".join(errors))
    path = run_dir / "knowledge" / "RETRIEVAL_SNAPSHOT.json"
    atomic_json(path, document)
    return path


def validate_retrieval_snapshot_document(
    document: dict[str, Any], *, run_id: str | None = None
) -> list[str]:
    """只校验快照自身，不把后续知识库变化解释为当前路线失效。"""
    errors: list[str] = []
    if document.get("schema_name") != "retrieval_snapshot" or document.get(
        "schema_version"
    ) != "1.0":
        errors.append("schema_name 或 schema_version 无效")
    if run_id is not None and document.get("run_id") != run_id:
        errors.append("run_id 与运行目录不一致")
    policy = document.get("retrieval_policy")
    if not isinstance(policy, dict) or document.get("retrieval_policy_sha256") != _policy_sha256(
        policy or {}
    ):
        errors.append("retrieval_policy_sha256 不匹配")
    selected = document.get("selected_cards")
    if not isinstance(selected, list):
        errors.append("selected_cards 必须是数组")
        selected = []
    ids = [item.get("paper_id") for item in selected if isinstance(item, dict)]
    if len(ids) != len(selected) or len(ids) != len(set(ids)):
        errors.append("selected_cards 包含无效或重复 paper_id")
    for item in selected:
        if not isinstance(item, dict):
            continue
        for field in ("card_sha256", "promotion_receipt_sha256"):
            value = item.get(field)
            if not isinstance(value, str) or len(value) != 64:
                errors.append(f"selected_cards.{field} 无效")
    exclusions = document.get("same_problem_exclusions")
    if not isinstance(exclusions, list):
        errors.append("same_problem_exclusions 必须是数组")
    elif set(ids).intersection(
        item.get("paper_id") for item in exclusions if isinstance(item, dict)
    ):
        errors.append("同题排除卡不得出现在 selected_cards")
    return errors


def verify_retrieval_snapshot(run_dir: Path) -> dict[str, Any]:
    """复验快照自身及其任务指纹；知识库后续变化只作为差异警告。"""
    path = run_dir / "knowledge" / "RETRIEVAL_SNAPSHOT.json"
    errors: list[str] = []
    warnings: list[str] = []
    try:
        document = load_json(path)
        errors.extend(validate_retrieval_snapshot_document(document, run_id=run_dir.name))
        fingerprint_path = run_dir / str(document["task_fingerprint_path"])
        if not fingerprint_path.is_file() or sha256_file(fingerprint_path) != document.get(
            "task_fingerprint_sha256"
        ):
            errors.append("TASK_FINGERPRINT 已变化或缺失")
        repo_root = run_dir.resolve().parents[1]
        index_path = repo_root / str(document["verified_index_path"])
        if not index_path.is_file():
            warnings.append("当前 verified 索引已删除；快照仍保留原始绑定")
        elif sha256_file(index_path) != document.get("verified_index_sha256"):
            warnings.append("当前 verified 索引已变化；已锁路线继续使用原快照")
    except (ContractError, KeyError, OSError) as exc:
        errors.append(str(exc))
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "path": path,
        "sha256": sha256_file(path) if path.is_file() else None,
    }
