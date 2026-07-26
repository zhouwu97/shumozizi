"""获奖论文结构专家库的 baseline 冻结、路由和审计命令行入口。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from shumozizi.core.io import load_json
from shumozizi.knowledge.award_experts import (
    audit_award_expert_route,
    write_award_expert_route,
    write_baseline_freeze,
)


def main() -> None:
    """执行结构专家库的一个明确动作。"""
    parser = argparse.ArgumentParser(description="管理获奖论文结构专家库")
    subparsers = parser.add_subparsers(dest="command", required=True)

    freeze = subparsers.add_parser("freeze", help="写入或修订 baseline 决策快照")
    freeze.add_argument("run_dir", type=Path)
    freeze.add_argument("--input", type=Path, required=True, help="baseline JSON 输入")

    route = subparsers.add_parser("route", help="路由少量结构建议卡；未冻结时仅作建议")
    route.add_argument("run_dir", type=Path)
    route.add_argument("--award-question", choices=("A", "B"), required=True)
    route.add_argument("--phase", choices=("analysis", "experiment", "paper", "paper_review", "verify"), required=True)
    route.add_argument("--topic-key", default="")

    audit = subparsers.add_parser("audit", help="审计当前结构卡路由")
    audit.add_argument("run_dir", type=Path)

    args = parser.parse_args()
    if args.command == "freeze":
        document = write_baseline_freeze(args.run_dir, load_json(args.input))
    elif args.command == "route":
        document = write_award_expert_route(
            args.run_dir,
            award_question=args.award_question,
            phase=args.phase,
            topic_key=args.topic_key,
        )
    else:
        document = audit_award_expert_route(args.run_dir)
    print(json.dumps(document, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
