"""Schema v2 运行初始化命令行薄入口。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.workflow.initialization import initialize_run, safe_run_id


def main() -> int:
    """解析参数并创建完整初始运行。"""
    parser = argparse.ArgumentParser(description="初始化 shumozizi Schema v2 运行")
    parser.add_argument("problem_path")
    parser.add_argument("--run-id")
    parser.add_argument(
        "--mode", choices=("competition", "training", "audit"), default="competition"
    )
    parser.add_argument("--profile", default="generic")
    parser.add_argument("--repo-root")
    args = parser.parse_args()
    repo_root = Path(args.repo_root).resolve() if args.repo_root else resolve_repo_root()
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
    print(
        json.dumps(
            {"run_id": run_dir.name, "run_dir": str(run_dir), "run_schema_version": "2.0"},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
