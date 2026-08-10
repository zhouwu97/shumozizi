"""回归：机械 QA 不得伪装成人工视觉门（P0 human review 语义门）。"""

from __future__ import annotations

import pytest

from shumozizi.core.io import ContractError
from shumozizi.simple.figure_promotion import validate_human_figure_review


def _review(**overrides: object) -> dict[str, object]:
    """构造机械复核基线（reviewed 必须为 False）。"""
    review: dict[str, object] = {
        "reviewed": False,
        "paper_width_preview_checked": True,
        "mathematical_object_visible": True,
        "key_observation_visible": True,
        "mechanism_or_relation_visible": True,
        "constraint_or_boundary_visible": True,
        "decision_consequence_visible": True,
        "not_redundant_with_table": True,
        "caption_matches_figure": True,
        "font_readable": True,
        "panel_mapping_valid": True,
        "focal_claim": "机械复核确认文件与结构断言一致。",
        "visible_elements": [
            {"type": "selected_point", "label": "Final plan", "panel": "main"}
        ],
        "reading_order": ["main"],
        "panel_takeaways": {"main": "文件、布局与元素断言全部通过。"},
        "issues": [],
        "verdict": "promote",
        "mechanical_review": True,
        "human_vision_performed": False,
        "review_kind": "mechanical",
    }
    review.update(overrides)
    return review


def test_mechanical_review_with_reviewed_true_rejected() -> None:
    """机械字段全真也不能通过人工视觉门：reviewed=true 必须被拒绝。"""
    with pytest.raises(ContractError, match="机械复核不得设置 reviewed=true"):
        validate_human_figure_review(
            _review(reviewed=True),
            figure_role="decisive_evidence",
            presentation_role="question_hero",
        )


def test_mechanical_missing_vision_fields_rejected() -> None:
    """机械复核缺 human_vision_performed=false 或 review_kind=mechanical 时拒绝。"""
    with pytest.raises(ContractError, match="human_vision_performed=false"):
        validate_human_figure_review(
            _review(human_vision_performed=True),
            figure_role="decisive_evidence",
            presentation_role="question_hero",
        )
    with pytest.raises(ContractError, match="review_kind=mechanical"):
        validate_human_figure_review(
            _review(review_kind="human"),
            figure_role="decisive_evidence",
            presentation_role="question_hero",
        )


def test_mechanical_reviewer_note_is_not_waiver() -> None:
    """reviewer_note 声称已人工看图不能把机械复核升级为人工验收。"""
    with pytest.raises(ContractError, match="reviewed=true"):
        validate_human_figure_review(
            _review(
                reviewed=True,
                reviewer_note="已完成真实人工看图，逐面板确认对象、机制与边界。",
            ),
            figure_role="decisive_evidence",
            presentation_role="question_hero",
        )


def test_mechanical_qualified_never_masquerades_as_human() -> None:
    """机械复核合法输入只能产生 mechanically_qualified，不能是 human_qualified。"""
    validated = validate_human_figure_review(
        _review(),
        figure_role="decisive_evidence",
        presentation_role="question_hero",
    )
    assert validated["qualification"] == "mechanically_qualified"
    assert validated["human_vision_performed"] is False
    assert validated["review_kind"] == "mechanical"
    assert validated["reviewed"] is False


def test_mechanical_review_cannot_emit_human_gate_pass() -> None:
    """机械回执不得携带人工视觉门通过标记，晋级索引必须另行保持 pending。"""
    validated = validate_human_figure_review(
        _review(),
        figure_role="decisive_evidence",
        presentation_role="question_hero",
    )
    assert validated.get("human_vision_gate") != "passed"
    assert validated["qualification"] == "mechanically_qualified"


def test_human_review_qualifies_as_human() -> None:
    """无机械标记的真实人工复核产生 human_qualified。"""
    validated = validate_human_figure_review(
        _review(
            reviewed=True,
            mechanical_review=False,
            human_vision_performed=True,
            review_kind="human",
        ),
        figure_role="decisive_evidence",
        presentation_role="question_hero",
    )
    assert validated["qualification"] == "human_qualified"
    assert validated["human_vision_performed"] is True
    assert validated["review_kind"] == "human"
