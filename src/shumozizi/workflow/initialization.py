"""初始化 Schema v2 运行目录。"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json
from shumozizi.profiles.lock import create_run_config_lock

RUN_DIRECTORIES = (
    "brief",
    "reports",
    "code",
    "results/candidates",
    "results/metric_specs",
    "results/sealed",
    "results/revocations",
    "experiments/plans",
    "claims",
    "figures",
    "paper/sections",
    "paper/generated",
    "review",
    "logs",
    "executions/manifests",
    "config",
)


def utc_now() -> str:
    """返回 RFC 3339 UTC 时间。"""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def safe_run_id(value: str) -> str:
    """把运行 ID 规范化为安全目录名。"""
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    if not normalized:
        raise ContractError("run_id 不能为空")
    return normalized


def initialize_run(
    repo_root: Path,
    problem_path: Path,
    run_id: str,
    *,
    mode: str = "competition",
    profile_id: str = "generic",
) -> Path:
    """创建完整的 Schema v2 初始运行。

    Args:
        repo_root: 目标仓库根。
        problem_path: 题面文件或目录。
        run_id: 运行 ID。
        mode: competition、training 或 audit。
        profile_id: 初始化时唯一允许选择的 Profile。

    Returns:
        新运行目录。
    """
    root = repo_root.resolve()
    problem = problem_path.resolve()
    if not problem.exists():
        raise FileNotFoundError(f"题面路径不存在: {problem}")
    if mode not in {"competition", "training", "audit"}:
        raise ContractError(f"未知运行模式: {mode}")
    identifier = safe_run_id(run_id)
    runs_root = (root / "runs").resolve()
    run_dir = (runs_root / identifier).resolve()
    if runs_root not in run_dir.parents:
        raise ContractError("运行目录越过 runs/ 边界")
    if run_dir.exists() and any(run_dir.iterdir()):
        raise FileExistsError(f"运行目录已存在且非空: {run_dir}")
    for relative in RUN_DIRECTORIES:
        (run_dir / relative).mkdir(parents=True, exist_ok=True)
    now = utc_now()
    try:
        source = problem.relative_to(root).as_posix()
    except ValueError:
        source = str(problem)
    state: dict[str, Any] = {
        "schema_name": "workflow_state",
        "schema_version": "2.0",
        "run_schema_version": "2.0",
        "run_id": identifier,
        "problem_source": source,
        "mode": mode,
        "status": "NEW",
        "revision": 0,
        "completed_stages": [],
        "active_stage": "ingest",
        "route_locked": False,
        "paper_ready": False,
        "question_progress": {},
        "review_gates": {
            gate: {"status": "pending", "receipt": None}
            for gate in (
                "R1_MODELING",
                "R3_PAPER_LOGIC",
                "R4_FORMAT_VISUAL",
                "R5_STANDARD_FINAL",
                "J0_FINAL_BLIND_JUDGE",
            )
        },
        "artifacts": {},
        "last_updated_by": "init_run.py",
        "updated_at": now,
        "history": [
            {
                "from_status": None,
                "status": "NEW",
                "event": "RUN_INITIALIZED",
                "timestamp": now,
                "actor": {"actor_id": "init_run.py", "actor_type": "system"},
                "artifact_refs": [],
                "note": "运行目录已初始化",
            }
        ],
    }
    atomic_json(run_dir / "state.json", state)
    atomic_json(
        run_dir / "results" / "result_registry.json",
        {
            "schema_name": "result_registry",
            "schema_version": "2.0",
            "run_id": identifier,
            "results": [],
        },
    )
    create_run_config_lock(root, run_dir, problem, profile_id=profile_id)
    atomic_json(
        run_dir / "brief" / "ROUTE_LOCK.template.json",
        {
            "schema_name": "route_lock",
            "schema_version": "2.0",
            "approved": False,
            "selected_route_id": "",
            "instructions": "必须通过人工批准回执物化 ROUTE_LOCK.json；不得直接编辑此模板为批准状态。",
        },
    )
    return run_dir
