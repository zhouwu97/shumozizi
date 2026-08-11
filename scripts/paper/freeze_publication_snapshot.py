"""冻结当前正式论文入口和真实依赖闭包。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.paper.publication import freeze_publication_snapshot  # noqa: E402


def main() -> int:
    """解析运行目录并输出已冻结的正式发布快照。"""
    parser = argparse.ArgumentParser(
        description="冻结 paper/main（或已接受外部稿）的真实源码闭包"
    )
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    snapshot = freeze_publication_snapshot(args.run_dir)
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
