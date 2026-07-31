"""输出数学建模论文的高置信度错误与报告式写作告警。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.paper.style_audit import audit_report_like_manuscript  # noqa: E402


def main() -> int:
    """解析运行目录并打印可机读的 errors/warnings 审计结果。"""
    parser = argparse.ArgumentParser(
        description="检测论文中的高置信度写作错误与报告式写作风险"
    )
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    result = audit_report_like_manuscript(args.run_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
