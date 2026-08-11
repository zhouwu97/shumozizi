"""登记并复验 v3 的真实结果图表，不评价其科学结论。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    json_bytes,
    load_json,
    relative_inside,
    resolve_inside,
    sha256_bytes,
    sha256_file,
)
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.core.schema import require_valid
from shumozizi.simple.figure_promotion import validate_human_figure_review
from shumozizi.simple.quality import quality_allows_paper
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import (
    is_competition_first_state,
    is_competition_first_v32_state,
    read_simple_state,
    utc_now,
)

INDEX_PATH = Path("figures/index.json")
FIGURE_PLAN_PATH = Path("figures/FIGURE_PLAN.json")
# 图的三种正当角色。stability 单列，因为舍入、采样层级和数值稳定性图是内部
# 审计产物：它们对评委的边际价值远低于机制、阈值和权衡，不该占据正文版面。
FIGURE_ROLES = frozenset({"model_understanding", "decisive_evidence", "insight", "stability"})
FIGURE_PLACEMENTS = frozenset({"body", "appendix"})
PRESENTATION_ROLES = frozenset({"data_portrait", "question_hero", "supporting", "appendix"})
_APPENDIX_ONLY_ROLES = frozenset({"stability"})
_PRESENTATION_SOURCE_PREFIXES = ("problem/", "analysis/", "results/raw/")
_NON_AUDITABLE_ARCHETYPE_TEMPLATES = frozenset({"", "custom", "zh/cumcm-latex"})

# 分数表达图形原型通常能承载的信息，而非对渲染质量作伪证明。实际图仍需人工
# 查看对象、边界、标注和视觉层级是否真的落地。
_VISUAL_VALUE_PROFILES: dict[str, tuple[int, int, int, int, int] | None] = {
    "spatial_scene_with_constraints": (2, 2, 2, 2, 1),
    "spatial_trajectory_with_constraints": (2, 2, 2, 2, 1),
    "pareto_feasible_region": (2, 2, 2, 2, 2),
    "response_surface_with_constraints": (2, 2, 2, 2, 1),
    "decision_surface_with_fallback": (2, 2, 2, 2, 2),
    "uncertainty_fan_with_threshold": (2, 2, 2, 2, 2),
    "network_flow_bottleneck": (2, 2, 2, 2, 1),
    "spatiotemporal_density": (2, 2, 1, 1, 2),
    "classifier_diagnostic_bundle": (2, 1, 2, 2, 2),
    "cluster_structure_embedding": (2, 2, 1, 1, 1),
    "phase_field_bifurcation": (2, 2, 2, 1, 1),
    "search_trajectory_envelope": (2, 2, 1, 2, 2),
    "multi_panel_evidence_chain": (2, 2, 2, 2, 2),
    "geometric_section_projection": (2, 2, 2, 2, 1),
    "interval_event_timeline": (2, 2, 2, 2, 1),
    "feasible_region_active_constraints": (2, 2, 2, 2, 1),
    "state_control_event_timeline": (2, 2, 2, 2, 1),
    "route_score_comparison": (1, 0, 0, 1, 1),
    "custom": None,
}
_VISUAL_VALUE_DIMENSIONS = (
    "mathematical_object",
    "mechanism_or_structure",
    "constraint_or_boundary",
    "final_decision",
    "uncertainty_or_comparison",
)
_STRUCTURE_AWARE_ARCHETYPES = {
    "spatial": frozenset(
        {
            "spatial_scene_with_constraints",
            "spatial_trajectory_with_constraints",
            "geometric_section_projection",
            "multi_panel_evidence_chain",
            "custom",
        }
    ),
    "temporal": frozenset(
        {
            "interval_event_timeline",
            "state_control_event_timeline",
            "spatial_trajectory_with_constraints",
            "uncertainty_fan_with_threshold",
            "multi_panel_evidence_chain",
            "custom",
        }
    ),
    "set": frozenset(
        {
            "interval_event_timeline",
            "feasible_region_active_constraints",
            "pareto_feasible_region",
            "multi_panel_evidence_chain",
            "custom",
        }
    ),
    "network": frozenset(
        {"network_flow_bottleneck", "multi_panel_evidence_chain", "custom"}
    ),
    "field": frozenset(
        {
            "response_surface_with_constraints",
            "phase_field_bifurcation",
            "spatiotemporal_density",
            "spatial_scene_with_constraints",
            "multi_panel_evidence_chain",
            "custom",
        }
    ),
    "tradeoff": frozenset(
        {
            "pareto_feasible_region",
            "response_surface_with_constraints",
            "decision_surface_with_fallback",
            "feasible_region_active_constraints",
            "multi_panel_evidence_chain",
            "custom",
        }
    ),
    "uncertainty": frozenset(
        {
            "uncertainty_fan_with_threshold",
            "classifier_diagnostic_bundle",
            "search_trajectory_envelope",
            "multi_panel_evidence_chain",
            "custom",
        }
    ),
}
_GENERIC_CHART_ARCHETYPES = frozenset({"route_score_comparison"})


def _auditable_visual_archetype(
    template_id: str,
    visual_archetype: str | None = None,
) -> str | None:
    """返回可计入高级图型配额的真实图型标识。

    支持的 renderer 模板本身就是可审计图型；手写/通用 LaTeX 模板则必须由
    调用方显式说明 ``visual_archetype``，否则不能用来凑“至少三种图型”。
    """
    candidate = (visual_archetype or template_id).strip()
    return candidate if candidate not in _NON_AUDITABLE_ARCHETYPE_TEMPLATES else None


def _schema() -> dict[str, Any]:
    """读取 v3 图表索引 Schema。"""
    return load_json(resolve_repo_root(Path(__file__)) / "schemas/simple_figure_index.schema.json")


def require_figure_index(payload: dict[str, Any]) -> None:
    """确保图表索引符合轻量追溯协议。

    Args:
        payload: 图表索引对象。

    Raises:
        ContractError: 图表索引不符合 Schema。
    """
    validator = Draft202012Validator(_schema(), format_checker=FormatChecker())
    errors = [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    ]
    if errors:
        raise ContractError("; ".join(errors))


def read_figure_index(run_dir: Path) -> dict[str, Any]:
    """读取并验证图表索引。

    Args:
        run_dir: v3 运行目录。

    Returns:
        已验证的图表索引。
    """
    payload = load_json(run_dir / INDEX_PATH)
    require_figure_index(payload)
    return payload


def recommended_visual_archetypes(information_structure: str) -> list[str]:
    """返回指定数学信息结构优先使用的视觉原型。

    Args:
        information_structure: spatial、temporal、set、network、field、
            tradeoff 或 uncertainty。

    Returns:
        稳定排序的优先视觉原型列表。

    Raises:
        ContractError: 信息结构不受支持。
    """
    recommended = _STRUCTURE_AWARE_ARCHETYPES.get(information_structure)
    if recommended is None:
        raise ContractError(f"未知 information_structure: {information_structure}")
    return sorted(recommended)


def _require_structure_aware_visual_grammar(payload: dict[str, Any]) -> None:
    """约束 2.3+ 正文主图从数学结构出发选择表达。"""
    if payload.get("schema_version") not in {"2.3", "2.4"}:
        return
    for raw in payload.get("figures", []):
        if not isinstance(raw, dict) or raw.get("presentation_role") not in {
            "data_portrait",
            "question_hero",
        }:
            continue
        figure_id = str(raw.get("figure_id", "<unknown>"))
        information_structure = str(raw.get("information_structure", ""))
        archetype = str(raw.get("visual_archetype", ""))
        if raw.get("generic_chart_considered") is not True:
            raise ContractError(
                f"{figure_id}.generic_chart_considered 必须为 true："
                "正文主图须显式比较普通柱形图/折线图"
            )
        recommended = _STRUCTURE_AWARE_ARCHETYPES[information_structure]
        if archetype in _GENERIC_CHART_ARCHETYPES:
            reason = raw.get("generic_chart_override_reason")
            if not isinstance(reason, str) or len(reason.strip()) < 16:
                raise ContractError(
                    f"{figure_id} 以普通柱形图/折线比较作为唯一正文主图时，"
                    "必须填写 generic_chart_override_reason 说明它为何最合适"
                )
            continue
        if archetype not in recommended:
            raise ContractError(
                f"{figure_id}.visual_archetype={archetype} 不匹配 "
                f"{information_structure} 信息结构；优先选择 "
                + "、".join(sorted(recommended))
            )


def _require_argument_obligation_contract(payload: dict[str, Any]) -> None:
    """复验图与论证单元、论证义务和面板之间的可解释映射。

    2.4 强制启用该合同；2.3 只有在作者主动填写任一新字段时才整组复验，
    从而既允许旧运行继续读取，也避免半迁移数据制造虚假的义务覆盖。

    Args:
        payload: 已通过 JSON Schema 初检的图表计划。

    Raises:
        ContractError: 新合同缺字段、面板重复或未覆盖声明的论证单元。
    """
    strict = payload.get("schema_version") == "2.4"
    for raw in payload.get("figures", []):
        if not isinstance(raw, dict):
            continue
        new_contract_present = any(
            key in raw for key in ("argument_unit_ids", "obligation_types", "panel_mapping")
        )
        if not strict and not new_contract_present:
            continue
        figure_id = str(raw.get("figure_id", "<unknown>"))
        argument_unit_ids = raw.get("argument_unit_ids")
        obligation_types = raw.get("obligation_types")
        if not isinstance(argument_unit_ids, list) or not argument_unit_ids:
            raise ContractError(f"{figure_id}.argument_unit_ids 必须是非空列表")
        if not isinstance(obligation_types, list) or not obligation_types:
            raise ContractError(f"{figure_id}.obligation_types 必须是非空列表")
        panel_mapping = raw.get("panel_mapping")
        if len(obligation_types) <= 2 and panel_mapping is None:
            continue
        if not isinstance(panel_mapping, list) or not panel_mapping:
            raise ContractError(
                f"{figure_id} 承担 3 项以上论证义务时必须填写 panel_mapping"
            )
        if len(obligation_types) > 2 and len(panel_mapping) < 2:
            raise ContractError(
                f"{figure_id} 承担 3 项以上论证义务时必须拆成至少两个可辨识面板"
            )
        panels = [str(item.get("panel", "")) for item in panel_mapping]
        if len(panels) != len(set(panels)):
            raise ContractError(f"{figure_id}.panel_mapping 的 panel 必须唯一")
        mapped_units = {
            str(item.get("argument_unit_id", ""))
            for item in panel_mapping
            if isinstance(item, dict)
        }
        declared_units = set(argument_unit_ids)
        unknown_units = mapped_units - declared_units
        missing_units = declared_units - mapped_units
        if unknown_units:
            raise ContractError(
                f"{figure_id}.panel_mapping 引用了未声明论证单元: "
                + "、".join(sorted(unknown_units))
            )
        if missing_units:
            raise ContractError(
                f"{figure_id}.panel_mapping 未覆盖论证单元: "
                + "、".join(sorted(missing_units))
            )


def _require_learned_visual_pattern_contract(
    run_dir: Path, payload: dict[str, Any]
) -> None:
    """验证视觉知识只作为当前题的受限建议进入图计划。"""
    selected: list[tuple[str, dict[str, Any]]] = []
    for figure in payload.get("figures", []):
        if not isinstance(figure, dict):
            continue
        ids = figure.get("learned_pattern_ids", [])
        if not ids:
            continue
        if not isinstance(ids, list):
            raise ContractError(
                f"{figure.get('figure_id', '<unknown>')}.learned_pattern_ids 必须为数组"
            )
        for pattern_id in ids:
            selected.append((str(pattern_id), figure))
    if not selected:
        return
    retrieval_path = run_dir / "knowledge/analysis-retrieval.json"
    if not retrieval_path.is_file():
        raise ContractError("图计划声明学习视觉模式，但缺少 knowledge/analysis-retrieval.json")
    retrieval = load_json(retrieval_path)
    visual_patterns = {
        str(pattern["pattern_id"]): pattern
        for card in retrieval.get("matched_cards", [])
        if isinstance(card, dict)
        for pattern in card.get("visual_patterns", [])
        if isinstance(pattern, dict) and isinstance(pattern.get("pattern_id"), str)
    }
    adopted = {
        str(visual_id): item
        for item in retrieval.get("accepted_patterns", [])
        if isinstance(item, dict) and item.get("application_layer") == "visual_design"
        for visual_id in item.get("visual_pattern_ids", [item.get("pattern_id")])
        if visual_id
    }
    from shumozizi.knowledge.usage import build_visual_pattern_suggestions

    suggestion_report = build_visual_pattern_suggestions(run_dir)
    eligible = {
        (str(item.get("question_id")), str(item.get("learned_pattern_id"))): item
        for item in suggestion_report.get("recommendations", [])
        if isinstance(item, dict)
    }
    rejected = {
        (str(item.get("question_id")), str(item.get("learned_pattern_id"))): item
        for item in suggestion_report.get("rejections", [])
        if isinstance(item, dict)
    }
    for pattern_id, figure in selected:
        figure_id = figure.get("figure_id", "<unknown>")
        question_id = str(figure.get("question_id", ""))
        if pattern_id not in visual_patterns:
            raise ContractError(f"图 {figure_id} 引用了不存在的学习视觉模式 {pattern_id}")
        if pattern_id not in adopted:
            raise ContractError(f"图 {figure_id} 使用的视觉模式 {pattern_id} 未在分析阶段采用")
        adoption = adopted[pattern_id]
        if figure_id not in set(map(str, adoption.get("figure_ids", []))):
            raise ContractError(
                f"图 {figure_id} 未出现在视觉知识模式 {adoption.get('pattern_id')} 的 figure_ids"
            )
        pattern = visual_patterns[pattern_id]
        archetype = figure.get("visual_archetype")
        if archetype and pattern.get("visual_archetype") not in {archetype, "custom"}:
            raise ContractError(
                f"图 {figure_id} 的 renderer 原型 {archetype} 与学习模式 {pattern_id} 不一致"
            )
        obligations = {str(value) for value in figure.get("obligation_types", [])}
        roles = {str(value) for value in pattern.get("argument_roles", [])}
        if obligations and roles and not obligations.intersection(roles):
            raise ContractError(f"图 {figure_id} 的论证义务与学习模式 {pattern_id} 没有交集")
        adaptation = figure.get("learned_pattern_adaptation")
        if not isinstance(adaptation, str) or len(adaptation.strip()) < 16:
            raise ContractError(f"图 {figure_id} 必须说明学习视觉模式的当前题改造方式")
        suggestion_key = (question_id, pattern_id)
        if suggestion_key not in eligible:
            rejection = rejected.get(suggestion_key, {})
            missing = rejection.get("missing_data_fields", [])
            detail = (
                "，缺少当前题结构数据: " + "、".join(map(str, missing))
                if missing
                else "，当前题视觉义务与该模式不匹配"
            )
            raise ContractError(f"图 {figure_id} 不能采用学习视觉模式 {pattern_id}{detail}")
        suggestion = eligible[suggestion_key]
        declared_arguments = set(map(str, figure.get("argument_unit_ids", [])))
        supporting_arguments = set(map(str, suggestion.get("argument_unit_ids", [])))
        if declared_arguments and not declared_arguments.intersection(supporting_arguments):
            raise ContractError(
                f"图 {figure_id} 的 argument_unit_ids 未绑定视觉模式所需的当前题结构输出"
            )


def write_figure_plan(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """受控保存 v3.2 正文图表计划与逐问视觉决策。

    Args:
        run_dir: 当前运行目录。
        payload: ``FIGURE_PLAN`` 2.1/2.2/2.3/2.4 文档。

    Returns:
        已原子写入的图表计划。

    Raises:
        ContractError: Schema 不合法，或首版截止后扩张图表集合。
    """
    require_valid(payload, "figure_plan")
    if payload.get("run_id") != run_dir.name:
        raise ContractError("FIGURE_PLAN 的 run_id 与当前运行不一致")
    _require_structure_aware_visual_grammar(payload)
    _require_argument_obligation_contract(payload)
    _require_learned_visual_pattern_contract(run_dir, payload)
    path = run_dir / FIGURE_PLAN_PATH
    old_ids: set[str] = set()
    if path.is_file():
        existing = load_json(path)
        old_ids = {
            item.get("figure_id")
            for item in existing.get("figures", [])
            if isinstance(item, dict) and isinstance(item.get("figure_id"), str)
        }
    new_ids = {
        item.get("figure_id")
        for item in payload.get("figures", [])
        if isinstance(item, dict) and isinstance(item.get("figure_id"), str)
    }
    added_ids = new_ids - old_ids
    if added_ids:
        from shumozizi.simple.delivery import require_delivery_action_allowed

        findings = [
            item.get("revision_case", str(item.get("review_finding", "")))
            for item in payload.get("figures", [])
            if isinstance(item, dict) and item.get("figure_id") in added_ids
        ]
        require_delivery_action_allowed(
            run_dir, "expand_figure_plan", review_findings=findings
        )
    atomic_json(path, payload)
    return payload


def audit_figure_information_value(payload: dict[str, Any]) -> dict[str, Any]:
    """按视觉原型审核正文图的信息承载机会，不替代实际看图。

    Args:
        payload: 已声明视觉原型的 ``FIGURE_PLAN`` 2.2/2.3 文档。

    Returns:
        每张图的五维分数、低价值修订建议和人工复核边界。建议阈值为 6 分，
        因而本报告始终是 advisory，不会自行改变工作流状态。

    Raises:
        ContractError: 图表计划不符合 Schema。
    """
    require_valid(payload, "figure_plan")
    records: list[dict[str, Any]] = []
    needs_revision: list[dict[str, str]] = []
    for figure in payload.get("figures", []):
        archetype = figure.get("visual_archetype")
        information_structure = figure.get("information_structure")
        profile = _VISUAL_VALUE_PROFILES.get(archetype)
        if profile is None:
            record = {
                "figure_id": figure.get("figure_id"),
                "visual_archetype": archetype,
                "information_structure": information_structure,
                "total_score": None,
                "scores": None,
                "requires_visual_review": True,
                "message": "custom 或旧版图必须由评阅者逐项检查五类信息价值。",
            }
        else:
            scores = dict(zip(_VISUAL_VALUE_DIMENSIONS, profile, strict=True))
            total = sum(profile)
            record = {
                "figure_id": figure.get("figure_id"),
                "visual_archetype": archetype,
                "information_structure": information_structure,
                "total_score": total,
                "scores": scores,
                "requires_visual_review": True,
                "message": "原型分只表示设计机会，仍需检查实际图是否兑现这些信息。",
            }
            if figure.get("required") is True and total < 6:
                needs_revision.append(
                    {
                        "figure_id": str(figure.get("figure_id")),
                        "message": (
                            "正文主图的信息价值低于建议阈值 6；检查是否只比较方法得分、"
                            "重复表格，或遗漏模型对象、约束边界与决策机制。"
                        ),
                    }
                )
            if (
                figure.get("presentation_role") == "question_hero"
                and archetype in _GENERIC_CHART_ARCHETYPES
            ):
                needs_revision.append(
                    {
                        "figure_id": str(figure.get("figure_id")),
                        "message": (
                            "正文 hero 使用通用柱形/折线比较；即使已登记 override 理由，"
                            "仍须人工确认数据确无空间、集合、边界、机制或不确定性结构。"
                        ),
                    }
                )
        records.append(record)
    return {
        "schema_version": payload.get("schema_version"),
        "advisory_only": True,
        "recommended_minimum": 6,
        "figures": records,
        "needs_revision": needs_revision,
        "limitations": (
            "information_structure、mechanism_annotation 和 rendering 声明不能证明 "
            "PNG/PDF 中确有可行域、活跃约束、最优点或不确定性，最终仍需打开图件复核。"
        ),
    }


def _file_record(run_dir: Path, relative: str) -> dict[str, str]:
    """生成一个已存在运行内文件的路径和哈希记录。"""
    path = resolve_inside(run_dir, relative, must_exist=True)
    return {"path": relative_inside(run_dir, path).as_posix(), "sha256": sha256_file(path)}


def _competition_first_run(run_dir: Path) -> bool:
    """判断当前运行是否使用 v3.1 简化图表协议。"""
    return is_competition_first_state(read_simple_state(run_dir))


def _promotion_record(
    run_dir: Path,
    *,
    figure_id: str,
    output_records: list[dict[str, str]],
    promotion_receipt: str,
    role: str | None,
    presentation_role: str | None = None,
) -> dict[str, str]:
    """复验候选图已通过机械 QA、角色内容检查并返回回执记录。"""
    receipt_record = _file_record(run_dir, promotion_receipt)
    receipt = load_json(resolve_inside(run_dir, receipt_record["path"], must_exist=True))
    promoted_hashes = {
        item.get("path"): item.get("sha256")
        for item in receipt.get("promoted_outputs", [])
        if isinstance(item, dict)
    }
    receipt_figure_role = receipt.get("figure_role")
    receipt_presentation_role = receipt.get("presentation_role")
    receipt_version = receipt.get("schema_version")
    human_review = receipt.get("human_review") or {}
    validated = validate_human_figure_review(
        human_review,
        figure_role=receipt_figure_role,
        presentation_role=receipt_presentation_role,
        require_element_binding=receipt_version == "1.2",
    )
    # 机械复核只能产生 mechanically_qualified，人工视觉门保持 pending；
    # 不能在回执校验层把机械复核当作人工验收。
    if validated.get("qualification") == "mechanically_qualified":
        if human_review.get("reviewed") is True:
            raise ContractError("机械复核 receipt 不得设置 reviewed=true")
    elif human_review.get("reviewed") is not True:
        raise ContractError("人工视觉门未通过：reviewed 必须为 true")
    manifest_valid = True
    if receipt_version == "1.2":
        manifest = receipt.get("visual_manifest")
        manifest_valid = (
            isinstance(manifest, dict)
            and isinstance(manifest.get("path"), str)
            and isinstance(manifest.get("sha256"), str)
            and isinstance(manifest.get("output_sha256"), str)
            and sha256_file(
                resolve_inside(run_dir, manifest.get("path"), must_exist=True)
            )
            == manifest.get("sha256")
            and any(
                item.get("sha256") == manifest.get("output_sha256")
                and str(item.get("path", "")).casefold().endswith(".png")
                for item in receipt.get("qa", {}).get("candidate_outputs", [])
                if isinstance(item, dict)
            )
        )
    if (
        receipt_version not in {"1.1", "1.2"}
        or receipt.get("figure_id") != figure_id
        or receipt_figure_role != role
        or receipt_presentation_role != presentation_role
        or receipt.get("qa", {}).get("success") is not True
        or human_review.get("verdict") != "promote"
        or human_review.get("issues") != []
        or not manifest_valid
        or any(promoted_hashes.get(item["path"]) != item["sha256"] for item in output_records)
    ):
        raise ContractError("图表晋级回执未绑定当前角色、输出、机械 QA 或内容化人工复核")
    return receipt_record


def _paper_visual_requirement_binding(
    run_dir: Path,
    *,
    opportunity: dict[str, Any] | None,
    promotion_receipt: str | None,
) -> dict[str, Any]:
    """从晋级回执复制论文视觉需求的精确覆盖绑定。"""
    if opportunity is None or opportunity.get("origin") != "paper_visual_requirement":
        return {}
    requirement_id = opportunity.get("requirement_id")
    requirement_digest = opportunity.get("requirement_digest")
    if not isinstance(requirement_id, str) or not isinstance(requirement_digest, str):
        raise ContractError("论文视觉机会缺少 requirement_id 或 requirement_digest")
    if not isinstance(promotion_receipt, str):
        raise ContractError("论文视觉需求图必须绑定正式晋级回执")
    receipt = load_json(resolve_inside(run_dir, promotion_receipt, must_exist=True))
    gate = receipt.get("visual_critic")
    focal_claim = receipt.get("human_review", {}).get("focal_claim")
    if (
        not isinstance(gate, dict)
        or gate.get("requirement_id") != requirement_id
        or gate.get("requirement_digest") != requirement_digest
        or not isinstance(focal_claim, str)
        or not focal_claim.strip()
        or gate.get("focal_claim") != focal_claim
    ):
        raise ContractError("图晋级回执未绑定当前论文视觉需求摘要和人工 focal_claim")
    return {
        "covered_requirement_ids": [requirement_id],
        "covered_requirement_digests": [requirement_digest],
        "focal_claim": focal_claim.strip(),
    }


def _register_competition_figure(
    run_dir: Path,
    *,
    figure_id: str,
    template_id: str,
    result_id: str,
    input_result: str,
    reference_template: str,
    renderer_script: str,
    outputs: list[str],
    text_boxes: str,
    figure_stage: str,
    scientific_question: str | None,
    expected_takeaway: str | None,
    cannot_prove: str | None,
    role: str | None = None,
    placement: str | None = None,
    promotion_receipt: str | None = None,
    visual_opportunity_id: str | None = None,
    selected_version: str | None = None,
    paper_location: str | None = None,
    critic_verdict: str | None = None,
    visual_archetype: str | None = None,
) -> dict[str, Any]:
    """登记由问题和 takeaway 驱动的 v3.1 图表。"""
    if figure_stage not in {"current", "evidence", "publication"}:
        raise ContractError("v3.1 figure_stage 必须为 current、evidence 或 publication")
    if role is None and is_competition_first_v32_state(read_simple_state(run_dir)):
        # role 可选时，把稳定性图放进正文只需不声明 role，附录约束等于可规避。
        raise ContractError(
            "v3.2 图表必须声明 role（model_understanding / decisive_evidence / "
            "insight / stability）：不声明角色时附录约束形同虚设"
        )
    if role is not None and role not in FIGURE_ROLES:
        raise ContractError("figure role 必须是 " + ", ".join(sorted(FIGURE_ROLES)))
    if placement is not None and placement not in FIGURE_PLACEMENTS:
        raise ContractError("figure placement 必须为 body 或 appendix")
    if critic_verdict is not None and critic_verdict not in {"PROMOTE", "REVISE", "SPLIT", "DROP"}:
        raise ContractError("critic_verdict 必须为 PROMOTE、REVISE、SPLIT 或 DROP")
    opportunity: dict[str, Any] | None = None
    if visual_opportunity_id is not None:
        opportunity_path = run_dir / "figures/visual-opportunities.json"
        if not opportunity_path.is_file():
            raise ContractError("图绑定 visual_opportunity_id 时必须存在视觉机会池")
        opportunity_payload = load_json(opportunity_path)
        opportunity = next(
            (
                item
                for item in opportunity_payload.get("opportunities", [])
                if isinstance(item, dict)
                and item.get("opportunity_id") == visual_opportunity_id
            ),
            None,
        )
        if opportunity is None:
            raise ContractError(f"图绑定了不存在的视觉机会: {visual_opportunity_id}")
        if critic_verdict != "PROMOTE" or opportunity.get("status") != "promote":
            raise ContractError("进入 figures/current 的机会必须有 PROMOTE 批评结论")
    if role in _APPENDIX_ONLY_ROLES:
        if placement == "body":
            raise ContractError(
                "稳定性、舍入与采样层级图默认进入附录，不得抢占正文版面；"
                "正文位置应留给机制、阈值与权衡"
            )
        placement = "appendix"
    index = read_figure_index(run_dir)
    source_result = next(
        (item for item in read_result_index(run_dir)["results"] if item["result_id"] == result_id), None
    )
    if source_result is None or source_result.get("status") != "current" or not source_result.get("execution_valid"):
        raise ContractError("图表只能绑定 current 且 execution_valid=true 的真实结果")
    input_record = _file_record(run_dir, input_result)
    if input_record["path"] not in source_result["output_hashes"]:
        raise ContractError("图表输入必须是所绑定结果的已登记输出")
    if input_record["sha256"] != source_result["output_hashes"][input_record["path"]]:
        raise ContractError("图表输入哈希与所绑定结果不一致")
    output_records = [_file_record(run_dir, item) for item in outputs]
    suffixes = {Path(item["path"]).suffix.lower() for item in output_records}
    if not output_records or not suffixes <= {".png", ".pdf", ".svg"} or not suffixes & {".png", ".pdf"}:
        raise ContractError("v3.1 图表至少需要可读 PNG 或 PDF 输出")
    expected_prefix = "figures/current/"
    if any(not item["path"].startswith(expected_prefix) for item in output_records):
        raise ContractError("v3.1 图输出必须位于 figures/current/")
    entry = {
        "figure_id": figure_id,
        "template_id": template_id,
        "result_id": result_id,
        "input_result": input_record,
        "renderer_script": _file_record(run_dir, renderer_script),
        "outputs": output_records,
        "status": "current",
        "question_id": source_result["question_id"],
        "figure_stage": "current",
        "source": [input_record["path"]],
        "question": scientific_question or f"{source_result['question_id']} 的当前结果回答什么问题？",
        "takeaway": expected_takeaway or "该图呈现当前结果中可直接核对的结构差异。",
        "limitations": cannot_prove or "图表不能单独证明模型正确性或因果关系。",
        "source_result_ids": [result_id],
        "source_result_sha256s": {result_id: sha256_bytes(json_bytes(source_result))},
        "objective_semantics_sha256": source_result["objective_semantics_sha256"],
        "paper_allowed": True,
        "demo": False,
        "created_at": utc_now(),
    }
    if archetype := _auditable_visual_archetype(template_id, visual_archetype):
        entry["visual_archetype"] = archetype
    if visual_opportunity_id is not None:
        from shumozizi.paper.policy import policy_fingerprint

        entry["visual_opportunity_id"] = visual_opportunity_id
        entry["critic_verdict"] = critic_verdict
        entry["visual_policy_fingerprint"] = policy_fingerprint(
            resolve_repo_root(Path(__file__)), "visual"
        )
        if selected_version is not None:
            entry["selected_version"] = selected_version
        if paper_location is not None:
            entry["paper_location"] = paper_location
    if role is not None:
        entry["role"] = role
    if placement is not None:
        entry["placement"] = placement
    if is_competition_first_v32_state(read_simple_state(run_dir)) and promotion_receipt is None:
        raise ContractError(
            "v3.2 图表必须先通过候选版式 QA 与人工看图，再绑定 promotion_receipt 登记"
        )
    if promotion_receipt is not None:
        entry["promotion_receipt"] = _promotion_record(
            run_dir,
            figure_id=figure_id,
            output_records=output_records,
            promotion_receipt=promotion_receipt,
            role=role,
        )
    entry.update(
        _paper_visual_requirement_binding(
            run_dir,
            opportunity=opportunity,
            promotion_receipt=promotion_receipt,
        )
    )
    for existing in index["figures"]:
        if existing["figure_id"] == figure_id and existing["status"] == "current":
            existing["status"] = "superseded"
    index["figures"].append(entry)
    require_figure_index(index)
    atomic_json(run_dir / INDEX_PATH, index)
    return entry


def register_insight_figure(
    run_dir: Path,
    *,
    figure_id: str,
    result_id: str,
    input_result: str,
    renderer_script: str,
    outputs: list[str],
    question: str,
    takeaway: str,
    limitations: str | None = None,
    template_id: str = "custom",
    role: str | None = None,
    placement: str | None = None,
    promotion_receipt: str | None = None,
    visual_opportunity_id: str | None = None,
    selected_version: str | None = None,
    paper_location: str | None = None,
    critic_verdict: str | None = None,
    visual_archetype: str | None = None,
) -> dict[str, Any]:
    """登记仅包含来源、问题和 takeaway 的 v3.1 图表。

    Args:
        run_dir: 当前运行目录。
        figure_id: 图表标识。
        result_id: 真实来源结果。
        input_result: 图表读取的结果文件。
        renderer_script: 实际执行的绘图脚本。
        outputs: 已生成的 PNG/PDF/SVG 输出。
        question: 图表回答的问题。
        takeaway: 读者应一眼看到的结论。
        limitations: 可选的论证边界。
        template_id: 绘图实现类型，仅用于追溯。
        role: 图的角色（model_understanding / decisive_evidence / insight /
            stability）；stability 会被强制归入附录。
        placement: 计划版面位置（body 或 appendix）。
        promotion_receipt: 候选图通过版式 QA 与人工看图后的晋级回执。
        visual_opportunity_id: v3.4 视觉机会池中的机会 ID。
        selected_version: 进入 current 的候选版本。
        paper_location: 正文或附录中的实际消费位置。
        critic_verdict: 新鲜视觉批评结论，进入 current 时必须为 PROMOTE。
        visual_archetype: 可计入高级图配额的图型；通用模板必须显式提供。

    Returns:
        当前图表索引条目。
    """
    if not _competition_first_run(run_dir):
        raise ContractError("register_insight_figure 仅适用于 Competition-First v3.1")
    return _register_competition_figure(
        run_dir,
        figure_id=figure_id,
        template_id=template_id,
        result_id=result_id,
        input_result=input_result,
        reference_template=renderer_script,
        renderer_script=renderer_script,
        outputs=outputs,
        text_boxes=renderer_script,
        figure_stage="current",
        scientific_question=question,
        expected_takeaway=takeaway,
        cannot_prove=limitations,
        role=role,
        placement=placement,
        promotion_receipt=promotion_receipt,
        visual_opportunity_id=visual_opportunity_id,
        selected_version=selected_version,
        paper_location=paper_location,
        critic_verdict=critic_verdict,
        visual_archetype=visual_archetype,
    )


def register_presentation_figure(
    run_dir: Path,
    *,
    figure_id: str,
    source_files: list[str],
    renderer_script: str,
    outputs: list[str],
    question_id: str,
    question: str,
    takeaway: str,
    limitations: str,
    presentation_role: str,
    role: str,
    promotion_receipt: str,
    template_id: str = "custom",
    visual_opportunity_id: str | None = None,
    selected_version: str | None = None,
    paper_location: str | None = None,
    critic_verdict: str | None = None,
    visual_archetype: str | None = None,
) -> dict[str, Any]:
    """登记不创造实验结果的竞赛呈现图。

    该入口只允许读取当前运行中已冻结的题面、分析产物或真实结果文件，适合数据画像
    和解释型主图。它保留输入、脚本、输出与人工晋级追溯，但不会把呈现需要伪装成
    新的生产结果。

    Args:
        run_dir: 当前 Competition-First v3.2 运行目录。
        figure_id: 图表标识。
        source_files: 运行内冻结输入文件。
        renderer_script: 实际执行的绘图脚本。
        outputs: 已晋级到 ``figures/current`` 的 PNG/PDF 输出。
        question_id: 对应问题；全文数据画像可使用 ``whole_paper``。
        question: 图回答的读者问题。
        takeaway: 读者应一眼看到的结论。
        limitations: 图不能证明的边界。
        presentation_role: data_portrait、question_hero、supporting 或 appendix。
        role: 既有科学叙事角色。
        promotion_receipt: 候选图机械 QA 与人工看图回执。
        template_id: 绘图实现类型。
        visual_opportunity_id: v3.4 视觉机会池中的机会 ID。
        selected_version: 进入 current 的候选版本。
        paper_location: 正文或附录中的实际消费位置。
        critic_verdict: 新鲜视觉批评结论，进入 current 时必须为 PROMOTE。
        visual_archetype: 可计入高级图配额的图型；通用模板必须显式提供。

    Returns:
        已写入 ``figures/index.json`` 的当前图条目。

    Raises:
        ContractError: 输入越界、输出未晋级或运行版本不支持。
    """
    state = read_simple_state(run_dir)
    if not is_competition_first_v32_state(state):
        raise ContractError("纯呈现图登记只适用于 Competition-First v3.2")
    if presentation_role not in PRESENTATION_ROLES:
        raise ContractError("presentation_role 必须是 " + ", ".join(sorted(PRESENTATION_ROLES)))
    if role not in FIGURE_ROLES:
        raise ContractError("figure role 必须是 " + ", ".join(sorted(FIGURE_ROLES)))
    if presentation_role == "appendix" or role == "stability":
        placement = "appendix"
    else:
        placement = "body"
    if role == "stability" and presentation_role != "appendix":
        raise ContractError("stability 图的 presentation_role 必须为 appendix")
    if not source_files:
        raise ContractError("纯呈现图至少需要一个冻结输入文件")
    source_records = [_file_record(run_dir, item) for item in source_files]
    invalid_sources = [
        item["path"]
        for item in source_records
        if not item["path"].startswith(_PRESENTATION_SOURCE_PREFIXES)
    ]
    if invalid_sources:
        raise ContractError(
            "纯呈现图只能读取 problem/、analysis/ 或 results/raw/："
            + ", ".join(invalid_sources)
        )
    output_records = [_file_record(run_dir, item) for item in outputs]
    suffixes = {Path(item["path"]).suffix.lower() for item in output_records}
    if (
        not output_records
        or not suffixes <= {".png", ".pdf", ".svg"}
        or not suffixes & {".png", ".pdf"}
        or any(not item["path"].startswith("figures/current/") for item in output_records)
    ):
        raise ContractError("纯呈现图必须提供 figures/current/ 下的可读 PNG 或 PDF")
    receipt_record = _promotion_record(
        run_dir,
        figure_id=figure_id,
        output_records=output_records,
        promotion_receipt=promotion_receipt,
        role=role,
        presentation_role=presentation_role,
    )
    entry = {
        "figure_id": figure_id,
        "template_id": template_id,
        "provenance_type": "frozen_inputs",
        "source_files": source_records,
        "renderer_script": _file_record(run_dir, renderer_script),
        "outputs": output_records,
        "status": "current",
        "question_id": question_id,
        "figure_stage": "current",
        "source": [item["path"] for item in source_records],
        "question": question,
        "takeaway": takeaway,
        "limitations": limitations,
        "role": role,
        "placement": placement,
        "presentation_role": presentation_role,
        "promotion_receipt": receipt_record,
        "paper_allowed": True,
        "demo": False,
        "created_at": utc_now(),
    }
    if archetype := _auditable_visual_archetype(template_id, visual_archetype):
        entry["visual_archetype"] = archetype
    opportunity: dict[str, Any] | None = None
    if visual_opportunity_id is not None:
        from shumozizi.paper.policy import policy_fingerprint
        from shumozizi.simple.visual_opportunities import (
            validate_visual_critic_record,
            visual_opportunity_pool_freshness,
        )

        if critic_verdict != "PROMOTE":
            raise ContractError("进入 figures/current 的机会必须有 PROMOTE 批评结论")
        opportunity_path = run_dir / "figures/visual-opportunities.json"
        opportunity_payload = load_json(opportunity_path) if opportunity_path.is_file() else {}
        opportunity = next(
            (
                item
                for item in opportunity_payload.get("opportunities", [])
                if isinstance(item, dict)
                and item.get("opportunity_id") == visual_opportunity_id
            ),
            None,
        )
        if opportunity is None or opportunity.get("status") != "promote":
            raise ContractError("进入 figures/current 的机会必须已在机会池中 PROMOTE")
        freshness = visual_opportunity_pool_freshness(run_dir)
        if not freshness["current"]:
            raise ContractError("视觉机会池已失效: " + "、".join(freshness["stale_fields"]))
        critic_version = selected_version
        promotion_payload: dict[str, Any] | None = None
        if promotion_receipt is not None:
            promotion_path = resolve_inside(run_dir, promotion_receipt, must_exist=True)
            promotion_payload = load_json(promotion_path)
            critic_version = critic_version or promotion_payload.get("candidate_version")
            critic_gate = promotion_payload.get("visual_critic", {})
            if not isinstance(critic_gate, dict) or critic_gate.get("mode") != "v34_visual_critic":
                raise ContractError("图晋级回执没有记录 v3.4 视觉批评硬门")
        if not isinstance(critic_version, str) or not critic_version.strip():
            raise ContractError("登记视觉机会图时必须提供 selected_version 或含候选版本的 promotion_receipt")
        critic = validate_visual_critic_record(
            run_dir,
            visual_opportunity_id,
            critic_version,
            require_artifact_binding=True,
        )
        if critic.get("verdict") != "PROMOTE":
            raise ContractError("进入 figures/current 的机会必须绑定 PROMOTE 视觉批评")
        entry["visual_opportunity_id"] = visual_opportunity_id
        entry["critic_verdict"] = critic_verdict
        entry["visual_policy_fingerprint"] = policy_fingerprint(
            resolve_repo_root(Path(__file__)), "visual"
        )
        if selected_version is not None:
            entry["selected_version"] = selected_version
        if paper_location is not None:
            entry["paper_location"] = paper_location
    entry.update(
        _paper_visual_requirement_binding(
            run_dir,
            opportunity=opportunity,
            promotion_receipt=promotion_receipt,
        )
    )
    # 人工视觉门：机械复核（receipt qualification=mechanically_qualified）只能
    # 工程晋级；index 必须显式标记 human_vision_gate=pending，不得视为人工验收。
    if promotion_receipt is not None:
        try:
            promotion_payload = load_json(
                resolve_inside(run_dir, promotion_receipt, must_exist=True)
            )
        except ContractError:
            promotion_payload = {}
        human = promotion_payload.get("human_review") or {}
        if human.get("qualification") == "mechanically_qualified":
            entry["human_vision_gate"] = "pending"
            entry["human_vision_performed"] = False
        else:
            entry["human_vision_gate"] = "passed"
            entry["human_vision_performed"] = True
    index = read_figure_index(run_dir)
    index["schema_version"] = "1.3"
    for existing in index["figures"]:
        if existing["figure_id"] == figure_id and existing["status"] == "current":
            existing["status"] = "superseded"
    index["figures"].append(entry)
    require_figure_index(index)
    atomic_json(run_dir / INDEX_PATH, index)
    return entry


def _verify_competition_figures(run_dir: Path) -> dict[str, Any]:
    """复验 v3.1 当前图的来源、哈希和基本可读性。"""
    index = read_figure_index(run_dir)
    results = {item["result_id"]: item for item in read_result_index(run_dir)["results"]}
    errors: list[dict[str, str]] = []
    checked: list[str] = []
    for figure in index["figures"]:
        if figure.get("status") != "current":
            continue
        figure_id = str(figure.get("figure_id", "<unknown>"))
        checked.append(figure_id)
        if figure.get("demo") or not figure.get("paper_allowed"):
            errors.append({"figure_id": figure_id, "message": "演示图或未允许图不能进入论文"})
        opportunity_id = figure.get("visual_opportunity_id")
        if opportunity_id is not None:
            from shumozizi.paper.policy import policy_fingerprint
            from shumozizi.simple.visual_opportunities import validate_visual_critic_record

            if figure.get("critic_verdict") != "PROMOTE":
                errors.append({"figure_id": figure_id, "message": "视觉机会没有 PROMOTE 批评结论"})
            expected_policy = policy_fingerprint(resolve_repo_root(Path(__file__)), "visual")
            if figure.get("visual_policy_fingerprint") != expected_policy:
                errors.append({"figure_id": figure_id, "message": "图表未绑定当前视觉政策"})
            opportunity_path = run_dir / "figures/visual-opportunities.json"
            try:
                opportunity_payload = load_json(opportunity_path)
                opportunity = next(
                    (
                        item
                        for item in opportunity_payload.get("opportunities", [])
                        if isinstance(item, dict)
                        and item.get("opportunity_id") == opportunity_id
                    ),
                    None,
                )
                if opportunity is None or opportunity.get("status") != "promote":
                    errors.append({"figure_id": figure_id, "message": "视觉机会已失效或未 PROMOTE"})
                critic_version = figure.get("selected_version")
                if not isinstance(critic_version, str) or not critic_version.strip():
                    promotion = figure.get("promotion_receipt", {})
                    if isinstance(promotion, dict):
                        critic_version = promotion.get("candidate_version")
                if not isinstance(critic_version, str) or not critic_version.strip():
                    errors.append({"figure_id": figure_id, "message": "当前图缺少视觉批评候选版本"})
                else:
                    validate_visual_critic_record(
                        run_dir,
                        str(opportunity_id),
                        critic_version,
                        require_artifact_binding=True,
                    )
            except (ContractError, OSError, ValueError, TypeError):
                errors.append({"figure_id": figure_id, "message": "视觉机会或视觉批评绑定缺失、失效或无法读取"})
        if figure.get("provenance_type") == "frozen_inputs":
            source_records = [
                *figure.get("source_files", []),
                figure.get("renderer_script", {}),
                figure.get("promotion_receipt", {}),
            ]
            for record in source_records:
                issue = _verify_recorded_file(run_dir, record, "呈现图来源")
                if issue:
                    errors.append({"figure_id": figure_id, "message": issue})
            for output in figure.get("outputs", []):
                issue = _verify_recorded_file(run_dir, output, "图表输出")
                if issue:
                    errors.append({"figure_id": figure_id, "message": issue})
                    continue
                path = resolve_inside(run_dir, output["path"], must_exist=True)
                if path.stat().st_size == 0:
                    errors.append({"figure_id": figure_id, "message": "图表输出为空"})
                elif path.suffix.lower() == ".png":
                    try:
                        from PIL import Image

                        with Image.open(path) as image:
                            image.verify()
                    except (OSError, ValueError) as exc:
                        errors.append(
                            {"figure_id": figure_id, "message": f"PNG 不可读: {exc}"}
                        )
                elif path.suffix.lower() == ".pdf" and not path.read_bytes().startswith(b"%PDF"):
                    errors.append(
                        {"figure_id": figure_id, "message": "PDF 图表不是有效 PDF 文件头"}
                    )
            continue
        result = results.get(figure.get("result_id"))
        if result is None or result.get("status") != "current" or not result.get("execution_valid"):
            errors.append({"figure_id": figure_id, "message": "源结果已被替代或不再有效"})
            continue
        expected = sha256_bytes(json_bytes(result))
        if figure.get("source_result_sha256s", {}).get(result["result_id"]) != expected:
            errors.append({"figure_id": figure_id, "message": "源结果变化后图表需要重新生成"})
        input_record = figure.get("input_result", {})
        if input_record.get("path") not in result.get("output_hashes", {}):
            errors.append({"figure_id": figure_id, "message": "图表输入不属于源结果输出"})
        elif input_record.get("sha256") != result["output_hashes"][input_record["path"]]:
            errors.append({"figure_id": figure_id, "message": "图表输入哈希已漂移"})
        source_records = [input_record, figure.get("renderer_script", {})]
        if isinstance(figure.get("promotion_receipt"), dict):
            source_records.append(figure["promotion_receipt"])
        for record in source_records:
            issue = _verify_recorded_file(run_dir, record, "图表来源")
            if issue:
                errors.append({"figure_id": figure_id, "message": issue})
        for output in figure.get("outputs", []):
            issue = _verify_recorded_file(run_dir, output, "图表输出")
            if issue:
                errors.append({"figure_id": figure_id, "message": issue})
                continue
            path = resolve_inside(run_dir, output["path"], must_exist=True)
            if path.stat().st_size == 0:
                errors.append({"figure_id": figure_id, "message": "图表输出为空"})
            elif path.suffix.lower() == ".png":
                try:
                    from PIL import Image

                    with Image.open(path) as image:
                        image.verify()
                except (OSError, ValueError) as exc:
                    errors.append({"figure_id": figure_id, "message": f"PNG 不可读: {exc}"})
            elif path.suffix.lower() == ".pdf" and not path.read_bytes().startswith(b"%PDF"):
                errors.append({"figure_id": figure_id, "message": "PDF 图表不是有效 PDF 文件头"})
    return {"success": not errors, "checked_figure_ids": checked, "errors": errors}


def register_figure(
    run_dir: Path,
    *,
    figure_id: str,
    template_id: str,
    result_id: str,
    input_result: str,
    reference_template: str,
    renderer_script: str,
    outputs: list[str],
    text_boxes: str,
    figure_stage: str = "publication",
    claim_ids: list[str] | None = None,
    scientific_question: str | None = None,
    expected_takeaway: str | None = None,
    cannot_prove: str | None = None,
    promotion_receipt: str | None = None,
    visual_archetype: str | None = None,
) -> dict[str, Any]:
    """登记一次真实图表生成并替代同 ID 的旧 current 图。

    Args:
        run_dir: v3 运行目录。
        figure_id: 用户可识别的图表 ID。
        template_id: 已接入的模板 ID。
        result_id: 数据来源结果 ID。
        input_result: 本次读取的 JSON 输出。
        reference_template: 复制到运行目录的保留模板源文件。
        renderer_script: 本仓 v3 渲染器副本。
        outputs: PNG、PDF、SVG 三种输出。
        text_boxes: 绘图 artist 文字边界输出。
        visual_archetype: 可计入高级图配额的图型；未指定时使用非通用模板 ID。

    Returns:
        新图表索引条目。

    Raises:
        ContractError: 任一文件、结果或 ID 不满足协议。
    """
    if _competition_first_run(run_dir):
        return _register_competition_figure(
            run_dir,
            figure_id=figure_id,
            template_id=template_id,
            result_id=result_id,
            input_result=input_result,
            reference_template=reference_template,
            renderer_script=renderer_script,
            outputs=outputs,
            text_boxes=text_boxes,
            figure_stage=figure_stage,
            scientific_question=scientific_question,
            expected_takeaway=expected_takeaway,
            cannot_prove=cannot_prove,
            promotion_receipt=promotion_receipt,
            visual_archetype=visual_archetype,
        )
    if not figure_id.replace("-", "").replace("_", "").replace(".", "").isalnum():
        raise ContractError(f"figure_id 不合法: {figure_id}")
    index = read_figure_index(run_dir)
    results = read_result_index(run_dir)
    source_result = next((item for item in results["results"] if item["result_id"] == result_id), None)
    if figure_stage not in {"evidence", "publication"}:
        raise ContractError("figure_stage 必须为 evidence 或 publication")
    if source_result is None or source_result["status"] != "current" or not source_result["execution_valid"]:
        raise ContractError("图表只能绑定 current 且 execution_valid=true 的真实结果")
    if figure_stage == "publication" and not quality_allows_paper(run_dir, result_id):
        raise ContractError("publication 图只能绑定已通过科学审核和质量层的结果")
    input_record = _file_record(run_dir, input_result)
    if input_record["path"] not in source_result["output_hashes"]:
        raise ContractError("图表输入必须是所绑定结果的已登记输出")
    if input_record["sha256"] != source_result["output_hashes"][input_record["path"]]:
        raise ContractError("图表输入哈希与所绑定结果不一致")
    output_records = [_file_record(run_dir, item) for item in outputs]
    expected_prefix = f"figures/{figure_stage}/"
    if any(not item["path"].startswith(expected_prefix) for item in output_records):
        raise ContractError(f"{figure_stage} 图输出必须位于 {expected_prefix}")
    suffixes = {Path(item["path"]).suffix.lower() for item in output_records}
    if suffixes != {".png", ".pdf", ".svg"} or any(
        resolve_inside(run_dir, item["path"], must_exist=True).stat().st_size == 0
        for item in output_records
    ):
        raise ContractError("图表必须生成非空 PNG、PDF、SVG 三种输出")
    entry = {
        "figure_id": figure_id,
        "template_id": template_id,
        "result_id": result_id,
        "input_result": input_record,
        "reference_template": _file_record(run_dir, reference_template),
        "renderer_script": _file_record(run_dir, renderer_script),
        "outputs": output_records,
        "text_boxes": _file_record(run_dir, text_boxes),
        "status": "current",
        "question_id": source_result["question_id"],
        "claim_ids": list(claim_ids or []),
        "figure_stage": figure_stage,
        "scientific_question": scientific_question
        or f"{source_result['question_id']} 的当前结果呈现什么可复验结构？",
        "expected_takeaway": expected_takeaway
        or "展示当前结果中可由图形直接核对的主要结构与差异。",
        "cannot_prove": cannot_prove
        or "该图不能单独证明模型正确性、因果关系或结论的普遍有效性。",
        "source_result_ids": [result_id],
        "source_result_sha256s": {result_id: sha256_bytes(json_bytes(source_result))},
        "objective_semantics_sha256": source_result["objective_semantics_sha256"],
        "paper_allowed": figure_stage == "publication",
        "demo": False,
        "created_at": utc_now(),
    }
    if archetype := _auditable_visual_archetype(template_id, visual_archetype):
        entry["visual_archetype"] = archetype
    for existing in index["figures"]:
        if existing["figure_id"] == figure_id and existing["status"] == "current":
            existing["status"] = "superseded"
    index["figures"].append(entry)
    require_figure_index(index)
    atomic_json(run_dir / INDEX_PATH, index)
    return entry


def _verify_recorded_file(run_dir: Path, record: dict[str, str], label: str) -> str | None:
    """复验一个路径/哈希记录并返回可读错误。"""
    try:
        current = sha256_file(resolve_inside(run_dir, record["path"], must_exist=True))
    except ContractError as exc:
        return f"{label} 无效: {exc}"
    if current != record["sha256"]:
        return f"{label} 哈希不一致: {record['path']}"
    return None


def verify_current_figure_files(
    run_dir: Path, *, figure_stage: str = "publication"
) -> dict[str, Any]:
    """复验当前图表仍由 current 真实结果生成且输出未漂移。

    Args:
        run_dir: v3 运行目录。

    Returns:
        检查过的图表、错误明细和总体成功状态。
    """
    if _competition_first_run(run_dir):
        return _verify_competition_figures(run_dir)
    index = read_figure_index(run_dir)
    results = read_result_index(run_dir)
    result_map = {item["result_id"]: item for item in results["results"]}
    errors: list[dict[str, str]] = []
    checked: list[str] = []
    for figure in index["figures"]:
        if figure["status"] != "current":
            continue
        recorded_stage = figure.get("figure_stage", "publication")
        if recorded_stage != figure_stage:
            continue
        figure_id = figure["figure_id"]
        checked.append(figure_id)
        if figure["demo"] or (figure_stage == "publication" and not figure["paper_allowed"]):
            errors.append({"figure_id": figure_id, "message": "demo 图或未允许图不能进入论文"})
        result = result_map.get(figure["result_id"])
        if (
            result is None
            or result["status"] != "current"
            or not result["execution_valid"]
            or (
                figure_stage == "publication"
                and not quality_allows_paper(run_dir, figure["result_id"])
            )
        ):
            errors.append({"figure_id": figure_id, "message": "源结果已被替代或不再可用于论文"})
        else:
            expected_result_sha = sha256_bytes(json_bytes(result))
            recorded_sha = figure.get("source_result_sha256s", {}).get(
                figure["result_id"]
            )
            if recorded_sha is not None and recorded_sha != expected_result_sha:
                errors.append({"figure_id": figure_id, "message": "源结果条目变化后图表需要重新生成"})
            if figure.get("objective_semantics_sha256") not in {
                None,
                result.get("objective_semantics_sha256"),
            }:
                errors.append({"figure_id": figure_id, "message": "图表绑定的目标语义已变化"})
            input_path = figure["input_result"]["path"]
            if input_path not in result["output_hashes"]:
                errors.append({"figure_id": figure_id, "message": "图表输入不再属于源结果输出"})
            elif figure["input_result"]["sha256"] != result["output_hashes"][input_path]:
                errors.append({"figure_id": figure_id, "message": "源结果更新后图表需要重新生成"})
        for label, record in (
            ("图表输入", figure["input_result"]),
            ("参考模板", figure["reference_template"]),
            ("渲染脚本", figure["renderer_script"]),
            ("文字边界", figure["text_boxes"]),
        ):
            issue = _verify_recorded_file(run_dir, record, label)
            if issue:
                errors.append({"figure_id": figure_id, "message": issue})
        for output in figure["outputs"]:
            issue = _verify_recorded_file(run_dir, output, "图表输出")
            if issue:
                errors.append({"figure_id": figure_id, "message": issue})
                continue
            if resolve_inside(run_dir, output["path"], must_exist=True).stat().st_size == 0:
                errors.append({"figure_id": figure_id, "message": f"图表输出为空: {output['path']}"})
        try:
            boxes_path = resolve_inside(run_dir, figure["text_boxes"]["path"], must_exist=True)
            boxes_document = json.loads(boxes_path.read_text(encoding="utf-8"))
            boxes = boxes_document.get("boxes") if isinstance(boxes_document, dict) else None
            if not isinstance(boxes, list):
                raise ContractError("文字边界文件缺少 boxes 数组")
            png = next(
                item["path"] for item in figure["outputs"] if Path(item["path"]).suffix.lower() == ".png"
            )
            # 复用独立 QA 的图片可读性和文字边界相交检查，不在索引层做主观评分。
            from tools.qa.figqa import audit_figure

            audit = audit_figure(resolve_inside(run_dir, png, must_exist=True), boxes)
            if audit["errors"]:
                raise ContractError("；".join(audit["errors"]))
        except (ContractError, OSError, json.JSONDecodeError, StopIteration) as exc:
            errors.append({"figure_id": figure_id, "message": f"图表 QA 失败: {exc}"})
    return {"success": not errors, "checked_figure_ids": checked, "errors": errors}
