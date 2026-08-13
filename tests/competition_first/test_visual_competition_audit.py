"""验证图集视觉竞争力审计区分"报告式图集"与"国奖式图集"。"""

from __future__ import annotations

from pathlib import Path

from shumozizi.core.io import atomic_json
from shumozizi.paper.visual_competition_audit import audit_visual_competition
from shumozizi.simple.initialization import initialize_simple_run


def _run(tmp_path: Path, name: str) -> Path:
    """创建三问 Competition-First 运行。"""
    return initialize_simple_run(
        tmp_path,
        name,
        required_questions=["Q1", "Q2", "Q3"],
        workflow_version="3.2",
    )


def _figure(
    figure_id: str,
    archetype: str,
    *,
    role: str = "decisive_evidence",
    presentation_role: str = "supporting",
) -> dict[str, object]:
    """构造一个可审计的正文图条目。"""
    return {
        "figure_id": figure_id,
        "visual_archetype": archetype,
        "template_id": "cti-data-driven",
        "status": "current",
        "paper_allowed": True,
        "placement": "body",
        "role": role,
        "presentation_role": presentation_role,
    }


def _write_index(run_dir: Path, figures: list[dict[str, object]]) -> None:
    """写入 v3 图索引。"""
    atomic_json(
        run_dir / "figures/index.json",
        {"schema_version": "1.3", "figures": figures},
    )


def _codes(report: dict[str, object]) -> set[str]:
    """返回审计发现代码集合。"""
    return {item["code"] for item in report["findings"]}  # type: ignore[arg-type]


def test_report_like_figure_set_is_flagged(tmp_path: Path) -> None:
    """清一色单面板诊断/验证曲线应被识别为报告式图集。"""
    run_dir = _run(tmp_path, "report-like-figures")
    _write_index(
        run_dir,
        [
            _figure("q1-cal", "calibration_curve"),
            _figure("q1-res", "residual_diagnostic"),
            _figure("q2-cal", "calibration_curve"),
            _figure("q2-prob", "probability_curve", presentation_role="question_hero"),
            _figure("q3-roc", "pr_roc"),
            _figure("q3-prob", "probability_curve", presentation_role="question_hero"),
        ],
    )

    report = audit_visual_competition(run_dir)
    assert report["advisory_only"] is True
    assert report["success"] is True
    assert "VISUAL_COMPETITION_REPORT_DOMINANCE" in _codes(report)
    assert "VISUAL_COMPETITION_WEAK_HERO" in _codes(report)
    assert "VISUAL_COMPETITION_MISSING_MECHANISM" in _codes(report)
    metrics = report["metrics"]
    assert metrics["body_figure_count"] == 6  # type: ignore[index]
    assert metrics["report_like_count"] == 6  # type: ignore[index]


def test_diverse_national_award_like_figure_set_is_clean(tmp_path: Path) -> None:
    """图种多样、覆盖多叙事角色的图集不应触发报告式告警。"""
    run_dir = _run(tmp_path, "award-like-figures")
    _write_index(
        run_dir,
        [
            _figure("q1-eda", "correlation_heatmap", role="model_understanding"),
            _figure("q1-traj", "longitudinal_trajectory", presentation_role="question_hero"),
            _figure("q2-shap", "shap_combo", role="insight"),
            _figure("q2-roc", "cv_roc_ci", presentation_role="question_hero"),
            _figure("q3-pareto", "pareto_frontier", role="insight"),
            _figure("q3-roadmap", "data_decision_flow", presentation_role="data_portrait"),
            _figure("q3-cal", "calibration_curve"),
        ],
    )

    report = audit_visual_competition(run_dir)
    codes = _codes(report)

    assert "VISUAL_COMPETITION_REPORT_DOMINANCE" not in codes
    assert "VISUAL_COMPETITION_WEAK_HERO" not in codes
    assert "VISUAL_COMPETITION_MISSING_MECHANISM" not in codes
    assert "VISUAL_COMPETITION_MISSING_DECISION" not in codes
    assert "VISUAL_COMPETITION_MISSING_ROADMAP" not in codes


def test_superseded_and_appendix_figures_are_ignored(tmp_path: Path) -> None:
    """被替换旧版本、附录图与稳定性审计图不应进入图集统计。"""
    run_dir = _run(tmp_path, "superseded-figures")
    _write_index(
        run_dir,
        [
            {
                "figure_id": "q1-old",
                "visual_archetype": "calibration_curve",
                "status": "superseded",
                "paper_allowed": True,
                "placement": "body",
                "role": "decisive_evidence",
                "presentation_role": "supporting",
            },
            _figure("q1-hero", "multi_panel_evidence_chain", presentation_role="question_hero"),
            {
                "figure_id": "q1-stability",
                "visual_archetype": "residual_diagnostic",
                "status": "current",
                "paper_allowed": True,
                "placement": "appendix",
                "role": "stability",
                "presentation_role": "appendix",
            },
        ],
    )

    report = audit_visual_competition(run_dir)
    metrics = report["metrics"]

    assert metrics["body_figure_count"] == 1  # type: ignore[index]
    assert metrics["report_like_count"] == 0  # type: ignore[index]
    assert metrics["high_impact_count"] == 1  # type: ignore[index]


def test_missing_figure_index_returns_clean_empty_report(tmp_path: Path) -> None:
    """没有图索引的运行应返回空发现而不是报错。"""
    run_dir = _run(tmp_path, "no-figures")

    report = audit_visual_competition(run_dir)

    assert report["advisory_only"] is True
    assert report["success"] is True
    assert report["findings"] == []
    assert report["metrics"]["body_figure_count"] == 0  # type: ignore[index]


def test_low_diversity_figure_set_reports_diversity(tmp_path: Path) -> None:
    """只有两种图型时即使不算报告式也应提示图种单一。"""
    run_dir = _run(tmp_path, "low-diversity-figures")
    _write_index(
        run_dir,
        [
            _figure("q1-roc", "cv_roc_ci", presentation_role="question_hero"),
            _figure("q2-roc", "cv_roc_ci", presentation_role="question_hero"),
            _figure("q3-roc", "cv_roc_ci", presentation_role="question_hero"),
        ],
    )

    report = audit_visual_competition(run_dir)

    assert "VISUAL_COMPETITION_LOW_DIVERSITY" in _codes(report)
    assert "VISUAL_COMPETITION_REPORT_DOMINANCE" not in _codes(report)
    assert report["metrics"]["distinct_archetypes"] == 1  # type: ignore[index]
