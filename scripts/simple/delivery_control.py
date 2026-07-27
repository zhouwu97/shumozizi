"""操作 Competition-First v3.2 的交付计划、工时账本和推进器。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from shumozizi.core.io import ContractError
from shumozizi.simple.delivery import (
    advance_delivery_phase,
    approve_workflow_p0_patch,
    freeze_pdf_milestone,
    next_required_action,
    record_work_session,
    start_work_session,
    stop_work_session,
    verify_workflow_source_lock,
    work_log_summary,
)


def main() -> int:
    """执行一个受控的交付管理动作。"""
    parser = argparse.ArgumentParser(description="管理 Competition-First v3.2 交付节奏")
    subparsers = parser.add_subparsers(dest="command", required=True)
    status = subparsers.add_parser("status", help="显示唯一下一动作、范围和工时")
    status.add_argument("run_dir", type=Path)
    log = subparsers.add_parser("log-work", help="登记不可重叠的真实工作时段")
    log.add_argument("run_dir", type=Path)
    log.add_argument("--category", required=True)
    log.add_argument("--started-at", required=True)
    log.add_argument("--finished-at", required=True)
    log.add_argument("--summary", required=True)
    log.add_argument("--blocking-delivery-repair", action="store_true")
    start = subparsers.add_parser("start-work", help="开始唯一活动工时段")
    start.add_argument("run_dir", type=Path)
    start.add_argument("--category", required=True)
    start.add_argument("--started-at")
    stop = subparsers.add_parser("stop-work", help="关闭活动工时段并登记产出")
    stop.add_argument("run_dir", type=Path)
    stop.add_argument("--summary", required=True)
    stop.add_argument("--finished-at")
    stop.add_argument("--blocking-delivery-repair", action="store_true")
    freeze = subparsers.add_parser("freeze-pdf", help="冻结第一版或候选 PDF")
    freeze.add_argument("run_dir", type=Path)
    freeze.add_argument("milestone", choices=("first_reviewable", "candidate"))
    patch = subparsers.add_parser("approve-p0-patch", help="登记阻断当前交付的唯一源码修补")
    patch.add_argument("run_dir", type=Path)
    patch.add_argument("--reason", required=True)
    source = subparsers.add_parser("verify-source-lock", help="复验运行期源码锁")
    source.add_argument("run_dir", type=Path)
    advance = subparsers.add_parser("advance", help="在真实门禁通过时自动推进一阶段")
    advance.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "status":
            document = next_required_action(args.run_dir)
        elif args.command == "log-work":
            document = record_work_session(
                args.run_dir,
                category=args.category,
                started_at=args.started_at,
                finished_at=args.finished_at,
                summary=args.summary,
                blocking_delivery_repair=args.blocking_delivery_repair,
            )
        elif args.command == "start-work":
            document = start_work_session(
                args.run_dir, category=args.category, started_at=args.started_at
            )
        elif args.command == "stop-work":
            document = stop_work_session(
                args.run_dir,
                summary=args.summary,
                finished_at=args.finished_at,
                blocking_delivery_repair=args.blocking_delivery_repair,
            )
        elif args.command == "freeze-pdf":
            document = freeze_pdf_milestone(args.run_dir, args.milestone)
        elif args.command == "approve-p0-patch":
            document = approve_workflow_p0_patch(args.run_dir, reason=args.reason)
        elif args.command == "verify-source-lock":
            document = {"source_lock": verify_workflow_source_lock(args.run_dir), "work_log": work_log_summary(args.run_dir)}
        else:
            document = advance_delivery_phase(args.run_dir)
    except ContractError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(document, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
