"""审计正文图集是否具备国奖级视觉竞争力，不评价其科学正确性。

现有 style_audit 只衡量"证据是否绑定、是否泄漏、论证是否完整"；这条第二质量轴
衡量"图**集合**是否像竞赛论文而非统计报告"。国奖论文的视觉竞争力来自图种多样、
承担数据直觉/机制/决策/路线等叙事角色、以及有冲击力的 hero 图——而不是多张
单面板诊断曲线。本模块只把这些差距写成 advisory 信号，交由独立 PDF 盲评裁决，
不能凭启发式规则阻断创作或编译。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, load_json

# 高冲击图型：多面板组合、3D/机制/结构/决策、EDA 直觉图。国奖论文靠它们承担
# 叙事角色。single-panel 的简单验证曲线不在其中。
_HIGH_IMPACT_ARCHETYPES: frozenset[str] = frozenset(
    {
        # 数据直觉 / EDA
        "correlation_heatmap",
        "pairplot",
        "jointplot",
        "group_violin",
        "paired_raincloud",
        "raincloud",
        "swarmplot",
        "ecdf",
        "hist_density",
        "ridgeline",
        "spatiotemporal_density",
        "cluster_structure_embedding",
        "longitudinal_trajectory",
        "spatial_trajectory_with_constraints",
        "spatial_scene_with_constraints",
        # 机制 / 解释
        "shap_combo",
        "feature_importance",
        "partial_dependence",
        "response_surface_with_constraints",
        "decision_surface_with_fallback",
        "phase_field_bifurcation",
        "network_flow_bottleneck",
        "geometric_section_projection",
        # 决策 / 权衡
        "pareto_frontier",
        "pareto_feasible_region",
        "feasible_region_active_constraints",
        "radar",
        "sankey",
        "parallel_coordinates",
        # 结构 / 路线
        "roadmap",
        "data_decision_flow",
        "model_workflow",
        "architecture_diagram",
        "search_trajectory_envelope",
        # 组合型决定性证据（多面板/带置信带）
        "multi_panel_evidence_chain",
        "classifier_diagnostic_bundle",
        "cv_roc_ci",
        "uncertainty_fan_with_threshold",
        "interval_event_timeline",
        "state_control_event_timeline",
        "survival_curve",
    }
)

# 报告式图型：单面板内部诊断或验证曲线。比例过高会让论文读起来像统计报告。
_REPORT_LIKE_ARCHETYPES: frozenset[str] = frozenset(
    {
        "residual_diagnostic",
        "qq_plot",
        "acf",
        "pacf",
        "convergence",
        "route_score_comparison",
        "timing",
        "calibration_curve",
        "probability_curve",
        "pr_roc",
        "roc_curve",
        "model_comparison",
        "ci_forest",
        "forest_plot",
        "threshold_tradeoff",
        "tradeoff",
        "objective_curve",
    }
)

# 高冲击图型按叙事角色分组，用于"缺哪类角色"的提示。
_HIGH_IMPACT_FAMILIES: dict[str, frozenset[str]] = {
    "data_intuition": frozenset(
        {
            "correlation_heatmap",
            "pairplot",
            "jointplot",
            "group_violin",
            "paired_raincloud",
            "raincloud",
            "swarmplot",
            "ecdf",
            "hist_density",
            "ridgeline",
            "spatiotemporal_density",
            "cluster_structure_embedding",
            "longitudinal_trajectory",
        }
    ),
    "mechanism": frozenset(
        {
            "shap_combo",
            "feature_importance",
            "partial_dependence",
            "response_surface_with_constraints",
            "decision_surface_with_fallback",
            "phase_field_bifurcation",
            "network_flow_bottleneck",
            "geometric_section_projection",
            "spatial_scene_with_constraints",
            "spatial_trajectory_with_constraints",
        }
    ),
    "decision": frozenset(
        {
            "pareto_frontier",
            "pareto_feasible_region",
            "feasible_region_active_constraints",
            "radar",
            "sankey",
            "parallel_coordinates",
            "uncertainty_fan_with_threshold",
            "interval_event_timeline",
            "state_control_event_timeline",
        }
    ),
    "roadmap": frozenset(
        {"roadmap", "data_decision_flow", "model_workflow", "architecture_diagram"}
    ),
}

_FAMILY_LABELS = {
    "data_intuition": "数据直觉/EDA",
    "mechanism": "机制/结构/解释",
    "decision": "决策/权衡",
    "roadmap": "技术路线/流程",
}


def _archetype_of(figure: dict[str, Any]) -> str:
    """返回图的可审计图型标识，优先显式声明再回退模板。"""
    value = figure.get("visual_archetype") or figure.get("template_id") or ""
    return str(value).strip()


def _is_body_figure(figure: dict[str, Any]) -> bool:
    """只统计最终进正文的 current 图，跳过失败与被替换的旧版本。"""
    if not isinstance(figure, dict):
        return False
    if figure.get("status") not in {None, "current"}:
        return False
    if figure.get("paper_allowed") is False:
        return False
    if figure.get("placement") == "appendix" or figure.get("presentation_role") == "appendix":
        return False
    if figure.get("role") == "stability":
        return False
    return True


def _read_figures(run_dir: Path) -> list[dict[str, Any]]:
    """读取图索引；优先 v3 index.json，兼容旧 FIGURE_PLAN。"""
    index_path = run_dir / "figures/index.json"
    try:
        payload = load_json(index_path) if index_path.is_file() else {}
    except (ContractError, OSError, ValueError):
        payload = {}
    figures = payload.get("figures")
    if isinstance(figures, list):
        return [item for item in figures if isinstance(item, dict)]
    legacy = run_dir / "figures/FIGURE_PLAN.json"
    if not legacy.is_file():
        return []
    try:
        plan = load_json(legacy)
    except (ContractError, OSError, ValueError):
        return []
    return [item for item in plan.get("figures", []) if isinstance(item, dict)]


def _classify_archetype(archetype: str) -> str:
    """把图型归类为 high_impact / report_like / unknown。"""
    if archetype in _HIGH_IMPACT_ARCHETYPES:
        return "high_impact"
    if archetype in _REPORT_LIKE_ARCHETYPES:
        return "report_like"
    return "unknown"


def audit_visual_competition(run_dir: Path) -> dict[str, Any]:
    """返回正文图集视觉竞争力的非阻断审计结果。

    Args:
        run_dir: v3 运行目录。

    Returns:
        含 ``findings`` 与 ``metrics`` 的可机读结果。所有发现均为 advisory，
        需要独立 PDF 盲评对照国奖观感后裁决。
    """
    root = run_dir.resolve()
    figures = _read_figures(root)
    body_figures = [item for item in figures if _is_body_figure(item)]

    findings: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}
    if not body_figures:
        return {
            "advisory_only": True,
            "success": True,
            "findings": [],
            "metrics": {"body_figure_count": 0, "source": "figures/index.json"},
            "limitations": "没有可审计的正文图；请在实验阶段产出并由 Visual Sandbox 晋级正式图。",
        }

    archetype_of = {item.get("figure_id", f"fig-{index}"): _archetype_of(item) for index, item in enumerate(body_figures)}
    classes = [ _classify_archetype(archetype) for archetype in archetype_of.values() ]
    high_impact_count = sum(1 for value in classes if value == "high_impact")
    report_like_count = sum(1 for value in classes if value == "report_like")
    known_count = high_impact_count + report_like_count
    total = len(body_figures)

    present_families = {
        family: any(_archetype_of(item) in archetypes for item in body_figures)
        for family, archetypes in _HIGH_IMPACT_FAMILIES.items()
    }

    metrics.update(
        {
            "body_figure_count": total,
            "distinct_archetypes": len(set(archetype_of.values())),
            "high_impact_count": high_impact_count,
            "report_like_count": report_like_count,
            "unknown_archetype_count": total - known_count,
            "present_families": {
                name: _FAMILY_LABELS[name] for name, present in present_families.items() if present
            },
            "missing_families": [
                _FAMILY_LABELS[name] for name, present in present_families.items() if not present
            ],
        }
    )

    # 报告式图主导：单面板诊断/验证曲线多于高冲击图型且占正文过半。
    if (
        total >= 3
        and report_like_count > high_impact_count
        and report_like_count / total >= 0.5
    ):
        findings.append(
            {
                "code": "VISUAL_COMPETITION_REPORT_DOMINANCE",
                "message": (
                    "正文图以单面板诊断/验证曲线为主，高冲击图型（组合图/机制图/"
                    "权衡图）偏少；请对照国奖论文补承担数据直觉、机制或决策角色的图，"
                    "否则论文读起来像统计报告。"
                ),
                "count": 1,
                "report_like_count": report_like_count,
                "high_impact_count": high_impact_count,
                "body_figure_count": total,
            }
        )

    # 图种单一：可用图型过少，正文视觉单调。
    if metrics["distinct_archetypes"] < 3:
        findings.append(
            {
                "code": "VISUAL_COMPETITION_LOW_DIVERSITY",
                "message": (
                    f"正文仅出现 {metrics['distinct_archetypes']} 种图型；"
                    "国奖论文通常覆盖 3 种以上承担不同论证角色的图型。"
                ),
                "count": 1,
                "distinct_archetypes": metrics["distinct_archetypes"],
            }
        )

    # 缺少高冲击叙事角色（仅在正文图数足够时提示，避免小论文被过度打扰）。
    if total >= 3:
        for family, present in present_families.items():
            if present:
                continue
            if family == "roadmap" and total >= 3:
                message = "正文缺少技术路线/流程类图；国赛论文几乎必有至少一张路线图。"
            else:
                message = (
                    f"正文缺少{_FAMILY_LABELS[family]}类图；国奖论文通常用该类图"
                    "承担对应叙事角色。若本题结构确实不需要，请在盲评中说明理由。"
                )
            findings.append(
                {
                    "code": f"VISUAL_COMPETITION_MISSING_{family.upper()}",
                    "message": message,
                    "count": 1,
                    "family": family,
                }
            )

    # hero 图冲击力：主图不应多数是单面板诊断曲线。
    hero_archetypes = [
        _archetype_of(item)
        for item in body_figures
        if item.get("presentation_role") in {"question_hero", "data_portrait"}
    ]
    metrics["hero_archetypes"] = hero_archetypes
    hero_report_like = sum(
        1
        for archetype in hero_archetypes
        if _classify_archetype(archetype) == "report_like"
    )
    if hero_archetypes and hero_report_like / len(hero_archetypes) > 0.5:
        findings.append(
            {
                "code": "VISUAL_COMPETITION_WEAK_HERO",
                "message": (
                    "多数问题主图为单面板诊断/验证曲线，缺乏组合图或机制图的视觉冲击；"
                    "请让每问 hero 图承担更完整的叙事角色。"
                ),
                "count": 1,
                "hero_archetypes": hero_archetypes,
                "hero_report_like_count": hero_report_like,
            }
        )

    return {
        "advisory_only": True,
        "success": True,
        "findings": findings,
        "metrics": metrics,
        "limitations": (
            "本审计只看图型集合与角色覆盖，不评价图本身的质量、美观或科学正确性；"
            "所有结论均需独立 PDF 盲评对照国奖观感裁决，不能凭启发式规则阻断。"
        ),
    }
