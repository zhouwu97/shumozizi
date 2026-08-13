"""输出数学建模论文正文图集的视觉竞争力告警（advisory）。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.paper.visual_competition_audit import (  # noqa: E402
    audit_visual_competition,
)


def main() -> int:
    """解析运行目录并打印图集视觉竞争力的 advisory findings。"""
    parser = argparse.ArgumentParser(
        description="检测正文图集是否像竞赛论文而非统计报告（不阻断）"
    )
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    result = audit_visual_competition(args.run_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
