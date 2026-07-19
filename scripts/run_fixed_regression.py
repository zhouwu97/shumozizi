"""运行固定条件回归并输出机器可读报告。"""

from __future__ import annotations

import argparse
import json

from shumozizi.core.io import atomic_json
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.regression import run_fixed_regression


def main() -> int:
    """执行固定回归；可选地把报告写入 reports。"""
    parser = argparse.ArgumentParser(description="运行固定条件回归")
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args()
    root = resolve_repo_root()
    report = run_fixed_regression(root)
    if args.write_report:
        atomic_json(root / "reports" / "fixed_condition_regression.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
