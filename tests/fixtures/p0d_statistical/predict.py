"""P0d 统计夹具：训练/验证划分上的均值基线和线性拟合。"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def read_rows(path: Path) -> list[tuple[float, float]]:
    """读取二维回归样本。"""
    with path.open(encoding="utf-8", newline="") as stream:
        return [(float(row["x"]), float(row["y"])) for row in csv.DictReader(stream)]


def rmse(actual: list[float], predicted: list[float]) -> float:
    """计算均方根误差。"""
    return (
        sum((left - right) ** 2 for left, right in zip(actual, predicted, strict=True))
        / len(actual)
    ) ** 0.5


def fit_line(rows: list[tuple[float, float]]) -> tuple[float, float]:
    """用最小二乘拟合 y = slope*x + intercept。"""
    x_values = [row[0] for row in rows]
    y_values = [row[1] for row in rows]
    x_mean = sum(x_values) / len(x_values)
    y_mean = sum(y_values) / len(y_values)
    denominator = sum((value - x_mean) ** 2 for value in x_values)
    slope = sum((x - x_mean) * (y - y_mean) for x, y in rows) / denominator
    return slope, y_mean - slope * x_mean


def main() -> None:
    """执行一个统计预测循环并输出结构化指标。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("data")
    parser.add_argument("output")
    parser.add_argument("mode", choices=("baseline", "primary"))
    args = parser.parse_args()
    rows = read_rows(Path(args.data))
    split = int(len(rows) * 0.6)
    train, validation = rows[:split], rows[split:]
    if args.mode == "baseline":
        prediction = sum(row[1] for row in train) / len(train)
        predictions = [prediction] * len(validation)
        slope, intercept = 0.0, prediction
    else:
        slope, intercept = fit_line(train)
        predictions = [slope * row[0] + intercept for row in validation]
    actual = [row[1] for row in validation]
    payload = {
        "validation_rmse": rmse(actual, predictions),
        "train_size": len(train),
        "validation_size": len(validation),
        "slope": slope,
        "intercept": intercept,
        "predictions": predictions,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
