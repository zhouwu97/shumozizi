"""验证 production→高级模板适配层与数据驱动生成器。"""

from __future__ import annotations

from pathlib import Path

from shumozizi.core.io import atomic_json
from shumozizi.paper.advanced_figure_adapters import (
    adapt_ci_forest,
    adapt_roc_ci,
    adapt_survival_curve,
    build_advanced_figures,
    hero_figure_upgrades,
)
from shumozizi.simple.initialization import initialize_simple_run


def _run(tmp_path: Path, name: str) -> Path:
    """创建三问 Competition-First 运行。"""
    return initialize_simple_run(
        tmp_path,
        name,
        required_questions=["Q1", "Q2", "Q3"],
        workflow_version="3.2",
    )


def _survival_result() -> dict:
    """构造带 recommendation.groups[].curve[] 的可靠性结果。"""
    curve = [
        {"week": 18.0, "probability": 0.88, "lcb": 0.87},
        {"week": 19.0, "probability": 0.90, "lcb": 0.895},
        {"week": 20.0, "probability": 0.92, "lcb": 0.915},
    ]
    return {
        "question_id": "Q2",
        "reliability_assumption": 0.90,
        "recommendation": {
            "groups": [
                {
                    "bmi_lower": 20.0,
                    "bmi_upper": 31.0,
                    "feasible": True,
                    "status": "feasible",
                    "curve": curve,
                },
                {
                    "bmi_lower": 31.0,
                    "bmi_upper": 46.0,
                    "feasible": False,
                    "status": "infeasible_within_window",
                    "curve": curve,
                },
            ]
        },
    }


def test_survival_adapter_builds_document_from_recommendation_groups() -> None:
    """recommendation.groups[].curve[] 应映射为 survival_curve 输入。"""
    built = adapt_survival_curve(_survival_result(), Path("x"))
    assert built is not None
    assert built["template"] == "survival_curve"
    assert built["question_id"] == "Q2"
    doc = built["document"]
    assert doc["threshold"] == 0.90
    assert len(doc["groups"]) == 2
    first = doc["groups"][0]
    assert "BMI 20.0" in first["label"]
    assert first["points"][1]["probability"] == 0.90
    assert first["points"][1]["ci_lower"] == 0.895


def test_survival_adapter_rejects_missing_groups() -> None:
    """没有 recommendation.groups 时适配器应返回 None（不硬编）。"""
    assert adapt_survival_curve({"question_id": "Q1"}, Path("x")) is None


def test_ci_forest_adapter_builds_document() -> None:
    """coefficients + confidence_intervals 应映射为 ci_forest 输入。"""
    document = {
        "question_id": "Q1",
        "coefficients": {"week": -0.0052, "bmi": -0.0016},
        "confidence_intervals": {"week": [-0.013, 0.002], "bmi": [-0.005, 0.002]},
    }
    built = adapt_ci_forest(document, Path("x"))
    assert built is not None
    assert built["template"] == "ci_forest"
    rows = built["document"]["rows"]
    assert rows[0]["label"] == "week"
    assert rows[0]["estimate"] == -0.0052
    assert rows[0]["low"] == -0.013
    assert rows[0]["high"] == 0.002


def test_ci_forest_adapter_rejects_missing_intervals() -> None:
    """缺 confidence_intervals 时不应适配。"""
    document = {"coefficients": {"week": -0.005}}
    assert adapt_ci_forest(document, Path("x")) is None


def test_roc_adapter_computes_deterministic_curve() -> None:
    """targets/predictions 应确定性算出 ROC 曲线与 AUC。"""
    document = {
        "question_id": "Q4",
        "targets": [0, 1, 0, 1, 1],
        "predictions": [0.1, 0.9, 0.2, 0.8, 0.7],
    }
    built = adapt_roc_ci(document, Path("x"))
    assert built is not None
    assert built["template"] == "cv_roc_ci"
    doc = built["document"]
    assert doc["fpr"][0] == 0.0
    assert doc["tpr"][-1] == 1.0
    assert 0.0 < doc["auc"] <= 1.0
    assert len(doc["fpr"]) == len(doc["tpr"])


def test_roc_adapter_requires_both_classes() -> None:
    """只有单类样本时无法画 ROC，应返回 None。"""
    document = {"targets": [0, 0, 0], "predictions": [0.1, 0.2, 0.3]}
    assert adapt_roc_ci(document, Path("x")) is None


def test_build_advanced_figures_only_consumes_referenced_results(
    tmp_path: Path,
) -> None:
    """生成器应只读论文 current 图引用的结果，不无差别扫描所有版本。"""
    run_dir = _run(tmp_path, "advanced-figures-plan")
    results = run_dir / "results/raw"
    results.mkdir(parents=True, exist_ok=True)
    atomic_json(results / "q2_primary_prod_r1.json", _survival_result())
    atomic_json(results / "q2_primary_prod_r5.json", _survival_result())
    # 论文 current 图只引用 r5。
    atomic_json(
        run_dir / "figures/index.json",
        {
            "schema_version": "1.3",
            "run_id": run_dir.name,
            "figures": [
                {
                    "figure_id": "q2-reliability",
                    "status": "current",
                    "paper_allowed": True,
                    "visual_archetype": "probability_curve",
                    "question_id": "Q2",
                    "input_result": {"path": "results/raw/q2_primary_prod_r5.json"},
                }
            ],
        },
    )
    plan = build_advanced_figures(run_dir)
    assert len(plan) == 1
    assert plan[0]["input"] == "results/raw/q2_primary_prod_r5.json"
    assert plan[0]["template"] == "survival_curve"


def test_hero_figure_upgrades_maps_relevant_plan_items() -> None:
    """有朴素 question_hero 的问应把高级图计划项标为 hero 接替。"""
    index = {
        "figures": [
            {
                "figure_id": "q2-reliability",
                "status": "current",
                "question_id": "Q2",
                "visual_archetype": "probability_curve",
                "presentation_role": "question_hero",
            }
        ]
    }
    plan = [
        {
            "output": "figures/current/adv_q2_primary_prod_r5_survival_curve",
            "question_id": "Q2",
        },
        {
            "output": "figures/current/adv_q1_primary_prod_r2_ci_forest",
            "question_id": "Q1",
        },
    ]
    upgrades = hero_figure_upgrades(index, plan)
    assert "adv_q2_primary_prod_r5_survival_curve" in upgrades
    # Q1 没有 hero，不应晋升。
    assert "adv_q1_primary_prod_r2_ci_forest" not in upgrades


def test_hero_figure_upgrades_ignores_non_hero_questions() -> None:
    """没有 question_hero 的索引不应产生任何晋升。"""
    index = {
        "figures": [
            {
                "figure_id": "q1-coefficients",
                "status": "current",
                "question_id": "Q1",
                "visual_archetype": "ci_forest",
                "presentation_role": "supporting",
            }
        ]
    }
    plan = [{"output": "figures/current/adv_q1_prod_r2_ci_forest", "question_id": "Q1"}]
    assert hero_figure_upgrades(index, plan) == {}


def test_empty_index_yields_empty_plan(tmp_path: Path) -> None:
    """没有图索引时生成器应返回空计划而不是报错。"""
    run_dir = _run(tmp_path, "advanced-figures-empty")
    assert build_advanced_figures(run_dir) == []
