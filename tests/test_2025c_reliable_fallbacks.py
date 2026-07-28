"""2025 C 题可靠回退实验的聚焦回归测试。"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

CODE_DIR = Path(__file__).resolve().parents[1] / "runs" / "2025c" / "code"


def _load(name: str) -> Any:
    """从运行代码目录导入实验模块。"""
    path = str(CODE_DIR)
    if path not in sys.path:
        sys.path.insert(0, path)
    return importlib.import_module(name)


def test_selective_metrics_excludes_review_records() -> None:
    """拒判区记录不能被计作自动分类正确或错误。"""
    module = _load("q4_selective_review")
    labels = np.array([0, 0, 1, 1])
    actions = np.array([-1, 0, 1, 0])

    metrics = module.selective_metrics(labels, actions)

    assert metrics["coverage"] == 0.5
    assert metrics["review_records"] == 2.0
    assert metrics["sensitivity"] == 1.0
    assert metrics["specificity"] == 1.0


def test_dual_threshold_selection_satisfies_training_constraints() -> None:
    """选出的双阈值必须在训练 OOF 数据上同时通过两个 guard。"""
    module = _load("q4_selective_review")
    labels = np.array([0, 0, 0, 0, 1, 1, 1, 1])
    probabilities = np.array([0.02, 0.08, 0.30, 0.45, 0.40, 0.72, 0.88, 0.96])

    low, high, metrics = module.choose_thresholds(labels, probabilities)

    assert low < high
    assert metrics["sensitivity"] >= module.SENSITIVITY_FLOOR
    assert metrics["specificity"] >= module.SPECIFICITY_FLOOR
    assert 0.0 < metrics["coverage"] <= 1.0


def test_inner_oof_never_predicts_fitted_rows(monkeypatch: Any) -> None:
    """每个内层模型只能预测与其拟合母体互斥的记录。"""
    module = _load("q4_selective_review")
    features = pd.DataFrame({"row_id": np.arange(16), "x": np.linspace(0.0, 1.0, 16)})
    labels = np.array([0, 1] * 8)
    groups = np.repeat(np.arange(8), 2)
    checks: list[tuple[set[int], set[int]]] = []

    class FakeModel:
        """记录拟合集并在预测时检查互斥。"""

        def __init__(self, fitted: set[int]) -> None:
            self.fitted = fitted

        def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
            predicted = set(frame["row_id"].astype(int))
            checks.append((self.fitted, predicted))
            p = np.clip(frame["x"].to_numpy(float), 0.01, 0.99)
            return np.column_stack([1.0 - p, p])

    def fake_fit(_route: str, frame: pd.DataFrame, _labels: np.ndarray) -> FakeModel:
        return FakeModel(set(frame["row_id"].astype(int)))

    monkeypatch.setattr(module.q4_nested, "fit_model", fake_fit)
    probabilities = module.inner_oof_probabilities(features, labels, groups)

    assert probabilities.shape == labels.shape
    assert checks
    assert all(fitted.isdisjoint(predicted) for fitted, predicted in checks)


def test_conservative_fallback_keeps_action_fixed(monkeypatch: Any, tmp_path: Path) -> None:
    """外层测试折与扰动场景只能评价冻结动作，不能重新选周。"""
    module = _load("conservative_fallback")
    table = pd.DataFrame({"mother_id": [f"m{i}" for i in range(30)]})
    observed_weeks: list[float] = []
    captured: dict[str, Any] = {}

    monkeypatch.setattr(module.pipeline, "load_data", lambda: (object(), object()))
    monkeypatch.setattr(module, "_table", lambda *_args, **_kwargs: table.copy())

    def fake_evaluate(_table: pd.DataFrame, week: float) -> dict[str, float]:
        observed_weeks.append(week)
        return {"risk_score": week, "worst_group_failure_rate": 0.0}

    monkeypatch.setattr(module, "_evaluate", fake_evaluate)
    monkeypatch.setattr(module.pipeline, "atomic_json", lambda _path, payload: captured.update(payload))

    module.run("q2", tmp_path / "ignored.json")

    assert observed_weeks
    assert set(observed_weeks) == {module.FROZEN_WEEKS["q2"]}
    assert all(fold["training_choice"] == "frozen_reliability_candidate" for fold in captured["outer_folds"])
