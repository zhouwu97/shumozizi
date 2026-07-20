"""Markdown 论文卡与简单索引测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from shumozizi.core.io import ContractError
from shumozizi.knowledge.papers import REQUIRED_CARD_SECTIONS, build_paper_index


def _write_card(path: Path, paper_id: str) -> None:
    sections = "\n\n".join(f"## {index}. {name}\n\n测试内容。" for index, name in enumerate(REQUIRED_CARD_SECTIONS, 1))
    path.write_text(
        "\n".join(
            [
                "---",
                f"paper_id: {paper_id}",
                f"title: {paper_id} 标题",
                "source_file: source.pdf",
                f"source_sha256: {'a' * 64}",
                "problem_type: optimization",
                "data_structure: tabular",
                "task_types:",
                "  - scheduling",
                "---",
                "",
                sections,
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_build_index_contains_only_declared_card_metadata(tmp_path: Path) -> None:
    cards = tmp_path / "knowledge/cards/papers"
    cards.mkdir(parents=True)
    _write_card(cards / "paper-b.md", "paper-b")
    _write_card(cards / "paper-a.md", "paper-a")

    document = build_paper_index(cards, tmp_path / "knowledge/indexes/papers.json")

    assert document["paper_count"] == 2
    assert [item["paper_id"] for item in document["papers"]] == ["paper-a", "paper-b"]
    assert set(document["papers"][0]) == {
        "paper_id",
        "title",
        "problem_type",
        "data_structure",
        "task_types",
        "domain_terms",
        "structural_tags",
        "source_sha256",
        "card_path",
    }


def test_build_index_rejects_duplicate_paper_ids(tmp_path: Path) -> None:
    cards = tmp_path / "cards"
    cards.mkdir()
    _write_card(cards / "one.md", "duplicate")
    _write_card(cards / "two.md", "duplicate")

    with pytest.raises(ContractError, match="paper_id 重复"):
        build_paper_index(cards, tmp_path / "papers.json")
