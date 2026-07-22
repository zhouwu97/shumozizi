"""初始化不依赖 legacy-v2 的 Capability-First v3 运行目录。"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json
from shumozizi.simple.state import require_simple_state, utc_now

SIMPLE_DIRECTORIES = (
    "problem/attachments",
    "state",
    "reports",
    "code",
    "results/raw",
    "figures",
    "paper/sections",
    "qa",
)


def safe_simple_run_id(value: str) -> str:
    """将运行 ID 规整为不会逃逸 ``runs/`` 的目录名。

    Args:
        value: 用户提供的运行 ID。

    Returns:
        仅由安全字符构成的运行 ID。

    Raises:
        ContractError: 规整后为空。
    """
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    if not normalized:
        raise ContractError("run_id 不能为空")
    return normalized


def _copy_problem(problem_path: Path, run_dir: Path) -> dict[str, str]:
    """复制只读题面和附件，避免后续工作修改原始输入。

    Args:
        problem_path: 题面文件或包含题面、附件的目录。
        run_dir: 新建 v3 运行目录。

    Returns:
        与输入有关的产物路径。

    Raises:
        FileNotFoundError: 输入题面不存在。
    """
    source = problem_path.resolve()
    if not source.exists():
        raise FileNotFoundError(f"题面路径不存在: {source}")
    problem_dir = run_dir / "problem"
    artifacts: dict[str, str] = {}
    if source.is_file():
        target = problem_dir / f"statement{source.suffix or '.md'}"
        shutil.copy2(source, target)
        artifacts["statement"] = target.relative_to(run_dir).as_posix()
        return artifacts

    candidates = sorted(
        path
        for path in source.iterdir()
        if path.is_file() and path.suffix.lower() in {".md", ".txt", ".pdf", ".docx"}
    )
    statement = next(
        (path for path in candidates if path.stem.lower() in {"statement", "problem", "题目"}),
        candidates[0] if candidates else None,
    )
    if statement is not None:
        target = problem_dir / f"statement{statement.suffix}"
        shutil.copy2(statement, target)
        artifacts["statement"] = target.relative_to(run_dir).as_posix()
    attachments = problem_dir / "attachments"
    for item in source.rglob("*"):
        if not item.is_file() or item == statement:
            continue
        relative = item.relative_to(source)
        target = attachments / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
    return artifacts


def initialize_simple_run(
    repo_root: Path,
    run_id: str,
    *,
    problem_path: Path | None = None,
    competition: str = "",
    problem_id: str = "",
    required_questions: list[str] | None = None,
    total_hours: float | None = None,
    token_soft_cap: int | None = None,
) -> Path:
    """创建可独立恢复的 v3 运行目录。

    Args:
        repo_root: 项目仓库根目录。
        run_id: 运行 ID。
        problem_path: 可选的题面文件或目录。
        competition: 竞赛类型或名称。
        problem_id: 题目编号。
        required_questions: 已知必答问题列表。
        total_hours: 可选的总时间预算。
        token_soft_cap: 可选的 token 软上限。

    Returns:
        新建运行目录。

    Raises:
        ContractError: 运行目录逃逸或状态不合法。
        FileExistsError: 指定运行目录已经包含内容。
    """
    root = repo_root.resolve()
    identifier = safe_simple_run_id(run_id)
    runs_root = (root / "runs").resolve()
    run_dir = (runs_root / identifier).resolve()
    if runs_root not in run_dir.parents:
        raise ContractError("运行目录越过 runs/ 边界")
    if run_dir.exists() and any(run_dir.iterdir()):
        raise FileExistsError(f"运行目录已存在且非空: {run_dir}")
    for relative in SIMPLE_DIRECTORIES:
        (run_dir / relative).mkdir(parents=True, exist_ok=True)

    artifacts = _copy_problem(problem_path, run_dir) if problem_path else {}
    now = utc_now()
    state: dict[str, Any] = {
        "schema_version": "3.0",
        "run_id": identifier,
        "workflow": "capability-first-v3",
        "phase": "analysis",
        "revision": 0,
        "competition": competition,
        "problem_id": problem_id,
        "required_questions": required_questions or [],
        "current_question": None,
        "completed_questions": [],
        "selected_route": None,
        "fallback_route": None,
        "artifacts": artifacts,
        "time_budget": {"total_hours": total_hours, "remaining_hours": total_hours},
        "token_budget": {"soft_cap": token_soft_cap, "used_estimate": None},
        "updated_at": now,
    }
    require_simple_state(state)
    atomic_json(run_dir / "state" / "run.json", state)
    atomic_json(
        run_dir / "results" / "index.json",
        {"schema_version": "1.0", "run_id": identifier, "results": []},
    )
    atomic_json(
        run_dir / "figures" / "index.json",
        {"schema_version": "1.0", "run_id": identifier, "figures": []},
    )
    (run_dir / "state" / "DECISIONS.md").write_text(
        "# 决策记录\n\n"
        "## 题意解释\n- 待补充。\n\n"
        "## 路线选择\n- 主路线：待确定。\n- fallback：待确定。\n- 放弃路线及原因：待确定。\n",
        encoding="utf-8",
        newline="\n",
    )
    return run_dir
