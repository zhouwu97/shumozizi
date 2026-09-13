"""定义按必答问题数自适应的 CUMCM 正式图合同。"""

from __future__ import annotations

from typing import Any

# WHY: 旧数量合同保留给显式 legacy/competition-quality 运行；新运行只检查
# 论证角色和 current 来源，避免作者为满足数量制造装饰图。
MIN_BODY_FIGURES_PER_QUESTION = 2
MAX_BODY_FIGURES_PER_QUESTION = 3
MIN_FORMAL_BODY_FIGURES = 13
MAX_FORMAL_BODY_FIGURES = 18
MIN_FORMAL_VISUAL_ARCHETYPES = 3
GLOBAL_FIGURE_HARD_MINIMUM_QUESTION_COUNT = 4


def advanced_figure_quota_payload(required_question_count: int) -> dict[str, Any]:
    """返回可写入视觉需求契约的按题数图合同。

    该函数仅生成 legacy 数量合同的兼容描述；science-editorial 运行不消费数量字段。

    Args:
        required_question_count: 当前正式候选稿的必答问题数量。

    Returns:
        新建的 JSON 可序列化对象，调用方可安全地交给 schema 校验或写盘。

    Raises:
        ValueError: 问题数不是非负整数。
    """
    if not isinstance(required_question_count, int) or isinstance(required_question_count, bool):
        raise ValueError("required_question_count 必须是整数")
    if required_question_count < 0:
        raise ValueError("required_question_count 不能为负数")
    global_hard_minimum = (
        required_question_count >= GLOBAL_FIGURE_HARD_MINIMUM_QUESTION_COUNT
    )
    return {
        "required_question_count": required_question_count,
        "per_required_question": {
            "minimum": MIN_BODY_FIGURES_PER_QUESTION,
            "maximum": MAX_BODY_FIGURES_PER_QUESTION,
        },
        "overall_enforcement": (
            "hard_minimum"
            if global_hard_minimum
            else "coverage_driven_editorial_target"
        ),
        "minimum_formal_current_figures": (
            MIN_FORMAL_BODY_FIGURES if global_hard_minimum else None
        ),
        "maximum_formal_current_figures": (
            MAX_FORMAL_BODY_FIGURES if global_hard_minimum else None
        ),
        "minimum_visual_archetypes": (
            MIN_FORMAL_VISUAL_ARCHETYPES if global_hard_minimum else None
        ),
        "editorial_target": (
            "按数学对象、决定性证据、机制和边界选择 current 正文图；一张图承担一个主要判断，"
            "数量只作编辑信号，不得通过重复图、拆分同一图或装饰图凑数。"
        ),
        "count_scope": (
            "仅计正式发布入口实际引用、status=current、paper_allowed=true 的图；"
            "长稿、素材池、草图、重复引用和附录图不计入任何硬配额。"
        ),
    }
