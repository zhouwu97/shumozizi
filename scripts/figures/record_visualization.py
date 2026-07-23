"""写入 Capability-First v3 的图表叙事计划。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.simple.visualization import write_visualization_plan


def main() -> int:
    """校验并保存图表合同，完成输出路径会自动冻结 SHA-256。"""
    parser = argparse.ArgumentParser(description="登记 v3 图表叙事计划")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    print(json.dumps(write_visualization_plan(args.run_dir, payload), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
