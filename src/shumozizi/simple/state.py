"""管理 Capability-First v3 的最小运行状态。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.core.repo_root import resolve_repo_root

PHASES = (
    "analysis",
    "capability_route",
    "experiment",
    "scientific_review",
    "visualization",
    "paper",
    "paper_review",
    "verify",
    "final_review",
    "complete",
    "blocked",
)
EXECUTION_MODES = ("production", "exploration")
ALLOWED_PHASE_TRANSITIONS = {
    "analysis": {"analysis", "capability_route", "blocked"},
    "capability_route": {"capability_route", "analysis", "experiment", "blocked"},
    "experiment": {"experiment", "scientific_review", "blocked"},
    "scientific_review": {"scientific_review", "analysis", "experiment", "visualization", "blocked"},
    "visualization": {"visualization", "paper", "blocked"},
    "paper": {"paper", "paper_review", "blocked"},
    "paper_review": {"paper_review", "paper", "verify", "blocked"},
    "verify": {"verify", "final_review", "blocked"},
    "final_review": {
        "final_review",
        "analysis",
        "experiment",
        "paper",
        "complete",
        "blocked",
    },
    "complete": {"complete"},
    # 阻断只允许回到实际生产阶段，避免绕过失败修复直接交付。
    "blocked": {"blocked", "analysis", "capability_route", "experiment"},
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
    # 旧 v3 运行尚未记录用途边界；只在内存中按保守生产语义解释，避免静默改写历史运行。
    payload.setdefault("execution_mode", "production")
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
        "execution_mode",
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
        if next_phase == "experiment":
            from shumozizi.simple.capabilities import require_capability_route

            require_capability_route(run_dir)
        if next_phase == "scientific_review":
            from shumozizi.simple.capabilities import require_independent_oracle_execution

            require_independent_oracle_execution(run_dir)
        # 科学审查结论不写入运行状态，但状态机必须在交付边界消费其可重放摘要。
        if next_phase == "visualization":
            from shumozizi.simple.review import require_paper_generation_allowed

            require_paper_generation_allowed(run_dir)
        if next_phase == "paper":
            from shumozizi.paper.templates import require_materialized_template
            from shumozizi.simple.visualization import require_visualization_complete

            require_visualization_complete(run_dir)
            require_materialized_template(run_dir)
        if next_phase == "paper_review":
            from shumozizi.paper.templates import require_materialized_template

            require_materialized_template(run_dir)
        if next_phase == "verify":
            from shumozizi.simple.review import require_paper_blind_review_allowed

            require_paper_blind_review_allowed(run_dir)
        if next_phase == "final_review":
            from shumozizi.simple.review import require_final_review_allowed

            require_final_review_allowed(run_dir)
        if next_phase == "complete":
            from shumozizi.simple.review import require_completion_allowed

            require_completion_allowed(run_dir)
    if "execution_mode" in changes and changes["execution_mode"] not in EXECUTION_MODES:
        raise ContractError("execution_mode 必须为 production 或 exploration")
    state.update(changes)
    state["revision"] += 1
    state["updated_at"] = utc_now()
    write_simple_state(run_dir, state)
    return state
