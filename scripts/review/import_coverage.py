"""验证并导入科学审核或论文盲审的覆盖闭环。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from shumozizi.simple.review import require_coverage_declaration_valid


def main() -> int:
    """复验覆盖声明、任务回执、风险哈希和专项追问。"""
    parser = argparse.ArgumentParser(description="验证动态审核覆盖声明")
    parser.add_argument("run_dir")
    parser.add_argument("--scope", choices=("scientific", "paper"), required=True)
    parser.add_argument("--report-file", required=True)
    parser.add_argument("--parent-task-id", required=True)
    args = parser.parse_args()
    payload = require_coverage_declaration_valid(
        Path(args.run_dir).resolve(),
        expected_report_file=args.report_file,
        scope=args.scope,
        expected_parent_task_id=args.parent_task_id,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
