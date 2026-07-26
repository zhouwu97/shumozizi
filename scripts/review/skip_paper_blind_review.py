"""显式记录 Competition-First PDF 盲评的跳过原因。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.simple.review import record_paper_blind_review_skip


def main() -> int:
    """写入不可静默跳过的 PDF 盲评说明。"""
    parser = argparse.ArgumentParser(description="记录 PDF 盲评跳过原因")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    print(record_paper_blind_review_skip(args.run_dir.resolve(), args.reason))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
