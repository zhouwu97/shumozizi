"""运行目录校验命令行薄入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from shumozizi.workflow.validation import validate_run


def main() -> int:
    """校验运行并输出 JSON 报告。"""
    parser = argparse.ArgumentParser(description="校验 shumozizi Schema v2 运行")
    parser.add_argument("run_dir")
    args = parser.parse_args()
    report = validate_run(Path(args.run_dir))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
