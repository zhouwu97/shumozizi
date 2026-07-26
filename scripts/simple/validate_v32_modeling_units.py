"""校验 Competition-First v3.2 建模单元的分析或实验完成状态。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError
from shumozizi.simple.modeling_units import (
    require_v32_experiment_evidence,
    require_v32_modeling_plan,
)


def main() -> int:
    """执行 v3.2 建模单元检查并输出适合自动化消费的结论。"""
    parser = argparse.ArgumentParser(description="校验 Competition-First v3.2 建模单元")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "--stage",
        choices=("analysis", "experiment"),
        default="analysis",
        help="analysis 校验进入实验前冻结；experiment 额外校验实际结果回填。",
    )
    args = parser.parse_args()
    try:
        if args.stage == "analysis":
            require_v32_modeling_plan(args.run_dir)
        else:
            require_v32_experiment_evidence(args.run_dir)
    except ContractError as exc:
        print(f"invalid: {exc}")
        return 1
    print("valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
