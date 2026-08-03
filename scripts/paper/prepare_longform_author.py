"""准备长篇论文 Author Pass 的命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from shumozizi.paper.author_pass import prepare_longform_author  # noqa: E402


def main() -> int:
    """生成作者材料并打印 manifest。"""
    parser = argparse.ArgumentParser(description="准备长篇论文 Author Pass")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare_longform_author(args.run_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
