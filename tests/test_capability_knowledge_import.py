"""验证 Capability-First v3 的知识资产导入边界。"""

from __future__ import annotations

import json
from pathlib import Path

from shumozizi.knowledge.selector import verify_knowledge_index

REPO_ROOT = Path(__file__).resolve().parents[1]

IMPORTED_CARD_IDS = {
    "structural-preflight",
    "structured-optimization-identification",
    "sparse-nonsmooth-search",
    "uncertainty-validation",
}


def test_imported_capability_cards_are_indexed_with_verified_sources() -> None:
    """导入卡必须留在可复验索引中，并绑定已登记的来源。"""
    registry = json.loads(
        (REPO_ROOT / "knowledge" / "SOURCE_REGISTRY.json").read_text(encoding="utf-8")
    )
    sources = {item["source_id"]: item for item in registry["sources"]}
    index = verify_knowledge_index(REPO_ROOT)
    entries = {item["card_id"]: item for item in index["cards"]}

    assert IMPORTED_CARD_IDS <= entries.keys()
    for source_id in {
        "pyomo-pyomo",
        "jckantor-mo-book",
        "anyoptimization-pymoo",
        "salib-salib",
    }:
        assert sources[source_id]["usage_mode"] == "original-factual-summary"
        assert len(sources[source_id]["commit"]) == 40
        assert sources[source_id]["license_paths"]


def test_solve_skill_requires_preflight_and_bounded_capability_selection() -> None:
    """生产建模必须先预检、受限加载能力包，再比较路线。"""
    skill = (REPO_ROOT / ".agents" / "skills" / "mathmodel-solve" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "先做结构预检" in skill
    assert "最多 3 个能力包" in skill
    assert "一个主能力包、至多一个交叉能力包、至多一个验证/不确定性包" in skill
    assert skill.index("先做结构预检") < skill.index("生成两到三条真正不同的候选路线")
    assert "既有质量协议只在路线比较后约束实际执行证据" in skill


def test_import_keeps_explicit_production_capabilities_and_review_boundary() -> None:
    """知识导入只能接入明确能力，不得恢复旧审核生命周期。"""
    skills = sorted(path.name for path in (REPO_ROOT / ".agents" / "skills").iterdir() if path.is_dir())

    assert skills == [
        "mathmodel-capability-router",
        "mathmodel-experiment",
        "mathmodel-final-check",
        "mathmodel-learn-paper",
        "mathmodel-matlab",
        "mathmodel-paper",
        "mathmodel-red-team",
        "mathmodel-solve",
        "mathmodel-visual",
        "mathmodel-workflow",
    ]
