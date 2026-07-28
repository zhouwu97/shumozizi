"""验证返修只失效必要的科学、论证或渲染层。"""

from __future__ import annotations

import pytest

from shumozizi.core.io import ContractError
from shumozizi.simple.revisions import classify_revision


def test_render_only_revision_does_not_invalidate_science() -> None:
    """调整箭头、字号和最终 PDF 只重做渲染检查。"""
    result = classify_revision(
        [
            "figures/current/overall-paper-workflow.png",
            "code/figures/render_overall_workflow.py",
            "paper/final.pdf",
        ]
    )

    assert result["impact"] == "render"
    assert result["invalidates"] == ["render"]


def test_argument_and_science_revisions_cascade_only_downstream() -> None:
    """正文改写和结果改动具有不同的重验范围。"""
    argument = classify_revision(["paper/sections/q2.tex"])
    science = classify_revision(
        ["paper/sections/q2.tex", "results/current/q2-policy.json"]
    )

    assert argument["invalidates"] == ["argument", "render"]
    assert science["invalidates"] == ["science", "argument", "render"]
    generated_argument = classify_revision(["paper/generated/argument_map.json"])
    assert generated_argument["impact"] == "argument"


def test_revision_paths_must_stay_inside_run() -> None:
    """失效分类不接受运行目录外路径。"""
    with pytest.raises(ContractError, match="运行目录内"):
        classify_revision(["../AGENTS.md"])
