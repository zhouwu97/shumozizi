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


def test_controlled_structure_concepts_match_long_fingerprint_to_compact_card(
    tmp_path: Path,
) -> None:
    """长题面指纹可命中同构统计卡，但不依赖题名或领域词。"""
    cards = tmp_path / "knowledge/cards/papers"
    cards.mkdir(parents=True)
    body = "\n\n".join(
        f"## {index}. {name}\n\n测试内容。"
        for index, name in enumerate(REQUIRED_CARD_SECTIONS, 1)
    )
    (cards / "longitudinal.md").write_text(
        "\n".join(
            [
                "---",
                "paper_id: longitudinal",
                "title: 设备检测案例",
                "source_file: longitudinal.pdf",
                f"source_sha256: {'d' * 64}",
                "problem_type: 纵向统计、区间删失与风险决策",
                "data_structure: 个体重复检测记录与首次阈值事件区间",
                "task_types:",
                "  - 纵向非线性建模",
                "  - 区间删失生存分析",
                "  - 阈值时点决策",
                "  - 分组交叉验证",
                "structural_tags:",
                "  - 个体内相关",
                "  - 阈值事件观测不完全",
                "  - 建议值不确定性",
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
        problem_type="多次采样下的非线性时间关系、首次达到阈值的删失事件与风险最小化",
        data_structure="同一主体多次采样，首次阈值只知道位于相邻记录之间",
        task_types=["重复测量回归建模", "时间阈值反演", "按主体分组验证"],
        keywords=["完全不相干的领域词"],
        structural_tags=["重复测量纵向回归", "时间阈值反演", "测量误差传播"],
    )[0]

    assert match["paper_id"] == "longitudinal"
    assert match["structural_similarity"] >= 0.6
    assert match["domain_similarity"] == 0.0
    assert any("结构概念匹配" in reason for reason in match["match_reasons"])


def test_strong_structural_overlap_survives_low_blended_score(tmp_path: Path) -> None:
    """structural_tags 强概念重叠不被四字段加权稀释到 0.30 混合阈值以下。"""
    cards = tmp_path / "knowledge/cards/papers"
    cards.mkdir(parents=True)
    body = "\n\n".join(
        f"## {index}. {name}\n\n"
        + (
            "首次阈值事件按区间删失建模，并按主体分组验证。"
            if name == "可迁移模式"
            else "测试内容。"
        )
        for index, name in enumerate(REQUIRED_CARD_SECTIONS, 1)
    )
    (cards / "longitudinal.md").write_text(
        "\n".join(
            [
                "---",
                "paper_id: longitudinal",
                "title: 无关领域标题",
                "source_file: longitudinal.pdf",
                f"source_sha256: {'e' * 64}",
                "problem_type: 完全无关的物理机理",
                "data_structure: 无任何统计结构的文本",
                "task_types:",
                "  - 物理模拟",
                "structural_tags:",
                "  - 个体内相关",
                "  - 阈值事件观测不完全",
                "  - 建议值不确定性",
                "  - 按主体分组验证",
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

    run_dir = tmp_path / "runs/strong-overlap"
    from shumozizi.knowledge.retrieval import write_analysis_knowledge_retrieval

    out = write_analysis_knowledge_retrieval(
        run_dir,
        index,
        {
            "problem_type": "多次采样下的非线性时间关系、首次达到阈值的删失事件与风险最小化",
            "data_structure": "同一主体多次采样，首次阈值只知道位于相邻记录之间",
            "task_types": ["重复测量回归建模", "时间阈值反演", "按主体分组验证"],
            "keywords": ["完全不相干的领域词"],
            "statistical_units": [],
            "mathematical_difficulties": [],
            "objective_structures": [],
            "constraint_types": [],
            "validation_risks": [],
            "structural_tags": ["个体内相关", "阈值事件观测不完全", "建议值不确定性"],
        },
    )
    artifact = json.loads(out.read_text(encoding="utf-8"))
    assert artifact["status"] == "matched"
    assert any(
        card["paper_id"] == "longitudinal" for card in artifact["matched_cards"]
    )
