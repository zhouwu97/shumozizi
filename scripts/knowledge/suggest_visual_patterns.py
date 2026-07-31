"""按当前视觉义务和结构化输出推荐候选或已采用的论文视觉模式。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from shumozizi.knowledge.usage import build_visual_pattern_suggestions


def main() -> int:
    """生成 advisory 推荐报告，并输出可用与拒绝数量。"""
    parser = argparse.ArgumentParser(
        description="用当前 MODELING_UNITS 视觉义务筛选已采用的论文视觉模式"
    )
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    report = build_visual_pattern_suggestions(args.run_dir)
    print(
        json.dumps(
            {
                "status": report["status"],
                "recommendations": len(report["recommendations"]),
                "rejections": len(report["rejections"]),
                "path": "figures/generated/learned-pattern-suggestions.json",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
