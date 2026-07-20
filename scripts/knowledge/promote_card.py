"""将一张通过独立知识审核的 Paper Card v2 晋级。"""

from __future__ import annotations

import argparse
from pathlib import Path

from shumozizi.knowledge.promotion import promote_paper_card


def main() -> int:
    parser = argparse.ArgumentParser(description="单卡晋级 Paper Card v2")
    parser.add_argument("paper_id")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    outputs = promote_paper_card(args.repo_root, args.paper_id)
    for name, path in outputs.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
