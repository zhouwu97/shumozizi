"""输出核心问题首个可行解后的轻量独立 AI 复核提示。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError
from shumozizi.simple.modeling_units import first_feasible_checkpoint_prompt


def main() -> int:
    """解析运行目录与问题 ID，并输出固定提示词。"""
    parser = argparse.ArgumentParser(description="生成核心问题首解后的独立 AI 复核提示")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--question", required=True)
    parser.add_argument(
        "--allow-non-search-core",
        action="store_true",
        help="显式允许 data_modeling 或 exact_oracle 核心问使用同一轻量复核。",
    )
    args = parser.parse_args()
    try:
        prompt = first_feasible_checkpoint_prompt(
            args.run_dir,
            args.question,
            allow_non_search_core=args.allow_non_search_core,
        )
    except (ContractError, OSError, ValueError) as exc:
        print(f"invalid: {exc}")
        return 1
    print(prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
