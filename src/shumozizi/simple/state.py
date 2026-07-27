"""管理 Competition-First v3.1/v3.2 的最小运行状态。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.core.repo_root import resolve_repo_root

PHASES = (
    "analysis",
    "experiment",
    "paper",
    "paper_review",
    "verify",
    "complete",
    "blocked",
)
LEGACY_PHASE_MAPPINGS = {
    "capability_route": "analysis",
    "scientific_review": "experiment",
    "visualization": "experiment",
    "final_review": "verify",
}
EXECUTION_MODES = ("production", "exploration")
ALLOWED_PHASE_TRANSITIONS = {
    "analysis": {"analysis", "experiment", "blocked"},
    "experiment": {"experiment", "analysis", "paper", "blocked"},
    "paper": {"paper", "experiment", "paper_review", "blocked"},
    "paper_review": {"paper_review", "paper", "verify", "blocked"},
    "verify": {"verify", "paper", "experiment", "complete", "blocked"},
    "complete": {"complete"},
    # 阻断只允许回到实际生产阶段，避免绕过失败修复直接交付。
    "blocked": {"blocked", "analysis", "experiment", "paper"},
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


def is_competition_first_state(payload: dict[str, Any]) -> bool:
    """判断状态是否使用 Competition-First v3 主链。

    Args:
        payload: 已读取或待校验的状态对象。

    Returns:
        当状态属于 v3.1 或 v3.2 时返回 ``True``。
    """
    return payload.get("schema_version") in {"3.1", "3.2"}


def is_competition_first_v32_state(payload: dict[str, Any]) -> bool:
    """判断状态是否启用 v3.2 的建模单元和 LaTeX 强制协议。

    Args:
        payload: 已读取或待校验的状态对象。

    Returns:
        当状态属于 Competition-First v3.2 时返回 ``True``。
    """
    return payload.get("schema_version") == "3.2"


def _map_legacy_state(payload: dict[str, Any]) -> dict[str, Any]:
    """在内存中映射旧 v3 阶段，不提前改写历史运行文件。

    Args:
        payload: 从 ``state/run.json`` 读取的原始状态。

    Returns:
        可以按 v3.1 规则消费的状态副本。
    """
    if payload.get("schema_version") != "3.0":
        return payload
    legacy_phase = str(payload.get("phase", "analysis"))
    mapped = dict(payload)
    mapped["schema_version"] = "3.1"
    mapped["workflow"] = "competition-first-v3.1"
    mapped["legacy_phase"] = legacy_phase
    mapped["phase"] = LEGACY_PHASE_MAPPINGS.get(legacy_phase, legacy_phase)
    return mapped


def _record_migration(run_dir: Path, state: dict[str, Any]) -> None:
    """在首次显式保存 v3.1 状态时记录旧阶段映射。

    Args:
        run_dir: 当前运行目录。
        state: 即将写入的 v3.1 状态。
    """
    legacy_phase = state.get("legacy_phase")
    if not isinstance(legacy_phase, str):
        return
    path = run_dir / "state" / "migrations.json"
    if path.is_file():
        return
    atomic_json(
        path,
        {
            "from_schema_version": "3.0",
            "to_schema_version": "3.1",
            "original_phase": legacy_phase,
            "mapped_phase": LEGACY_PHASE_MAPPINGS.get(legacy_phase, legacy_phase),
            "migrated_at": utc_now(),
        },
    )


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
    mapped = _map_legacy_state(payload)
    require_simple_state(mapped)
    return mapped


def write_simple_state(run_dir: Path, payload: dict[str, Any]) -> None:
    """原子写入已校验的最小状态。

    Args:
        run_dir: v3 运行目录。
        payload: 新状态对象。

    Raises:
        ContractError: 状态不符合 v3 协议。
    """
    require_simple_state(payload)
    _record_migration(run_dir, payload)
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
            from shumozizi.simple.modeling_units import require_v32_modeling_plan
            from shumozizi.simple.objective_consequences import (
                require_objective_candidate_plan,
            )
            from shumozizi.simple.objective_semantics import objective_semantics_review_required
            from shumozizi.simple.review import require_objective_semantics_review

            require_objective_candidate_plan(run_dir)
            require_v32_modeling_plan(run_dir)
            if objective_semantics_review_required(run_dir):
                require_objective_semantics_review(run_dir)
        if next_phase == "paper":
            if is_competition_first_v32_state(state) and state["execution_mode"] == "production":
                from scripts.qa.metric_ledger import require_v32_metric_ledger_for_paper

                require_v32_metric_ledger_for_paper(run_dir)
            from shumozizi.paper.templates import require_materialized_template
            from shumozizi.simple.modeling_units import require_v32_experiment_evidence
            from shumozizi.simple.objective_consequences import (
                require_objective_consequences,
            )
            from shumozizi.simple.review import require_paper_generation_allowed

            require_paper_generation_allowed(run_dir)
            require_objective_consequences(run_dir)
            require_v32_experiment_evidence(run_dir)
            require_materialized_template(run_dir)
        if next_phase == "paper_review":
            from shumozizi.paper.templates import require_materialized_template

            require_materialized_template(run_dir)
            if is_competition_first_v32_state(state) and (run_dir / "state/delivery-control.json").is_file():
                from shumozizi.simple.delivery import require_current_pdf_milestone

                require_current_pdf_milestone(run_dir, "candidate")
        if next_phase == "verify":
            from shumozizi.simple.review import require_paper_blind_review_allowed

            require_paper_blind_review_allowed(run_dir)
            if is_competition_first_v32_state(state):
                from shumozizi.knowledge.external_discussion import (
                    require_web_paper_audit_release,
                    validate_web_paper_audit_if_present,
                )

                # 网页审核是可选增强：有文件时全量复验，无文件时直接放行。
                # 使用 require_web_paper_audit_release 会在无审核文件时阻断终检，
                # 导致纯 PDF 盲评路径无法进入 verify。
                validate_web_paper_audit_if_present(run_dir)
                if (run_dir / "state/delivery-control.json").is_file():
                    from shumozizi.simple.delivery import web_review_required

                    if web_review_required(run_dir):
                        require_web_paper_audit_release(run_dir)
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
