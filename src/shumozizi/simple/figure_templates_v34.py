"""v3.4 图形与示意图设计资产注册表。

注册表只声明某类数学结构适合什么表达，不携带示例数据，也不把 design_only
模板伪装成可直接渲染的生产图；真正使用前仍需当前题视觉机会和 renderer。
"""

from __future__ import annotations

from typing import Any

from shumozizi.core.io import ContractError
from shumozizi.core.schema import require_valid

V34_FIGURE_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "template_id": "active_constraint_map",
        "family": "scientific",
        "information_structure": "tradeoff",
        "claim_roles": ["mechanism", "boundary", "decision"],
        "status": "renderer_available",
        "renderer": "src/shumozizi/simple/figure_templates.py",
        "required_data": ["points", "feasible_mask", "boundaries", "active_constraints", "selected_point"],
        "notes": "用活跃约束、可行边界和最优点解释瓶颈；不得把静态热力图当作替代。",
    },
    {
        "template_id": "constraint_margin_timeline",
        "family": "scientific",
        "information_structure": "temporal",
        "claim_roles": ["mathematical_object", "mechanism", "boundary"],
        "status": "renderer_available",
        "renderer": "src/shumozizi/simple/figure_templates.py",
        "required_data": ["time", "series[].label", "series[].margin", "active_tolerance"],
        "notes": "显示时间/事件余量和临界日，适合回答哪个事件决定下界。",
    },
    {
        "template_id": "uncertainty_threshold_ribbon",
        "family": "scientific",
        "information_structure": "uncertainty",
        "claim_roles": ["uncertainty", "comparison", "decision"],
        "status": "renderer_available",
        "renderer": "src/shumozizi/simple/figure_templates.py",
        "required_data": ["x", "median", "bands", "threshold"],
        "notes": "同时保留区间、阈值和行动后果，不得只画均值折线。",
    },
    {
        "template_id": "model_evolution_schematic",
        "family": "schematic",
        "information_structure": "network",
        "claim_roles": ["mathematical_object", "model_structure", "inheritance"],
        "status": "renderer_available",
        "renderer": "src/shumozizi/simple/figure_templates.py",
        "required_data": ["nodes[].id", "nodes[].label", "nodes[].stage", "edges[].relation"],
        "notes": "表示共享对象从前问到后问的继承与新增约束；节点必须对应当前模型字段。",
    },
    {
        "template_id": "argument_evidence_map",
        "family": "schematic",
        "information_structure": "network",
        "claim_roles": ["derivation", "evidence", "boundary"],
        "status": "renderer_available",
        "renderer": "src/shumozizi/simple/figure_templates.py",
        "required_data": ["nodes[].id", "nodes[].label", "nodes[].kind", "edges[].relation"],
        "notes": "把结论、推导、证据功能和边界连接起来，不能替代正文推导。",
    },
    {
        "template_id": "cumcm_semantic_v34",
        "family": "competition",
        "information_structure": "narrative",
        "claim_roles": ["inheritance", "model_structure", "direct_answer"],
        "status": "renderer_available",
        "renderer": "src/shumozizi/paper/cumcm_adapter.py",
        "required_data": ["cumcm_structure_map", "paper_source"],
        "notes": "经典国赛外壳加语义内核；不得借版式改变模型或结果。",
    },
    {
        "template_id": "cumcm_classic_v34",
        "family": "competition",
        "information_structure": "narrative",
        "claim_roles": ["direct_answer", "derivation", "validation"],
        "status": "renderer_available",
        "renderer": "src/shumozizi/paper/cumcm_adapter.py",
        "required_data": ["cumcm_structure_map", "paper_source"],
        "notes": "经典栏目兜底；仍须满足素材池、故事板和逐问答案合同。",
    },
)


def list_v34_templates(*, family: str | None = None) -> list[dict[str, Any]]:
    """列出当前 v3.4 设计资产，返回副本避免调用者污染注册表。"""
    if family is not None and family not in {"scientific", "schematic", "competition"}:
        raise ContractError("模板 family 必须为 scientific、schematic 或 competition")
    return [
        {**item, "claim_roles": list(item["claim_roles"])}
        for item in V34_FIGURE_TEMPLATES
        if family is None or item["family"] == family
    ]


def v34_template_registry_payload() -> dict[str, Any]:
    """构造并校验可供论文计划引用的模板注册表。"""
    payload = {
        "schema_name": "figure_template_registry",
        "schema_version": "1.0",
        "templates": list_v34_templates(),
    }
    require_valid(payload, "figure_template_registry")
    return payload


def select_v34_template(template_id: str) -> dict[str, Any]:
    """读取一个模板设计资产；design_only 只能作为候选，不承诺已有 renderer。"""
    item = next(
        (item for item in v34_template_registry_payload()["templates"] if item["template_id"] == template_id),
        None,
    )
    if item is None:
        raise ContractError(f"未知 v3.4 模板: {template_id}")
    return {**item, "claim_roles": list(item["claim_roles"])}
