"""验证仓内论文卡从存储能力进入 v3.2 主流程。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, load_json
from shumozizi.knowledge.papers import REQUIRED_CARD_SECTIONS, build_paper_index
from shumozizi.knowledge.retrieval import (
    record_analysis_knowledge_decisions,
    require_analysis_knowledge_retrieval,
    require_paper_knowledge_application,
    write_analysis_knowledge_retrieval,
    write_paper_knowledge_application,
)
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.modeling_units import require_v32_modeling_plan
from shumozizi.simple.revisions import classify_revision
from shumozizi.simple.state import read_simple_state

REPO_ROOT = Path(__file__).resolve().parents[2]


def _seed_card(
    root: Path,
    *,
    paper_id: str = "structural-card",
    title: str = "跨领域纵向决策案例",
    problem_type: str = "纵向统计与决策",
    data_structure: str = "个体重复测量表",
    task_types: list[str] | None = None,
    domain_terms: list[str] | None = None,
    structural_tags: list[str] | None = None,
    transferable: str | None = None,
) -> Path:
    """写入一张完整论文卡并重建测试索引。"""
    cards = root / "knowledge/cards/papers"
    cards.mkdir(parents=True, exist_ok=True)
    sections: list[str] = []
    for index, name in enumerate(REQUIRED_CARD_SECTIONS, start=1):
        content = "本节记录结构化研究经验。"
        if name == "可迁移模式":
            content = transferable or (
                "- 按个体而非观测记录划分验证集。\n"
                "- 先定义评价模型，再把阈值选择写成决策模型。"
            )
        elif name == "不可迁移内容":
            content = "原题参数、公式、代码、数值结论和奖项评价均不得迁移。"
        sections.extend([f"## {index}. {name}", "", content, ""])
    metadata = [
        "---",
        f"paper_id: {paper_id}",
        f"title: {title}",
        f"source_file: {paper_id}.pdf",
        f"source_sha256: {'a' * 64}",
        f"problem_type: {problem_type}",
        f"data_structure: {data_structure}",
        "task_types:",
        *[f"  - {item}" for item in (task_types or ["分组验证", "阈值决策"])],
    ]
    if domain_terms:
        metadata.extend(["domain_terms:", *[f"  - {item}" for item in domain_terms]])
    if structural_tags:
        metadata.extend(
            ["structural_tags:", *[f"  - {item}" for item in structural_tags]]
        )
    card_path = cards / f"{paper_id}.md"
    card_path.write_text(
        "\n".join([*metadata, "---", "", *sections]),
        encoding="utf-8",
    )
    index_path = root / "knowledge/indexes/papers.json"
    build_paper_index(cards, index_path)
    return index_path


def _fingerprint(**changes: object) -> dict[str, object]:
    """返回结构字段比领域词更丰富的测试任务指纹。"""
    payload: dict[str, object] = {
        "problem_type": "纵向统计与决策",
        "data_structure": "个体重复测量表",
        "task_types": ["分组验证", "阈值决策"],
        "statistical_units": ["个体级"],
        "mathematical_difficulties": ["重复测量", "删失结构"],
        "objective_structures": ["评价到决策"],
        "constraint_types": ["可靠性约束"],
        "validation_risks": ["同一个体跨折泄漏"],
        "structural_tags": ["多问共享样本键"],
        "keywords": ["NIPT"],
    }
    payload.update(changes)
    return payload


def _complete_analysis_decisions(run_dir: Path) -> dict[str, object]:
    """对检索返回的全部模式作出一项采用、其余拒绝的判断。"""
    document = load_json(run_dir / "knowledge/analysis-retrieval.json")
    pattern_ids = [
        pattern["pattern_id"]
        for card in document["matched_cards"]
        for pattern in card["candidate_patterns"]
    ]
    accepted = [
        {
            "pattern_id": pattern_ids[0],
            "reason": "该模式直接针对当前题的个体级验证风险。",
            "route_application": "在当前题中按孕妇标识完成训练验证分组。",
        }
    ]
    rejected = [
        {
            "pattern_id": pattern_id,
            "reason": "当前题已有更直接的建模合同，不需要重复迁移。",
        }
        for pattern_id in pattern_ids[1:]
    ]
    record_analysis_knowledge_decisions(
        run_dir,
        accepted_patterns=accepted,
        rejected_patterns=rejected,
    )
    return load_json(run_dir / "knowledge/analysis-retrieval.json")


def test_missing_analysis_retrieval_blocks_formal_route_freeze(tmp_path: Path) -> None:
    """仓库已有卡片时，未执行检索不能正式进入实验。"""
    _seed_card(tmp_path)
    run_dir = initialize_simple_run(
        tmp_path, "missing-retrieval", workflow_version="3.2", required_questions=["Q1"]
    )

    with pytest.raises(ContractError, match="analysis-retrieval.json"):
        require_v32_modeling_plan(run_dir)


def test_no_relevant_match_is_a_valid_completed_retrieval(tmp_path: Path) -> None:
    """没有结构相关卡片时可以明确降级并继续。"""
    index = _seed_card(tmp_path)
    run_dir = initialize_simple_run(tmp_path, "no-match", workflow_version="3.2")
    path = write_analysis_knowledge_retrieval(
        run_dir,
        index,
        _fingerprint(
            problem_type="空间组合优化",
            data_structure="离散图像片段",
            task_types=["路径搜索"],
            structural_tags=["图匹配"],
        ),
    )

    assert load_json(path)["status"] == "no_relevant_match"
    require_analysis_knowledge_retrieval(run_dir)


def test_domain_title_match_cannot_replace_structural_match(tmp_path: Path) -> None:
    """只命中标题和领域词的卡片不得成为分析候选。"""
    index = _seed_card(
        tmp_path,
        title="NIPT 首次达标与风险分类",
        problem_type="空间组合优化",
        data_structure="图像片段",
        task_types=["路径搜索"],
        domain_terms=["NIPT"],
    )
    run_dir = initialize_simple_run(tmp_path, "title-only", workflow_version="3.2")
    path = write_analysis_knowledge_retrieval(run_dir, index, _fingerprint())

    document = load_json(path)
    assert document["status"] == "no_relevant_match"
    assert document["matched_cards"] == []


def test_same_domain_wrong_structure_is_downweighted(tmp_path: Path) -> None:
    """同领域错结构卡片不能压过跨领域同结构卡片。"""
    _seed_card(
        tmp_path,
        paper_id="same-domain-wrong-structure",
        title="NIPT 风险分析",
        problem_type="空间组合优化",
        data_structure="规则图像网格",
        task_types=["路径搜索"],
        domain_terms=["NIPT"],
    )
    index = _seed_card(
        tmp_path,
        paper_id="cross-domain-right-structure",
        title="设备重复检测策略",
        domain_terms=["工业设备"],
        structural_tags=["多问共享样本键"],
    )
    run_dir = initialize_simple_run(tmp_path, "structure-first", workflow_version="3.2")
    document = load_json(
        write_analysis_knowledge_retrieval(run_dir, index, _fingerprint())
    )

    assert [card["paper_id"] for card in document["matched_cards"]] == [
        "cross-domain-right-structure"
    ]


def test_retrieval_never_selects_or_rewrites_a_route(tmp_path: Path) -> None:
    """检索只生成候选启发，不自动晋级路线。"""
    index = _seed_card(tmp_path)
    run_dir = initialize_simple_run(tmp_path, "advisory-only", workflow_version="3.2")
    before_plan = (run_dir / "analysis/MODELING_UNITS.json").read_bytes()
    before_state = read_simple_state(run_dir)

    write_analysis_knowledge_retrieval(run_dir, index, _fingerprint())

    assert (run_dir / "analysis/MODELING_UNITS.json").read_bytes() == before_plan
    after_state = read_simple_state(run_dir)
    assert after_state["selected_route"] == before_state["selected_route"] is None
    assert after_state["phase"] == "analysis"


def test_numbers_formulas_and_code_do_not_enter_transfer_artifacts(tmp_path: Path) -> None:
    """题目特定数字、公式和代码不会进入分析或写作迁移文件。"""
    index = _seed_card(
        tmp_path,
        transferable=(
            "- 使用阈值 0.92342 并写出 y = ax + b。\n"
            "```python\nprint('forbidden-code')\n```\n"
            "- 把模型与算法分离，再由当前题数据重新验证。"
        ),
    )
    run_dir = initialize_simple_run(tmp_path, "safe-transfer", workflow_version="3.2")
    analysis_path = write_analysis_knowledge_retrieval(run_dir, index, _fingerprint())
    _complete_analysis_decisions(run_dir)
    paper_path = write_paper_knowledge_application(run_dir)

    combined = analysis_path.read_text(encoding="utf-8") + paper_path.read_text(encoding="utf-8")
    assert "0.92342" not in combined
    assert "y = ax + b" not in combined
    assert "forbidden-code" not in combined
    assert "把模型与算法分离" in combined


def test_paper_application_requires_a_decision_for_every_pattern(tmp_path: Path) -> None:
    """写论证计划前必须逐项完成采用或拒绝。"""
    index = _seed_card(tmp_path)
    run_dir = initialize_simple_run(tmp_path, "paper-decisions", workflow_version="3.2")
    write_analysis_knowledge_retrieval(run_dir, index, _fingerprint())
    document = _complete_analysis_decisions(run_dir)
    path = write_paper_knowledge_application(run_dir)

    with pytest.raises(ContractError, match="必须明确采用或拒绝"):
        require_paper_knowledge_application(run_dir)

    text = path.read_text(encoding="utf-8")
    first = True
    for card in document["matched_cards"]:
        for _pattern in card["candidate_patterns"]:
            if first:
                replacement = (
                    "- 写作决定：采用\n"
                    "- 理由：该模式能解释当前论文的验证单位选择。\n"
                    "- 应用位置：问题分析与验证设计\n"
                    "- 当前题证据：当前题重复检测数据存在个体跨折泄漏风险。"
                )
                first = False
            else:
                replacement = (
                    "- 写作决定：拒绝\n"
                    "- 理由：当前题的论证链不需要该结构模式。\n"
                    "- 应用位置：不适用\n"
                    "- 当前题证据：不适用"
                )
            text = text.replace(
                "- 写作决定：待判断\n- 理由：待填写\n- 应用位置：待填写\n- 当前题证据：待填写",
                replacement,
                1,
            )
    path.write_text(text, encoding="utf-8")

    assert require_paper_knowledge_application(run_dir) == path


def test_card_updates_do_not_invalidate_scientific_results(tmp_path: Path) -> None:
    """知识库变化不通过哈希反向失效既有科学事实。"""
    index = _seed_card(tmp_path)
    run_dir = initialize_simple_run(tmp_path, "no-hash-invalidation", workflow_version="3.2")
    analysis_path = write_analysis_knowledge_retrieval(run_dir, index, _fingerprint())
    _complete_analysis_decisions(run_dir)
    before = load_json(analysis_path)

    _seed_card(
        tmp_path,
        paper_id="later-card",
        title="后来新增的优化论文卡",
        problem_type="连续优化",
        data_structure="参数网格",
        task_types=["数值优化"],
    )

    assert "sha256" not in analysis_path.read_text(encoding="utf-8").casefold()
    assert require_analysis_knowledge_retrieval(run_dir) == before
    impact = classify_revision(["knowledge/analysis-retrieval.json"])
    assert impact["impact"] == "argument"
    assert "science" not in impact["invalidates"]


def test_retrieval_cli_uses_workspace_package_when_run_directly() -> None:
    """直接运行 CLI 时不能误用环境中已安装的旧包。"""
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/knowledge/retrieve_for_run.py"),
            "--help",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert b"--stage {analysis,paper}" in completed.stdout
