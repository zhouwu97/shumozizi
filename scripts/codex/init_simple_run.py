"""初始化 Capability-First v3 运行的命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.simple.initialization import initialize_simple_run


def main() -> int:
    """解析参数并创建 v3 运行目录。

    Returns:
        成功时为零。
    """
    parser = argparse.ArgumentParser(description="初始化 Capability-First v3 数学建模运行")
    parser.add_argument("problem_path", nargs="?", help="可选的题面文件或题目目录")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--competition", default="")
    parser.add_argument("--problem-id", default="")
    parser.add_argument("--question", dest="questions", action="append", default=[])
    parser.add_argument("--total-hours", type=float)
    parser.add_argument("--token-soft-cap", type=int)
    parser.add_argument("--repo-root")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve() if args.repo_root else resolve_repo_root()
    problem = Path(args.problem_path).resolve() if args.problem_path else None
    run_dir = initialize_simple_run(
        root,
        args.run_id,
        problem_path=problem,
        competition=args.competition,
        problem_id=args.problem_id,
        required_questions=args.questions,
        total_hours=args.total_hours,
        token_soft_cap=args.token_soft_cap,
    )
    print(json.dumps({"run_id": run_dir.name, "run_dir": str(run_dir), "run_schema_version": "3.0"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
