"""验证当前运行的高价值关键主张合同。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from shumozizi.simple.critical_claims import require_critical_claims


def main() -> int:
    """执行关键主张 Schema、哈希和同问结果绑定检查。"""
    parser = argparse.ArgumentParser(description="验证 analysis/critical_claims.json")
    parser.add_argument("run_dir")
    args = parser.parse_args()
    payload = require_critical_claims(Path(args.run_dir).resolve())
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
