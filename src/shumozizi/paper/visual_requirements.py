"""从论文论证需求生成轻量视觉需求，并路由到视觉机会池。

v3.4 起按数学对象感知路由：``mathematical_object + argument_role +
required_visibility + available_fields`` 决定 archetype，purpose 只决定论证
角色。正文抽取先清洗 LaTeX 噪声、再按 ``(question_id, mathematical_object,
argument_role, source_result_ids)`` 归并，避免把表格 token、已有图环境和重复
边界段落放大成独立需求。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    load_json,
    resolve_inside,
    sha256_file,
)
from shumozizi.core.schema import require_valid
from shumozizi.paper.advanced_figure_policy import advanced_figure_quota_payload
from shumozizi.paper.argument_extraction import extract_paper_argument_units
from shumozizi.paper.publication import publication_source_digest, publication_text_sources
from shumozizi.simple.data_availability import availability_for_requirement
from shumozizi.simple.paper_image_types import recommend_paper_image
from shumozizi.simple.state import read_simple_state, utc_now
from shumozizi.simple.visual_requirements import (
    declared_mathematical_objects,
    derive_visual_requirements,
)

VISUAL_REQUIREMENTS_PATH = Path("paper/generated/VISUAL_REQUIREMENTS.json")

_PURPOSE_ORDER = (
    "model_understanding",
    "decisive_evidence",
    "mechanism",
    "boundary",
)
_PURPOSE_BY_OBLIGATION = {
    "mathematical_object": "model_understanding",
    "decision": "decisive_evidence",
    "mechanism": "mechanism",
    "boundary": "boundary",
    "uncertainty": "boundary",
}
_MATERIAL_CATEGORY_BY_PURPOSE = {
    "model_understanding": {"mathematical derivation", "structural observation"},
    "decisive_evidence": {"direct answer", "baseline/contrast"},
    "mechanism": {"mechanism"},
    "boundary": {"boundary/robustness"},
}
_PREFERRED_STRUCTURES = {
    "model_understanding": ["mathematical-object schematic", "structure map"],
    "decisive_evidence": ["baseline comparison", "decision surface"],
    "mechanism": ["active-constraint plot", "mechanism map"],
    "boundary": ["sensitivity curve", "feasible-region boundary"],
}
_PREFERRED_ARCHETYPES = {
    "model_understanding": [
        {
            "id": "model_evolution_schematic",
            "renderer_status": "available",
            "required_data": [
                "nodes[].id", "nodes[].label", "nodes[].stage", "edges[].relation"
            ],
        },
        {
            "id": "argument_evidence_map",
            "renderer_status": "available",
            "required_data": [
                "nodes[].id", "nodes[].label", "nodes[].kind", "edges[].relation"
            ],
        },
    ],
    "decisive_evidence": [
        {
            "id": "active_constraint_map",
            "renderer_status": "available",
            "required_data": [
                "points", "feasible_mask", "boundaries", "active_constraints", "selected_point"
            ],
        }
    ],
    "mechanism": [
        {
            "id": "constraint_margin_timeline",
            "renderer_status": "available",
            "required_data": ["time", "series[].label", "series[].margin", "active_tolerance"],
        }
    ],
    "boundary": [
        {
            "id": "uncertainty_threshold_ribbon",
            "renderer_status": "available",
            "required_data": ["x", "median", "bands", "threshold"],
        }
    ],
}

# 8.2 对象感知路由矩阵：数学对象 + 论证角色 -> 首选 archetype 与禁止的默认替代。
_OBJECT_ROUTE: dict[str, dict[str, Any]] = {
    "spatial_geometry": {
        "preferred_structures": ["3D spatial scene + orthogonal cross-section"],
        "preferred_archetypes": [
            {
                "id": "spatial_scene_cross_section",
                "renderer_status": "available",
                "required_data": ["coordinates", "boundary"],
            }
        ],
        "forbidden_defaults": ["academic_flowchart", "model_evolution_schematic"],
    },
    "periodic_spatial_geometry": {
        "preferred_structures": ["3D periodic unit cell + orthogonal cross-section"],
        "preferred_archetypes": [
            {
                "id": "periodic_spatial_scene",
                "renderer_status": "available",
                "required_data": ["coordinates", "boundary", "wrapped_fragments", "identity_map"],
            }
        ],
        "forbidden_defaults": ["academic_flowchart", "model_evolution_schematic"],
    },
    "contact_network": {
        "preferred_structures": ["contact network with electrodes and backbone"],
        "preferred_archetypes": [
            {
                "id": "contact_network_backbone",
                "renderer_status": "available",
                "required_data": ["nodes", "edges", "electrodes", "conductive_path"],
            }
        ],
        "forbidden_defaults": ["conductance_bar_chart"],
    },
    "periodic_contact_network": {
        "preferred_structures": ["spatial contact backbone triptych"],
        "preferred_archetypes": [
            {
                "id": "spatial_contact_backbone_triptych",
                "renderer_status": "available",
                "required_data": [
                    "coordinates", "boundary", "identity_map",
                    "edges", "electrodes", "conductive_path",
                ],
            }
        ],
        "forbidden_defaults": ["conductance_bar_chart"],
    },
    "geometric_oracle_comparison": {
        "preferred_structures": ["end-cap zoom with removed pseudo-edge contrast"],
        "preferred_archetypes": [
            {
                "id": "oracle_comparison_zoom",
                "renderer_status": "available",
                "required_data": ["candidate_pairs", "exact_distance", "capsule_distance"],
            }
        ],
        "forbidden_defaults": ["error_bar_only"],
    },
    "probability_transition": {
        "preferred_structures": ["probability curve with Wilson interval and threshold band"],
        "preferred_archetypes": [
            {
                "id": "probability_threshold_curve",
                "renderer_status": "available",
                "required_data": ["x", "successes", "trials", "interval", "threshold"],
            }
        ],
        "forbidden_defaults": ["logistic_smooth_curve_only"],
    },
    "uncertainty_threshold": {
        "preferred_structures": ["interval lower bound margin or threshold band"],
        "preferred_archetypes": [
            {
                "id": "uncertainty_margin_ribbon",
                "renderer_status": "available",
                "required_data": ["x", "interval_low", "threshold"],
            }
        ],
        "forbidden_defaults": ["mean_only_line"],
    },
    "integer_feasible_region": {
        "preferred_structures": ["integer lattice feasible region with active boundary and cost contours"],
        "preferred_archetypes": [
            {
                "id": "integer_feasible_region",
                "renderer_status": "available",
                "required_data": [
                    "lattice_points", "feasible_mask", "constraint_margins", "costs", "selected_point",
                ],
            }
        ],
        "forbidden_defaults": ["candidate_table_only"],
    },
    "pareto_cost_reliability": {
        "preferred_structures": ["layered frontier with formal and sensitivity domain"],
        "preferred_archetypes": [
            {
                "id": "cost_reliability_frontier",
                "renderer_status": "available",
                "required_data": ["candidate_points", "dominance", "formal_region", "sensitivity_region"],
            }
        ],
        "forbidden_defaults": ["mixed_scatter_only"],
    },
    "search_stability": {
        "preferred_structures": ["multi-seed envelope or sample-size convergence band"],
        "preferred_archetypes": [
            {
                "id": "convergence_envelope",
                "renderer_status": "available",
                "required_data": ["seeds", "budget_or_samples", "quantile_bands", "stopping_point"],
            }
        ],
        "forbidden_defaults": ["single_best_curve"],
    },
    "implementation_agreement": {
        "preferred_structures": ["classification agreement with difference detail"],
        "preferred_archetypes": [
            {
                "id": "implementation_agreement",
                "renderer_status": "available",
                "required_data": ["classifications", "differences", "critical_recheck"],
            }
        ],
        "forbidden_defaults": ["all_green_checklist"],
    },
    "shared_model_pipeline": {
        "preferred_structures": ["shared model pipeline with object-level stages"],
        "preferred_archetypes": [
            {
                "id": "shared_model_pipeline",
                "renderer_status": "available",
                "required_data": ["stages", "relations"],
            }
        ],
        "forbidden_defaults": ["decorative_flowchart"],
    },
}
_OBJECT_ROUTE_DEFAULTS = {
    "preferred_structures": ["mathematical-object schematic"],
    "preferred_archetypes": [
        {
            "id": "mathematical_object_schematic",
            "renderer_status": "available",
            "required_data": ["nodes[].id", "nodes[].label", "edges[].relation"],
        }
    ],
    "forbidden_defaults": [],
}

# 8.3.1 正文抽取噪声：LaTeX 环境外壳、表格 token、引用标签与已有图环境。
_EXTRACTION_NOISE = re.compile(
    r"(?:\b(?:longtable|tabularx?|enumerate|itemize|description|includegraphics|"
    r"equation|align|gather|figure|table|documentclass|usepackage)\b|"
    r"(?:table|figure|equation|align|gather|itemize|enumerate)\[[^\]]*\]|"
    r"\\begin\{[a-zA-Z*]+\}|\\end\{[a-zA-Z*]+\}|"
    r"&[^&]{0,120}&|\\\\|"
    r"\[[a-zA-Z]+=[^\]]*\]|"
    r"\\(?:ref|label|cite|pageref)\{[^{}]*\}|"
    r"(?:tab|fig|eq|sec|alg):[A-Za-z0-9._-]+)",
    re.IGNORECASE,
)


def _clean_extraction_text(value: str) -> str:
    """移除论文抽取的 LaTeX/表格噪声，保留可读科学语义。"""
    text = re.sub(r"(?<!\\)%[^\n]*", "", value)
    text = _EXTRACTION_NOISE.sub(" ", text)
    text = re.sub(r"\\(?:textbf|textit|emph|ref|label|cite)\{([^{}]*)\}", r"\1", text)
    text = text.replace("\\textwidth", " ").replace("\\columnwidth", " ")
    text = text.replace("{", " ").replace("}", " ")
    text = re.sub(r"\$+", " ", text)
    text = re.sub(r"\\[A-Za-z]+(?:\[[^\]]*\])?", " ", text)
    text = re.sub(r"(?<![A-Za-z0-9])[A-Za-z]{2,}\d{4}(?:,[A-Za-z]{2,}\d{4})*", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _substantive_claim(text: str) -> bool:
    """清洗后仍保留可读断言的正文才成为需求；纯公式/表格 token 直接丢弃。"""
    if len(text) < 24:
        return False
    if re.fullmatch(r"[\W\d\s%$^_{}()\[\]=+*/<>,.;:，。；：、]+", text):
        return False
    return True


# 多对象单元中，正文段落按关键词归属最可能对象；无匹配时保持无对象。
_OBJECT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "periodic_contact_network": ("回绕", "身份", "周期", "接触边", "导电骨架", "贯通路径", "伪接触边"),
    "periodic_spatial_geometry": ("回绕", "周期", "片段", "胞元"),
    "contact_network": ("接触网络", "电极", "接触边"),
    "geometric_oracle_comparison": ("平端", "胶囊", "实体距离", "端面", "伪边", "轴线距离"),
    "probability_transition": ("概率", "Wilson", "区间", "阈值", "越过", "样本量"),
    "uncertainty_threshold": ("下界", "裕量", "阈值带"),
    "integer_feasible_region": ("可行域", "格点", "n_A", "n_B", "整数", "活跃边界"),
    "pareto_cost_reliability": ("前沿", "零允许", "敏感性", "支配", "成本—可靠性", "成本"),
    "search_stability": ("种子", "收敛", "稳定性"),
    "implementation_agreement": ("核对", "一致", "复算", "独立实现"),
    "shared_model_pipeline": ("共享", "管线", "原子事件", "统一对象"),
}


def _match_mathematical_object(claim: str, candidates: list[str]) -> str:
    """按关键词为正文段落匹配最可能的数学对象（多对象单元的归属）。"""
    best = ""
    best_score = 0
    for candidate in candidates:
        score = sum(claim.count(keyword) for keyword in _OBJECT_KEYWORDS.get(candidate, ()))
        if score > best_score:
            best = candidate
            best_score = score
    return best


def _already_figure_noise(text: str) -> bool:
    """正文片段若是已有图引用或表格环境，不再反向生成新图需求（8.3.1）。"""
    if "figures/current/" in text:
        return True
    if re.search(r"\b(?:tabularx?|longtable)\b", text, re.IGNORECASE):
        return True
    if re.search(r"\\begin\{figure\}|\\includegraphics", text, re.IGNORECASE):
        return True
    return False


def _route_for(mathematical_object: str) -> dict[str, Any]:
    """返回数学对象的视觉路由；未登记对象回退到通用对象示意。"""
    if mathematical_object in _OBJECT_ROUTE:
        return _OBJECT_ROUTE[mathematical_object]
    return dict(_OBJECT_ROUTE_DEFAULTS)


def _optional_json(root: Path, relative: str) -> dict[str, Any]:
    """读取可选 JSON；缺失时返回空对象，损坏时保留明确失败。"""
    path = root / relative
    if not path.is_file():
        return {}
    value = load_json(path)
    return value if isinstance(value, dict) else {}


def _input_hashes(root: Path) -> dict[str, str]:
    """绑定生成器实际消费的论文、模型、结果与图索引。"""
    relatives = (
        "analysis/MODELING_UNITS.json",
        "analysis/critical_claims.json",
        "paper/generated/material_pool.json",
        "paper/answer-map.json",
        "analysis/answer_map.json",
        "paper/longform-source.tex",
        "paper/longform-source.typ",
        "paper/external-author/draft.tex",
        "figures/index.json",
        "results/index.json",
    )
    return {
        relative: sha256_file(root / relative)
        for relative in relatives
        if (root / relative).is_file()
    }


def _units_by_question(modeling: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """按必答问题选择一个建模单元。"""
    units: dict[str, dict[str, Any]] = {}
    for raw in modeling.get("units", []):
        if not isinstance(raw, dict) or not isinstance(raw.get("question_id"), str):
            continue
        question_id = raw["question_id"]
        if question_id not in units or raw.get("answer_contract"):
            units[question_id] = raw
    return units


def _materials_by_question(materials: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """按问题聚合仍可用于正文的研究素材。"""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in materials.get("items", []):
        if not isinstance(raw, dict) or raw.get("status", "current") != "current":
            continue
        question_id = raw.get("question_id")
        if isinstance(question_id, str):
            grouped.setdefault(question_id, []).append(raw)
    return grouped


def _answer_result_ids(root: Path) -> dict[str, set[str]]:
    """返回每问正式答案绑定的结果集合。"""
    payload = _optional_json(root, "paper/answer-map.json")
    if not payload:
        payload = _optional_json(root, "analysis/answer_map.json")
    answers = payload.get("answers", payload)
    mapped: dict[str, set[str]] = {}
    if not isinstance(answers, dict):
        return mapped
    for question_id, raw in answers.items():
        if not isinstance(raw, dict):
            continue
        values = raw.get("result_ids", [])
        primary = raw.get("primary_result_id")
        result_ids = {str(item) for item in values if isinstance(item, str)}
        if isinstance(primary, str):
            result_ids.add(primary)
        mapped[str(question_id)] = result_ids
    return mapped


def _current_figures(root: Path) -> list[dict[str, Any]]:
    """读取所有可进入论文的 current 正式图，不限制数量。"""
    figures = _optional_json(root, "figures/index.json").get("figures", [])
    if not isinstance(figures, list):
        return []
    return [
        item
        for item in figures
        if isinstance(item, dict)
        and item.get("status") == "current"
        and item.get("paper_allowed", True) is not False
    ]


def _strings(value: object) -> set[str]:
    """把字符串或字符串列表规范为集合。"""
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {str(item) for item in value if isinstance(item, str)}
    return set()


def _insight_ids(value: object) -> set[str]:
    """递归收集建模单元中的 insight_id，兼容 actual 等嵌套结构。"""
    if isinstance(value, dict):
        identifiers = _strings(value.get("insight_id")) | _strings(value.get("insight_ids"))
        return identifiers | {
            identifier
            for child in value.values()
            for identifier in _insight_ids(child)
        }
    if isinstance(value, list):
        return {
            identifier
            for child in value
            for identifier in _insight_ids(child)
        }
    return set()


def _figure_covers(
    root: Path,
    figure: dict[str, Any],
    *,
    requirement_id: str,
    requirement_digest: str,
    source_paths: Iterable[Path],
) -> bool:
    """只接受精确绑定且已被实际论文源消费的正文 current 图。"""
    if requirement_id not in _strings(figure.get("covered_requirement_ids")):
        return False
    if requirement_digest not in _strings(figure.get("covered_requirement_digests")):
        return False
    role = str(figure.get("role", figure.get("promotion_role", ""))).casefold()
    if role == "stability" or str(figure.get("placement", "body")).casefold() == "appendix":
        return False
    if not str(figure.get("focal_claim", "")).strip():
        return False
    anchors = {str(figure.get("figure_id", "")).strip()}
    paper_location = str(figure.get("paper_location", "")).strip()
    if paper_location:
        anchors.add(paper_location)
    for output in figure.get("outputs", []):
        if not isinstance(output, dict) or not isinstance(output.get("path"), str):
            continue
        path = output["path"].replace("\\", "/")
        anchors.update({path, Path(path).name, str(Path(path).with_suffix("")), Path(path).stem})
    anchors.discard("")
    for source in source_paths:
        if not source.is_file():
            continue
        text = source.read_text(encoding="utf-8", errors="replace").replace("\\", "/")
        if any(anchor in text for anchor in anchors):
            return True
    return False


def _requirement_digest(item: dict[str, Any]) -> str:
    """计算 claim、来源与论证单元共同决定的稳定需求摘要。

    主键包含数学对象、论证角色与结果集合（8.3.3），保证同一对象、角色、
    结果绑定的重复段落归并后摘要稳定，current 图覆盖关系不漂移。
    """
    fields = {
        key: item.get(key)
        for key in (
            "question_id",
            "purpose",
            "mathematical_object",
            "claim",
            "visual_question",
            "source_result_ids",
            "source_insight_ids",
            "argument_unit_ids",
        )
    }
    encoded = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _first_material(
    materials: Iterable[dict[str, Any]], purpose: str
) -> dict[str, Any] | None:
    """选择最先出现、能说明该视觉目的的研究素材。"""
    allowed = _MATERIAL_CATEGORY_BY_PURPOSE[purpose]
    return next(
        (
            item
            for item in materials
            if str(item.get("category", "")).strip().casefold() in allowed
        ),
        None,
    )


def _visual_output_requirements(unit: dict[str, Any]) -> list[dict[str, Any]]:
    """把事前 visual_outputs 转为不依赖 Figure Plan 的显式需求。

    事前合同携带数学对象、论证角色与候选 archetype（7.1），正文抽取只补充
    遗漏，不覆盖这些合同（8.3.2）。
    """
    requirements: list[dict[str, Any]] = []
    for index, raw in enumerate(unit.get("visual_outputs", []), 1):
        if not isinstance(raw, dict):
            continue
        visual_question = str(raw.get("visual_question", "")).strip()
        claim = str(raw.get("takeaway", raw.get("claim", ""))).strip()
        if not visual_question and not claim:
            continue
        mathematical_object = str(raw.get("mathematical_object", "")).strip()
        route = _route_for(mathematical_object)
        archetypes = [
            str(candidate).strip()
            for candidate in raw.get("candidate_archetypes", [])
            if isinstance(candidate, str) and candidate.strip()
        ]
        preferred_archetypes = [
            {
                "id": archetype,
                "renderer_status": "available",
                "required_data": list(raw.get("required_data", [])),
            }
            for archetype in archetypes
        ] or route["preferred_archetypes"]
        requirements.append(
            {
                "purpose": str(raw.get("argument_role", raw.get("purpose", "model_understanding"))),
                "mathematical_object": mathematical_object,
                "visual_question": visual_question or f"如何直观看到：{claim}？",
                "claim": claim or visual_question,
                "argument_unit_ids": sorted(
                    _strings(raw.get("argument_unit_ids"))
                    | _strings(raw.get("argument_unit_id"))
                ),
                "preferred_structures": route["preferred_structures"]
                if not archetypes
                else archetypes,
                "forbidden_defaults": route["forbidden_defaults"],
                "preferred_archetypes": preferred_archetypes,
                "required_visibility": [
                    str(item)
                    for item in raw.get("required_visibility", [])
                    if isinstance(item, str) and item.strip()
                ],
                # visual_outputs 声明的 output_path 是结构化绘图原语工件（results/raw/），
                # 必须与 answer-map 主结果一起作为 source 绑定，否则数据可画性解析器
                # 找不到坐标/边等绘图原语，会把“有数据”误判成 data_missing。
                "source_artifact_paths": [
                    str(raw["output_path"]).strip()
                ]
                if raw.get("output_path") and str(raw["output_path"]).strip()
                else [],
                "ordinal": index,
            }
        )
    return requirements


def _compose_takeaway(claims: list[str]) -> str:
    """把指向同一对象的多个正文段落合成一个短 takeaway（8.3.4）。"""
    candidates = [claim for claim in claims if len(claim) >= 24]
    if not candidates:
        return ""
    longest = max(candidates, key=len)
    if len(longest) <= 200:
        return longest
    return longest[:200].rsplit("。", 1)[0] + "。"


def _object_artifact_paths(unit: dict[str, Any], mathematical_object: str) -> list[str]:
    """收集该数学对象声明的 visual_output output_path 绘图原语工件。

    正文抽取需求补充的是同一对象的论证角色，应共享事前合同绑定的结构化工件，
    否则 resolver 会因“没绑定坐标工件”把有数据的 supporting 需求误判为
    data_missing（与显式合同需求不一致）。
    """
    if not mathematical_object:
        return []
    paths: list[str] = []
    for output in unit.get("visual_outputs", []):
        if not isinstance(output, dict):
            continue
        if str(output.get("mathematical_object", "")).strip() != mathematical_object:
            continue
        value = output.get("output_path")
        if isinstance(value, str) and value.strip() and value.strip() not in paths:
            paths.append(value.strip())
    return paths


def _paper_argument_requirements(
    unit: dict[str, Any],
    paper_arguments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """正文论证 -> 清洗 -> 按 (角色, 对象) 归并的需求。

    不把 LaTeX 表格、已有图环境和公式外壳放大成独立需求；多段文字指向
    同一对象时合成一个短 takeaway 与一个 visual_question（8.3.1/8.3.4）。
    """
    unit_objects = sorted(declared_mathematical_objects(unit))
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for argument in paper_arguments:
        role = str(argument.get("role", ""))
        if role not in _PURPOSE_ORDER or argument.get("visualizability") not in {
            "high",
            "medium",
        }:
            continue
        raw_claim = str(argument.get("claim", ""))
        if _already_figure_noise(raw_claim):
            continue
        claim = _clean_extraction_text(raw_claim)
        if not _substantive_claim(claim):
            continue
        mathematical_object = (
            unit_objects[0]
            if len(unit_objects) == 1
            else _match_mathematical_object(claim, unit_objects)
        )
        key = (role, mathematical_object)
        grouped.setdefault(key, []).append(
            {
                "claim": claim,
                "argument_unit_ids": [str(argument["argument_id"])],
                "source_span": argument.get("source_span"),
            }
        )
    requirements: list[dict[str, Any]] = []
    for (role, mathematical_object), items in grouped.items():
        takeaway = _compose_takeaway([item["claim"] for item in items])
        if not takeaway:
            continue
        route = _route_for(mathematical_object)
        requirements.append(
            {
                "purpose": role,
                "mathematical_object": mathematical_object,
                "visual_question": f"如何让评委直接看到：{takeaway}？",
                "claim": takeaway,
                "argument_unit_ids": sorted(
                    {
                        argument_id
                        for item in items
                        for argument_id in item["argument_unit_ids"]
                    }
                ),
                "preferred_structures": route["preferred_structures"],
                "forbidden_defaults": route["forbidden_defaults"],
                "preferred_archetypes": route["preferred_archetypes"],
                "source_span": items[0].get("source_span"),
                "paper_derived": True,
            }
        )
    return requirements


def _question_requirements(
    *,
    root: Path,
    question_id: str,
    unit: dict[str, Any],
    materials: list[dict[str, Any]],
    result_ids: set[str],
    insight_ids: set[str],
    paper_arguments: list[dict[str, Any]],
    figures: list[dict[str, Any]],
    source_paths: Iterable[Path],
) -> list[dict[str, Any]]:
    """生成一问的视觉需求；事前合同优先，正文抽取只补充遗漏。"""
    explicit = _visual_output_requirements(unit)
    paper_derived = _paper_argument_requirements(unit, paper_arguments)
    purposes = {
        _PURPOSE_BY_OBLIGATION[item]
        for item in derive_visual_requirements(unit).obligations
        if item in _PURPOSE_BY_OBLIGATION
    }
    for purpose, categories in _MATERIAL_CATEGORY_BY_PURPOSE.items():
        if any(
            str(item.get("category", "")).strip().casefold() in categories
            for item in materials
        ):
            purposes.add(purpose)
    present = {
        str(item["purpose"])
        for item in (*explicit, *paper_derived)
        if item.get("purpose") in _PURPOSE_ORDER
    }
    # 义务兜底必须同时有真实素材支撑，否则只生成空泛需求（8.3.6）。
    material_seeds: list[dict[str, Any]] = []
    for purpose in _PURPOSE_ORDER:
        if purpose in present or purpose not in purposes:
            continue
        material = _first_material(materials, purpose)
        if material is None:
            continue
        content = str(material.get("content", "")).strip()
        if not _substantive_claim(content):
            continue
        material_seeds.append(
            {
                "purpose": purpose,
                "mathematical_object": "",
                "visual_question": f"如何让评委直接看到：{str(material.get('title', '')).strip() or content}？",
                "claim": content,
                "argument_unit_ids": [],
                "preferred_structures": [],
                "forbidden_defaults": [],
                "preferred_archetypes": [],
                "ordinal": 0,
            }
        )
    seeds = explicit + paper_derived + material_seeds
    if not seeds:
        # 整问没有任何对象、论证或素材时，只保留一条可回答的 model_understanding 兜底。
        seeds = [
            {
                "purpose": "model_understanding",
                "mathematical_object": "",
                "visual_question": f"如何让评委直接看到 {question_id} 的核心模型对象？",
                "claim": f"{question_id} 的核心模型对象与判定机制需要视觉支持。",
                "argument_unit_ids": [],
                "preferred_structures": [],
                "forbidden_defaults": [],
                "preferred_archetypes": [],
                "ordinal": 0,
            }
        ]
    requirements: list[dict[str, Any]] = []
    for seed in seeds:
        purpose = str(seed["purpose"])
        if purpose not in _PURPOSE_ORDER:
            purpose = "model_understanding"
        material = _first_material(materials, purpose)
        title = str(material.get("title", "")).strip() if material else ""
        content = str(material.get("content", "")).strip() if material else ""
        claim = str(seed.get("claim", "")).strip() or content or (
            f"{question_id} 的{purpose}论证需要视觉支持"
        )
        visual_question = str(seed.get("visual_question", "")).strip() or (
            f"如何让评委直接看到：{title or claim}？"
        )
        argument_unit_ids = set(map(str, seed.get("argument_unit_ids", [])))
        mathematical_object = str(seed.get("mathematical_object", "")).strip()
        route = _route_for(mathematical_object)
        preferred = list(dict.fromkeys([
            *map(str, seed.get("preferred_structures", [])),
            *route["preferred_structures"],
        ]))
        # Hero 名额只给事前 visual_outputs 合同（9.1）；正文抽取需求默认 supporting，
        # 避免正文段落反向把验证段升格为主图。
        figure_tier = (
            "hero_figure"
            if (
                purpose == "decisive_evidence"
                and unit.get("core_question") is True
                and not seed.get("paper_derived")
            )
            else "supporting_figure"
        )
        requirement: dict[str, Any] = {
            "question_id": question_id,
            "figure_tier": figure_tier,
            "purpose": purpose,
            "mathematical_object": mathematical_object,
            "claim": claim,
            "visual_question": visual_question,
            "source_result_ids": sorted(result_ids),
            "source_insight_ids": sorted(insight_ids),
            "argument_unit_ids": sorted(argument_unit_ids),
            "preferred_structures": preferred,
            "forbidden_defaults": [
                str(item)
                for item in seed.get("forbidden_defaults", [])
                or route["forbidden_defaults"]
            ],
            "preferred_archetypes": (
                seed.get("preferred_archetypes")
                or route["preferred_archetypes"]
                or _PREFERRED_ARCHETYPES[purpose]
            ),
            # 事前 visual_outputs 声明的 required_visibility 必须贯穿到机会池，
            # 不能在中途重建 requirement 时丢弃（否则下游只知道“要画什么对象”，
            # 不知道“正式图必须同时看到哪些要素”）。
            "required_visibility": [
                str(item)
                for item in seed.get("required_visibility", [])
                if isinstance(item, str) and item.strip()
            ],
            "source_artifact_paths": list(
                dict.fromkeys(
                    [
                        str(item)
                        for item in seed.get("source_artifact_paths", [])
                        if isinstance(item, str) and item.strip()
                    ]
                    + _object_artifact_paths(unit, mathematical_object)
                )
            ),
            "source_span": seed.get("source_span"),
        }
        requirement["paper_image_opportunity"] = recommend_paper_image(requirement, unit)
        digest = _requirement_digest(requirement)
        requirement["requirement_digest"] = digest
        requirement["requirement_id"] = f"VR-{question_id}-{purpose}-{digest[:10]}"
        covered = [
            str(figure.get("figure_id"))
            for figure in figures
            if isinstance(figure.get("figure_id"), str)
            and _figure_covers(
                root,
                figure,
                requirement_id=requirement["requirement_id"],
                requirement_digest=digest,
                source_paths=source_paths,
            )
        ]
        requirement["covered_by_figure_ids"] = covered
        requirement["status"] = "covered" if covered else "open"
        requirements.append(requirement)
    return requirements


def _visual_source_paths(root: Path, source_role: str) -> list[Path]:
    """按创作/发布阶段选择图消费文本，禁止最终门混用长稿。"""
    if source_role == "author_draft":
        for relative in ("paper/longform-source.tex", "paper/longform-source.typ"):
            path = root / relative
            if path.is_file():
                return [path]
        # Author 尚未落稿时，需求只能来自建模合同和素材，不能提前借正式模板正文。
        return []
    if source_role not in {"author_draft", "publication"}:
        raise ContractError("source_role 必须为 author_draft 或 publication")
    return publication_text_sources(root)


def derive_visual_requirements_from_paper(
    run_dir: Path,
    *,
    source_role: str = "author_draft",
) -> dict[str, Any]:
    """只读推导论文视觉需求；最终候选稿须显式使用 ``publication``。"""
    root = run_dir.resolve()
    state = read_simple_state(root)
    modeling = _optional_json(root, "analysis/MODELING_UNITS.json")
    materials = _optional_json(root, "paper/generated/material_pool.json")
    units = _units_by_question(modeling)
    grouped_materials = _materials_by_question(materials)
    results = _answer_result_ids(root)
    figures = _current_figures(root)
    source_paths = _visual_source_paths(root, source_role)
    paper_arguments = extract_paper_argument_units(
        root, write=True, source_role=source_role
    ).get("arguments", [])
    requirements = [
        requirement
        for question_id in state.get("required_questions", [])
        for requirement in _question_requirements(
            root=root,
            question_id=str(question_id),
            unit=units.get(str(question_id), {}),
            materials=grouped_materials.get(str(question_id), []),
            result_ids=results.get(str(question_id), set()),
            insight_ids=_insight_ids(units.get(str(question_id), {})),
            paper_arguments=[
                item
                for item in paper_arguments
                if isinstance(item, dict) and item.get("question_id") == str(question_id)
            ],
            figures=figures,
            source_paths=source_paths,
        )
    ]
    from shumozizi.paper.policy import workflow_quality_policy

    quota_enabled = workflow_quality_policy(root) == "competition-quality-v1"
    payload: dict[str, Any] = {
        "schema_name": "paper_visual_requirements",
        "schema_version": "1.3" if quota_enabled else "1.2",
        "run_id": state["run_id"],
        "generation_policy": (
            "argument_driven_with_advanced_figure_quota"
            if quota_enabled
            else "argument_driven_no_figure_count_target"
        ),
        "figure_tiers": {
            "hero_figure": (
                "仅用于最关键、最值得记忆的视觉论证；仍须由正式 current 图实际消费。"
            ),
            "supporting_figure": (
                "按推导、机制、比较与边界分配；新质量合同要求每个必答问题 2--3 张，"
                "全篇至少 12 张且至少 3 种图型。"
                if quota_enabled
                else "按推导、机制、比较与边界的实际论证需要生成，不设数量上限。"
            ),
        },
        "review_policy": {
            "mode": "open_world_discovery_then_requirement_reconciliation",
            "discovery_blind_to_requirements": True,
            "discovery_artifact": "review/VISUAL_DISCOVERY.json",
        },
        "input_hashes": _input_hashes(root),
        "requirements": requirements,
        "summary": {
            "total": len(requirements),
            "covered": sum(item["status"] == "covered" for item in requirements),
            "open": sum(item["status"] == "open" for item in requirements),
        },
        "generated_at": utc_now(),
    }
    if quota_enabled:
        payload["advanced_figure_quota"] = advanced_figure_quota_payload()
    require_valid(payload, "paper_visual_requirements")
    return payload


def _sync_open_requirements(run_dir: Path, payload: dict[str, Any]) -> None:
    """把未覆盖需求追加到 living opportunity pool，并保留既有评阅状态。"""
    from shumozizi.simple.visual_opportunities import (
        VISUAL_OPPORTUNITY_POOL_PATH,
        build_visual_opportunity_pool,
        read_visual_opportunity_pool,
        write_visual_opportunity_pool,
    )

    root = run_dir.resolve()
    try:
        existing = read_visual_opportunity_pool(root)
        existing_items = list(existing.get("opportunities", []))
    except (ContractError, OSError, TypeError, ValueError):
        existing_items = []
    refreshed = build_visual_opportunity_pool(root, opportunities=[], write=False)
    active_ids = {str(item["requirement_id"]) for item in payload["requirements"]}
    existing_items = [
        item
        for item in existing_items
        if not isinstance(item, dict)
        or item.get("origin") != "paper_visual_requirement"
        or item.get("requirement_id") in active_ids
    ]
    known = {
        str(item.get("requirement_id", item.get("opportunity_id", "")))
        for item in existing_items
        if isinstance(item, dict)
    }
    for requirement in payload["requirements"]:
        if requirement["status"] != "open" or requirement["requirement_id"] in known:
            continue
        # candidate_archetypes 必须传真实 renderer archetype ID，而不是人类可读的
        # preferred_structures 描述；机器路由（figure_design、prompt 规划、renderer
        # 分发）只认 archetype ID，否则会在需求与机会之间丢失渲染目标（根因 3）。
        preferred_archetypes = [
            item
            for item in requirement.get("preferred_archetypes", [])
            if isinstance(item, dict) and str(item.get("id", "")).strip()
        ]
        archetype_ids = [
            str(item["id"])
            for item in preferred_archetypes
        ]
        required_data: list[str] = []
        for item in preferred_archetypes:
            for field in item.get("required_data", []):
                if isinstance(field, str) and field.strip() and field not in required_data:
                    required_data.append(field)
        data_availability = availability_for_requirement(root, requirement)
        existing_items.append(
            {
                "opportunity_id": requirement["requirement_id"],
                "question_id": requirement["question_id"],
                "visual_question": requirement["visual_question"],
                "atomic_claim": requirement["claim"],
                "source_result_ids": requirement["source_result_ids"],
                "source_figure_ids": [],
                "candidate_archetypes": archetype_ids
                or [str(item) for item in requirement.get("preferred_structures", [])]
                or ["undecided"],
                "selected_archetype": None,
                "paper_location": requirement["question_id"],
                "status": "candidate",
                "critic_verdict": None,
                "critic_path": None,
                "origin": "paper_visual_requirement",
                "requirement_id": requirement["requirement_id"],
                "requirement_digest": requirement["requirement_digest"],
                "figure_tier": requirement["figure_tier"],
                "purpose": requirement["purpose"],
                "mathematical_object": requirement.get("mathematical_object", ""),
                "argument_role": requirement.get("purpose"),
                "required_visibility": requirement.get("required_visibility", []),
                "required_data": required_data,
                "source_artifact_paths": requirement.get("source_artifact_paths", []),
                "forbidden_defaults": requirement.get("forbidden_defaults", []),
                "source_span": requirement.get("source_span"),
                "paper_image_opportunity": requirement["paper_image_opportunity"],
                "data_availability": data_availability,
            }
        )
    refreshed["opportunities"] = existing_items
    refreshed["status"] = "current" if existing_items else "draft"
    write_visual_opportunity_pool(root, refreshed)
    if not (root / VISUAL_OPPORTUNITY_POOL_PATH).is_file():
        raise ContractError("视觉需求未能写入视觉机会池")


def build_visual_requirements_from_paper(
    run_dir: Path,
    *,
    write: bool = True,
    sync_opportunities: bool = True,
    source_role: str = "author_draft",
) -> dict[str, Any]:
    """生成论文驱动视觉需求，并可把未覆盖需求自动路由到 Visual Sandbox。"""
    root = run_dir.resolve()
    payload = derive_visual_requirements_from_paper(root, source_role=source_role)
    if write:
        atomic_json(root / VISUAL_REQUIREMENTS_PATH, payload)
    if sync_opportunities:
        _sync_open_requirements(root, payload)
    return payload


def _drop_evidence_error(root: Path, record: dict[str, Any]) -> str | None:
    """验证 DROP 是否由当前正式稿中的替代证据闭合。"""
    anchor = record.get("evidence_anchor")
    if not isinstance(anchor, dict):
        return "DROP 未绑定正式稿中的替代证据"
    required = ("kind", "source_path", "source_span", "statement")
    if any(not isinstance(anchor.get(key), str) or not anchor[key].strip() for key in required):
        return "DROP 替代证据字段不完整"
    kind = str(anchor["kind"])
    if kind not in {"figure", "table", "derivation"}:
        return "DROP 替代证据类型无效"
    try:
        current_digest = publication_source_digest(root)
        sources = {path.relative_to(root).as_posix(): path for path in publication_text_sources(root)}
    except ContractError as exc:
        return f"无法读取正式稿: {exc}"
    if record.get("publication_source_sha256") != current_digest:
        return "DROP 未绑定当前正式稿依赖摘要"
    source_path = str(anchor["source_path"])
    source = sources.get(source_path)
    if source is None:
        return "DROP 引用的证据不在正式稿依赖闭包中"
    match = re.fullmatch(r"(.+):(\d+)-(\d+)", str(anchor["source_span"]).strip())
    if match is None or match.group(1) != source_path:
        return "DROP source_span 未绑定声明的正式稿文件"
    start, end = int(match.group(2)), int(match.group(3))
    if start < 1 or end < start:
        return "DROP source_span 行号无效"
    lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
    if end > len(lines):
        return "DROP source_span 超出正式稿范围"
    excerpt = "\n".join(lines[start - 1 : end])
    statement = re.sub(r"\s+", "", str(anchor["statement"]))
    if statement not in re.sub(r"\s+", "", excerpt):
        return "DROP 的可复述替代证据不在声明源码位置"
    if kind == "table" and not re.search(r"\\begin\{(?:tabular|table)|表", excerpt):
        return "DROP 声称表格替代证据，但声明位置没有表格"
    if kind == "derivation" and not re.search(
        r"\\begin\{(?:equation|align)|\\\[|\$|推导|公式|判据", excerpt
    ):
        return "DROP 声称推导替代证据，但声明位置没有推导或公式"
    if kind == "figure":
        figure_id = anchor.get("figure_id")
        if not isinstance(figure_id, str) or not figure_id.strip():
            return "DROP 声称图替代证据，但缺少 figure_id"
        figures = _optional_json(root, "figures/index.json").get("figures", [])
        figure = next(
            (
                item
                for item in figures
                if isinstance(item, dict)
                and item.get("figure_id") == figure_id
                and item.get("status") == "current"
            ),
            None,
        )
        if figure is None:
            return "DROP 引用的替代图不是 current 正式图"
        anchors = {figure_id}
        for output in figure.get("outputs", []):
            if isinstance(output, dict) and isinstance(output.get("path"), str):
                output_path = str(output["path"]).replace("\\", "/")
                anchors.update({output_path, Path(output_path).name, Path(output_path).stem})
        if not any(value in excerpt.replace("\\", "/") for value in anchors):
            return "DROP 的替代图未在声明正式稿位置被实际引用"
    return None


def validate_paper_visual_requirement_closure(run_dir: Path) -> list[str]:
    """复验已启用新闭环的运行是否处置了全部当前视觉需求。

    旧运行没有 ``VISUAL_REQUIREMENTS.json`` 时保持兼容；一旦生成过该文件，
    current 图覆盖或带实质评阅记录的 DROP 才能关闭需求。
    """
    root = run_dir.resolve()
    path = root / VISUAL_REQUIREMENTS_PATH
    if not path.is_file():
        return []
    try:
        recorded = load_json(path)
        if recorded.get("run_id") != read_simple_state(root)["run_id"]:
            return ["VISUAL_REQUIREMENT_OPEN：视觉需求 run_id 与当前运行不一致"]
        # 候选稿闭环只能读取正式入口，Author 长稿中的图或替代解释不能代为放行。
        current = derive_visual_requirements_from_paper(root, source_role="publication")
        from shumozizi.simple.visual_opportunities import read_visual_opportunity_pool

        pool = read_visual_opportunity_pool(root)
        opportunities = {
            str(item.get("requirement_id", item.get("opportunity_id", ""))): item
            for item in pool.get("opportunities", [])
            if isinstance(item, dict)
        }
    except (ContractError, OSError, TypeError, ValueError) as exc:
        return [f"VISUAL_REQUIREMENT_OPEN：视觉需求或机会池无法复验：{exc}"]

    errors: list[str] = []
    for requirement in current["requirements"]:
        if requirement["status"] == "covered":
            continue
        requirement_id = requirement["requirement_id"]
        opportunity = opportunities.get(requirement_id)
        if not isinstance(opportunity, dict):
            errors.append(
                f"VISUAL_REQUIREMENT_OPEN：{requirement_id} 尚未路由到视觉机会池"
            )
            continue
        if (
            opportunity.get("status") == "drop"
            and opportunity.get("critic_verdict") == "DROP"
            and opportunity.get("requirement_digest") == requirement["requirement_digest"]
        ):
            critic_path = opportunity.get("critic_record_path")
            if isinstance(critic_path, str):
                try:
                    critic = resolve_inside(root, critic_path, must_exist=True)
                except ContractError:
                    critic = None
                if critic is not None:
                    record = load_json(critic)
                    if (
                        record.get("verdict") == "DROP"
                        and record.get("requirement_digest")
                        == requirement["requirement_digest"]
                    ):
                        evidence_error = _drop_evidence_error(root, record)
                        if evidence_error is None:
                            continue
                        errors.append(
                            f"VISUAL_REQUIREMENT_OPEN：{requirement_id} 的 DROP 无效：{evidence_error}"
                        )
                        continue
        errors.append(
            f"VISUAL_REQUIREMENT_OPEN：{requirement_id} 尚未由 current 图覆盖或经实质评阅放弃"
        )
    return errors
