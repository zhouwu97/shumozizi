"""审计论文页面视觉节奏与正文图稀疏度。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from shumozizi.paper.style_audit import audit_page_visual_rhythm  # noqa: E402


def main() -> int:
    """运行视觉节奏 advisory 检查。"""
    parser = argparse.ArgumentParser(description="审计论文页面视觉节奏")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit_page_visual_rhythm(args.run_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
