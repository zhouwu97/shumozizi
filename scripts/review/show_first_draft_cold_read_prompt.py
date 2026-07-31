"""输出只接收第一版 PDF 的独立冷读固定提示词。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError
from shumozizi.paper.paper_review import first_draft_cold_read_prompt


def main() -> int:
    """校验冻结 PDF 边界并输出三分钟冷读提示。"""
    parser = argparse.ArgumentParser(description="输出第一版 PDF 独立冷读提示词")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--pdf", default="paper/draft-1.pdf")
    args = parser.parse_args()
    try:
        print(first_draft_cold_read_prompt(args.run_dir.resolve(), pdf_path=args.pdf))
        return 0
    except (ContractError, OSError, ValueError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
