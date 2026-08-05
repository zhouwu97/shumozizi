"""从论文论证需求生成轻量视觉需求，并路由到视觉机会池。"""

from __future__ import annotations

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
from shumozizi.simple.state import read_simple_state, utc_now
from shumozizi.simple.visual_requirements import derive_visual_requirements

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
_FIGURE_ROLES_BY_PURPOSE = {
    "model_understanding": {
        "model_understanding",
        "schematic",
        "data_portrait",
        "question_hero",
    },
    "decisive_evidence": {"decisive_evidence", "insight", "question_hero"},
    "mechanism": {"mechanism", "insight", "question_hero"},
    "boundary": {"boundary", "stability", "insight"},
}
_PREFERRED_STRUCTURES = {
    "model_understanding": ["mathematical-object schematic", "structure map"],
    "decisive_evidence": ["baseline comparison", "decision surface"],
    "mechanism": ["active-constraint plot", "mechanism map"],
    "boundary": ["sensitivity curve", "feasible-region boundary"],
}


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
    figure: dict[str, Any],
    *,
    question_id: str,
    purpose: str,
    result_ids: set[str],
    argument_unit_ids: set[str],
) -> bool:
    """判断 current 图是否在对象、证据来源和论证角色上覆盖需求。"""
    figure_questions = _strings(figure.get("question_id")) | _strings(
        figure.get("question_ids")
    )
    figure_results = _strings(figure.get("source_result_ids"))
    figure_arguments = _strings(figure.get("argument_unit_ids")) | _strings(
        figure.get("argument_unit_id")
    )
    # 显式论证单元比问题级作用域更精确；否则一张 Q1 主图会错误关闭 Q1
    # 下所有同角色 supporting requirements。
    same_scope = (
        bool(argument_unit_ids.intersection(figure_arguments))
        if argument_unit_ids
        else question_id in figure_questions or bool(result_ids.intersection(figure_results))
    )
    if not same_scope:
        return False
    obligations = _strings(figure.get("obligation_types"))
    role = str(figure.get("role", figure.get("promotion_role", ""))).casefold()
    return purpose in obligations or role in _FIGURE_ROLES_BY_PURPOSE[purpose]


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
    """把事前 visual_outputs 转为不依赖 Figure Plan 的显式需求。"""
    requirements: list[dict[str, Any]] = []
    for index, raw in enumerate(unit.get("visual_outputs", []), 1):
        if not isinstance(raw, dict):
            continue
        visual_question = str(raw.get("visual_question", "")).strip()
        claim = str(raw.get("takeaway", raw.get("claim", ""))).strip()
        if not visual_question and not claim:
            continue
        archetype = str(raw.get("visual_archetype", raw.get("archetype", ""))).strip()
        requirements.append(
            {
                "purpose": str(raw.get("purpose", "model_understanding")),
                "visual_question": visual_question or f"如何直观看到：{claim}？",
                "claim": claim or visual_question,
                "argument_unit_ids": sorted(
                    _strings(raw.get("argument_unit_ids"))
                    | _strings(raw.get("argument_unit_id"))
                ),
                "preferred_structures": [archetype] if archetype else [],
                "ordinal": index,
            }
        )
    return requirements


def _question_requirements(
    *,
    question_id: str,
    unit: dict[str, Any],
    materials: list[dict[str, Any]],
    result_ids: set[str],
    insight_ids: set[str],
    figures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """生成一问的视觉需求；按论证角色生成，不按固定图数生成。"""
    explicit = _visual_output_requirements(unit)
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

    seeds = explicit + [
        {
            "purpose": purpose,
            "visual_question": "",
            "claim": "",
            "argument_unit_ids": [],
            "preferred_structures": [],
            "ordinal": 0,
        }
        for purpose in _PURPOSE_ORDER
        if purpose in purposes and not any(item["purpose"] == purpose for item in explicit)
    ]
    requirements: list[dict[str, Any]] = []
    purpose_counts: dict[str, int] = {}
    for seed in seeds:
        purpose = str(seed["purpose"])
        if purpose not in _PURPOSE_ORDER:
            purpose = "model_understanding"
        purpose_counts[purpose] = purpose_counts.get(purpose, 0) + 1
        suffix = purpose_counts[purpose]
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
        covered = [
            str(figure.get("figure_id"))
            for figure in figures
            if isinstance(figure.get("figure_id"), str)
            and _figure_covers(
                figure,
                question_id=question_id,
                purpose=purpose,
                result_ids=result_ids,
                argument_unit_ids=argument_unit_ids,
            )
        ]
        requirement_id = f"VR-{question_id}-{purpose}"
        if suffix > 1:
            requirement_id += f"-{suffix}"
        preferred = list(dict.fromkeys([
            *map(str, seed.get("preferred_structures", [])),
            *_PREFERRED_STRUCTURES[purpose],
        ]))
        requirements.append(
            {
                "requirement_id": requirement_id,
                "question_id": question_id,
                "figure_tier": (
                    "hero_figure"
                    if purpose == "decisive_evidence" and unit.get("core_question") is True
                    else "supporting_figure"
                ),
                "purpose": purpose,
                "claim": claim,
                "visual_question": visual_question,
                "source_result_ids": sorted(result_ids),
                "source_insight_ids": sorted(insight_ids),
                "argument_unit_ids": sorted(argument_unit_ids),
                "preferred_structures": preferred,
                "covered_by_figure_ids": covered,
                "status": "covered" if covered else "open",
            }
        )
    return requirements


def derive_visual_requirements_from_paper(run_dir: Path) -> dict[str, Any]:
    """只读推导当前论文视觉需求，不写文件或改变阶段状态。"""
    root = run_dir.resolve()
    state = read_simple_state(root)
    modeling = _optional_json(root, "analysis/MODELING_UNITS.json")
    materials = _optional_json(root, "paper/generated/material_pool.json")
    units = _units_by_question(modeling)
    grouped_materials = _materials_by_question(materials)
    results = _answer_result_ids(root)
    figures = _current_figures(root)
    requirements = [
        requirement
        for question_id in state.get("required_questions", [])
        for requirement in _question_requirements(
            question_id=str(question_id),
            unit=units.get(str(question_id), {}),
            materials=grouped_materials.get(str(question_id), []),
            result_ids=results.get(str(question_id), set()),
            insight_ids=_insight_ids(units.get(str(question_id), {})),
            figures=figures,
        )
    ]
    payload = {
        "schema_name": "paper_visual_requirements",
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "generation_policy": "argument_driven_no_figure_count_target",
        "figure_tiers": {
            "hero_figure": "仅用于最关键、最值得记忆的视觉论证；建议数量不是硬门。",
            "supporting_figure": "按推导、机制、比较与边界的实际论证需要生成，不设数量上限。",
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
    known = {
        str(item.get("requirement_id", item.get("opportunity_id", "")))
        for item in existing_items
        if isinstance(item, dict)
    }
    for requirement in payload["requirements"]:
        if requirement["status"] != "open" or requirement["requirement_id"] in known:
            continue
        existing_items.append(
            {
                "opportunity_id": requirement["requirement_id"],
                "question_id": requirement["question_id"],
                "visual_question": requirement["visual_question"],
                "atomic_claim": requirement["claim"],
                "source_result_ids": requirement["source_result_ids"],
                "source_figure_ids": [],
                "candidate_archetypes": requirement["preferred_structures"],
                "selected_archetype": None,
                "paper_location": requirement["question_id"],
                "status": "candidate",
                "critic_verdict": None,
                "critic_path": None,
                "origin": "paper_visual_requirement",
                "requirement_id": requirement["requirement_id"],
                "figure_tier": requirement["figure_tier"],
                "purpose": requirement["purpose"],
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
) -> dict[str, Any]:
    """生成论文驱动视觉需求，并可把未覆盖需求自动路由到 Visual Sandbox。"""
    root = run_dir.resolve()
    payload = derive_visual_requirements_from_paper(root)
    if write:
        atomic_json(root / VISUAL_REQUIREMENTS_PATH, payload)
    if sync_opportunities:
        _sync_open_requirements(root, payload)
    return payload


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
        current = derive_visual_requirements_from_paper(root)
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
        if opportunity.get("status") == "drop" and opportunity.get("critic_verdict") == "DROP":
            critic_path = opportunity.get("critic_path")
            if isinstance(critic_path, str):
                try:
                    critic = resolve_inside(root, critic_path, must_exist=True)
                except ContractError:
                    critic = None
                if critic is not None and critic.stat().st_size > 0:
                    continue
        errors.append(
            f"VISUAL_REQUIREMENT_OPEN：{requirement_id} 尚未由 current 图覆盖或经实质评阅放弃"
        )
    return errors
