"""受控写入 Competition-First v3.2 的正文图表计划。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError, load_json  # noqa: E402
from shumozizi.simple.figures import write_figure_plan  # noqa: E402


def main() -> int:
    """校验并原子写入 FIGURE_PLAN 2.1。"""
    parser = argparse.ArgumentParser(description="写入 v3.2 正文图表计划")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = write_figure_plan(args.run_dir, load_json(args.input))
    except ContractError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
