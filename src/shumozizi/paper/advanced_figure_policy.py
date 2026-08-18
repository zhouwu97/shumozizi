"""定义按必答问题数自适应的 CUMCM 正式图合同。"""

from __future__ import annotations

from typing import Any

# WHY: 图的论证覆盖始终是硬门，但少题运行若同时强制逐题上限与全篇 12 图，
# 在数学上不可满足。把按题数的判定集中在此处，避免生成、Author Brief 与终检
# 各自复制数值后再次漂移。
MIN_BODY_FIGURES_PER_QUESTION = 2
MAX_BODY_FIGURES_PER_QUESTION = 3
MIN_FORMAL_BODY_FIGURES = 12
MIN_FORMAL_VISUAL_ARCHETYPES = 3
GLOBAL_FIGURE_HARD_MINIMUM_QUESTION_COUNT = 4


def advanced_figure_quota_payload(required_question_count: int) -> dict[str, Any]:
    """返回可写入视觉需求契约的按题数图合同。

    每个必答问题始终需要足以承担不同论证角色的两到三张 current 正文图。
    全篇十二图和三种图型只在至少四问时作为硬门；较少问题以论证角色为
    编辑目标，不能为了满足全局数量而拆分或重复插图。

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
        "minimum_visual_archetypes": (
            MIN_FORMAL_VISUAL_ARCHETYPES if global_hard_minimum else None
        ),
        "editorial_target": (
            "核心问题通常需要 1 张能被记住的 Hero Figure；若一个图不能同时解释数据直觉、"
            "机制、权衡或边界，再增加 supporting figure。全篇 13–18 图作为复杂建模赛题视觉"
            "充足的推荐参考信号，按论证角色真实展开，不得为数量机械凑图。"
        ),
        "count_scope": (
            "仅计正式发布入口实际引用、status=current、paper_allowed=true 的图；"
            "长稿、素材池、草图、重复引用和附录图不计入任何硬配额。"
        ),
    }
