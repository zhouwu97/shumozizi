"""记录 Visual Sandbox 竞争，并把胜出草图冻结为正式重绘参考。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from shumozizi.simple.visual_sandbox import (  # noqa: E402
    graduate_visual_candidate,
    record_visual_competition,
)


def main() -> int:
    """执行 review 或 graduate 子命令。"""
    parser = argparse.ArgumentParser(description="Visual Sandbox")
    subparsers = parser.add_subparsers(dest="command", required=True)
    review = subparsers.add_parser("review")
    review.add_argument("run_dir", type=Path)
    review.add_argument("idea_id")
    review.add_argument("--selected-candidate", required=True)
    review.add_argument("--reviewer-context-id", required=True)
    review.add_argument("--fastest-mechanism", required=True)
    review.add_argument("--full-width-value", required=True)
    review.add_argument("--table-redundancy", required=True)
    review.add_argument("--rationale", required=True)
    graduate = subparsers.add_parser("graduate")
    graduate.add_argument("run_dir", type=Path)
    graduate.add_argument("idea_id")
    graduate.add_argument("--candidate-version", default="v1")
    args = parser.parse_args()
    if args.command == "review":
        payload = record_visual_competition(
            args.run_dir,
            args.idea_id,
            selected_candidate=args.selected_candidate,
            reviewer_context_id=args.reviewer_context_id,
            fastest_mechanism=args.fastest_mechanism,
            full_width_value=args.full_width_value,
            table_redundancy=args.table_redundancy,
            rationale=args.rationale,
        )
    else:
        payload = graduate_visual_candidate(
            args.run_dir, args.idea_id, candidate_version=args.candidate_version
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
