"""写入或选择论文叙事候选。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from shumozizi.core.io import load_json  # noqa: E402
from shumozizi.paper.narrative_competition import (  # noqa: E402
    select_narrative_candidate,
    write_narrative_candidates,
)


def main() -> int:
    """执行 write 或 select 子命令。"""
    parser = argparse.ArgumentParser(description="论文 Narrative Competition")
    subparsers = parser.add_subparsers(dest="command", required=True)
    write = subparsers.add_parser("write")
    write.add_argument("run_dir", type=Path)
    write.add_argument("--input", type=Path, required=True)
    select = subparsers.add_parser("select")
    select.add_argument("run_dir", type=Path)
    select.add_argument("candidate_id")
    select.add_argument("--reviewer-context-id", required=True)
    select.add_argument("--selection-reason", required=True)
    select.add_argument("--revision-advice", required=True)
    args = parser.parse_args()
    if args.command == "write":
        source = load_json(args.input)
        payload = write_narrative_candidates(args.run_dir, source.get("candidates", source))
    else:
        payload = select_narrative_candidate(
            args.run_dir,
            args.candidate_id,
            reviewer_context_id=args.reviewer_context_id,
            selection_reason=args.selection_reason,
            revision_advice=args.revision_advice,
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
