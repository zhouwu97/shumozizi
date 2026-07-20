"""原子知识模式、反模式、独立晋级与赛后 provisional 学习。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    load_json,
    relative_inside,
    resolve_inside,
    sha256_bytes,
    sha256_file,
)

ATOMIC_PATTERN_TYPES = {
    "problem_decomposition",
    "model_selection",
    "validation",
    "uncertainty",
    "figure_narrative",
    "argument_chain",
    "failure_disclosure",
    "negative_result",
}
ANTIPATTERN_TYPES = {
    "data_leakage",
    "pseudo_innovation",
    "model_stacking",
    "non_discriminating_robustness",
    "figure_conclusion_disconnect",
    "good_fit_unidentifiable",
    "complexity_without_decision_value",
}
PATTERN_PROMOTION_POLICY = "atomic-pattern-promotion-v1"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _content_sha256(document: dict[str, Any]) -> str:
    encoded = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256_bytes(encoded)


def _require_strings(value: object, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ContractError(f"{field} 必须是字符串数组")
    return value


def _write_or_verify_receipt(path: Path, stable_fields: dict[str, Any]) -> None:
    """首次写入模式晋级回执，或精确复验中断后遗留的回执。"""
    if path.exists():
        existing = load_json(path)
        promoted_at = existing.get("promoted_at")
        if not isinstance(promoted_at, str) or not promoted_at.strip():
            raise ContractError("原子模式晋级回执缺少 promoted_at")
        if existing != {**stable_fields, "promoted_at": promoted_at}:
            raise ContractError("已存在的原子模式晋级回执与当前晋级事实不一致")
        return
    atomic_json(path, {**stable_fields, "promoted_at": _utc_now()})


def validate_pattern_document(document: dict[str, Any]) -> None:
    """校验单个原子模式或反模式的迁移边界与证据职责。"""
    schema_name = document.get("schema_name")
    if schema_name == "atomic_knowledge_pattern":
        allowed_types = ATOMIC_PATTERN_TYPES
        type_field = "pattern_type"
        extra_fields = ("common_misuses", "counterexamples")
    elif schema_name == "knowledge_antipattern":
        allowed_types = ANTIPATTERN_TYPES
        type_field = "antipattern_type"
        extra_fields = ("detection_signals", "harms", "corrections")
    else:
        raise ContractError("未知知识模式 schema_name")
    if document.get("schema_version") != "1.0":
        raise ContractError("知识模式 schema_version 必须为 1.0")
    if document.get(type_field) not in allowed_types:
        raise ContractError(f"{type_field} 无效")
    for field in ("pattern_id", "title", "origin", "authoring_session_id"):
        if not isinstance(document.get(field), str) or not document[field].strip():
            raise ContractError(f"{field} 必须是非空字符串")
    for field in (
        "applicable_when",
        "not_applicable_when",
        "required_evidence",
        "source_paper_ids",
        *extra_fields,
    ):
        _require_strings(document.get(field), field)
    if document.get("review_status") not in {"provisional", "revision_required"}:
        raise ContractError("知识模式源文件只能是 provisional 或 revision_required")


def load_pattern_review_registry(path: Path) -> dict[str, Any]:
    registry = load_json(path)
    if registry.get("schema_name") != "atomic_pattern_review_registry" or registry.get(
        "schema_version"
    ) != "1.0":
        raise ContractError("无效 atomic pattern review registry")
    if registry.get("default_status") != "provisional" or not isinstance(
        registry.get("patterns"), dict
    ):
        raise ContractError("atomic pattern review registry 结构无效")
    for pattern_id, record in registry["patterns"].items():
        if not isinstance(record, dict) or record.get("review_status") not in {
            "provisional",
            "revision_required",
            "rejected",
            "verified",
            "superseded",
        }:
            raise ContractError(f"原子模式审核状态无效: {pattern_id}")
        if record["review_status"] == "verified" and (
            not record.get("promotion_receipt")
            or not record.get("promotion_receipt_sha256")
        ):
            raise ContractError(f"原子模式 {pattern_id} 缺少晋级回执")
    return registry


def _pattern_files(repo_root: Path) -> list[Path]:
    paths: list[Path] = []
    for directory in (
        repo_root / "knowledge/patterns/atomic",
        repo_root / "knowledge/patterns/antipatterns",
    ):
        if directory.is_dir():
            paths.extend(sorted(directory.glob("*.json")))
    return paths


def _verify_pattern_promotion(
    repo_root: Path,
    pattern_path: Path,
    document: dict[str, Any],
    record: dict[str, Any],
) -> str:
    receipt_path = resolve_inside(
        repo_root, str(record.get("promotion_receipt", "")), must_exist=True
    )
    digest = sha256_file(receipt_path)
    if digest != record.get("promotion_receipt_sha256"):
        raise ContractError(f"原子模式晋级回执哈希不匹配: {document['pattern_id']}")
    receipt = load_json(receipt_path)
    expected = {
        "schema_name": "atomic_pattern_promotion_receipt",
        "schema_version": "1.0",
        "pattern_id": document["pattern_id"],
        "pattern_path": pattern_path.relative_to(repo_root).as_posix(),
        "pattern_sha256": sha256_file(pattern_path),
        "pattern_content_sha256": _content_sha256(document),
        "promotion_policy_version": PATTERN_PROMOTION_POLICY,
    }
    for field, value in expected.items():
        if receipt.get(field) != value:
            raise ContractError(f"原子模式晋级回执未绑定 {field}")
    review_path = resolve_inside(
        repo_root, str(receipt.get("review_report_path", "")), must_exist=True
    )
    if receipt.get("review_report_sha256") != sha256_file(review_path):
        raise ContractError("原子模式晋级回执未绑定当前审核报告")
    return digest


def build_pattern_indexes(repo_root: Path) -> dict[str, dict[str, Any]]:
    """确定性构建 provisional/verified 原子模式与反模式索引。"""
    root = repo_root.resolve()
    registry_path = root / "knowledge/reviews/atomic_pattern_review_registry.json"
    registry = load_pattern_review_registry(registry_path)
    provisional: list[dict[str, Any]] = []
    verified: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in _pattern_files(root):
        document = load_json(path)
        validate_pattern_document(document)
        pattern_id = document["pattern_id"]
        if pattern_id in seen:
            raise ContractError(f"pattern_id 重复: {pattern_id}")
        seen.add(pattern_id)
        record = registry["patterns"].get(
            pattern_id,
            {
                "review_status": registry["default_status"],
                "promotion_receipt": None,
                "promotion_receipt_sha256": None,
            },
        )
        entry = {
            "pattern_id": pattern_id,
            "schema_name": document["schema_name"],
            "pattern_type": document.get("pattern_type", document.get("antipattern_type")),
            "title": document["title"],
            "path": path.relative_to(root).as_posix(),
            "sha256": sha256_file(path),
            "content_sha256": _content_sha256(document),
            "source_paper_ids": document["source_paper_ids"],
            "origin": document["origin"],
            "review_status": record["review_status"],
            "promotion_receipt_sha256": record.get("promotion_receipt_sha256"),
        }
        if record["review_status"] == "verified":
            _verify_pattern_promotion(root, path, document, record)
            verified.append(entry)
        elif record["review_status"] in {"provisional", "revision_required"}:
            provisional.append(entry)

    base = {
        "schema_name": "atomic_pattern_index",
        "schema_version": "1.0",
        "review_registry_sha256": sha256_file(registry_path),
    }
    provisional_index = {
        **base,
        "index_kind": "provisional",
        "pattern_count": len(provisional),
        "patterns": provisional,
    }
    verified_index = {
        **base,
        "index_kind": "verified",
        "pattern_count": len(verified),
        "patterns": verified,
    }
    atomic_json(root / "knowledge/indexes/atomic_patterns_provisional.json", provisional_index)
    atomic_json(root / "knowledge/indexes/atomic_patterns_verified.json", verified_index)
    return {"provisional": provisional_index, "verified": verified_index}


def promote_pattern(repo_root: Path, pattern_id: str, review_report_path: Path) -> Path:
    """用独立审核报告晋级单个原子模式，不修改模式源文件。"""
    root = repo_root.resolve()
    matches = [
        path
        for path in _pattern_files(root)
        if load_json(path).get("pattern_id") == pattern_id
    ]
    if len(matches) != 1:
        raise ContractError("待晋级 pattern_id 不存在或重复")
    pattern_path = matches[0]
    document = load_json(pattern_path)
    validate_pattern_document(document)
    review_path = review_report_path.resolve()
    relative_inside(root, review_path)
    review = load_json(review_path)
    expected = {
        "schema_name": "atomic_pattern_review_report",
        "schema_version": "1.0",
        "pattern_id": pattern_id,
        "pattern_sha256": sha256_file(pattern_path),
    }
    for field, value in expected.items():
        if review.get(field) != value:
            raise ContractError(f"原子模式审核报告未绑定 {field}")
    if review.get("verdict") != "verified":
        raise ContractError("只有 verified 原子模式审核可以晋级")
    if review.get("review_session_id") == document["authoring_session_id"]:
        raise ContractError("原子模式制作与审核必须使用独立会话")
    if any(item.get("status") == "open" for item in review.get("findings", [])):
        raise ContractError("存在 open finding 时不能晋级原子模式")

    registry_path = root / "knowledge/reviews/atomic_pattern_review_registry.json"
    registry = load_pattern_review_registry(registry_path)
    current = registry["patterns"].get(pattern_id, {})
    receipt_path = root / f"knowledge/reviews/pattern_promotions/{pattern_id}.json"
    receipt = {
        "schema_name": "atomic_pattern_promotion_receipt",
        "schema_version": "1.0",
        "pattern_id": pattern_id,
        "pattern_path": pattern_path.relative_to(root).as_posix(),
        "pattern_sha256": sha256_file(pattern_path),
        "pattern_content_sha256": _content_sha256(document),
        "review_report_path": review_path.relative_to(root).as_posix(),
        "review_report_sha256": sha256_file(review_path),
        "review_session_id": review["review_session_id"],
        "reviewer_identity": review["reviewer_identity"],
        "promotion_policy_version": PATTERN_PROMOTION_POLICY,
    }
    _write_or_verify_receipt(receipt_path, receipt)
    expected_record = {
        "review_status": "verified",
        "promotion_receipt": receipt_path.relative_to(root).as_posix(),
        "promotion_receipt_sha256": sha256_file(receipt_path),
    }
    if current.get("review_status") == "verified":
        if current != expected_record:
            raise ContractError("verified 原子模式注册记录与晋级回执不一致")
    else:
        registry["patterns"][pattern_id] = expected_record
        atomic_json(registry_path, registry)
    build_pattern_indexes(root)
    return receipt_path


def write_postmortem_pattern(repo_root: Path, document: dict[str, Any]) -> Path:
    """将赛后复盘写为 provisional 原子模式，拒绝任何自动 verified 请求。"""
    root = repo_root.resolve()
    payload = dict(document)
    if payload.get("review_status") not in {None, "provisional"}:
        raise ContractError("赛后 postmortem 只能生成 provisional 知识")
    payload["schema_name"] = "atomic_knowledge_pattern"
    payload["schema_version"] = "1.0"
    payload["origin"] = "postmortem"
    payload["review_status"] = "provisional"
    validate_pattern_document(payload)
    path = root / f"knowledge/patterns/atomic/{payload['pattern_id']}.json"
    if path.exists():
        raise ContractError("postmortem pattern_id 已存在")
    atomic_json(path, payload)
    registry_path = root / "knowledge/reviews/atomic_pattern_review_registry.json"
    registry = load_pattern_review_registry(registry_path)
    registry["patterns"][payload["pattern_id"]] = {
        "review_status": "provisional",
        "promotion_receipt": None,
        "promotion_receipt_sha256": None,
    }
    atomic_json(registry_path, registry)
    build_pattern_indexes(root)
    return path
