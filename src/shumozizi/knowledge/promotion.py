"""Paper Card v2 的来源、证据、独立审核与单卡晋级。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, resolve_inside, sha256_file
from shumozizi.knowledge.papers import (
    build_paper_indexes,
    load_paper_card_review_registry,
    read_paper_card,
)

CARD_V2_FIELDS = {
    "paper_id",
    "card_version",
    "source_id",
    "source_asset_sha256",
    "canonical_problem_id",
    "problem_asset_sha256",
    "paper_asset_sha256",
    "problem_type",
    "data_structure",
    "task_types",
    "model_family",
    "validation_methods",
    "assumption_pattern",
    "argument_pattern",
    "failure_modes",
    "transferable_patterns",
    "non_transferable_context",
    "evidence_locations",
    "review_status",
    "authoring_session_id",
}
PROMOTION_POLICY_VERSION = "paper-card-promotion-v1"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ContractError(f"{field} 不是有效 SHA-256")
    return value


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} 必须是非空字符串")
    return value


def _require_string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ContractError(f"{field} 必须是非空字符串数组")
    return value


def load_paper_source_registry(path: Path) -> dict[str, Any]:
    """读取稳定论文来源注册表。"""
    registry = load_json(path)
    if registry.get("schema_name") != "paper_source_registry" or registry.get(
        "schema_version"
    ) != "1.0":
        raise ContractError(f"无效论文来源注册表: {path}")
    sources = registry.get("sources")
    if not isinstance(sources, list):
        raise ContractError("paper_source_registry.sources 必须是数组")
    ids: set[str] = set()
    paper_ids: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ContractError("论文来源记录必须是对象")
        source_id = _require_string(source.get("source_id"), "source_id")
        paper_id = _require_string(source.get("paper_id"), "paper_id")
        if source_id in ids or paper_id in paper_ids:
            raise ContractError("论文来源 source_id 或 paper_id 重复")
        ids.add(source_id)
        paper_ids.add(paper_id)
        _require_sha256(source.get("source_asset_sha256"), "source_asset_sha256")
        problem_sha = source.get("problem_asset_sha256")
        if problem_sha is not None:
            _require_sha256(problem_sha, "problem_asset_sha256")
    return registry


def validate_card_v2(card_path: Path, source_registry_path: Path) -> dict[str, Any]:
    """校验 Card v2 front matter 与稳定来源身份。"""
    card = read_paper_card(card_path)
    metadata = card["metadata"]
    missing = sorted(CARD_V2_FIELDS - metadata.keys())
    if missing:
        raise ContractError("Paper Card v2 缺少字段: " + ", ".join(missing))
    if str(metadata["card_version"]) != "2.0":
        raise ContractError("Paper Card v2 的 card_version 必须为 2.0")
    for field in (
        "paper_id",
        "source_id",
        "canonical_problem_id",
        "problem_type",
        "data_structure",
        "assumption_pattern",
        "argument_pattern",
        "non_transferable_context",
        "authoring_session_id",
    ):
        _require_string(metadata[field], field)
    for field in (
        "task_types",
        "model_family",
        "validation_methods",
        "failure_modes",
        "transferable_patterns",
        "evidence_locations",
    ):
        _require_string_list(metadata[field], field)
    for field in ("source_asset_sha256", "problem_asset_sha256", "paper_asset_sha256"):
        _require_sha256(metadata[field], field)
    if metadata["source_asset_sha256"] != metadata["paper_asset_sha256"]:
        raise ContractError("source_asset_sha256 与 paper_asset_sha256 必须一致")
    if metadata["source_sha256"] != metadata["source_asset_sha256"]:
        raise ContractError("source_sha256 与 source_asset_sha256 必须一致")
    if metadata["review_status"] not in {"provisional", "revision_required"}:
        raise ContractError("Card v2 草稿中的 review_status 只能是 provisional 或 revision_required")

    registry = load_paper_source_registry(source_registry_path)
    source = next(
        (item for item in registry["sources"] if item["source_id"] == metadata["source_id"]),
        None,
    )
    if source is None:
        raise ContractError("Card v2 的 source_id 未登记")
    bindings = {
        "paper_id": metadata["paper_id"],
        "source_asset_sha256": metadata["source_asset_sha256"],
        "canonical_problem_id": metadata["canonical_problem_id"],
        "problem_asset_sha256": metadata["problem_asset_sha256"],
    }
    for field, expected in bindings.items():
        if source.get(field) != expected:
            raise ContractError(f"Card v2 与来源注册表的 {field} 不一致")
    return card


def validate_evidence_map(
    path: Path, *, card_path: Path, metadata: dict[str, Any]
) -> dict[str, Any]:
    """校验卡片主张到论文页码、章节和原文片段哈希的映射。"""
    evidence = load_json(path)
    if evidence.get("schema_name") != "paper_card_evidence_map" or evidence.get(
        "schema_version"
    ) != "1.0":
        raise ContractError("无效 Paper Card evidence map")
    expected = {
        "paper_id": metadata["paper_id"],
        "card_sha256": sha256_file(card_path),
        "source_id": metadata["source_id"],
        "source_asset_sha256": metadata["source_asset_sha256"],
    }
    for field, value in expected.items():
        if evidence.get(field) != value:
            raise ContractError(f"evidence map 未绑定 {field}")
    claims = evidence.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ContractError("evidence map 至少需要一条主张")
    claim_ids: set[str] = set()
    for claim in claims:
        if not isinstance(claim, dict):
            raise ContractError("evidence map claim 必须是对象")
        claim_id = _require_string(claim.get("claim_id"), "claim_id")
        if claim_id in claim_ids:
            raise ContractError("evidence map claim_id 重复")
        claim_ids.add(claim_id)
        for field in ("card_claim", "source_page", "section", "location", "review_confidence"):
            _require_string(claim.get(field), field)
        _require_sha256(claim.get("source_excerpt_sha256"), "source_excerpt_sha256")
    missing_locations = sorted(set(metadata["evidence_locations"]) - claim_ids)
    if missing_locations:
        raise ContractError("Card v2 的 evidence_locations 未覆盖: " + ", ".join(missing_locations))
    return evidence


def validate_knowledge_review(
    path: Path,
    *,
    card_path: Path,
    evidence_map_path: Path,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """校验隔离知识审核的结论和输入绑定。"""
    review = load_json(path)
    if review.get("schema_name") != "paper_card_review_report" or review.get(
        "schema_version"
    ) != "1.0":
        raise ContractError("无效 Paper Card review report")
    expected = {
        "paper_id": metadata["paper_id"],
        "card_sha256": sha256_file(card_path),
        "evidence_map_sha256": sha256_file(evidence_map_path),
        "source_asset_sha256": metadata["source_asset_sha256"],
    }
    for field, value in expected.items():
        if review.get(field) != value:
            raise ContractError(f"知识审核报告未绑定 {field}")
    for field in ("review_session_id", "reviewer_identity", "reviewer_attestation"):
        _require_string(review.get(field), field)
    if review["review_session_id"] == metadata["authoring_session_id"]:
        raise ContractError("论文卡制作与知识审核必须使用独立会话")
    if review.get("verdict") not in {"verified", "revision_required", "rejected"}:
        raise ContractError("知识审核 verdict 无效")
    findings = review.get("findings")
    if not isinstance(findings, list):
        raise ContractError("知识审核 findings 必须是数组")
    if review["verdict"] == "verified" and any(
        isinstance(item, dict) and item.get("status") == "open" for item in findings
    ):
        raise ContractError("存在 open finding 时不能判定 verified")
    return review


def promote_paper_card(repo_root: Path, paper_id: str) -> dict[str, Path]:
    """仅晋级一张通过独立审核的 Card v2，并重建双索引。"""
    root = repo_root.resolve()
    card_path = resolve_inside(
        root, f"knowledge/cards/papers/{paper_id}.md", must_exist=True
    )
    source_registry_path = root / "knowledge/reviews/paper_source_registry.json"
    card = validate_card_v2(card_path, source_registry_path)
    metadata = card["metadata"]
    evidence_map_path = resolve_inside(
        root, f"knowledge/reviews/evidence_maps/{paper_id}.json", must_exist=True
    )
    review_report_path = resolve_inside(
        root, f"knowledge/reviews/reports/{paper_id}.json", must_exist=True
    )
    validate_evidence_map(evidence_map_path, card_path=card_path, metadata=metadata)
    review = validate_knowledge_review(
        review_report_path,
        card_path=card_path,
        evidence_map_path=evidence_map_path,
        metadata=metadata,
    )
    if review["verdict"] != "verified":
        raise ContractError("只有 verdict=verified 的独立审核可以晋级")

    registry_path = root / "knowledge/reviews/paper_card_review_registry.json"
    registry = load_paper_card_review_registry(registry_path)
    current = registry["cards"].get(paper_id, {})
    if current.get("review_status") == "verified":
        raise ContractError("论文卡已经 verified，不得覆盖原晋级回执")
    receipt_path = root / f"knowledge/reviews/promotions/{paper_id}.json"
    if receipt_path.exists():
        raise ContractError("晋级回执已存在，不得覆盖")
    receipt = {
        "schema_name": "paper_card_promotion_receipt",
        "schema_version": "1.0",
        "paper_id": paper_id,
        "card_version": str(metadata["card_version"]),
        "source_id": metadata["source_id"],
        "source_asset_sha256": metadata["source_asset_sha256"],
        "source_sha256": metadata["source_sha256"],
        "card_sha256": sha256_file(card_path),
        "canonical_problem_id": metadata["canonical_problem_id"],
        "problem_asset_sha256": metadata["problem_asset_sha256"],
        "evidence_map_sha256": sha256_file(evidence_map_path),
        "review_report_sha256": sha256_file(review_report_path),
        "review_session_id": review["review_session_id"],
        "reviewer_identity": review["reviewer_identity"],
        "reviewer_attestation": review["reviewer_attestation"],
        "promotion_policy_version": PROMOTION_POLICY_VERSION,
        "promoted_at": _utc_now(),
    }
    atomic_json(receipt_path, receipt)
    registry["cards"][paper_id] = {
        "review_status": "verified",
        "promotion_receipt": f"knowledge/reviews/promotions/{paper_id}.json",
        "promotion_receipt_sha256": sha256_file(receipt_path),
    }
    atomic_json(registry_path, registry)
    build_paper_indexes(
        root / "knowledge/cards/papers",
        registry_path,
        root / "knowledge/indexes/papers_provisional.json",
        root / "knowledge/indexes/papers_verified.json",
    )
    return {
        "receipt": receipt_path,
        "registry": registry_path,
        "verified_index": root / "knowledge/indexes/papers_verified.json",
    }
