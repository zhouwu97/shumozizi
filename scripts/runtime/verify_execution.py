"""执行记录复验命令行薄入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from shumozizi.runtime.execution import *  # noqa: F403


def main() -> int:
    """复验指定执行记录。"""
    parser = argparse.ArgumentParser(description="复验 Schema v2 执行记录")
    parser.add_argument("run_dir")
    parser.add_argument("execution_id")
    args = parser.parse_args()
    report = verify_execution_record(Path(args.run_dir), args.execution_id)  # noqa: F405
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
