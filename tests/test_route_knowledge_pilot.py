"""路线前知识检索的降级与迁移边界测试。"""

from __future__ import annotations

import json
from pathlib import Path

from shumozizi.core.io import atomic_json, sha256_file
from shumozizi.knowledge.papers import (
    REQUIRED_CARD_SECTIONS,
    build_paper_indexes,
    retrieve_papers,
    write_retrieval_artifacts,
)


def _build_verified_index(tmp_path: Path, card_path: Path, paper_id: str) -> Path:
    metadata = card_path.read_text(encoding="utf-8")
    source_sha256 = next(
        line.split(":", 1)[1].strip()
        for line in metadata.splitlines()
        if line.startswith("source_sha256:")
    )
    canonical_problem_id = next(
        line.split(":", 1)[1].strip()
        for line in metadata.splitlines()
        if line.startswith("canonical_problem_id:")
    )
    problem_asset_sha256 = next(
        line.split(":", 1)[1].strip()
        for line in metadata.splitlines()
        if line.startswith("problem_asset_sha256:")
    )
    receipt_path = tmp_path / f"knowledge/reviews/promotions/{paper_id}.json"
    atomic_json(
        receipt_path,
        {
            "schema_name": "paper_card_promotion_receipt",
            "schema_version": "1.0",
            "paper_id": paper_id,
            "card_version": "2.0",
            "card_sha256": sha256_file(card_path),
            "source_sha256": source_sha256,
            "canonical_problem_id": canonical_problem_id,
            "problem_asset_sha256": problem_asset_sha256,
        },
    )
    registry_path = tmp_path / "knowledge/reviews/paper_card_review_registry.json"
    atomic_json(
        registry_path,
        {
            "schema_name": "paper_card_review_registry",
            "schema_version": "1.0",
            "default_status": "legacy_provisional",
            "cards": {
                paper_id: {
                    "review_status": "verified",
                    "promotion_receipt": f"knowledge/reviews/promotions/{paper_id}.json",
                    "promotion_receipt_sha256": sha256_file(receipt_path),
                }
            },
        },
    )
    index = tmp_path / "knowledge/indexes/papers_verified.json"
    build_paper_indexes(
        tmp_path / "knowledge/cards/papers",
        registry_path,
        tmp_path / "knowledge/indexes/papers_provisional.json",
        index,
    )
    return index


def _seed_index(tmp_path: Path) -> Path:
    cards = tmp_path / "knowledge/cards/papers"
    cards.mkdir(parents=True)
    body = "\n\n".join(
        f"## {index}. {name}\n\n" + ("迁移传热边界条件。" if name == "可迁移模式" else "不得迁移原参数。")
        for index, name in enumerate(REQUIRED_CARD_SECTIONS, 1)
    )
    (cards / "heat.md").write_text(
        "\n".join(
            [
                "---",
                "paper_id: heat",
                "card_version: '2.0'",
                "title: 热防护机理模型",
                "source_file: heat.pdf",
                f"source_sha256: {'b' * 64}",
                "competition_id: cumcm",
                "competition_year: 2018",
                "problem_code: A",
                "canonical_problem_id: cumcm-2018-a",
                f"problem_asset_sha256: {'a' * 64}",
                f"paper_asset_sha256: {'b' * 64}",
                "problem_type: mechanism",
                "data_structure: time-series",
                "task_types:",
                "  - heat-transfer",
                "---",
                "",
                body,
                "",
            ]
        ),
        encoding="utf-8",
    )
    return _build_verified_index(tmp_path, cards / "heat.md", "heat")


def test_high_confidence_match_writes_all_route_artifacts(tmp_path: Path) -> None:
    index = _seed_index(tmp_path)
    run_dir = tmp_path / "runs/unseen-problem"
    outputs = write_retrieval_artifacts(
        run_dir,
        index,
        {
            "problem_type": "mechanism",
            "data_structure": "time-series",
            "task_types": ["heat-transfer"],
            "keywords": ["热防护"],
            "question_chain": ["识别参数", "优化厚度"],
            "canonical_problem_id": "unseen-heat-problem",
            "problem_asset_sha256": "e" * 64,
        },
    )

    assert set(outputs) == {
        "task_fingerprint",
        "retrieved_patterns",
        "pattern_transfer_plan",
        "model_storyboard",
        "retrieval_snapshot",
    }
    assert all(path.is_file() for path in outputs.values())
    fingerprint = json.loads(outputs["task_fingerprint"].read_text(encoding="utf-8"))
    assert fingerprint["run_id"] == "unseen-problem"
    transfer = outputs["pattern_transfer_plan"].read_text(encoding="utf-8")
    assert "迁移传热边界条件" in transfer
    assert "不迁移原论文数字、结论、代码或题目特定参数" in transfer


def test_no_match_degrades_without_blocking_route_design(tmp_path: Path) -> None:
    index = _seed_index(tmp_path)
    run_dir = tmp_path / "runs/no-match"
    outputs = write_retrieval_artifacts(
        run_dir,
        index,
        {
            "problem_type": "network",
            "data_structure": "graph",
            "task_types": ["community-detection"],
            "keywords": ["社团"],
            "canonical_problem_id": "unseen-network-problem",
            "problem_asset_sha256": "f" * 64,
        },
    )

    retrieved = outputs["retrieved_patterns"].read_text(encoding="utf-8")
    assert "无高置信匹配" in retrieved
    assert outputs["model_storyboard"].is_file()


def test_domain_distant_statistical_match_is_not_high_confidence(tmp_path: Path) -> None:
    cards = tmp_path / "knowledge/cards/papers"
    cards.mkdir(parents=True)
    body = "\n\n".join(
        f"## {index}. {name}\n\n测试内容。"
        for index, name in enumerate(REQUIRED_CARD_SECTIONS, 1)
    )
    (cards / "wine.md").write_text(
        "\n".join(
            [
                "---",
                "paper_id: wine",
                "card_version: '2.0'",
                "title: 葡萄酒质量评价",
                "source_file: wine.pdf",
                f"source_sha256: {'c' * 64}",
                "competition_id: cumcm",
                "competition_year: 2012",
                "problem_code: A",
                "canonical_problem_id: cumcm-2012-a",
                f"problem_asset_sha256: {'d' * 64}",
                f"paper_asset_sha256: {'c' * 64}",
                "problem_type: 统计评价与预测",
                "data_structure: 多评委多指标表格",
                "task_types:",
                "  - 回归分析",
                "domain_terms:",
                "  - 葡萄酒",
                "  - 理化指标",
                "---",
                "",
                body,
                "",
            ]
        ),
        encoding="utf-8",
    )
    index = _build_verified_index(tmp_path, cards / "wine.md", "wine")

    match = retrieve_papers(
        index,
        problem_type="统计评价与预测",
        data_structure="混合类型母婴观测表格",
        task_types=["回归分析", "分类分析"],
        keywords=["母婴", "睡眠"],
        current_canonical_problem_id="unseen-mother-child-problem",
        current_problem_asset_sha256="e" * 64,
    )[0]

    assert match["structural_similarity"] == 0.5
    assert match["domain_similarity"] == 0.0
    assert match["overall_confidence"] == "medium"
    assert match["high_confidence"] is False
