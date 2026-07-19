"""建立并使用可复验知识索引；知识层不参与状态推进。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.core.schema import require_valid


def build_knowledge_index(repo_root: Path) -> dict[str, Any]:
    """校验来源与知识卡，并生成绑定内容哈希的稳定索引。"""
    registry_path = repo_root / "knowledge" / "SOURCE_REGISTRY.json"
    registry = load_json(registry_path)
    require_valid(registry, "external_source_registry")
    source_ids = {source["source_id"] for source in registry["sources"]}
    if len(source_ids) != len(registry["sources"]):
        raise ContractError("SOURCE_REGISTRY 中 source_id 重复")
    cards: list[dict[str, Any]] = []
    seen_cards: set[str] = set()
    for path in sorted((repo_root / "knowledge" / "cards").glob("*.json")):
        card = load_json(path)
        require_valid(card, "knowledge_card")
        if card["card_id"] in seen_cards:
            raise ContractError(f"知识卡 ID 重复: {card['card_id']}")
        missing_sources = sorted(set(card["source_ids"]) - source_ids)
        if missing_sources:
            raise ContractError(f"知识卡引用未知来源: {', '.join(missing_sources)}")
        seen_cards.add(card["card_id"])
        cards.append(
            {
                "card_id": card["card_id"],
                "path": path.relative_to(repo_root).as_posix(),
                "sha256": sha256_file(path),
                "source_ids": card["source_ids"],
                "tags": card["tags"],
            }
        )
    index = {
        "schema_name": "knowledge_index",
        "schema_version": "2.0",
        "source_registry_sha256": sha256_file(registry_path),
        "cards": cards,
    }
    require_valid(index, "knowledge_index")
    atomic_json(repo_root / "knowledge" / "INDEX.json", index)
    return index


def verify_knowledge_index(repo_root: Path) -> dict[str, Any]:
    """复验索引绑定的来源登记和每张知识卡内容。"""
    index = load_json(repo_root / "knowledge" / "INDEX.json")
    require_valid(index, "knowledge_index")
    registry_path = repo_root / "knowledge" / "SOURCE_REGISTRY.json"
    if index["source_registry_sha256"] != sha256_file(registry_path):
        raise ContractError("知识索引绑定的来源登记哈希已失效")
    for entry in index["cards"]:
        path = repo_root / entry["path"]
        if sha256_file(path) != entry["sha256"]:
            raise ContractError(f"知识卡哈希已失效: {entry['card_id']}")
        card = load_json(path)
        require_valid(card, "knowledge_card")
        if card["card_id"] != entry["card_id"]:
            raise ContractError(f"知识卡 ID 与索引不一致: {entry['path']}")
    return index


def select_knowledge_cards(repo_root: Path, tags: set[str]) -> list[dict[str, Any]]:
    """从已复验索引返回与输入标签交集最大的知识卡。"""
    index = verify_knowledge_index(repo_root)
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for entry in index["cards"]:
        path = repo_root / entry["path"]
        card = load_json(path)
        score = len(tags.intersection(card.get("tags", [])))
        if score:
            ranked.append((score, card["card_id"], card))
    return [item[2] for item in sorted(ranked, key=lambda item: (-item[0], item[1]))]
