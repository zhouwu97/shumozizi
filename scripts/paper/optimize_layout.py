"""生成 v3.4 论文高级版面优化建议。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.paper.layout_optimizer import build_layout_optimization  # noqa: E402


def main() -> int:
    """执行版面建议生成并输出 JSON。"""
    parser = argparse.ArgumentParser(description="生成 v3.4 论文版面优化建议")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    payload = build_layout_optimization(args.run_dir)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
