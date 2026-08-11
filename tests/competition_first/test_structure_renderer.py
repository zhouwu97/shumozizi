"""验证 SECOND STEP 结构图 renderer：3 模板产出确定性 TikZ，decisive_evidence 被拒。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".agents" / "skills" / "mathmodel-advanced-figures" / "scripts"))

import pytest  # noqa: E402
from render_structure import _validate  # noqa: E402
from structure_templates import (  # noqa: E402
    TEMPLATES,
    render_mechanism_decision,
    render_problem_progression,
    render_shared_model_map,
)


def _base_spec(template: str) -> dict:
    return {
        "template": template,
        "title": "结构图",
        "argument_role": "model_understanding",
        "nodes": [
            {"id": "in", "label": "输入", "role": "input"},
            {"id": "core", "label": "共享状态", "role": "center",
             "math": r"S(t)=\{x_e(t)\}_{e\in E}"},
            {"id": "q1", "label": "问题一", "role": "output"},
        ],
        "edges": [
            {"from": "in", "to": "core", "kind": "feed"},
            {"from": "core", "to": "q1", "kind": "inherit"},
        ],
        "emphasis": ["core"],
    }


def test_all_templates_are_registered() -> None:
    """三个高频结构模板必须可用。"""
    assert set(TEMPLATES) == {"shared_model_map", "problem_progression", "mechanism_decision"}


def test_shared_model_map_renders_math_center_unboxed() -> None:
    """中央数学对象必须无边框（draw=none），避免流程图生成器味。"""
    tex = render_shared_model_map(_base_spec("shared_model_map"))
    assert "draw=none" in tex
    assert "S(t)" in tex
    assert "(core)" in tex


def test_problem_progression_renders_chain() -> None:
    """问题递进必须输出水平链 + 继承虚线。"""
    spec = {
        "template": "problem_progression",
        "argument_role": "model_understanding",
        "nodes": [{"id": "q1", "label": "Q1"}, {"id": "q2", "label": "Q2"}, {"id": "q3", "label": "Q3"}],
        "edges": [{"from": "q1", "to": "q2", "kind": "inherit", "label": "进入"}, {"from": "q2", "to": "q3", "kind": "inherit"}],
    }
    tex = render_problem_progression(spec)
    assert "dashed" in tex
    assert "进入" in tex
    assert "(q1)" in tex and "(q3)" in tex


def test_mechanism_decision_renders_feedback_loop() -> None:
    """机制判定必须输出主链 + 反馈回环，节点全部在边之前放置。"""
    spec = {
        "template": "mechanism_decision",
        "argument_role": "mechanism",
        "nodes": [
            {"id": "in", "label": "输入", "role": "input"},
            {"id": "st", "label": "状态更新", "role": "state"},
            {"id": "cond", "label": "条件？", "role": "condition"},
            {"id": "out", "label": "输出", "role": "output"},
        ],
        "edges": [{"from": "cond", "to": "st", "kind": "feedback", "label": "回环"}],
    }
    tex = render_mechanism_decision(spec)
    assert "bend left" in tex  # 反馈弯线
    assert "回环" in tex
    # 节点必须先于边引用（边引用的 id 都已 \node 放置）
    for nid in ("in", "st", "cond", "out"):
        node_pos = tex.find(f"({nid}) at")
        edge_pos = tex.find(f"({nid})")
        assert node_pos >= 0 and edge_pos >= 0


def test_render_structure_rejects_decisive_evidence() -> None:
    """decisive_evidence 必须被 TikZ renderer 拒绝（结构图不进证据层）。"""
    spec = _base_spec("shared_model_map")
    spec["argument_role"] = "decisive_evidence"
    with pytest.raises(SystemExit, match="decisive_evidence"):
        _validate(spec)


def test_render_structure_rejects_unknown_template() -> None:
    """未知模板必须明确失败。"""
    spec = _base_spec("no_such_template")
    with pytest.raises(SystemExit, match="未知结构模板"):
        _validate(spec)
