"""从当前论文论证生成视觉需求，并路由未覆盖项。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shumozizi.paper.visual_requirements import (  # noqa: E402
    build_visual_requirements_from_paper,
)


def _main() -> int:
    """执行视觉需求生成器。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "--no-sync",
        action="store_true",
        help="只写 VISUAL_REQUIREMENTS.json，不同步到视觉机会池。",
    )
    args = parser.parse_args()
    payload = build_visual_requirements_from_paper(
        args.run_dir,
        sync_opportunities=not args.no_sync,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
