"""校验 Competition-First v3.2 候选目标后果比较的计划或冻结状态。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError
from shumozizi.simple.objective_consequences import (
    require_objective_candidate_plan,
    require_objective_consequences,
)


def main() -> int:
    """执行候选目标检查并输出适合自动化消费的结论。"""
    parser = argparse.ArgumentParser(description="校验 v3.2 候选目标后果比较")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "--stage",
        choices=("analysis", "paper"),
        default="analysis",
        help="analysis 校验候选集合与后果度量；paper 额外要求真实 probe 与冻结裁决。",
    )
    args = parser.parse_args()
    try:
        if args.stage == "analysis":
            require_objective_candidate_plan(args.run_dir)
        else:
            require_objective_consequences(args.run_dir)
    except ContractError as exc:
        print(f"invalid: {exc}")
        return 1
    print("valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
