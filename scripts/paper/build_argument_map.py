"""从 Competition-First 当前产物生成后台 argument map。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError
from shumozizi.paper.readiness import build_argument_map_from_current_artifacts


def main() -> int:
    """生成 ``paper/generated/argument_map.json``。"""
    parser = argparse.ArgumentParser(description="从当前答案、结果和图表生成 argument map")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    try:
        payload = build_argument_map_from_current_artifacts(args.run_dir.resolve())
    except ContractError as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
