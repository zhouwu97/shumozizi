"""管理 Capability-First v3 的最小运行状态。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.core.repo_root import resolve_repo_root

PHASES = ("analysis", "experiment", "paper", "verify", "complete", "blocked")
ALLOWED_PHASE_TRANSITIONS = {
    "analysis": {"analysis", "experiment", "blocked"},
    "experiment": {"experiment", "paper", "blocked"},
    "paper": {"paper", "verify", "blocked"},
    "verify": {"verify", "complete", "blocked"},
    "complete": {"complete"},
    # 阻断只允许回到实际生产阶段，避免绕过失败修复直接交付。
    "blocked": {"blocked", "analysis", "experiment"},
}
STATE_PATH = Path("state/run.json")


def utc_now() -> str:
    """返回 RFC 3339 格式的 UTC 时间。

    Returns:
        带 ``Z`` 后缀的 UTC 时间字符串。
    """
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _schema() -> dict[str, Any]:
    """读取 v3 状态 Schema。

    Returns:
        JSON Schema 对象。
    """
    return load_json(resolve_repo_root(Path(__file__)) / "schemas/simple_run_state.schema.json")


def validate_simple_state(payload: dict[str, Any]) -> list[str]:
    """校验最小状态对象。

    Args:
        payload: 待校验状态。

    Returns:
        全部可读的校验错误；为空表示通过。
    """
    validator = Draft202012Validator(_schema(), format_checker=FormatChecker())
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    ]


def require_simple_state(payload: dict[str, Any]) -> None:
    """确保状态符合 v3 Schema。

    Args:
        payload: 待校验状态。

    Raises:
        ContractError: 状态字段缺失或不合法。
    """
    errors = validate_simple_state(payload)
    if errors:
        raise ContractError("; ".join(errors))


def read_simple_state(run_dir: Path) -> dict[str, Any]:
    """读取并校验指定运行的最小状态。

    Args:
        run_dir: v3 运行目录。

    Returns:
        已校验的状态对象。

    Raises:
        ContractError: 状态文件不符合 v3 协议。
    """
    payload = load_json(run_dir / STATE_PATH)
    require_simple_state(payload)
    return payload


def write_simple_state(run_dir: Path, payload: dict[str, Any]) -> None:
    """原子写入已校验的最小状态。

    Args:
        run_dir: v3 运行目录。
        payload: 新状态对象。

    Raises:
        ContractError: 状态不符合 v3 协议。
    """
    require_simple_state(payload)
    atomic_json(run_dir / STATE_PATH, payload)


def update_simple_state(run_dir: Path, **changes: Any) -> dict[str, Any]:
    """以一次修订更新允许变更的最小状态字段。

    Args:
        run_dir: v3 运行目录。
        **changes: 允许更新的状态字段。

    Returns:
        已写入的新状态。

    Raises:
        ContractError: 请求尝试改写受保护字段或给出非法阶段。
    """
    allowed = {
        "phase",
        "competition",
        "problem_id",
        "required_questions",
        "current_question",
        "completed_questions",
        "selected_route",
        "fallback_route",
        "artifacts",
        "time_budget",
        "token_budget",
    }
    unknown = sorted(set(changes) - allowed)
    if unknown:
        raise ContractError(f"v3 状态不允许更新字段: {', '.join(unknown)}")
    state = read_simple_state(run_dir)
    if "phase" in changes:
        next_phase = changes["phase"]
        if next_phase not in PHASES:
            raise ContractError(f"未知 v3 阶段: {next_phase}")
        if next_phase not in ALLOWED_PHASE_TRANSITIONS[state["phase"]]:
            raise ContractError(f"v3 状态不允许从 {state['phase']} 直接进入 {next_phase}")
    state.update(changes)
    state["revision"] += 1
    state["updated_at"] = utc_now()
    write_simple_state(run_dir, state)
    return state
