"""审核并晋级版本化图像候选。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError  # noqa: E402
from shumozizi.simple.figure_promotion import promote_figure_candidate  # noqa: E402


def main() -> int:
    """执行 work 图 QA 和 current 晋级。"""
    parser = argparse.ArgumentParser(description="审核并晋级论文图候选")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--figure-id", required=True)
    parser.add_argument(
        "--visual-opportunity-id",
        help="v3.4 视觉机会 ID；提供后必须有绑定真实候选产物的 PROMOTE 批评",
    )
    parser.add_argument("--candidate", action="append", required=True)
    parser.add_argument("--target-stem", required=True)
    parser.add_argument("--rendering-mode", choices=("plot", "diagram"), required=True)
    parser.add_argument(
        "--layout-report",
        required=True,
        help="与候选同目录的流程图几何或统计图语义布局 JSON",
    )
    parser.add_argument(
        "--figure-role",
        choices=("model_understanding", "decisive_evidence", "insight", "stability"),
        required=True,
    )
    parser.add_argument(
        "--presentation-role",
        choices=("data_portrait", "question_hero", "supporting", "appendix"),
    )
    parser.add_argument(
        "--human-review",
        type=Path,
        required=True,
        help="内容化人工复核 JSON；必须包含角色所需的可见性检查和 promote 结论",
    )
    parser.add_argument(
        "--visual-manifest",
        required=True,
        help="与候选同目录、绑定当前 PNG 哈希的 renderer 视觉元素清单",
    )
    args = parser.parse_args()
    try:
        review = json.loads(args.human_review.read_text(encoding="utf-8"))
        result = promote_figure_candidate(
            args.run_dir,
            figure_id=args.figure_id,
            candidate_outputs=args.candidate,
            target_stem=args.target_stem,
            rendering_mode=args.rendering_mode,
            layout_report=args.layout_report,
            figure_role=args.figure_role,
            presentation_role=args.presentation_role,
            human_review=review,
            visual_manifest=args.visual_manifest,
            visual_opportunity_id=args.visual_opportunity_id,
        )
    except (ContractError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
