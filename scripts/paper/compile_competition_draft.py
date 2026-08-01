"""在长篇首稿冷读动作关闭后编译竞赛候选稿。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from shumozizi.paper.compiler import compile_paper  # noqa: E402


def main() -> int:
    """编译严格竞赛稿并输出受控回执。"""
    parser = argparse.ArgumentParser(description="编译竞赛候选论文")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument(
        "--revision-impact",
        choices=("auto", "render", "argument", "science"),
        default="auto",
    )
    args = parser.parse_args()
    payload = compile_paper(
        args.run_dir,
        timeout_seconds=args.timeout_seconds,
        revision_impact=args.revision_impact,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
