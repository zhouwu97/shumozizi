"""初始化一次文件状态驱动的数学建模运行。"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="初始化 MathModelAgent 运行目录")
    parser.add_argument("problem_path", help="题面文件或题目目录")
    parser.add_argument("--run-id", help="运行 ID；默认由题目名和时间生成")
    parser.add_argument(
        "--mode",
        choices=("competition", "training", "audit"),
        default="competition",
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[2]),
        help="仓库根目录",
    )
    return parser.parse_args()


def safe_run_id(value: str) -> str:
    """把运行 ID 规范化为安全目录名。"""
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    if not normalized:
        raise ValueError("run_id 不能为空")
    return normalized


def atomic_json(path: Path, payload: dict) -> None:
    """原子写入 JSON，避免中断留下半文件。"""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    """创建运行目录、初始状态与空结果注册表。"""
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    problem_path = Path(args.problem_path)
    if not problem_path.is_absolute():
        problem_path = (repo_root / problem_path).resolve()
    if not problem_path.exists():
        raise FileNotFoundError(f"题面路径不存在: {problem_path}")

    default_id = f"{problem_path.stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    run_id = safe_run_id(args.run_id or default_id)
    run_dir = (repo_root / "runs" / run_id).resolve()
    runs_root = (repo_root / "runs").resolve()
    if runs_root not in run_dir.parents:
        raise ValueError("运行目录越过 runs/ 边界")
    if run_dir.exists() and any(run_dir.iterdir()):
        raise FileExistsError(f"运行目录已存在且非空: {run_dir}")

    for name in (
        "brief",
        "reports",
        "code",
        "results",
        "figures",
        "paper/sections",
        "review",
        "logs",
    ):
        (run_dir / name).mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).isoformat()
    try:
        source = str(problem_path.relative_to(repo_root))
    except ValueError:
        source = str(problem_path)
    state = {
        "schema_version": "1.0",
        "run_id": run_id,
        "problem_source": source,
        "mode": args.mode,
        "status": "NEW",
        "completed_stages": [],
        "active_stage": "ingest",
        "route_locked": False,
        "paper_ready": False,
        "question_progress": {},
        "artifacts": {},
        "last_updated_by": "init_run.py",
        "updated_at": now,
        "history": [
            {
                "status": "NEW",
                "timestamp": now,
                "actor": "init_run.py",
                "note": "运行目录已初始化",
            }
        ],
    }
    atomic_json(run_dir / "state.json", state)
    atomic_json(
        run_dir / "results" / "result_registry.json",
        {"schema_version": "1.0", "run_id": run_id, "results": []},
    )
    atomic_json(
        run_dir / "brief" / "ROUTE_LOCK.template.json",
        {
            "approved": False,
            "selected_route_id": "",
            "problem_interpretation": "",
            "primary_route": "",
            "fallback_route": "",
            "required_baselines": [],
            "innovation": {
                "major_per_question": 1,
                "minor_per_question": 1,
                "claims": [],
            },
            "validation": [],
            "resource_limits": {
                "max_main_experiment_cycles_per_question": 3,
                "max_web_searches": 5,
                "max_full_self_reviews": 1,
                "route_drift_budget_ratio": 0.3,
            },
            "approved_by": "",
            "approved_at": "",
        },
    )
    print(json.dumps({"run_id": run_id, "run_dir": str(run_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
