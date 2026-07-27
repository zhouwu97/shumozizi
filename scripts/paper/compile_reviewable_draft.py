"""编译带明确未完成披露的 Competition-First 首版可审阅草稿。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError, load_json
from shumozizi.paper.compiler import compile_reviewable_draft


def main() -> int:
    """读取显式披露文件，编译并冻结 ``paper/draft-1.pdf``。"""
    parser = argparse.ArgumentParser(description="编译 v3.2 首版可审阅草稿")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--disclosure", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    try:
        disclosure = load_json(args.disclosure)
        payload = compile_reviewable_draft(
            args.run_dir,
            completed_content=disclosure.get("completed_content", []),
            unfinished_questions=disclosure.get("unfinished_questions", []),
            remaining_experiments=disclosure.get("remaining_experiments", []),
            provisional_conclusions=disclosure.get("provisional_conclusions", []),
            timeout_seconds=args.timeout,
        )
    except ContractError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
