"""统一首稿入口：默认长篇科学首稿，reviewable 仅作显式 fallback。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from shumozizi.paper.compiler import (  # noqa: E402
    compile_longform_draft,
    compile_reviewable_draft,
)


def main() -> int:
    """按模式编译首稿并输出回执。"""
    parser = argparse.ArgumentParser(description="编译论文首稿")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "--mode",
        choices=("longform_scientific_draft", "reviewable_draft"),
        default="longform_scientific_draft",
    )
    parser.add_argument("--disclosure", type=Path, help="reviewable fallback 的披露 JSON")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    if args.mode == "longform_scientific_draft":
        payload = compile_longform_draft(args.run_dir, timeout_seconds=args.timeout_seconds)
    else:
        if args.disclosure is None:
            parser.error("reviewable_draft 必须提供 --disclosure")
        disclosure = json.loads(args.disclosure.read_text(encoding="utf-8"))
        payload = compile_reviewable_draft(
            args.run_dir,
            completed_content=disclosure.get("completed_content", []),
            unfinished_questions=disclosure.get("unfinished_questions", []),
            remaining_experiments=disclosure.get("remaining_experiments", []),
            provisional_conclusions=disclosure.get("provisional_conclusions", []),
            timeout_seconds=args.timeout_seconds,
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
