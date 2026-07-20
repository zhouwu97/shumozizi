"""用独立审核报告晋级一个原子模式或反模式。"""

from __future__ import annotations

import argparse
from pathlib import Path

from shumozizi.knowledge.patterns import promote_pattern


def main() -> int:
    parser = argparse.ArgumentParser(description="单个原子模式独立晋级")
    parser.add_argument("pattern_id")
    parser.add_argument("review_report", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    path = promote_pattern(args.repo_root, args.pattern_id, args.review_report)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
