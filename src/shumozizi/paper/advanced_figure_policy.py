"""定义 CUMCM 正式候选稿的高级图硬规格。"""

from __future__ import annotations

from typing import Any

# WHY: 数量规格要在生成、Author Brief、终检三处一致；此模块是 Python 侧唯一
# 数值来源，JSON Schema 再以 const 固化外部合同，防止“文案是 12、门禁是 10”。
MIN_BODY_FIGURES_PER_QUESTION = 2
MAX_BODY_FIGURES_PER_QUESTION = 3
MIN_FORMAL_BODY_FIGURES = 12
MIN_FORMAL_VISUAL_ARCHETYPES = 3


def advanced_figure_quota_payload() -> dict[str, Any]:
    """返回可写入视觉需求契约的高级图硬规格。

    Returns:
        新建的 JSON 可序列化对象，调用方可安全地交给 schema 校验或写盘。
    """
    return {
        "per_required_question": {
            "minimum": MIN_BODY_FIGURES_PER_QUESTION,
            "maximum": MAX_BODY_FIGURES_PER_QUESTION,
        },
        "minimum_formal_current_figures": MIN_FORMAL_BODY_FIGURES,
        "minimum_visual_archetypes": MIN_FORMAL_VISUAL_ARCHETYPES,
        "count_scope": (
            "仅计正式发布入口实际引用、status=current、paper_allowed=true 的图；"
            "长稿、素材池、草图、重复引用和附录图不计入任何硬配额。"
        ),
    }
