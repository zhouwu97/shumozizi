"""科学优先论文层共享的实质洞察分类。

该模块故意不依赖建模合同，使 Author Pass 可以消费 checkpoint/manifest，
而不把旧 ``MODELING_UNITS`` 控制面重新变成论文阶段硬依赖。
"""

from __future__ import annotations

_SUBSTANTIVE_INSIGHT_KINDS = frozenset(
    {"mechanism", "marginal_gain", "active_constraint", "tradeoff"}
)
