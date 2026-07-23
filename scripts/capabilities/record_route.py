"""将能力路由 JSON 以受控路径写入 v3 运行。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.simple.capabilities import write_capability_route


def main() -> int:
    """读取路由输入文件并保存验证后的清单。"""
    parser = argparse.ArgumentParser(description="登记 Capability-First v3 能力路由")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    print(json.dumps(write_capability_route(args.run_dir, payload), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
