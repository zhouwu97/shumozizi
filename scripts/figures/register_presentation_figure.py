"""登记只重组冻结事实、不创造实验结果的竞赛呈现图。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError  # noqa: E402
from shumozizi.simple.figures import register_presentation_figure  # noqa: E402


def main() -> int:
    """解析参数并登记已通过候选晋级的呈现图。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--figure-id", required=True)
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--renderer-script", required=True)
    parser.add_argument("--output", action="append", required=True)
    parser.add_argument("--question-id", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--takeaway", required=True)
    parser.add_argument("--limitations", required=True)
    parser.add_argument(
        "--presentation-role",
        choices=("data_portrait", "question_hero", "supporting", "appendix"),
        required=True,
    )
    parser.add_argument(
        "--role",
        choices=("model_understanding", "decisive_evidence", "insight", "stability"),
        required=True,
    )
    parser.add_argument("--promotion-receipt", required=True)
    parser.add_argument("--template-id", default="custom")
    args = parser.parse_args()
    try:
        entry = register_presentation_figure(
            args.run_dir,
            figure_id=args.figure_id,
            source_files=args.source,
            renderer_script=args.renderer_script,
            outputs=args.output,
            question_id=args.question_id,
            question=args.question,
            takeaway=args.takeaway,
            limitations=args.limitations,
            presentation_role=args.presentation_role,
            role=args.role,
            promotion_receipt=args.promotion_receipt,
            template_id=args.template_id,
        )
    except ContractError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(entry, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
