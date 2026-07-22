"""Schema v2 运行初始化命令行薄入口。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.workflow.initialization import initialize_run, safe_run_id


def main() -> int:
    """解析参数并创建完整初始运行。"""
    parser = argparse.ArgumentParser(description="初始化 shumozizi 运行")
    parser.add_argument("problem_path", nargs="?", help="题面文件或题目目录")
    parser.add_argument("--run-id")
    parser.add_argument(
        "--workflow",
        choices=("legacy-v2", "capability-first-v3"),
        default="legacy-v2",
        help="legacy-v2 保持兼容；capability-first-v3 使用独立轻量运行时",
    )
    parser.add_argument(
        "--mode", choices=("competition", "training", "audit"), default="competition"
    )
    parser.add_argument("--profile", default="generic")
    parser.add_argument("--competition", default="")
    parser.add_argument("--problem-id", default="")
    parser.add_argument("--question", dest="questions", action="append", default=[])
    parser.add_argument("--total-hours", type=float)
    parser.add_argument("--token-soft-cap", type=int)
    parser.add_argument("--repo-root")
    args = parser.parse_args()
    repo_root = Path(args.repo_root).resolve() if args.repo_root else resolve_repo_root()
    if args.workflow == "capability-first-v3":
        if args.problem_path:
            problem = Path(args.problem_path)
            if not problem.is_absolute():
                problem = repo_root / problem
            default_id = f"{problem.stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        else:
            problem = None
            default_id = f"v3-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        run_dir = initialize_simple_run(
            repo_root,
            args.run_id or default_id,
            problem_path=problem,
            competition=args.competition,
            problem_id=args.problem_id,
            required_questions=args.questions,
            total_hours=args.total_hours,
            token_soft_cap=args.token_soft_cap,
        )
        version = "3.0"
    else:
        if not args.problem_path:
            parser.error("legacy-v2 必须提供 problem_path")
        problem = Path(args.problem_path)
        if not problem.is_absolute():
            problem = repo_root / problem
        default_id = f"{problem.stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        run_dir = initialize_run(
            repo_root,
            problem,
            safe_run_id(args.run_id or default_id),
            mode=args.mode,
            profile_id=args.profile,
        )
        version = "2.0"
    print(
        json.dumps(
            {"run_id": run_dir.name, "run_dir": str(run_dir), "run_schema_version": version},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
