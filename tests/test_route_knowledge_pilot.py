"""路线前知识检索的降级与迁移边界测试。"""

from __future__ import annotations

import json
from pathlib import Path

from shumozizi.knowledge.papers import (
    REQUIRED_CARD_SECTIONS,
    build_paper_index,
    retrieve_papers,
    write_retrieval_artifacts,
)


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
                "title: 热防护机理模型",
                "source_file: heat.pdf",
                f"source_sha256: {'b' * 64}",
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
    index = tmp_path / "knowledge/indexes/papers.json"
    build_paper_index(cards, index)
    return index


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
        },
    )

    assert set(outputs) == {
        "task_fingerprint",
        "retrieved_patterns",
        "pattern_transfer_plan",
        "model_storyboard",
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
                "title: 葡萄酒质量评价",
                "source_file: wine.pdf",
                f"source_sha256: {'c' * 64}",
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
    index = tmp_path / "knowledge/indexes/papers.json"
    build_paper_index(cards, index)

    match = retrieve_papers(
        index,
        problem_type="统计评价与预测",
        data_structure="混合类型母婴观测表格",
        task_types=["回归分析", "分类分析"],
        keywords=["母婴", "睡眠"],
    )[0]

    assert match["structural_similarity"] == 0.5
    assert match["domain_similarity"] == 0.0
    assert match["overall_confidence"] == "medium"
    assert match["high_confidence"] is False
