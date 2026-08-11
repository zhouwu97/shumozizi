"""按已选择的 v3 模板受控编译论文。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError
from shumozizi.paper.compiler import compile_paper


def main() -> int:
    """编译论文并输出冻结回执。"""
    parser = argparse.ArgumentParser(description="编译 Capability-First v3 论文并写入回执")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument(
        "--revision-impact",
        choices=("auto", "render", "argument", "science"),
        default="auto",
        help="本次改动影响层级；首轮编译会自动建立 argument revision",
    )
    parser.add_argument(
        "--reference-docx",
        type=Path,
        help="Word 样式参考模板；CUMCM 候选稿会绑定其摘要",
    )
    parser.add_argument(
        "--include-docx",
        action="store_true",
        help="赛事未要求 Word 时仍显式生成并审计 DOCX 交付物。",
    )
    parser.add_argument(
        "--strict-competition",
        action="store_true",
        help="启用独立冷读和低于 18 页硬门",
    )
    args = parser.parse_args()
    try:
        payload = compile_paper(
            args.run_dir,
            timeout_seconds=args.timeout,
            revision_impact=args.revision_impact,
            reference_docx=args.reference_docx,
            include_docx=True if args.include_docx else None,
            strict_editorial=args.strict_competition,
            enforce_page_budget=args.strict_competition,
        )
    except ContractError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
