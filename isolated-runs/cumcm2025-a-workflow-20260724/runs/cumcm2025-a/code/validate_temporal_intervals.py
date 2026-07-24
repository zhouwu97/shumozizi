"""验证自适应时间区间分类器不会漏掉窄岛、切触和端点事件。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from model_core import _certified_event_intervals

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "results" / "raw" / "temporal_interval_certificate.json"


def _duration(intervals: list[tuple[float, float]]) -> float:
    """返回互不重叠区间的总长度。"""

    return float(sum(right - left for left, right in intervals))


def _run_case(
    name: str,
    function: Callable[[float], float],
    left: float,
    right: float,
    lipschitz: float,
    tolerance: float,
    true_duration: float,
) -> dict[str, object]:
    """执行单个解析反例并检查真值被包络包含。"""

    confirmed, estimated, uncertain = _certified_event_intervals(
        function,
        left,
        right,
        lipschitz=lipschitz,
        tolerance=tolerance,
    )
    lower = _duration(confirmed)
    estimate = _duration(estimated)
    upper = _duration([*confirmed, *uncertain])
    passed = lower - 1e-12 <= true_duration <= upper + 1e-12
    if not passed:
        raise AssertionError(f"{name} 的真值未被时间包络覆盖")
    return {
        "name": name,
        "true_duration_s": true_duration,
        "lower_bound_s": lower,
        "estimate_s": estimate,
        "upper_bound_s": upper,
        "uncertain_cell_count": len(uncertain),
        "passed": passed,
    }


def main() -> int:
    """运行红队最小复现与边界反例。"""

    tolerance = 1e-4
    cases = [
        _run_case(
            "cell-centered-narrow-island",
            lambda time_s: (time_s - 0.45) ** 2 - 0.01**2,
            0.0,
            0.9,
            0.9,
            tolerance,
            0.02,
        ),
        _run_case(
            "left-edge-narrow-island",
            lambda time_s: (time_s - 0.025) ** 2 - 0.01**2,
            0.0,
            1.0,
            1.95,
            tolerance,
            0.02,
        ),
        _run_case(
            "tangent-zero-duration",
            lambda time_s: (time_s - 0.5) ** 2,
            0.0,
            1.0,
            1.0,
            tolerance,
            0.0,
        ),
        _run_case(
            "left-endpoint-active",
            lambda time_s: time_s - 0.02,
            0.0,
            1.0,
            1.0,
            tolerance,
            0.02,
        ),
        _run_case(
            "right-endpoint-active",
            lambda time_s: 0.98 - time_s,
            0.0,
            1.0,
            1.0,
            tolerance,
            0.02,
        ),
    ]
    payload = {
        "schema_version": "1.0",
        "method": "adaptive-lipschitz-interval-classification",
        "tolerance_s": tolerance,
        "cases": cases,
        "metrics": {
            "case_count": len(cases),
            "passed_count": sum(bool(case["passed"]) for case in cases),
            "maximum_bound_width_s": max(
                float(case["upper_bound_s"]) - float(case["lower_bound_s"])
                for case in cases
            ),
        },
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["metrics"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
