"""展示当前运行的 Friendly Mode 人工检查点。"""

from __future__ import annotations

import argparse

from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.workflow.friendly import checkpoint_json


def main() -> int:
    """读取运行目录并输出只读检查点提示。"""
    parser = argparse.ArgumentParser(description="展示路线或最终人工检查点")
    parser.add_argument("run_dir")
    args = parser.parse_args()
    run_dir = resolve_repo_root() / args.run_dir
    print(checkpoint_json(run_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
