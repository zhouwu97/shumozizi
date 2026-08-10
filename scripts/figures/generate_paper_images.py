"""生成、审查并登记论文解释图候选。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shumozizi.simple.paper_image_generation import (  # noqa: E402
    command_generator,
    command_reviewer,
    run_paper_image_generation,
)


def main() -> int:
    """执行论文图片候选生成 CLI。"""
    parser = argparse.ArgumentParser(description="生成并审查论文解释图候选")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("image_id")
    parser.add_argument("--generator-executable", nargs="+", required=True)
    parser.add_argument("--reviewer-executable", nargs="+", required=True)
    parser.add_argument("--reviewer-context-id", required=True)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    result = run_paper_image_generation(
        args.run_dir,
        args.image_id,
        generator=command_generator(args.generator_executable, timeout_seconds=args.timeout),
        reviewer=command_reviewer(args.reviewer_executable, timeout_seconds=args.timeout),
        reviewer_context_id=args.reviewer_context_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
