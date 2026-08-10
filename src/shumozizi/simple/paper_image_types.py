"""论文解释型图片工作流的稳定类型与状态常量。

这些常量只描述候选设计和审图协议，不代表图片已经具备论文证据资格。
"""

from __future__ import annotations

from typing import Any

ACADEMIC_FLOWCHART = "academic_flowchart"
MECHANISM_DIAGRAM = "mechanism_diagram"
TIMELINE_DIAGRAM = "timeline_diagram"
ACADEMIC_INFOGRAPHIC_STYLE = "academic_bilingual_infographic_v1"

PRIORITY_HIGH = "high"
PRIORITY_MEDIUM = "medium"
PRIORITY_LOW = "low"

SUPPORTED_VISUAL_TYPES = frozenset(
    {ACADEMIC_FLOWCHART, MECHANISM_DIAGRAM, TIMELINE_DIAGRAM}
)
SUPPORTED_LAYOUT_VARIANTS = frozenset({"five_stage_balanced", "center_emphasis"})
SUPPORTED_VISUAL_ELEMENT_TYPES = frozenset(
    {
        "formula",
        "network_sketch",
        "state_diagram",
        "timeline",
        "mini_chart",
        "metric",
        "decision_node",
        "icon",
    }
)
REVIEW_VERDICTS = frozenset({"KEEP", "RETRY", "DROP_AI_IMAGE"})
REVIEW_OUTCOMES = frozenset({"PASS", "FAIL", "UNCERTAIN"})
HARD_REVIEW_CHECKS = (
    "critical_text_readable",
    "must_show_complete",
    "critical_values_correct",
    "formula_semantics",
    "no_severe_clipping",
    "no_concept_confusion",
    "minimum_non_text_visuals",
)
SOFT_REVIEW_CHECKS = (
    "information_hierarchy",
    "reading_path",
    "mathematical_focus",
    "whitespace",
    "alignment",
    "restrained_palette",
    "icon_density",
    "poster_feel",
    "paper_fit",
    "academic_visual_richness",
)
GENERIC_BOX_LEVELS = frozenset({"LOW", "MEDIUM", "HIGH"})
MIN_NON_TEXT_VISUAL_ELEMENTS = 2


def _first_renderer_archetype(requirement: dict[str, Any]) -> str | None:
    """返回需求中第一个已接入正式 renderer 的 archetype ID；无则返回 None。

    以 figures.renderers 的分发表为唯一权威，排除默认 ``mathematical_object_schematic``
    这类“设计可用但无生产 renderer”的伪可用 archetype。
    """
    from shumozizi.figures.renderers import deterministic_renderer_archetypes

    deterministic = deterministic_renderer_archetypes()
    for item in requirement.get("preferred_archetypes", []):
        if isinstance(item, dict) and str(item.get("id", "")) in deterministic:
            return str(item["id"])
    return None


def recommend_paper_image(requirement: dict[str, Any], unit: dict[str, Any]) -> dict[str, Any]:
    """根据结构化论文需求给出图片类型、生产路径与优先级建议。

    路由分离（根因 4 修复）：数据证据类论证（Q3/Q4 的概率、搜索、可行域、几何）
    优先由确定性 renderer 从 current production 结果生成，不再因为 purpose 落入
    else 分支而被误送 academic_flowchart；AI 解释图只负责没有生产 renderer 的
    模型/机制/流程示意，且只作设计参考，不承担证据。
    """
    purpose = str(requirement.get("purpose", ""))
    renderer_archetype = _first_renderer_archetype(requirement)
    if renderer_archetype is not None:
        priority = PRIORITY_HIGH if purpose == "decisive_evidence" else PRIORITY_MEDIUM
        return {
            "recommended_visual_type": None,
            "priority": priority,
            "reason": (
                f"该论证由确定性 renderer（{renderer_archetype}）从 current production "
                "结果直接生成；AI 解释图最多作布局参考，不承担证据。"
            ),
            "expected_value": "evidence_figure",
            "production_status": "renderer_ready",
            "production_path": "deterministic_renderer",
            "renderer_archetype": renderer_archetype,
        }
    preferred = {str(item).casefold() for item in requirement.get("preferred_structures", [])}
    if purpose == "mechanism":
        visual_type = MECHANISM_DIAGRAM
    elif purpose == "boundary":
        visual_type = TIMELINE_DIAGRAM
    else:
        visual_type = ACADEMIC_FLOWCHART
    has_chain = bool(
        preferred.intersection(
            {
                "model evolution schematic",
                "mathematical-object schematic",
                "structure map",
                "argument evidence map",
            }
        )
    )
    if purpose in {"model_understanding", "mechanism"} and (
        unit.get("core_question") is True or has_chain
    ):
        priority = PRIORITY_HIGH
        reason = "该论证包含核心模型或机制链，纯公式/文字不利于快速建立整体结构。"
    elif purpose in {"model_understanding", "mechanism", "decisive_evidence"}:
        priority = PRIORITY_MEDIUM
        reason = "该论证可增强理解，但不承担唯一的正式证据。"
    else:
        priority = PRIORITY_LOW
        reason = "该视觉机会对当前论证的增益有限，或可能与已有图重复。"
    production_enabled = visual_type == ACADEMIC_FLOWCHART and priority != PRIORITY_LOW
    return {
        "recommended_visual_type": visual_type,
        "priority": priority,
        "reason": reason,
        "expected_value": (
            "explain_method" if visual_type == ACADEMIC_FLOWCHART else "explain_structure"
        ),
        "production_status": "planned" if production_enabled else "suggested_only",
        "production_path": "ai_image",
    }
