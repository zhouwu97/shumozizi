"""使用闭式解拟合一元线性回归并输出结构化指标。"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


def main() -> None:
    """读取两列 CSV，拟合并输出斜率、截距与 RMSE。"""
    rows = list(csv.DictReader(Path(sys.argv[1]).open(encoding="utf-8-sig")))
    x = [float(row["{{x_column}}"] ) for row in rows]
    y = [float(row["{{y_column}}"] ) for row in rows]
    mean_x, mean_y = sum(x) / len(x), sum(y) / len(y)
    denominator = sum((value - mean_x) ** 2 for value in x)
    if denominator == 0:
        raise ValueError("自变量没有变化，无法拟合斜率")
    slope = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y, strict=True)) / denominator
    intercept = mean_y - slope * mean_x
    residuals = [b - (slope * a + intercept) for a, b in zip(x, y, strict=True)]
    rmse = (sum(value * value for value in residuals) / len(residuals)) ** 0.5
    Path(sys.argv[2]).write_text(json.dumps({"metrics": {"slope": slope, "intercept": intercept, "rmse": rmse}}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
