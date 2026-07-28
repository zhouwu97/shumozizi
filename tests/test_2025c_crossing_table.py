"""验证 CUMCM 2025 C 题首次达标端点的重复记录语义。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

RUN_CODE = Path(__file__).resolve().parents[1] / "runs" / "2025c" / "code"


def _load_pipeline():
    """从当前生产 run 加载端点实现。"""
    path = RUN_CODE / "pipeline.py"
    specification = importlib.util.spec_from_file_location("pipeline_2025c", path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"无法加载运行模块: {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def _mother_rows() -> pd.DataFrame:
    """构造同一孕妇在两个名义孕周各有重复检测的记录。"""
    return pd.DataFrame(
        {
            "mother_id": ["M1"] * 4,
            "gest_week": [12.0, 11.0, 12.0, 11.0],
            "y_fraction": [0.050, 0.020, 0.039, 0.030],
            "bmi": [31.0] * 4,
            "age": [29.0] * 4,
            "height": [165.0] * 4,
            "gravidity": [2.0] * 4,
            "parity": [1.0] * 4,
            "IVF妊娠": ["自然受孕"] * 4,
        }
    )


def test_crossing_table_aggregates_same_week_before_interpolation() -> None:
    """同孕周先取中位数，穿越点应由两个聚合孕周插值得到。"""
    pipeline = _load_pipeline()

    result = pipeline.crossing_table(_mother_rows()).iloc[0]

    expected = 11.0 + (0.04 - 0.025) / (0.0445 - 0.025)
    assert result["censoring"] == "interval"
    assert result["crossing_week"] == pytest.approx(expected)
    assert 11.0 < result["crossing_week"] < 12.0


def test_crossing_table_is_invariant_to_raw_row_order() -> None:
    """重复检测的原始行顺序不得制造零宽区间或改变端点。"""
    pipeline = _load_pipeline()
    rows = _mother_rows()

    forward = pipeline.crossing_table(rows).iloc[0]
    reversed_rows = rows.iloc[::-1].reset_index(drop=True)
    backward = pipeline.crossing_table(reversed_rows).iloc[0]

    assert backward["censoring"] == forward["censoring"]
    assert backward["crossing_week"] == pytest.approx(forward["crossing_week"])
