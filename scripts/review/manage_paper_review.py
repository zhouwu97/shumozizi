"""导入、处置并检查 PAPER_REVIEW 批量返修 finding。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError
from shumozizi.paper.checkpoints import (
    paper_checkpoint_errors,
    record_first_draft_cold_read_checkpoint,
    record_paper_blueprint_review_checkpoint,
)
from shumozizi.paper.paper_review import (
    close_paper_review_finding,
    load_paper_review,
    merge_paper_review_findings,
    paper_review_errors,
    paper_review_status,
)


def main() -> int:
    """执行 PAPER_REVIEW 的导入、关闭、校验或状态查询。"""
    parser = argparse.ArgumentParser(description="管理 PAPER_REVIEW 批量返修 finding")
    parser.add_argument("run_dir", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import", help="导入一次独立审核的最多五项 finding")
    import_parser.add_argument("--input", required=True, help="运行目录内 JSON 相对路径")
    import_parser.add_argument("--source", required=True)

    close_parser = subparsers.add_parser("close", help="登记 finding 的处置状态和关闭证据")
    close_parser.add_argument("--finding-id", required=True)
    close_parser.add_argument(
        "--status",
        choices=("accepted", "repaired", "false_positive", "deferred_with_reason"),
        required=True,
    )
    close_parser.add_argument("--evidence", action="append", required=True)

    subparsers.add_parser("validate", help="校验 finding 字段、组合类型、路径与闭环状态")
    subparsers.add_parser("status", help="输出 P0/P1 是否已经闭合")
    blueprint_parser = subparsers.add_parser(
        "record-blueprint", help="记录写作前独立蓝图审核 checkpoint"
    )
    blueprint_parser.add_argument("--report", required=True)
    blueprint_parser.add_argument("--reviewer-context-id", required=True)
    cold_parser = subparsers.add_parser(
        "record-cold-read", help="记录第一版 PDF 独立冷读 checkpoint"
    )
    cold_parser.add_argument("--report", required=True)
    cold_parser.add_argument("--reviewer-context-id", required=True)
    cold_parser.add_argument("--pdf", default="paper/draft-1.pdf")
    subparsers.add_parser("checkpoints", help="复验候选稿所需的两个论文 checkpoint")
    args = parser.parse_args()
    root = args.run_dir.resolve()
    try:
        if args.command == "import":
            payload = merge_paper_review_findings(
                root, input_path=args.input, source=args.source
            )
        elif args.command == "close":
            payload = close_paper_review_finding(
                root,
                finding_id=args.finding_id,
                status=args.status,
                evidence_of_closure=args.evidence,
            )
        elif args.command == "validate":
            document = load_paper_review(root)
            errors = paper_review_errors(document, run_dir=root)
            payload = {"valid": not errors, "errors": errors}
        elif args.command == "record-blueprint":
            payload = record_paper_blueprint_review_checkpoint(
                root,
                report_path=args.report,
                reviewer_context_id=args.reviewer_context_id,
            )
        elif args.command == "record-cold-read":
            payload = record_first_draft_cold_read_checkpoint(
                root,
                report_path=args.report,
                reviewer_context_id=args.reviewer_context_id,
                pdf_path=args.pdf,
            )
        elif args.command == "checkpoints":
            errors = paper_checkpoint_errors(root, candidate=True)
            payload = {"valid": not errors, "errors": errors}
        else:
            payload = paper_review_status(root)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if args.command in {"validate", "checkpoints"} and not payload["valid"]:
            return 1
        return 0
    except (ContractError, OSError, TypeError, ValueError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
