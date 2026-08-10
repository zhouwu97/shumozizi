"""为论文视觉机会生成可追溯的 A/B 解释图 Prompt。

Prompt 是设计参考，关键数字和公式必须在正式 renderer 中从 current 结果重生成，
不能把模型生成的文字直接当作论文事实。
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, relative_inside, sha256_file
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.paper.visual_requirements import (
    VISUAL_REQUIREMENTS_PATH,
    build_visual_requirements_from_paper,
)
from shumozizi.simple.paper_image_types import (
    ACADEMIC_INFOGRAPHIC_STYLE,
    MIN_NON_TEXT_VISUAL_ELEMENTS,
    SUPPORTED_LAYOUT_VARIANTS,
    SUPPORTED_VISUAL_ELEMENT_TYPES,
    recommend_paper_image,
)

PROMPT_ROOT = Path("figures/prompts")
TEMPLATE_ROOT = Path("templates/image_prompts")
PLAN_PATH = PROMPT_ROOT / "plan.json"

_EXTRACTION_NOISE = re.compile(
    r"(?:\b(?:longtable|tabularx?|enumerate|includegraphics)\b|"
    r"(?:table|figure|equation)\[.*?\]|\\\\|&[^&]{0,80}&)",
    re.IGNORECASE,
)
_PROCESS_TERMS = (
    "框架",
    "流程",
    "模型",
    "机制",
    "状态",
    "事件",
    "队列",
    "更新",
    "输入",
    "输出",
    "判定",
    "algorithm",
    "framework",
    "state",
    "event",
)


def _atomic_text(path: Path, value: str) -> None:
    """在同目录安全替换 Prompt 文本，避免中断留下半文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _optional_json(root: Path, relative: str) -> dict[str, Any]:
    """读取可选运行文件，缺失时返回空对象。"""
    path = root / relative
    if not path.is_file():
        return {}
    value = load_json(path)
    return value if isinstance(value, dict) else {}


def _input_hashes(root: Path) -> dict[str, str]:
    """绑定 Prompt Builder 实际消费的运行输入，避免旧数字静默复用。"""
    relatives = (
        "analysis/MODELING_UNITS.json",
        "paper/answer-map.json",
        "analysis/answer_map.json",
        "results/index.json",
        "paper/generated/VISUAL_REQUIREMENTS.json",
        "paper/generated/material_pool.json",
    )
    return {
        relative: sha256_file(root / relative)
        for relative in relatives
        if (root / relative).is_file()
    }


def _priority(requirement: dict[str, Any], unit: dict[str, Any]) -> tuple[str, str]:
    """依据结构化论证角色给机会分级；关键词只作为 claim 的弱补充信号。"""
    recommendation = recommend_paper_image(requirement, unit)
    return str(recommendation["priority"]), str(recommendation["reason"])


def _visual_type(requirement: dict[str, Any]) -> str:
    """把已有视觉目的映射为 P0 支持的类型。"""
    return str(recommend_paper_image(requirement, {})["recommended_visual_type"])


def _result_metrics(root: Path, result_ids: list[str]) -> list[dict[str, Any]]:
    """提取正式结果登记的标量指标，并保留 metric_sources 追溯信息。"""
    index = _optional_json(root, "results/index.json")
    wanted = set(result_ids)
    preserved: list[dict[str, Any]] = []
    for result in index.get("results", []):
        if not isinstance(result, dict) or result.get("result_id") not in wanted:
            continue
        if result.get("execution_valid") is not True or result.get("status") != "current":
            continue
        metrics = result.get("metrics", {})
        sources = result.get("metric_sources", {})
        if not isinstance(metrics, dict):
            continue
        for label, value in metrics.items():
            if isinstance(value, (str, int, float, bool)) and value is not None:
                preserved.append(
                    {
                        "label": str(label),
                        "value": value,
                        "source_result_id": result["result_id"],
                        "metric_source": sources.get(label) if isinstance(sources, dict) else None,
                    }
                )
    return preserved[:12]


def _visual_elements(requirement: dict[str, Any], unit: dict[str, Any]) -> list[dict[str, Any]]:
    """从建模单元的真实结构字段规划至少两种非文字视觉元素。"""
    required_fields = {
        str(field).casefold()
        for output in unit.get("visual_outputs", [])
        if isinstance(output, dict)
        for field in output.get("required_data", [])
    }
    kind = str(unit.get("unit_kind", "")).casefold()
    elements: list[dict[str, Any]] = []

    def add(
        element_type: str,
        label: str,
        role: str,
        instruction: str,
        data_requirements: list[str],
    ) -> None:
        if element_type not in SUPPORTED_VISUAL_ELEMENT_TYPES:
            raise ContractError(f"不支持的论文信息图元素类型: {element_type}")
        if any(item["type"] == element_type for item in elements):
            return
        elements.append(
            {
                "type": element_type,
                "label": label,
                "role": role,
                "required": True,
                "instruction": instruction,
                "data_requirements": data_requirements,
            }
        )

    add(
        "formula",
        "核心状态方程或判定函数",
        "mathematical_object",
        "在模块内放置一条短公式或判据，红色点缀；正式公式由 renderer 填入。",
        sorted(required_fields.intersection({"events", "time", "state_trajectory", "objective_values"})),
    )
    if kind in {"simulation", "coordination", "optimization"} or {"nodes", "edges"}.intersection(required_fields):
        add(
            "network_sketch",
            "对象拓扑或路径微型示意",
            "mathematical_object",
            "用 3--6 个节点和有向边画出真实对象关系，不使用空白矩形替代。",
            sorted(required_fields.intersection({"nodes", "edges", "routes", "assignments"})),
        )
    if {"events", "state_trajectory", "states", "control_trajectory"}.intersection(required_fields) or kind in {"simulation", "coordination"}:
        add(
            "state_diagram",
            "状态/事件推进示意",
            "mechanism",
            "显示当前状态、事件队列或状态更新回路，至少包含一个状态变化箭头。",
            sorted(required_fields.intersection({"events", "state_trajectory", "states", "control_trajectory"})),
        )
    if {"time", "event_times", "timestamps"}.intersection(required_fields) or kind in {"simulation", "coordination"}:
        add(
            "timeline",
            "绝对时间轴或事件窗口",
            "mechanism",
            "用时间刻度、窗口或批次标记表达事件先后，不把时间关系压成普通文本。",
            sorted(required_fields.intersection({"time", "event_times", "timestamps"})),
        )
    if {"time", "events", "state_trajectory", "objective_values"}.intersection(required_fields):
        add(
            "mini_chart",
            "累计状态与阈值迷你曲线",
            "decision_evidence",
            "用一条累计量-时间小曲线标出关键阈值与首次达到时刻；只保留符号占位，正式值由 renderer 填入。",
            sorted(
                required_fields.intersection(
                    {"time", "events", "state_trajectory", "objective_values"}
                )
            ),
        )
    if requirement.get("source_result_ids"):
        add(
            "metric",
            "当前结果指标",
            "decisive_evidence",
            "保留一至两个由 current 结果绑定的关键指标卡，避免生成未绑定数字。",
            ["source_result_ids"],
        )
    if (
        unit.get("core_question") is True
        or str(requirement.get("purpose")) == "decisive_evidence"
        or isinstance(unit.get("answer_contract"), dict)
    ):
        add(
            "decision_node",
            "核心判定或输出",
            "decision",
            "用菱形或高亮节点突出正式判据、首达/充满或方案选择。",
            ["answer_contract"],
        )
    if len(elements) < MIN_NON_TEXT_VISUAL_ELEMENTS:
        add(
            "icon",
            "语义线性图标",
            "orientation",
            "使用一个与数学对象对应的线性图标，不能用装饰性图标填空。",
            [],
        )
    return elements


def _image_id(requirement: dict[str, Any], visual_type: str) -> str:
    """用需求身份构造稳定且唯一的 ASCII 图片 ID。"""
    question_id = re.sub(r"[^A-Za-z0-9_-]+", "-", str(requirement.get("question_id", "question")))
    purpose = re.sub(r"[^A-Za-z0-9_-]+", "-", str(requirement.get("purpose", "visual")))
    digest = str(requirement.get("requirement_digest", "")).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{10,64}", digest):
        requirement_id = str(requirement.get("requirement_id", "")).strip()
        digest = hashlib.sha256(requirement_id.encode("utf-8")).hexdigest()
    return f"{question_id}_{purpose}_{digest[:10]}_{visual_type}"


def _candidate_score(requirement: dict[str, Any], unit: dict[str, Any]) -> tuple[int, list[str]]:
    """给 Hero 候选排序，并显式惩罚正文抽取噪声。

    决定性证据、机制和边界论证与 model_understanding 一样可以成为 Hero 候选
    （9.1）；数学对象声明的候选优先于通用流程图。
    """
    claim = str(requirement.get("claim", "")).strip()
    visual_question = str(requirement.get("visual_question", "")).strip()
    combined = f"{claim} {visual_question}"
    score = 0
    reasons: list[str] = []
    if requirement.get("status") == "covered" or requirement.get("covered_by_figure_ids"):
        return -1000, ["already_covered_by_current_figure"]
    if not claim or len(claim) > 900 or _EXTRACTION_NOISE.search(combined):
        return -800, ["latex_or_longform_extraction_noise"]
    if 70 <= len(claim) <= 520:
        score += 20
        reasons.append("claim_length_suitable_for_hero")
    if requirement.get("source_span"):
        score += 12
        reasons.append("bound_to_paper_argument")
    purpose = str(requirement.get("purpose", ""))
    tier = str(requirement.get("figure_tier", ""))
    if tier == "hero_figure" and purpose == "decisive_evidence":
        score += 30
        reasons.append("decisive_evidence_hero")
    elif tier == "hero_figure":
        score += 18
        reasons.append("hero_figure_tier")
    elif purpose in {"mechanism", "boundary"}:
        score += 12
        reasons.append(f"{purpose}_argument_role")
    mathematical_object = str(requirement.get("mathematical_object", "")).strip()
    if mathematical_object:
        score += 22
        reasons.append(f"object_aware={mathematical_object}")
    process_hits = sum(term.casefold() in combined.casefold() for term in _PROCESS_TERMS)
    score += min(process_hits, 6) * 6
    if process_hits:
        reasons.append(f"process_terms={process_hits}")
    structures = {str(item).casefold() for item in requirement.get("preferred_structures", [])}
    if structures.intersection({"mathematical-object schematic", "structure map"}):
        score += 10
        reasons.append("structure_schematic_fit")
    required_fields = {
        str(field).casefold()
        for output in unit.get("visual_outputs", [])
        if isinstance(output, dict)
        for field in output.get("required_data", [])
    }
    score += min(len(required_fields.intersection({"nodes", "edges", "events", "time", "state_trajectory"})), 5) * 2
    return score, reasons


# 全篇少量 Hero 预算：只让最高价值的少数论证进入正式结构竞争，supporting 按需。
HERO_BUDGET = 4


def _selected_hero_ids(
    requirements: list[dict[str, Any]], units: dict[str, dict[str, Any]]
) -> tuple[set[str], dict[str, dict[str, Any]]]:
    """按全篇预算选择最高价值 Hero，不机械限制每问一个（9.1）。"""
    diagnostics: dict[str, dict[str, Any]] = {}
    scored: list[tuple[int, str, list[str]]] = []
    for requirement in requirements:
        question_id = str(requirement.get("question_id", "question"))
        requirement_id = str(requirement.get("requirement_id", ""))
        score, reasons = _candidate_score(requirement, units.get(question_id, {}))
        diagnostics[requirement_id] = {"selection_score": score, "selection_reasons": reasons}
        if score >= 0:
            scored.append((score, requirement_id, reasons))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = {
        requirement_id
        for _, requirement_id, _ in scored[:HERO_BUDGET]
    }
    return selected, diagnostics


def _elements_text(elements: list[dict[str, Any]]) -> str:
    """把结构化元素计划渲染成 Prompt 片段。"""
    return "\n".join(
        f"- {item['type']}: {item['label']}；{item['instruction']}"
        for item in elements
    )


def _clean_prompt_text(value: object) -> str:
    """移除论文抽取产生的引用标签，保留可读的科学语义。"""
    text = str(value or "").strip()
    text = re.sub(r"(?:fig|eq|tab):[A-Za-z0-9._-]+", "", text)
    text = re.sub(
        r"(?<=[\u4e00-\u9fff。；，])(?:[a-z]{3,}\d{4})(?:,[a-z]{3,}\d{4})*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", text).strip()


def _title_spec(requirement: dict[str, Any], unit: dict[str, Any]) -> str:
    """给生成器提供短而明确的双语标题，避免照抄长段正文。"""
    question_id = str(requirement.get("question_id", "Q"))
    claim = _clean_prompt_text(requirement.get("claim"))
    answer = unit.get("answer_contract", {})
    required_output = (
        _clean_prompt_text(answer.get("required_output"))
        if isinstance(answer, dict)
        else ""
    )
    combined = f"{claim} {required_output}"
    if "传播" in combined and "首次到达" in combined and "充满" in combined:
        return (
            f'中文主标题（逐字）："{question_id} 单源传播：共享状态驱动首达与充满判定"\n'
            '英文副标题（逐字）："Event-driven propagation with shared state and threshold decisions"'
        )
    labels = {
        "simulation": ("事件驱动仿真框架", "Event-driven simulation framework"),
        "coordination": ("协同决策框架", "Coordinated decision framework"),
        "optimization": ("约束优化框架", "Constraint-aware optimization framework"),
        "data_modeling": ("数据建模框架", "Data modeling framework"),
        "evaluation": ("评价与判定框架", "Evaluation and decision framework"),
    }
    chinese, english = labels.get(
        str(unit.get("unit_kind", "")), ("模型与判定框架", "Model and decision framework")
    )
    return f'中文主标题（逐字）："{question_id} {chinese}"\n英文副标题（逐字）："{english}"'


def _content_blueprint(requirement: dict[str, Any], unit: dict[str, Any]) -> str:
    """把结构化单元压缩为可画的模块蓝图，不让生成器自行发明内容。"""
    claim = _clean_prompt_text(requirement.get("claim"))
    answer = unit.get("answer_contract", {})
    required_output = (
        _clean_prompt_text(answer.get("required_output"))
        if isinstance(answer, dict)
        else "正式输出"
    )
    if "水锋" in claim and "优先队列" in claim:
        return "\n".join(
            (
                "- INPUT：微型矿网拓扑 G=(V,E)，用 4--6 个节点、坡向和分支边表达三维几何输入。",
                "- SHARED STATE（视觉面积最大）：单条巷道双端水锋、湿区、分源流量批次和累计体积 V_e(t)。",
                "- EVENT ENGINE：纵向事件优先队列，依次表示水源启动、节点首达、边端贯通、边内相遇；同刻事件先合并。",
                "- JUDGMENT：V_e(t)-t 迷你曲线与三条符号阈值，标注首达、关闭、充满的首次达到时刻。",
                f"- OUTPUT：{required_output}；用两个高亮判定节点突出“首达”和“充满”。",
                "- BOTTOM SUMMARY：共享边状态统一连接几何输入、事件推进与阈值输出。",
            )
        )
    return "\n".join(
        (
            "- INPUT：用真实对象关系的小型结构图表达输入，不用文字列表替代。",
            "- CORE：把中心主张拆成共享状态、更新机制和一个短公式/判据。",
            "- JUDGMENT：用迷你曲线、时间轴或判定节点表达如何得到结论。",
            f"- OUTPUT：{required_output}。",
            "- BOTTOM SUMMARY：用一句话说明输入、核心机制与输出的因果链。",
        )
    )


def _layout_text(variant: str, elements: list[dict[str, Any]]) -> str:
    element_names = "、".join(item["label"] for item in elements)
    if variant == "five_stage_balanced":
        return (
            "采用论文级双语信息图的五阶段水平结构 INPUT -> MODEL -> JUDGMENT -> SOLVE -> OUTPUT；"
            "每个阶段必须包含中文标题、英文副标题、语义图标、至少一个子卡片和公式/关系细节，"
            f"并将 {element_names} 分布到对应阶段。底部加入一句方法总结。"
        )
    if variant == "center_emphasis":
        return (
            "采用中心强化的论文信息图：左侧 INPUT 与对象拓扑，中央最大区域为共享状态/核心机制，"
            "右侧放事件推进、判定和结果小图，底部放继承关系与总结；"
            f"核心区域必须同时容纳 {element_names}，不能退化成一个大矩形。"
        )
    raise ContractError(f"不支持的论文图片版式: {variant}")


def _prompt(requirement: dict[str, Any], unit: dict[str, Any], variant: str, elements: list[dict[str, Any]]) -> str:
    claim = _clean_prompt_text(requirement.get("claim"))
    question = _clean_prompt_text(requirement.get("visual_question"))
    visual_type = _visual_type(requirement)
    template_path = resolve_repo_root(Path(__file__)) / TEMPLATE_ROOT / f"{visual_type}.md"
    if not template_path.is_file():
        raise ContractError(f"缺少论文图片 Prompt 模板: {template_path}")
    return template_path.read_text(encoding="utf-8").format(
        visual_type=visual_type,
        visual_question=question,
        claim=claim,
        title_spec=_title_spec(requirement, unit),
        content_blueprint=_content_blueprint(requirement, unit),
        style_reference=ACADEMIC_INFOGRAPHIC_STYLE,
        visual_elements=_elements_text(elements),
        layout_instruction=_layout_text(variant, elements),
        unit_kind=str(unit.get("unit_kind", "")),
    ).strip()


def _meta(root: Path, requirement: dict[str, Any], unit: dict[str, Any], image_id: str) -> dict[str, Any]:
    """构造轻量验收契约并保留事实来源。"""
    recommendation = recommend_paper_image(requirement, unit)
    priority, reason = _priority(requirement, unit)
    visual_type = str(recommendation["recommended_visual_type"])
    elements = _visual_elements(requirement, unit)
    must_show = [
        str(requirement.get("claim", "")).strip() or "核心模型与判定关系",
        "输入到输出的主要推理方向",
    ]
    answer_contract = unit.get("answer_contract", {})
    if isinstance(answer_contract, dict):
        required_output = str(answer_contract.get("required_output", "")).strip()
        if required_output:
            must_show.append(required_output)
    result_ids = sorted({str(item) for item in requirement.get("source_result_ids", [])})
    must_preserve = [
        {"label": "正式结果来源", "source_result_ids": list(requirement.get("source_result_ids", []))},
        {"label": "视觉需求摘要", "value": str(requirement.get("visual_question", ""))},
        *_result_metrics(root, result_ids),
    ]
    must_not_confuse = [
        "设计参考中的文字、数字和公式不是正式证据，不能替代 current 数据。",
    ]
    return {
        "schema_name": "paper_image_prompt",
        "schema_version": "1.0",
        "image_id": image_id,
        "question_id": requirement.get("question_id"),
        "requirement_id": requirement.get("requirement_id"),
        "requirement_digest": requirement.get("requirement_digest"),
        "visual_type": visual_type,
        "style_reference": ACADEMIC_INFOGRAPHIC_STYLE,
        "style_reference_spec": (
            TEMPLATE_ROOT / "style_references" / f"{ACADEMIC_INFOGRAPHIC_STYLE}.md"
        ).as_posix(),
        "priority": priority,
        "reason": reason,
        "expected_value": recommendation["expected_value"],
        "must_show": must_show,
        "must_preserve": must_preserve,
        "must_not_confuse": must_not_confuse,
        "visual_elements": elements,
        "minimum_non_text_visual_elements": MIN_NON_TEXT_VISUAL_ELEMENTS,
        "layout_variants": sorted(SUPPORTED_LAYOUT_VARIANTS),
        "layout_variant_specs": {
            "five_stage_balanced": "五阶段双语模块，每阶段含子卡片、公式/关系细节和语义图标。",
            "center_emphasis": "核心机制占最大面积，外围输入/事件/判定/输出以互补小图围绕。",
        },
        "input_hashes": _input_hashes(root),
        "source_result_ids": result_ids,
        "status": recommendation["production_status"],
    }


def build_paper_image_prompts(run_dir: Path, *, refresh_requirements: bool = True) -> dict[str, Any]:
    """规划 high/medium 论文解释图并生成 A/B Prompt 文件。"""
    root = run_dir.resolve()
    requirements_path = root / VISUAL_REQUIREMENTS_PATH
    if refresh_requirements or not requirements_path.is_file():
        requirements_payload = build_visual_requirements_from_paper(root, write=True, sync_opportunities=True)
    else:
        requirements_payload = load_json(requirements_path)
    modeling = _optional_json(root, "analysis/MODELING_UNITS.json")
    units = {
        str(item.get("question_id")): item
        for item in modeling.get("units", [])
        if isinstance(item, dict) and item.get("question_id")
    }
    raw_requirements = [
        item
        for item in requirements_payload.get("requirements", [])
        if isinstance(item, dict)
    ]
    selected_ids, diagnostics = _selected_hero_ids(raw_requirements, units)
    root_prompts = root / PROMPT_ROOT
    planned: list[dict[str, Any]] = []
    seen_requirement_ids: set[str] = set()
    seen_image_ids: set[str] = set()
    for requirement in raw_requirements:
        question_id = str(requirement.get("question_id", "question"))
        requirement_id = str(requirement.get("requirement_id", "")).strip()
        if not requirement_id or requirement_id in seen_requirement_ids:
            raise ContractError(f"论文图片需求 ID 缺失或重复: {requirement_id or '<empty>'}")
        seen_requirement_ids.add(requirement_id)
        visual_type = _visual_type(requirement)
        image_id = _image_id(requirement, visual_type)
        if image_id in seen_image_ids:
            raise ContractError(f"论文图片 image_id 重复: {image_id}")
        seen_image_ids.add(image_id)
        meta = _meta(root, requirement, units.get(question_id, {}), image_id)
        meta.update(diagnostics[requirement_id])
        if requirement_id not in selected_ids:
            meta["status"] = "suggested_only"
            if meta["selection_score"] < 0:
                meta["suppression_reason"] = meta["selection_reasons"][0]
            else:
                meta["suppression_reason"] = "outside_global_hero_budget"
        else:
            meta["status"] = "planned"
            meta["selection_role"] = "hero"
        target = root_prompts / image_id
        target.mkdir(parents=True, exist_ok=True)
        atomic_json(target / "meta.json", meta)
        if meta["status"] == "suggested_only":
            planned.append(meta)
            continue
        elements = list(meta.get("visual_elements", []))
        base = _prompt(requirement, units.get(question_id, {}), "five_stage_balanced", elements)
        variant_a = base
        variant_b = _prompt(requirement, units.get(question_id, {}), "center_emphasis", elements)
        _atomic_text(target / "base.txt", base)
        _atomic_text(target / "variant_a.txt", variant_a)
        _atomic_text(target / "variant_b.txt", variant_b)
        meta["prompt_sha256"] = {
            "base": hashlib.sha256(base.encode("utf-8")).hexdigest(),
            "variant_a": hashlib.sha256(variant_a.encode("utf-8")).hexdigest(),
            "variant_b": hashlib.sha256(variant_b.encode("utf-8")).hexdigest(),
        }
        atomic_json(target / "meta.json", meta)
        planned.append(meta)
    payload = {
        "schema_name": "paper_image_prompt_plan",
        "schema_version": "1.1",
        "run_id": root.name,
        "requirements_path": relative_inside(root, requirements_path).as_posix(),
        "prompts_root": relative_inside(root, root_prompts).as_posix(),
        "planned": planned,
        "generated_count": sum(item["status"] == "planned" for item in planned),
        "suggested_only_count": sum(item["status"] == "suggested_only" for item in planned),
    }
    atomic_json(root / PLAN_PATH, payload)
    return payload
