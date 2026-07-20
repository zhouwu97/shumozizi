"""为跨模块测试生成合法的空 verified 检索快照。"""

from __future__ import annotations

from pathlib import Path

from shumozizi.core.io import atomic_json, sha256_file
from shumozizi.knowledge.papers import build_paper_indexes, write_retrieval_artifacts


def seed_empty_retrieval_snapshot(repo_root: Path, run_dir: Path) -> dict[str, str]:
    """执行真实空索引检索，并返回路线产物需要的快照绑定。"""
    cards_dir = repo_root / "knowledge/cards/papers"
    cards_dir.mkdir(parents=True, exist_ok=True)
    registry_path = repo_root / "knowledge/reviews/paper_card_review_registry.json"
    if not registry_path.is_file():
        atomic_json(
            registry_path,
            {
                "schema_name": "paper_card_review_registry",
                "schema_version": "1.0",
                "default_status": "legacy_provisional",
                "cards": {},
            },
        )
    verified_path = repo_root / "knowledge/indexes/papers_verified.json"
    build_paper_indexes(
        cards_dir,
        registry_path,
        repo_root / "knowledge/indexes/papers_provisional.json",
        verified_path,
    )
    outputs = write_retrieval_artifacts(
        run_dir,
        verified_path,
        {
            "problem_type": "deterministic-test",
            "data_structure": "scalar",
            "task_types": ["calculation"],
            "keywords": ["test"],
            "canonical_problem_id": f"test-{run_dir.name}",
            "problem_asset_sha256": "e" * 64,
        },
    )
    return {
        "retrieval_snapshot_path": "knowledge/RETRIEVAL_SNAPSHOT.json",
        "retrieval_snapshot_sha256": sha256_file(outputs["retrieval_snapshot"]),
    }
