"""写入轻量视觉想法。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from shumozizi.core.io import load_json  # noqa: E402
from shumozizi.simple.visual_sandbox import write_visual_ideas  # noqa: E402


def main() -> int:
    """读取 ideas 数组并写入当前运行。"""
    parser = argparse.ArgumentParser(description="写入 Visual Sandbox 想法")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    source = load_json(args.input)
    ideas = source.get("ideas", source) if isinstance(source, dict) else source
    print(json.dumps(write_visual_ideas(args.run_dir, ideas), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
