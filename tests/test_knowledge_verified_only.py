"""B1 论文卡 verified-only 准入与同题排除测试。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from shumozizi.core.io import ContractError, atomic_json, sha256_file
from shumozizi.knowledge.papers import (
    REQUIRED_CARD_SECTIONS,
    build_paper_indexes,
    retrieve_papers,
    write_retrieval_artifacts,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_card(
    root: Path,
    paper_id: str = "paper-a",
    *,
    with_identity: bool = True,
    canonical_problem_id: str = "contest-2026-a",
    problem_asset_sha256: str = "a" * 64,
) -> Path:
    cards_dir = root / "knowledge/cards/papers"
    cards_dir.mkdir(parents=True, exist_ok=True)
    identity = []
    if with_identity:
        identity = [
            "card_version: '2.0'",
            "competition_id: contest",
            "competition_year: 2026",
            "problem_code: A",
            f"canonical_problem_id: {canonical_problem_id}",
            f"problem_asset_sha256: {problem_asset_sha256}",
            f"paper_asset_sha256: {'b' * 64}",
        ]
    sections = "\n\n".join(
        f"## {index}. {name}\n\n测试内容。"
        for index, name in enumerate(REQUIRED_CARD_SECTIONS, 1)
    )
    path = cards_dir / f"{paper_id}.md"
    path.write_text(
        "\n".join(
            [
                "---",
                f"paper_id: {paper_id}",
                *identity,
                "title: 通用优化方法",
                "source_file: source.pdf",
                f"source_sha256: {'b' * 64}",
                "problem_type: optimization",
                "data_structure: tabular",
                "task_types:",
                "  - scheduling",
                "domain_terms:",
                "  - 优化",
                "---",
                "",
                sections,
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _write_registry(root: Path, cards: dict[str, dict[str, str | None]]) -> Path:
    path = root / "knowledge/reviews/paper_card_review_registry.json"
    atomic_json(
        path,
        {
            "schema_name": "paper_card_review_registry",
            "schema_version": "1.0",
            "default_status": "legacy_provisional",
            "cards": cards,
        },
    )
    return path


def _promote(root: Path, card_path: Path, paper_id: str = "paper-a") -> Path:
    receipt_path = root / f"knowledge/reviews/promotions/{paper_id}.json"
    atomic_json(
        receipt_path,
        {
            "schema_name": "paper_card_promotion_receipt",
            "schema_version": "1.0",
            "paper_id": paper_id,
            "card_version": "2.0",
            "card_sha256": sha256_file(card_path),
            "source_sha256": "b" * 64,
            "canonical_problem_id": "contest-2026-a",
            "problem_asset_sha256": "a" * 64,
        },
    )
    return _write_registry(
        root,
        {
            paper_id: {
                "review_status": "verified",
                "promotion_receipt": f"knowledge/reviews/promotions/{paper_id}.json",
                "promotion_receipt_sha256": sha256_file(receipt_path),
            }
        },
    )


def _build(root: Path, registry_path: Path) -> dict[str, dict]:
    return build_paper_indexes(
        root / "knowledge/cards/papers",
        registry_path,
        root / "knowledge/indexes/papers_provisional.json",
        root / "knowledge/indexes/papers_verified.json",
    )


def test_existing_ten_cards_are_provisional_and_none_are_verified(tmp_path: Path) -> None:
    shutil.copytree(REPO_ROOT / "knowledge/cards/papers", tmp_path / "knowledge/cards/papers")
    registry = tmp_path / "knowledge/reviews/paper_card_review_registry.json"
    registry.parent.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "knowledge/reviews/paper_card_review_registry.json", registry)

    indexes = _build(tmp_path, registry)

    assert indexes["provisional"]["paper_count"] == 10
    assert indexes["verified"]["paper_count"] == 0
    assert {
        entry["review_status"] for entry in indexes["provisional"]["papers"]
    } == {"legacy_provisional"}


def test_card_without_registry_record_defaults_to_legacy_provisional(tmp_path: Path) -> None:
    _write_card(tmp_path, with_identity=False)
    indexes = _build(tmp_path, _write_registry(tmp_path, {}))

    assert indexes["provisional"]["papers"][0]["review_status"] == "legacy_provisional"
    assert indexes["verified"]["paper_count"] == 0


def test_registry_cannot_mark_card_verified_without_promotion_receipt(tmp_path: Path) -> None:
    _write_card(tmp_path)
    registry = _write_registry(
        tmp_path,
        {
            "paper-a": {
                "review_status": "verified",
                "promotion_receipt": None,
                "promotion_receipt_sha256": None,
            }
        },
    )

    with pytest.raises(ContractError, match="缺少 promotion receipt"):
        _build(tmp_path, registry)


@pytest.mark.parametrize(
    ("canonical_problem_id", "problem_asset_sha256"),
    [("contest-2026-a", "f" * 64), ("other-problem", "a" * 64)],
)
def test_same_problem_identity_is_hard_excluded(
    tmp_path: Path,
    canonical_problem_id: str,
    problem_asset_sha256: str,
) -> None:
    card = _write_card(tmp_path)
    _build(tmp_path, _promote(tmp_path, card))

    matches = retrieve_papers(
        tmp_path / "knowledge/indexes/papers_verified.json",
        problem_type="optimization",
        data_structure="tabular",
        task_types=["scheduling"],
        keywords=["优化"],
        current_canonical_problem_id=canonical_problem_id,
        current_problem_asset_sha256=problem_asset_sha256,
    )

    assert matches == []


def test_empty_verified_index_keeps_route_generation_and_never_falls_back(
    tmp_path: Path,
) -> None:
    _write_card(tmp_path, with_identity=False)
    _build(tmp_path, _write_registry(tmp_path, {}))
    outputs = write_retrieval_artifacts(
        tmp_path / "runs/empty-verified",
        tmp_path / "knowledge/indexes/papers_verified.json",
        {
            "problem_type": "optimization",
            "data_structure": "tabular",
            "task_types": ["scheduling"],
            "keywords": ["优化"],
            "canonical_problem_id": "unseen-empty-index",
            "problem_asset_sha256": "e" * 64,
        },
    )

    retrieved = outputs["retrieved_patterns"].read_text(encoding="utf-8")
    assert "本轮没有使用经过验证的论文知识卡" in retrieved
    assert "通用优化方法" not in retrieved
    assert outputs["model_storyboard"].is_file()


def test_retrieval_requires_current_problem_identity(tmp_path: Path) -> None:
    _write_card(tmp_path, with_identity=False)
    _build(tmp_path, _write_registry(tmp_path, {}))

    with pytest.raises(ContractError, match="当前题身份字段"):
        write_retrieval_artifacts(
            tmp_path / "runs/missing-identity",
            tmp_path / "knowledge/indexes/papers_verified.json",
            {
                "problem_type": "optimization",
                "data_structure": "tabular",
                "task_types": ["scheduling"],
                "keywords": ["优化"],
            },
        )


def test_production_retrieval_rejects_provisional_index(tmp_path: Path) -> None:
    _write_card(tmp_path, with_identity=False)
    _build(tmp_path, _write_registry(tmp_path, {}))

    with pytest.raises(ContractError, match="只允许使用 verified 索引"):
        retrieve_papers(
            tmp_path / "knowledge/indexes/papers_provisional.json",
            problem_type="optimization",
            data_structure="tabular",
            task_types=["scheduling"],
            keywords=["优化"],
        )


def test_dual_index_build_is_deterministic(tmp_path: Path) -> None:
    _write_card(tmp_path, with_identity=False)
    registry = _write_registry(tmp_path, {})
    _build(tmp_path, registry)
    first = {
        path.name: path.read_bytes() for path in (tmp_path / "knowledge/indexes").glob("*.json")
    }

    _build(tmp_path, registry)
    second = {
        path.name: path.read_bytes() for path in (tmp_path / "knowledge/indexes").glob("*.json")
    }

    assert first == second


def test_checked_in_dual_indexes_match_schema_and_registry() -> None:
    schema = json.loads(
        (REPO_ROOT / "schemas/paper_card_index.schema.json").read_text(encoding="utf-8")
    )
    for name in ("papers_provisional.json", "papers_verified.json"):
        document = json.loads(
            (REPO_ROOT / f"knowledge/indexes/{name}").read_text(encoding="utf-8")
        )
        Draft202012Validator(schema).validate(document)


def test_legacy_index_is_an_empty_diagnostic_stub() -> None:
    document = json.loads(
        (REPO_ROOT / "knowledge/indexes/papers.json").read_text(encoding="utf-8")
    )

    assert document["index_kind"] == "legacy_diagnostic_stub"
    assert document["paper_count"] == 0
    assert document["papers"] == []
