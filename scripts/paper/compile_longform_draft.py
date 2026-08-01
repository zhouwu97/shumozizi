"""编译长篇科学首稿的命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from shumozizi.paper.compiler import compile_longform_draft  # noqa: E402


def main() -> int:
    """解析参数并输出长篇首稿回执。"""
    parser = argparse.ArgumentParser(description="编译长篇科学首稿")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    payload = compile_longform_draft(args.run_dir, timeout_seconds=args.timeout_seconds)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
