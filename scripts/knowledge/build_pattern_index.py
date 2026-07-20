"""构建原子模式和反模式的隔离索引。"""

from __future__ import annotations

import argparse
from pathlib import Path

from shumozizi.knowledge.patterns import build_pattern_indexes


def main() -> int:
    parser = argparse.ArgumentParser(description="构建原子知识模式双索引")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    indexes = build_pattern_indexes(args.repo_root)
    print(f"provisional: {indexes['provisional']['pattern_count']}")
    print(f"verified: {indexes['verified']['pattern_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
