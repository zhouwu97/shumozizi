"""构建论文解释图候选 Prompt。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shumozizi.simple.paper_image_prompts import build_paper_image_prompts  # noqa: E402


def main() -> int:
    """执行 Prompt 规划 CLI。"""
    parser = argparse.ArgumentParser(description="规划论文解释图并生成 A/B Prompt")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--no-refresh", action="store_true", help="复用已有 VISUAL_REQUIREMENTS")
    args = parser.parse_args()
    payload = build_paper_image_prompts(args.run_dir, refresh_requirements=not args.no_refresh)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
