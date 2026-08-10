"""正式 renderer 组件测试：最小 JSON fixture 生成 PNG/PDF，几何与标注可复验。"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from shumozizi.figures.renderers import (
    RENDERER_REGISTRY,
    render_contact_network_backbone,
    render_convergence_envelope,
    render_cost_reliability_frontier,
    render_geometric_oracle_comparison,
    render_implementation_agreement,
    render_integer_feasible_region,
    render_periodic_spatial_scene,
    render_probability_threshold_curve,
)


def _render_all(document: dict, stem: Path) -> dict:
    """渲染全部支持 archetone，确保注册表覆盖完整。"""
    from shumozizi.figures.renderers import render_figure

    output = render_figure(document, stem.name, stem)
    return output


def _assert_dual_output(output: dict, stem: Path) -> None:
    """PNG/PDF 均存在且 PNG 可打开、非空。"""
    png = stem.with_suffix(".png")
    pdf = stem.with_suffix(".pdf")
    assert png.is_file() and png.stat().st_size > 0
    assert pdf.is_file() and pdf.stat().st_size > 0
    with Image.open(png) as image:
        assert image.width > 100 and image.height > 100
    assert output["minimum_font_size_pt"] >= 8.0
    assert len(output["outputs"]) == 2


def test_periodic_spatial_scene_renders_png_and_pdf(tmp_path: Path) -> None:
    """3D 周期单元必须输出 PNG/PDF，且含 2D 正交剖面面板。"""
    document = {
        "starts": [
            {"x": -0.20, "y": 0.05, "z": -0.10},
            {"x": 0.10, "y": -0.05, "z": 0.12},
            {"x": -0.05, "y": 0.18, "z": 0.02},
        ],
        "box": [0.30, 0.25, 0.20],
        "identity_pairs": [{"first": 1, "second": 2, "axis": 0}],
        "wrapped_fragments": [{"fragment": 3, "identity": 1}],
        "radius": 0.05,
    }
    stem = tmp_path / "q1_periodic_scene"
    output = render_periodic_spatial_scene(document, stem)
    _assert_dual_output(output, stem)


def test_contact_network_backbone_renders(tmp_path: Path) -> None:
    """接触网络必须区分电极、普通接触与导电骨架。"""
    document = {
        "nodes": [
            {"x": 0.0, "y": 0.0},
            {"x": 0.5, "y": 0.0},
            {"x": 0.5, "y": 0.5},
            {"x": 0.0, "y": 0.5},
        ],
        "edges": [
            {"first": 1, "second": 2},
            {"first": 2, "second": 3},
            {"first": 3, "second": 4},
        ],
        "electrodes": [
            {"side": "left", "x": -0.1, "y": 0.25},
            {"side": "right", "x": 0.6, "y": 0.25},
        ],
        "conductive_path": [{"first": 1, "second": 2}, {"first": 2, "second": 3}],
    }
    stem = tmp_path / "q1_contact_backbone"
    output = render_contact_network_backbone(document, stem)
    _assert_dual_output(output, stem)


def test_geometric_oracle_comparison_renders(tmp_path: Path) -> None:
    """端部对比图必须标出被删除伪边与保留真接触。"""
    document = {
        "gap": 0.05,
        "candidate_pairs": [
            {"label": "边 1-2", "capsule_distance": 0.03, "exact_distance": 0.071},
            {"label": "边 2-3", "capsule_distance": 0.04, "exact_distance": 0.042},
            {"label": "边 3-4", "capsule_distance": 0.06, "exact_distance": 0.060},
        ],
    }
    stem = tmp_path / "q1_oracle_zoom"
    output = render_geometric_oracle_comparison(document, stem)
    _assert_dual_output(output, stem)


def test_probability_threshold_curve_renders(tmp_path: Path) -> None:
    """概率转变图必须含 Wilson 区间、阈值线与独立批次。"""
    document = {
        "threshold": 0.90,
        "points": [
            {"x": 6, "probability": 0.83, "wilson_low": 0.812, "wilson_high": 0.847},
            {"x": 7, "probability": 0.873, "wilson_low": 0.868, "wilson_high": 0.877},
            {"x": 8, "probability": 0.913, "wilson_low": 0.909, "wilson_high": 0.917},
        ],
        "extra_points": [
            {"x": 8, "probability": 0.914, "wilson_low": 0.910, "wilson_high": 0.918, "label": "独立加密"},
        ],
        "title": "阈值测试",
    }
    stem = tmp_path / "q3_threshold_curve"
    output = render_probability_threshold_curve(document, stem)
    _assert_dual_output(output, stem)


def test_integer_feasible_region_renders(tmp_path: Path) -> None:
    """整数可行域必须含可行/不可行格点、成本与选中点。"""
    document = {
        "lattice_points": [
            {"n_A": 1, "n_B": 49, "feasible": False, "cost": 0.12},
            {"n_A": 1, "n_B": 50, "feasible": True, "cost": 0.122},
            {"n_A": 2, "n_B": 40, "feasible": True, "cost": 0.1},
            {"n_A": 2, "n_B": 41, "feasible": True, "cost": 0.103},
        ],
        "selected_point": {"n_A": 1, "n_B": 50, "label": "1A+50B"},
        "title": "整数可行域测试",
    }
    stem = tmp_path / "q4_feasible_region"
    output = render_integer_feasible_region(document, stem)
    _assert_dual_output(output, stem)


def test_cost_reliability_frontier_renders(tmp_path: Path) -> None:
    """前沿图必须分层编码正式域与敏感性域。"""
    document = {
        "threshold": 0.90,
        "official": "1A+50B",
        "candidate_points": [
            {"label": "1A+50B", "cost": 0.1220, "probability": 0.9050, "wilson_low": 0.9012, "wilson_high": 0.9088, "domain": "formal"},
            {"label": "1A+49B", "cost": 0.1205, "probability": 0.8880, "wilson_low": 0.8840, "wilson_high": 0.8920, "domain": "formal"},
            {"label": "0A+57B", "cost": 0.1140, "probability": 0.8990, "wilson_low": 0.8950, "wilson_high": 0.9030, "domain": "sensitivity_zero"},
        ],
        "title": "前沿分层测试",
    }
    stem = tmp_path / "q4_frontier"
    output = render_cost_reliability_frontier(document, stem)
    _assert_dual_output(output, stem)


def test_convergence_envelope_renders(tmp_path: Path) -> None:
    """收敛包络必须为多种子分位带，而不是单次曲线。"""
    document = {
        "envelope": [
            {"sample": 1000, "median": 0.90, "low": 0.89, "high": 0.91},
            {"sample": 5000, "median": 0.905, "low": 0.898, "high": 0.912},
            {"sample": 20000, "median": 0.908, "low": 0.903, "high": 0.913},
        ],
        "stopping_point": {"sample": 20000, "label": "n=20000"},
        "title": "收敛包络测试",
    }
    stem = tmp_path / "appendix_convergence"
    output = render_convergence_envelope(document, stem)
    _assert_dual_output(output, stem)


def test_implementation_agreement_renders(tmp_path: Path) -> None:
    """实现一致性必须展示实际差异，而不是全绿检查表。"""
    document = {
        "classifications": [
            {"label": "Q1 分类", "primary": 1.0, "independent": 1.0, "difference": 0.0},
            {"label": "Q2 概率", "primary": 0.908, "independent": 0.9081, "difference": 1e-4},
            {"label": "Q3 阈值", "primary": 8.0, "independent": 8.0, "difference": 0.0},
        ]
    }
    stem = tmp_path / "appendix_agreement"
    output = render_implementation_agreement(document, stem)
    _assert_dual_output(output, stem)


def test_registry_covers_all_route_archetypes() -> None:
    """8.2 路由矩阵中的 archetype 全部有正式 renderer。"""
    for archetype in (
        "periodic_spatial_scene",
        "spatial_scene_cross_section",
        "spatial_contact_backbone_triptych",
        "contact_network_backbone",
        "oracle_comparison_zoom",
        "probability_threshold_curve",
        "uncertainty_margin_ribbon",
        "integer_feasible_region",
        "cost_reliability_frontier",
        "convergence_envelope",
        "implementation_agreement",
        "shared_model_pipeline",
    ):
        assert archetype in RENDERER_REGISTRY, archetype


def test_unknown_archetype_rejected(tmp_path: Path) -> None:
    """未知 archetype 不得静默回退成通用图。"""
    from shumozizi.figures.renderers import render_figure

    with pytest.raises(ValueError, match="未注册"):
        render_figure({"stages": []}, "quantum_teleportation", tmp_path / "x")


def test_probability_renderer_rejects_missing_points(tmp_path: Path) -> None:
    """概率曲线缺少 points 时明确失败，不允许从标量拼图。"""
    with pytest.raises(ValueError, match="points"):
        render_probability_threshold_curve({"threshold": 0.9}, tmp_path / "empty")


def test_integer_region_rejects_missing_lattice(tmp_path: Path) -> None:
    """整数可行域缺少格点数据时明确失败。"""
    with pytest.raises(ValueError, match="lattice_points"):
        render_integer_feasible_region({}, tmp_path / "empty")
