"""从当前结果索引生成或校验唯一 production manifest。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from shumozizi.simple.production_manifest import (
    build_production_manifest,
    require_production_manifest,
)


def main() -> int:
    """执行 build 或 check。"""
    parser = argparse.ArgumentParser(description="管理唯一 production manifest")
    parser.add_argument("command", choices=("build", "check"))
    parser.add_argument("run_dir")
    args = parser.parse_args()
    root = Path(args.run_dir)
    payload = (
        build_production_manifest(root)
        if args.command == "build"
        else require_production_manifest(root)
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
