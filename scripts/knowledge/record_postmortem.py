"""将单个赛后复盘模式写入 provisional 知识区。"""

from __future__ import annotations

import argparse
from pathlib import Path

from shumozizi.core.io import load_json
from shumozizi.knowledge.patterns import write_postmortem_pattern


def main() -> int:
    parser = argparse.ArgumentParser(description="记录 provisional 赛后原子模式")
    parser.add_argument("document", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    path = write_postmortem_pattern(args.repo_root, load_json(args.document))
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
