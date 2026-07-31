"""输出写作前独立论文蓝图审核的固定提示词。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError
from shumozizi.paper.blueprint import paper_blueprint_review_prompt


def main() -> int:
    """读取受限材料并输出可交给独立上下文的审核提示。"""
    parser = argparse.ArgumentParser(description="输出写作前独立论文蓝图审核提示词")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "--problem-summary",
        default="problem/PROBLEM_SUMMARY.md",
        help="运行目录 problem/ 内的题目需求摘要相对路径",
    )
    args = parser.parse_args()
    try:
        print(
            paper_blueprint_review_prompt(
                args.run_dir.resolve(), problem_summary_path=args.problem_summary
            )
        )
        return 0
    except (ContractError, OSError, ValueError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
