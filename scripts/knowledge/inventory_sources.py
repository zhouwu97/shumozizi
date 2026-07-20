"""清点只读优秀论文材料目录。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from shumozizi.knowledge.papers import write_source_inventory


def main() -> int:
    parser = argparse.ArgumentParser(description="清点优秀论文材料并计算 SHA-256")
    parser.add_argument("--source-dir", action="append", dest="source_dirs")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source_dirs = args.source_dirs or [os.environ.get("SHUMO_EXCELLENT_PAPER_DIR", "")]
    paths = [Path(item) for item in source_dirs if item]
    if not paths:
        parser.error("请通过 --source-dir 或 SHUMO_EXCELLENT_PAPER_DIR 指定材料目录")
    write_source_inventory(paths, args.output)
    print(f"已写入材料清点报告: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
