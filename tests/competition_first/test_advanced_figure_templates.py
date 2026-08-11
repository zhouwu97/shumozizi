"""render_advanced.py 模板冒烟测试：每个模板都能从生产风格 JSON 渲染三格式输出。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_SCRIPTS = (
    Path(__file__).resolve().parents[2] / ".agents/skills/mathmodel-advanced-figures/scripts"
)


def _render(template: str, document: dict, tmp_path: Path) -> list[Path]:
    inp = tmp_path / f"{template}.json"
    inp.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / template
    result = subprocess.run(
        [sys.executable, str(SKILL_SCRIPTS / "render_advanced.py"),
         "--template", template, "--input", str(inp), "--output", str(out)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert out.with_suffix(".png").is_file()
    assert out.with_suffix(".pdf").is_file()
    assert out.with_suffix(".svg").is_file()
    return [out.with_suffix(s) for s in (".png", ".pdf", ".svg")]


DOCS = {
    "survival_curve": {
        "groups": [
            {"label": "G1", "points": [
                {"x": 12, "probability": 0.3, "ci_lower": 0.2, "ci_upper": 0.4},
                {"x": 15, "probability": 0.5, "ci_lower": 0.4, "ci_upper": 0.6},
            ]},
            {"label": "G2", "points": [
                {"x": 12, "probability": 0.2, "ci_lower": 0.1, "ci_upper": 0.3},
                {"x": 15, "probability": 0.4, "ci_lower": 0.3, "ci_upper": 0.5},
            ]},
        ],
        "threshold": 0.9,
        "x_label": "孕周",
        "y_label": "达标比例",
    },
    "shap_combo": {
        "shap_values": [[0.1, 0.2, 0.3], [0.2, 0.1, -0.1], [0.3, 0.2, 0.1]],
        "feature_names": ["BMI", "孕周", "年龄"],
        "feature_values": [[25, 12, 30], [30, 15, 35], [35, 18, 40]],
    },
    "correlation_heatmap": {
        "matrix": [[1.0, 0.5, 0.2], [0.5, 1.0, 0.3], [0.2, 0.3, 1.0]],
        "labels": ["孕周", "BMI", "浓度"],
    },
    "paired_raincloud": {
        "groups": [
            {"label": "正常", "values": [1.0, 1.2, 1.5, 0.8]},
            {"label": "异常", "values": [2.0, 2.2, 1.8, 2.5]},
        ],
    },
    "cv_roc_ci": {
        "fpr": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
        "tpr": [0.0, 0.5, 0.7, 0.8, 0.9, 1.0],
        "ci_lower": [0.0, 0.4, 0.6, 0.7, 0.8, 1.0],
        "ci_upper": [0.0, 0.6, 0.8, 0.9, 1.0, 1.0],
        "auc": 0.85,
        "operating_point": {"fpr": 0.1, "tpr": 0.49},
    },
    "probability_curve": {
        "points": [
            {"x": 10, "probability": 0.3, "ci_lo": 0.2, "ci_hi": 0.4},
            {"x": 15, "probability": 0.7, "ci_lo": 0.6, "ci_hi": 0.8},
        ],
        "threshold": 0.9,
    },
    "ci_forest": {
        "rows": [
            {"label": "G1", "estimate": 15.2, "low": 14.0, "high": 16.5},
            {"label": "G5", "estimate": 22.8, "low": 21.0, "high": 24.5},
        ],
        "threshold": 0.9,
    },
    "group_violin": {
        "groups": [
            {"group": "A", "values": [1.0, 1.2, 1.5]},
            {"group": "B", "values": [2.0, 2.2, 2.5]},
        ],
    },
}


@pytest.mark.parametrize("template", sorted(DOCS))
def test_advanced_template_renders(template: str, tmp_path: Path) -> None:
    _render(template, DOCS[template], tmp_path)


def test_list_contains_new_templates(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SKILL_SCRIPTS / "render_advanced.py"), "--list"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    for expected in ("survival_curve", "shap_combo", "correlation_heatmap",
                     "paired_raincloud", "cv_roc_ci"):
        assert expected in result.stdout
