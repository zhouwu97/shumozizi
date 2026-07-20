"""B3 Card v2、证据图、独立审核与单卡晋级测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import shumozizi.knowledge.promotion as promotion_module
from shumozizi.core.io import ContractError, atomic_json, sha256_file
from shumozizi.knowledge.papers import REQUIRED_CARD_SECTIONS, load_paper_index
from shumozizi.knowledge.promotion import promote_paper_card
from shumozizi.knowledge.reviews import (
    claim_knowledge_review_request,
    create_knowledge_review_request,
)


def _seed_v2(
    root: Path,
    *,
    paper_id: str = "paper-v2",
    claimed: bool = True,
    thread_id: str = "independent-review-thread",
) -> tuple[Path, Path, Path]:
    cards = root / "knowledge/cards/papers"
    cards.mkdir(parents=True, exist_ok=True)
    sections = "\n\n".join(
        f"## {index}. {name}\n\n测试内容。"
        for index, name in enumerate(REQUIRED_CARD_SECTIONS, 1)
    )
    card_path = cards / f"{paper_id}.md"
    card_path.write_text(
        "\n".join(
            [
                "---",
                f"paper_id: {paper_id}",
                "card_version: '2.0'",
                "title: 独立审核论文卡",
                "source_file: paper.pdf",
                f"source_sha256: {'b' * 64}",
                f"source_asset_sha256: {'b' * 64}",
                f"paper_asset_sha256: {'b' * 64}",
                f"problem_asset_sha256: {'a' * 64}",
                f"source_id: src-{paper_id}",
                "competition_id: contest",
                "competition_year: 2026",
                "problem_code: A",
                "canonical_problem_id: contest-2026-a",
                "problem_type: optimization",
                "data_structure: tabular",
                "task_types: [scheduling]",
                "model_family: [mixed-integer-programming]",
                "validation_methods: [small-instance-enumeration]",
                "assumption_pattern: 先声明容量与时间窗假设",
                "argument_pattern: 基线到主模型再到稳健性验证",
                "failure_modes: [遗漏硬约束]",
                "transferable_patterns: [约束分层检查]",
                "non_transferable_context: 原题参数和最优值不得迁移",
                "evidence_locations: [claim-1]",
                "review_status: provisional",
                "authoring_session_id: author-session",
                "---",
                "",
                sections,
                "",
            ]
        ),
        encoding="utf-8",
    )
    reviews = root / "knowledge/reviews"
    atomic_json(
        reviews / "paper_source_registry.json",
        {
            "schema_name": "paper_source_registry",
            "schema_version": "1.0",
            "sources": [
                {
                    "source_id": f"src-{paper_id}",
                    "paper_id": paper_id,
                    "source_asset_sha256": "b" * 64,
                    "problem_asset_sha256": "a" * 64,
                    "canonical_problem_id": "contest-2026-a",
                    "source_type": "official_awarded_paper",
                    "origin": "local-read-only/paper.pdf",
                    "retrieved_at": "2026-07-20T00:00:00Z",
                    "license_or_access_note": "仅用于本地知识学习",
                }
            ],
        },
    )
    atomic_json(
        reviews / "paper_card_review_registry.json",
        {
            "schema_name": "paper_card_review_registry",
            "schema_version": "1.0",
            "default_status": "legacy_provisional",
            "cards": {
                paper_id: {
                    "review_status": "provisional",
                    "promotion_receipt": None,
                    "promotion_receipt_sha256": None,
                }
            },
        },
    )
    evidence_path = reviews / f"evidence_maps/{paper_id}.json"
    atomic_json(
        evidence_path,
        {
            "schema_name": "paper_card_evidence_map",
            "schema_version": "1.0",
            "paper_id": paper_id,
            "card_sha256": sha256_file(card_path),
            "source_id": f"src-{paper_id}",
            "source_asset_sha256": "b" * 64,
            "claims": [
                {
                    "claim_id": "claim-1",
                    "card_claim": "约束应分层验证",
                    "source_page": "12",
                    "section": "4.2",
                    "location": "公式(8)及表3",
                    "source_excerpt_sha256": "c" * 64,
                    "review_confidence": "high",
                }
            ],
        },
    )
    request_path: Path | None = None
    session_path: Path | None = None
    session: dict[str, object] | None = None
    if claimed:
        request_path = create_knowledge_review_request(root, paper_id)
        session_path = claim_knowledge_review_request(
            request_path,
            thread_id=thread_id,
            reviewer_identity="independent-knowledge-reviewer",
        )
        session = json.loads(session_path.read_text(encoding="utf-8"))
    review_path = reviews / f"reports/{paper_id}.json"
    review = {
        "schema_name": "paper_card_review_report",
        "schema_version": "1.0",
        "paper_id": paper_id,
        "card_sha256": sha256_file(card_path),
        "evidence_map_sha256": sha256_file(evidence_path),
        "source_asset_sha256": "b" * 64,
        "review_session_id": (
            session["session_id"] if session else "independent-review-session"
        ),
        "reviewer_identity": "independent-knowledge-reviewer",
        "reviewer_attestation": "未参与论文卡制作并逐项核对原文证据",
        "verdict": "verified",
        "findings": [],
        "reviewed_at": "2026-07-20T01:00:00Z",
    }
    if request_path and session_path and session:
        review.update(
            {
                "review_request_sha256": sha256_file(request_path),
                "review_session_sha256": sha256_file(session_path),
                "attestation_level": session["attestation_level"],
            }
        )
    atomic_json(review_path, review)
    return card_path, evidence_path, review_path


def test_single_card_promotion_binds_all_evidence_and_enters_verified_index(
    tmp_path: Path,
) -> None:
    card_path, evidence_path, review_path = _seed_v2(tmp_path)

    outputs = promote_paper_card(tmp_path, "paper-v2")

    receipt = json.loads(outputs["receipt"].read_text(encoding="utf-8"))
    registry = json.loads(outputs["registry"].read_text(encoding="utf-8"))
    verified = load_paper_index(outputs["verified_index"], production=True)
    assert receipt["card_sha256"] == sha256_file(card_path)
    assert receipt["evidence_map_sha256"] == sha256_file(evidence_path)
    assert receipt["review_request_sha256"] == sha256_file(
        tmp_path
        / "knowledge/reviews/requests/paper-v2/knowledge_review_request.json"
    )
    assert receipt["review_session_sha256"] == sha256_file(
        tmp_path
        / "knowledge/reviews/requests/paper-v2/knowledge_review_session.json"
    )
    assert receipt["review_report_sha256"] == sha256_file(review_path)
    assert receipt["attestation_level"] == "self_declared"
    assert receipt["promotion_policy_version"] == "paper-card-promotion-v1"
    assert registry["cards"]["paper-v2"]["review_status"] == "verified"
    assert [item["paper_id"] for item in verified["papers"]] == ["paper-v2"]


def test_promotion_requires_claimed_knowledge_review_session(tmp_path: Path) -> None:
    _seed_v2(tmp_path, claimed=False)

    with pytest.raises(ContractError, match="knowledge_review_request"):
        promote_paper_card(tmp_path, "paper-v2")


def test_knowledge_review_request_is_single_claim_and_top_level(tmp_path: Path) -> None:
    _seed_v2(tmp_path)
    request_path = (
        tmp_path
        / "knowledge/reviews/requests/paper-v2/knowledge_review_request.json"
    )
    session = json.loads(
        request_path.with_name("knowledge_review_session.json").read_text(
            encoding="utf-8"
        )
    )

    assert session["execution_policy"] == {
        "new_thread": True,
        "subagent": False,
        "forked": False,
        "context_inherited": False,
    }
    assert session["executor"]["task_kind"] == "top_level"
    assert session["executor"]["parent_thread_id"] is None
    with pytest.raises(ContractError, match="只能领取一次"):
        claim_knowledge_review_request(
            request_path,
            thread_id="another-review-thread",
            reviewer_identity="another-reviewer",
        )


def test_knowledge_review_thread_cannot_claim_two_requests(tmp_path: Path) -> None:
    _seed_v2(tmp_path, thread_id="shared-review-thread")
    _, _, report_path = _seed_v2(tmp_path, paper_id="paper-v3", claimed=False)
    report_path.unlink()
    request_path = create_knowledge_review_request(tmp_path, "paper-v3")

    with pytest.raises(ContractError, match="thread_id"):
        claim_knowledge_review_request(
            request_path,
            thread_id="shared-review-thread",
            reviewer_identity="second-reviewer",
        )


def test_revision_required_review_cannot_promote(tmp_path: Path) -> None:
    _, _, review_path = _seed_v2(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["verdict"] = "revision_required"
    atomic_json(review_path, review)

    with pytest.raises(ContractError, match="只有 verdict=verified"):
        promote_paper_card(tmp_path, "paper-v2")


def test_authoring_and_review_sessions_must_be_independent(tmp_path: Path) -> None:
    _, _, review_path = _seed_v2(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["review_session_id"] = "author-session"
    atomic_json(review_path, review)

    with pytest.raises(ContractError, match="review_session_id"):
        promote_paper_card(tmp_path, "paper-v2")


def test_evidence_map_tampering_revokes_production_read(tmp_path: Path) -> None:
    _, evidence_path, _ = _seed_v2(tmp_path)
    outputs = promote_paper_card(tmp_path, "paper-v2")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["claims"][0]["source_page"] = "99"
    atomic_json(evidence_path, evidence)

    with pytest.raises(ContractError, match="evidence map 已变化"):
        load_paper_index(outputs["verified_index"], production=True)


def test_completed_card_promotion_is_idempotent(tmp_path: Path) -> None:
    _seed_v2(tmp_path)
    first = promote_paper_card(tmp_path, "paper-v2")
    receipt_sha256 = sha256_file(first["receipt"])

    second = promote_paper_card(tmp_path, "paper-v2")

    assert sha256_file(second["receipt"]) == receipt_sha256
    assert load_paper_index(second["verified_index"], production=True)["paper_count"] == 1


def test_card_promotion_rejects_mismatched_existing_receipt(tmp_path: Path) -> None:
    _seed_v2(tmp_path)
    outputs = promote_paper_card(tmp_path, "paper-v2")
    receipt = json.loads(outputs["receipt"].read_text(encoding="utf-8"))
    receipt["reviewer_identity"] = "tampered-reviewer"
    atomic_json(outputs["receipt"], receipt)

    with pytest.raises(ContractError, match="晋级回执与当前晋级事实不一致"):
        promote_paper_card(tmp_path, "paper-v2")


def test_card_promotion_recovers_after_registry_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_v2(tmp_path)
    real_atomic_json = promotion_module.atomic_json

    def fail_registry_write(path: Path, document: dict) -> None:
        if path.name == "paper_card_review_registry.json":
            raise OSError("injected registry failure")
        real_atomic_json(path, document)

    monkeypatch.setattr(promotion_module, "atomic_json", fail_registry_write)
    with pytest.raises(OSError, match="injected registry failure"):
        promote_paper_card(tmp_path, "paper-v2")
    receipt_path = tmp_path / "knowledge/reviews/promotions/paper-v2.json"
    receipt_sha256 = sha256_file(receipt_path)

    monkeypatch.setattr(promotion_module, "atomic_json", real_atomic_json)
    outputs = promote_paper_card(tmp_path, "paper-v2")

    assert sha256_file(outputs["receipt"]) == receipt_sha256
    registry = json.loads(outputs["registry"].read_text(encoding="utf-8"))
    assert registry["cards"]["paper-v2"]["review_status"] == "verified"
    assert load_paper_index(outputs["verified_index"], production=True)["paper_count"] == 1
