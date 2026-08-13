"""输出提交 PDF 的年度格式审计结果（advisory，独立于求解）。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.paper.submission_contract import (  # noqa: E402
    audit_submission_contract,
)


def main() -> int:
    """解析运行目录并打印提交格式审计结果。"""
    parser = argparse.ArgumentParser(
        description="检查提交 PDF 是否符合指定年度格式规范（不阻断求解）"
    )
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--year", type=int, default=2026)
    args = parser.parse_args()
    result = audit_submission_contract(args.run_dir, year=args.year)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
