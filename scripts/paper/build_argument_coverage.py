"""从 PAPER_BLUEPRINT.md 生成逐问论证义务覆盖矩阵。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError
from shumozizi.paper.blueprint import build_argument_coverage, validate_argument_coverage


def main() -> int:
    """解析运行内蓝图、原子写入派生产物并输出覆盖状态。"""
    parser = argparse.ArgumentParser(description="生成论文逐问论证义务覆盖矩阵")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--blueprint", default="paper/PAPER_BLUEPRINT.md")
    parser.add_argument("--output", default="paper/generated/argument_coverage.json")
    args = parser.parse_args()
    try:
        document = build_argument_coverage(
            args.run_dir.resolve(),
            blueprint_path=args.blueprint,
            output_path=args.output,
        )
        errors = validate_argument_coverage(document)
        print(
            json.dumps(
                {"success": not errors, "errors": errors, "document": document},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if not errors else 1
    except (ContractError, OSError, ValueError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
