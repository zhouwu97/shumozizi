"""保存 v3 运行可用的 Python、MATLAB 与 Octave 工具信息。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.simple.capabilities import write_local_tooling


def main() -> int:
    """解析命令行并输出工具可用性 JSON。"""
    parser = argparse.ArgumentParser(description="探测 v3 运行的本地工具")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(write_local_tooling(args.run_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
