"""将独立对话生成的自由审查报告绑定为 v3 质量放行摘要。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError
from shumozizi.simple.review import (
    import_final_audit,
    import_objective_semantics_review,
    import_paper_blind_review,
    import_scientific_review,
)


def main() -> int:
    """导入已完成的科学红队或 PDF 盲审报告。"""
    parser = argparse.ArgumentParser(description="导入 Capability-First v3 独立审查结论")
    parser.add_argument("run_dir")
    parser.add_argument(
        "--kind",
        choices=("objective-semantics", "scientific", "paper-blind", "final-audit"),
        required=True,
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--verdict", choices=("pass", "fail", "needs_rework", "revoked"), required=True)
    parser.add_argument("--severity", choices=("none", "P0", "P1", "P2", "P3"), required=True)
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--report")
    parser.add_argument("--competition-strength", choices=("weak", "qualified", "strong", "unknown"))
    parser.add_argument("--full-rerun-required", action="store_true")
    parser.add_argument("--affected-question", action="append", default=[])
    parser.add_argument("--assessment")
    parser.add_argument("--argumentation-complete", action="store_true")
    parser.add_argument("--readability-passed", action="store_true")
    parser.add_argument("--empty-section", action="append", default=[])
    parser.add_argument("--unreadable-page", action="append", type=int, default=[])
    args = parser.parse_args()
    try:
        root = Path(args.run_dir)
        if args.kind == "objective-semantics":
            summary = import_objective_semantics_review(
                root,
                manifest_file=args.manifest,
                verdict=args.verdict,
                highest_severity=args.severity,
                reviewer_thread_id=args.thread_id,
                assessment_file=(
                    Path(args.assessment)
                    if args.assessment
                    else Path("review/OBJECTIVE_SEMANTICS.json")
                ),
                report_file=(
                    Path(args.report)
                    if args.report
                    else Path("review/OBJECTIVE_SEMANTICS_REVIEW.md")
                ),
            )
        elif args.kind == "scientific":
            if args.competition_strength is None:
                parser.error("scientific 审查必须提供 --competition-strength")
            summary = import_scientific_review(
                root,
                manifest_file=args.manifest,
                verdict=args.verdict,
                highest_severity=args.severity,
                competition_strength=args.competition_strength,
                full_rerun_required=args.full_rerun_required,
                affected_questions=args.affected_question,
                reviewer_thread_id=args.thread_id,
                report_file=Path(args.report) if args.report else Path("review/SCIENTIFIC_RED_TEAM.md"),
            )
        elif args.kind == "paper-blind":
            summary = import_paper_blind_review(
                root,
                manifest_file=args.manifest,
                verdict=args.verdict,
                highest_severity=args.severity,
                reviewer_thread_id=args.thread_id,
                argumentation_complete=args.argumentation_complete,
                readability_passed=args.readability_passed,
                empty_sections=args.empty_section,
                unreadable_pages=args.unreadable_page,
                report_file=Path(args.report) if args.report else Path("review/PAPER_BLIND_REVIEW.md"),
            )
        else:
            summary = import_final_audit(
                root,
                manifest_file=args.manifest,
                verdict=args.verdict,
                highest_severity=args.severity,
                reviewer_thread_id=args.thread_id,
                report_file=(
                    Path(args.report)
                    if args.report
                    else Path("review/FINAL_SUBMISSION_REVIEW.md")
                ),
            )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except (ContractError, OSError, ValueError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
