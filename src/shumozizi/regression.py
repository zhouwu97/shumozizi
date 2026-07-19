"""固定条件回归：检测基础算法、输入数据和输出摘要的确定性漂移。"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, load_json, sha256_file


def run_fixed_regression(repo_root: Path) -> dict[str, Any]:
    """在固定 CSV 上执行闭式 OLS，并与版本化基线逐字段比较。"""
    baseline = load_json(repo_root / "regression" / "fixed_baseline.json")
    fixture = repo_root / baseline["fixture"]
    if sha256_file(fixture) != baseline["data_sha256"]:
        raise ContractError("固定回归输入数据哈希已变化")
    rows = list(csv.DictReader(fixture.open(encoding="utf-8-sig", newline="")))
    if not rows or not {"x", "y"}.issubset(rows[0]):
        raise ContractError("固定回归夹具必须包含 x、y 两列")
    x = [float(row["x"]) for row in rows]
    y = [float(row["y"]) for row in rows]
    mean_x, mean_y = sum(x) / len(x), sum(y) / len(y)
    denominator = sum((value - mean_x) ** 2 for value in x)
    if denominator == 0:
        raise ContractError("固定回归自变量没有变化")
    slope = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y, strict=True)) / denominator
    intercept = mean_y - slope * mean_x
    rmse = math.sqrt(
        sum((b - (slope * a + intercept)) ** 2 for a, b in zip(x, y, strict=True)) / len(x)
    )
    output = {"intercept": intercept, "rmse": rmse, "slope": slope}
    canonical = json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    output_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    mismatches = [key for key, expected in baseline["expected"].items() if output[key] != expected]
    if output_sha256 != baseline["output_sha256"]:
        mismatches.append("output_sha256")
    return {
        "schema_name": "fixed_regression_report",
        "schema_version": "2.0",
        "fixture": baseline["fixture"],
        "algorithm_id": baseline["algorithm_id"],
        "status": "pass" if not mismatches else "blocked",
        "data_sha256": baseline["data_sha256"],
        "output_sha256": output_sha256,
        "output": output,
        "mismatches": mismatches,
    }
