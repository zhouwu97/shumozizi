"""管理 Competition-First v3.2 的交付节奏、真实工时与运行期范围。"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.simple.state import paper_revision_status, read_simple_state, utc_now

DELIVERY_CONTROL_PATH = Path("state/delivery-control.json")
WORK_LOG_PATH = Path("state/work-log.json")
PDF_MILESTONES_PATH = Path("state/pdf-milestones.json")
DEFAULT_TOTAL_MINUTES = 720.0
DEFAULT_PROTOCOL_PATCH_BUDGET_MINUTES = 30.0
DEFAULT_PROTOCOL_OVERHEAD_RATIO_LIMIT = 0.10
WORK_CATEGORIES = frozenset(
    {
        "problem_analysis",
        "experiment_search",
        "experiment_validation",
        "workflow_protocol",
        "executor_debugging",
        "paper_writing",
        "figure_generation",
        "external_review",
        "verification",
    }
)
_PROTOCOL_CATEGORIES = frozenset({"workflow_protocol", "executor_debugging"})
_LOCK_ROOTS = (
    Path("src/shumozizi"),
    Path("scripts"),
    Path("schemas"),
    Path("tools"),
    Path(".agents/skills"),
)
_IGNORED_SOURCE_SUFFIXES = {".pyc", ".pyo"}
_DELIVERY_FREEZE_ACTIONS = [
    "add_new_route",
    "create_extra_review_task",
    "modify_workflow_schema",
    "migrate_protocol",
    "expand_review_protocol",
    "refactor_executor",
]
_REVIEW_REPAIR_ACTIONS = frozenset({"add_experiment_plan", "expand_figure_plan"})
_DELIVERY_ALLOWED_ACTIONS = frozenset(
    {
        "paper_write",
        "figure_fix",
        "compile_pdf",
        "review_fix",
        "mechanical_verify",
        "blocking_delivery_repair",
        "record_existing_experiment",
    }
)


def _parse_time(value: str | datetime) -> datetime:
    """将 RFC 3339 字符串或 datetime 规整为 UTC 时间。"""
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ContractError("时间必须包含时区")
    return parsed.astimezone(UTC)


def _source_manifest(repo_root: Path) -> dict[str, str]:
    """计算运行期间禁止静默修改的工作流源码清单。"""
    root = repo_root.resolve()
    manifest: dict[str, str] = {}
    for relative_root in _LOCK_ROOTS:
        source_root = root / relative_root
        if not source_root.is_dir():
            continue
        for path in sorted(item for item in source_root.rglob("*") if item.is_file()):
            if "__pycache__" in path.parts or path.suffix.lower() in _IGNORED_SOURCE_SUFFIXES:
                continue
            manifest[path.relative_to(root).as_posix()] = sha256_file(path)
    return manifest


def _delivery_plan(total_minutes: float) -> dict[str, float]:
    """按总赛程生成单调、可缩放的交付时间表。"""
    return {
        "total_minutes": total_minutes,
        "analysis_soft_limit": total_minutes / 8,
        "experiment_soft_limit": total_minutes * 5 / 12,
        "first_reviewable_pdf_deadline": total_minutes * 2 / 3,
        "candidate_pdf_deadline": total_minutes * 5 / 6,
        "blind_review_deadline": total_minutes * 11 / 12,
        "final_deadline": total_minutes,
    }


def initialize_delivery_control(
    run_dir: Path,
    repo_root: Path,
    *,
    total_hours: float | None,
    require_web_review: bool = False,
    started_at: str | None = None,
) -> dict[str, Any]:
    """为新 v3.2 运行冻结交付计划、源码基线和工时账本。

    Args:
        run_dir: 新建运行目录。
        repo_root: 工作流仓库根目录。
        total_hours: 比赛总时长；未提供时使用 12 小时可覆盖默认值。
        require_web_review: 是否把网页版 GPT 人工新对话设为交付必需项。
        started_at: 可选的确定性开始时间，主要用于迁移和测试。

    Returns:
        已写入的交付控制对象。
    """
    if total_hours is not None and total_hours <= 0:
        raise ContractError("交付总时长必须大于零")
    total_minutes = float(total_hours * 60 if total_hours is not None else DEFAULT_TOTAL_MINUTES)
    control = {
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "started_at": started_at or utc_now(),
        "delivery_plan": _delivery_plan(total_minutes),
        "workflow_source_locked": True,
        "workflow_source_manifest": _source_manifest(repo_root),
        "protocol_patch_budget_minutes": DEFAULT_PROTOCOL_PATCH_BUDGET_MINUTES,
        "protocol_overhead_ratio_limit": DEFAULT_PROTOCOL_OVERHEAD_RATIO_LIMIT,
        "web_review": {
            "required": require_web_review,
            "provider": "chatgpt_web",
            "creation_mode": "manual_new_chat",
        },
    }
    atomic_json(run_dir / DELIVERY_CONTROL_PATH, control)
    atomic_json(
        run_dir / WORK_LOG_PATH,
        {
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "entries": [],
            "active_session": None,
            "phase_sessions": [
                {
                    "phase": "analysis",
                    "started_at": control["started_at"],
                    "finished_at": None,
                }
            ],
        },
    )
    atomic_json(
        run_dir / PDF_MILESTONES_PATH,
        {"schema_version": "1.0", "run_id": run_dir.name, "milestones": {}},
    )
    return control


def _control(run_dir: Path) -> dict[str, Any]:
    """读取并执行交付控制的最小结构校验。"""
    control = load_json(run_dir / DELIVERY_CONTROL_PATH)
    if control.get("schema_version") != "1.0" or control.get("run_id") != run_dir.name:
        raise ContractError("delivery-control 的 schema_version 或 run_id 不匹配")
    _parse_time(control.get("started_at", ""))
    plan = control.get("delivery_plan")
    if not isinstance(plan, dict):
        raise ContractError("delivery-control 缺少 delivery_plan")
    deadlines = [
        plan.get("analysis_soft_limit"),
        plan.get("experiment_soft_limit"),
        plan.get("first_reviewable_pdf_deadline"),
        plan.get("candidate_pdf_deadline"),
        plan.get("blind_review_deadline"),
        plan.get("final_deadline"),
    ]
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in deadlines):
        raise ContractError("delivery_plan 的截止点必须是分钟数")
    if deadlines != sorted(deadlines) or deadlines[-1] != plan.get("total_minutes"):
        raise ContractError("delivery_plan 截止点必须单调且 final_deadline 等于 total_minutes")
    return control


def require_delivery_action_allowed(
    run_dir: Path,
    action_kind: str,
    *,
    now: str | datetime | None = None,
    review_findings: list[str] | None = None,
) -> None:
    """控制首版后的范围冻结，并保留评审驱动的有限返修窗口。

    Args:
        run_dir: 当前 v3.2 运行目录。
        action_kind: 调用入口准备执行的语义动作。
        now: 可选的确定性当前时间，主要供测试和恢复工具使用。
        review_findings: 新实验或新图所回应的评审发现；首版后必填。

    Raises:
        ContractError: 截止后请求了禁止动作，或动作类型不属于公开许可表。
    """
    if not isinstance(action_kind, str) or not action_kind.strip():
        raise ContractError("delivery action_kind 必须是非空文本")
    action = action_kind.strip()
    known = (
        set(_DELIVERY_FREEZE_ACTIONS)
        | set(_DELIVERY_ALLOWED_ACTIONS)
        | set(_REVIEW_REPAIR_ACTIONS)
    )
    if action not in known:
        raise ContractError(f"未知 delivery action_kind: {action}")
    control = _control(run_dir)
    current = _parse_time(now or utc_now())
    started = _parse_time(control["started_at"])
    elapsed = max(0.0, (current - started).total_seconds() / 60)
    cutoff = float(control["delivery_plan"]["first_reviewable_pdf_deadline"])
    first_reviewable_frozen = _milestone_current(run_dir, "first_reviewable")
    scope_frozen = elapsed >= cutoff or first_reviewable_frozen
    if scope_frozen and action in _DELIVERY_FREEZE_ACTIONS:
        raise ContractError(
            f"交付首版截止后禁止动作 {action}；路线、协议、审核范围和执行器必须冻结"
        )
    if not scope_frozen or action not in _REVIEW_REPAIR_ACTIONS:
        return
    if _milestone_current(run_dir, "candidate"):
        raise ContractError(f"候选 PDF 已冻结，禁止继续执行 {action} 新增科学内容")
    if not first_reviewable_frozen:
        raise ContractError(
            f"首版截止后必须先冻结 first_reviewable，再以评审发现驱动 {action}"
        )
    findings = review_findings or []
    if not 1 <= len(findings) <= 5 or any(
        not isinstance(item, str) or len(item.strip()) < 12 for item in findings
    ):
        raise ContractError(
            f"首版后的 {action} 必须为每个新增项提供 12 字以上 review_finding，"
            "且单次最多新增 5 项"
        )


def record_work_session(
    run_dir: Path,
    *,
    category: str,
    started_at: str,
    finished_at: str,
    summary: str,
    blocking_delivery_repair: bool = False,
) -> dict[str, Any]:
    """原子登记一段真实工作时间并拒绝重叠或模糊分类。

    Args:
        run_dir: 当前运行目录。
        category: 九类工作之一。
        started_at: 工作开始时间。
        finished_at: 工作结束时间。
        summary: 该时段的实际产出。
        blocking_delivery_repair: 协议工作是否仅用于修复当前交付 P0。

    Returns:
        新增的账本条目。
    """
    if category not in WORK_CATEGORIES:
        raise ContractError(f"work_log category 不受支持: {category}")
    if not summary.strip():
        raise ContractError("work_log summary 不能为空")
    start = _parse_time(started_at)
    finish = _parse_time(finished_at)
    if finish <= start:
        raise ContractError("work_log finished_at 必须晚于 started_at")
    document = load_json(run_dir / WORK_LOG_PATH)
    if document.get("schema_version") != "1.0" or document.get("run_id") != run_dir.name:
        raise ContractError("work-log 的 schema_version 或 run_id 不匹配")
    for existing in document.get("entries", []):
        old_start = _parse_time(existing["started_at"])
        old_finish = _parse_time(existing["finished_at"])
        if start < old_finish and finish > old_start:
            raise ContractError("work_log 时间区间不得重叠")
    entry = {
        "category": category,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_minutes": (finish - start).total_seconds() / 60,
        "summary": summary.strip(),
        "blocking_delivery_repair": bool(blocking_delivery_repair),
    }
    document.setdefault("entries", []).append(entry)
    document["entries"].sort(key=lambda item: item["started_at"])
    atomic_json(run_dir / WORK_LOG_PATH, document)
    return entry


def start_work_session(
    run_dir: Path, *, category: str, started_at: str | None = None
) -> dict[str, Any]:
    """开始唯一活动工时段，避免代理工作后忘记补记起点。

    Args:
        run_dir: 当前运行目录。
        category: 九类真实工作之一。
        started_at: 可选的显式开始时间。

    Returns:
        已持久化的活动会话。
    """
    if category not in WORK_CATEGORIES:
        raise ContractError(f"work_log category 不受支持: {category}")
    document = load_json(run_dir / WORK_LOG_PATH)
    if document.get("active_session") is not None:
        raise ContractError("已有未关闭的 active_session，必须先 stop-work")
    started = started_at or utc_now()
    _parse_time(started)
    session = {"category": category, "started_at": started}
    document["active_session"] = session
    atomic_json(run_dir / WORK_LOG_PATH, document)
    return session


def stop_work_session(
    run_dir: Path,
    *,
    summary: str,
    finished_at: str | None = None,
    blocking_delivery_repair: bool = False,
) -> dict[str, Any]:
    """关闭活动会话并原子转成正式工时条目。

    Args:
        run_dir: 当前运行目录。
        summary: 本段实际产出。
        finished_at: 可选的显式结束时间。
        blocking_delivery_repair: 是否为当前交付 P0 的阻断修复。

    Returns:
        已写入的正式工时条目。
    """
    document = load_json(run_dir / WORK_LOG_PATH)
    active = document.get("active_session")
    if not isinstance(active, dict):
        raise ContractError("没有可关闭的 active_session")
    if not summary.strip():
        raise ContractError("work_log summary 不能为空")
    start = _parse_time(active["started_at"])
    finish_text = finished_at or utc_now()
    finish = _parse_time(finish_text)
    if finish <= start:
        raise ContractError("stop-work 时间必须晚于 start-work")
    for existing in document.get("entries", []):
        old_start = _parse_time(existing["started_at"])
        old_finish = _parse_time(existing["finished_at"])
        if start < old_finish and finish > old_start:
            raise ContractError("active_session 与已有工时区间重叠")
    entry = {
        "category": active["category"],
        "started_at": active["started_at"],
        "finished_at": finish_text,
        "duration_minutes": (finish - start).total_seconds() / 60,
        "summary": summary.strip(),
        "blocking_delivery_repair": bool(blocking_delivery_repair),
    }
    document.setdefault("entries", []).append(entry)
    document["entries"].sort(key=lambda item: item["started_at"])
    document["active_session"] = None
    atomic_json(run_dir / WORK_LOG_PATH, document)
    return entry


def record_phase_transition(
    run_dir: Path,
    *,
    from_phase: str,
    to_phase: str,
    changed_at: str | None = None,
) -> None:
    """在状态切换时自动关闭上一阶段并开始下一阶段计时。

    Args:
        run_dir: 当前运行目录。
        from_phase: 切换前阶段。
        to_phase: 切换后阶段。
        changed_at: 可选的确定性切换时间。
    """
    if from_phase == to_phase or not (run_dir / WORK_LOG_PATH).is_file():
        return
    timestamp = changed_at or utc_now()
    _parse_time(timestamp)
    document = load_json(run_dir / WORK_LOG_PATH)
    sessions = document.setdefault("phase_sessions", [])
    if not sessions:
        sessions.append(
            {
                "phase": from_phase,
                "started_at": _control(run_dir)["started_at"],
                "finished_at": timestamp,
            }
        )
    else:
        active = sessions[-1]
        if active.get("finished_at") is None:
            active["finished_at"] = timestamp
    sessions.append(
        {"phase": to_phase, "started_at": timestamp, "finished_at": None}
    )
    atomic_json(run_dir / WORK_LOG_PATH, document)


def work_log_summary(
    run_dir: Path, *, now: str | datetime | None = None
) -> dict[str, Any]:
    """汇总阶段级工时，并保留可选的细粒度工作记录。"""
    document = load_json(run_dir / WORK_LOG_PATH)
    totals = {category: 0.0 for category in sorted(WORK_CATEGORIES)}
    for entry in document.get("entries", []):
        category = entry.get("category")
        if category not in WORK_CATEGORIES:
            raise ContractError(f"work_log category 不受支持: {category}")
        totals[category] += float(entry["duration_minutes"])
    total = sum(totals.values())
    protocol = sum(totals[category] for category in _PROTOCOL_CATEGORIES)
    current = _parse_time(now or utc_now())
    started = _parse_time(_control(run_dir)["started_at"])
    wall_minutes = max(0.0, (current - started).total_seconds() / 60)
    active = document.get("active_session")
    active_minutes = 0.0
    if isinstance(active, dict):
        active_minutes = max(
            0.0, (current - _parse_time(active["started_at"])).total_seconds() / 60
        )
    phase_sessions: list[dict[str, Any]] = []
    for session in document.get("phase_sessions", []):
        if not isinstance(session, dict):
            continue
        session_start = _parse_time(session["started_at"])
        session_finish = (
            _parse_time(session["finished_at"])
            if isinstance(session.get("finished_at"), str)
            else current
        )
        phase_sessions.append(
            {
                **session,
                "duration_minutes": max(
                    0.0, (session_finish - session_start).total_seconds() / 60
                ),
            }
        )
    return {
        "total_minutes": total,
        "category_minutes": totals,
        "protocol_overhead_minutes": protocol,
        "protocol_overhead_ratio": protocol / total if total else 0.0,
        "active_session": active,
        "active_session_minutes": active_minutes,
        "active_session_long_running": active_minutes >= 120,
        "elapsed_wall_minutes": wall_minutes,
        "logged_time_coverage_ratio": 1.0 if phase_sessions else 0.0,
        "coverage_warning": False,
        "unexplained_gaps": [],
        "phase_sessions": phase_sessions,
    }


def verify_workflow_source_lock(run_dir: Path) -> dict[str, Any]:
    """比较运行初始化时的工作流源码基线与当前仓库。"""
    control = _control(run_dir)
    if control.get("workflow_source_locked") is not True:
        return {"valid": False, "changed_files": [], "reason": "workflow_source_locked 未启用"}
    repo_root = run_dir.resolve().parents[1]
    expected = control.get("workflow_source_manifest", {})
    current = _source_manifest(repo_root)
    changed = sorted(
        path
        for path in set(expected) | set(current)
        if expected.get(path) != current.get(path)
    )
    return {"valid": not changed, "changed_files": changed, "reason": "" if not changed else "运行期间工作流源码发生变化"}


def approve_workflow_p0_patch(run_dir: Path, *, reason: str) -> dict[str, Any]:
    """登记唯一允许的运行期源码变更：修复当前交付的阻断性 P0。"""
    if not reason.strip():
        raise ContractError("P0 工作流修补必须说明当前交付阻断原因")
    control = _control(run_dir)
    verification = verify_workflow_source_lock(run_dir)
    if verification["valid"]:
        raise ContractError("当前源码没有漂移，不能登记 P0 工作流修补")
    summary = work_log_summary(run_dir)
    if summary["protocol_overhead_minutes"] > control["protocol_patch_budget_minutes"]:
        raise ContractError("协议修补已超过预算，不能继续扩展工作流")
    patches = control.setdefault("approved_p0_patches", [])
    used_entries = {
        patch.get("work_log_entry_index")
        for patch in patches
        if isinstance(patch, dict)
    }
    work_log = load_json(run_dir / WORK_LOG_PATH)
    repair_entry_index = next(
        (
            index
            for index in range(len(work_log.get("entries", [])) - 1, -1, -1)
            if index not in used_entries
            and work_log["entries"][index].get("category") in _PROTOCOL_CATEGORIES
            and work_log["entries"][index].get("blocking_delivery_repair") is True
        ),
        None,
    )
    if repair_entry_index is None:
        raise ContractError("P0 工作流修补必须先登记 blocking_delivery_repair=true 的协议工时")
    patches.append(
        {
            "reason": reason.strip(),
            "changed_files": verification["changed_files"],
            "work_log_entry_index": repair_entry_index,
            "approved_at": utc_now(),
        }
    )
    repo_root = run_dir.resolve().parents[1]
    control["workflow_source_manifest"] = _source_manifest(repo_root)
    atomic_json(run_dir / DELIVERY_CONTROL_PATH, control)
    return patches[-1]


def _valid_pdf(path: Path) -> bool:
    """判断文件是否为非空 PDF 产物。"""
    return path.is_file() and path.stat().st_size > 8 and path.read_bytes()[:4] == b"%PDF"


def _milestone_current(run_dir: Path, name: str) -> bool:
    """复验 PDF 里程碑文件与冻结哈希仍一致。"""
    document = load_json(run_dir / PDF_MILESTONES_PATH)
    milestone = document.get("milestones", {}).get(name)
    if not isinstance(milestone, dict):
        return False
    path = run_dir / milestone.get("path", "")
    if not (_valid_pdf(path) and milestone.get("sha256") == sha256_file(path)):
        return False
    receipt_path = milestone.get("compile_receipt_path")
    if receipt_path:
        receipt = run_dir / receipt_path
        if not receipt.is_file() or milestone.get("compile_receipt_sha256") != sha256_file(receipt):
            return False
    if name == "first_reviewable" and receipt_path == "paper/reviewable-draft-receipt.json":
        from shumozizi.paper.compiler import verify_reviewable_draft_receipt

        return verify_reviewable_draft_receipt(run_dir)["valid"]
    if name == "candidate":
        final_pdf = run_dir / "paper/final.pdf"
        return _valid_pdf(final_pdf) and milestone.get("source_pdf_sha256") == sha256_file(final_pdf)
    return True


def require_current_pdf_milestone(run_dir: Path, milestone: str) -> None:
    """要求第一版或候选 PDF 里程碑仍绑定当前受控编译产物。"""
    if not _milestone_current(run_dir, milestone):
        raise ContractError(f"交付里程碑 {milestone} 缺失、损坏或已不再绑定当前 PDF")


def freeze_pdf_milestone(run_dir: Path, milestone: str) -> dict[str, Any]:
    """把当前受控编译 PDF 冻结为第一版或候选版里程碑。"""
    targets = {"first_reviewable": "paper/draft-1.pdf", "candidate": "paper/candidate.pdf"}
    if milestone not in targets:
        raise ContractError("PDF milestone 必须为 first_reviewable 或 candidate")
    if milestone == "first_reviewable":
        from shumozizi.paper.compiler import verify_reviewable_draft_receipt

        verification = verify_reviewable_draft_receipt(run_dir)
        if verification["valid"]:
            target = run_dir / targets[milestone]
            receipt_path = run_dir / "paper/reviewable-draft-receipt.json"
            document = load_json(run_dir / PDF_MILESTONES_PATH)
            record = {
                "path": targets[milestone],
                "sha256": sha256_file(target),
                "source_pdf_sha256": sha256_file(target),
                "compile_receipt_path": "paper/reviewable-draft-receipt.json",
                "compile_receipt_sha256": sha256_file(receipt_path),
                "frozen_at": utc_now(),
            }
            document.setdefault("milestones", {})[milestone] = record
            atomic_json(run_dir / PDF_MILESTONES_PATH, document)
            return record
    source = run_dir / "paper" / "final.pdf"
    if not _valid_pdf(source):
        raise ContractError("冻结 PDF 里程碑前必须先生成有效 paper/final.pdf")
    from shumozizi.paper.compiler import verify_paper_compile_receipt

    receipt = verify_paper_compile_receipt(run_dir)
    if not receipt["valid"]:
        raise ContractError("冻结 PDF 里程碑前必须先通过受控编译回执复验: " + "；".join(receipt["errors"]))
    document = load_json(run_dir / PDF_MILESTONES_PATH)
    predecessor: dict[str, Any] | None = None
    if milestone == "candidate":
        if not _milestone_current(run_dir, "first_reviewable"):
            raise ContractError("候选 PDF 必须继承仍有效的 first_reviewable 里程碑")
        predecessor = document.get("milestones", {}).get("first_reviewable")
        if not isinstance(predecessor, dict):
            raise ContractError("候选 PDF 缺少可复验的 first_reviewable 记录")
        first_receipt_path = run_dir / predecessor.get("compile_receipt_path", "")
        first_receipt = load_json(first_receipt_path) if first_receipt_path.is_file() else {}
        current_receipt = load_json(run_dir / "paper/compile-receipt.json")
        first_source_hash = first_receipt.get("paper_source_sha256")
        current_source_hash = current_receipt.get("paper_source_sha256")
        # PDF 元数据可能随重编译变化；优先比较源码摘要，避免同一正文仅靠重编译过关。
        same_source = (
            isinstance(first_source_hash, str)
            and isinstance(current_source_hash, str)
            and first_source_hash == current_source_hash
        )
        if same_source or predecessor.get("sha256") == sha256_file(source):
            raise ContractError("候选 PDF 相对首版没有实质内容增量，不能冻结新里程碑")
    target = run_dir / targets[milestone]
    temporary = target.with_suffix(target.suffix + ".tmp")
    shutil.copy2(source, temporary)
    temporary.replace(target)
    record = {
        "path": targets[milestone],
        "sha256": sha256_file(target),
        "source_pdf_sha256": sha256_file(source),
        "compile_receipt_path": "paper/compile-receipt.json",
        "compile_receipt_sha256": sha256_file(run_dir / "paper/compile-receipt.json"),
        "frozen_at": utc_now(),
    }
    if predecessor is not None:
        record["predecessor_sha256"] = predecessor["sha256"]
        record["predecessor_compile_receipt_sha256"] = predecessor.get(
            "compile_receipt_sha256"
        )
    document.setdefault("milestones", {})[milestone] = record
    atomic_json(run_dir / PDF_MILESTONES_PATH, document)
    return record


def web_review_required(run_dir: Path) -> bool:
    """返回本运行是否明确要求人工网页 PDF 审核。"""
    return bool(_control(run_dir).get("web_review", {}).get("required"))


def advance_delivery_phase(run_dir: Path) -> dict[str, Any]:
    """在真实阶段门通过时推进一格，不以状态字段替代证据。"""
    action = next_required_action(run_dir)
    if action["priority"] in {"P0_SCOPE", "P0_DELIVERY"}:
        blocked_by = action["blocked_by"] or [
            f"最高优先级动作尚未完成: {action['next_action']}"
        ]
        return {"advanced": False, "action": action, "blocked_by": blocked_by}
    state = read_simple_state(run_dir)
    targets = {
        "analysis": "experiment",
        "experiment": "paper",
        "paper": "paper_review",
        "paper_review": "verify",
        "verify": "complete",
    }
    target = targets.get(state["phase"])
    if target is None:
        return {"advanced": False, "action": action, "blocked_by": ["当前阶段不需要自动推进"]}
    try:
        if state["phase"] == "paper":
            require_current_pdf_milestone(run_dir, "candidate")
        if state["phase"] == "paper_review" and web_review_required(run_dir):
            from shumozizi.knowledge.external_discussion import require_web_paper_audit_release

            require_web_paper_audit_release(run_dir)
        from shumozizi.simple.state import update_simple_state

        updated = update_simple_state(run_dir, phase=target)
    except ContractError as exc:
        return {"advanced": False, "action": action, "blocked_by": [str(exc)]}
    return {"advanced": True, "from_phase": state["phase"], "to_phase": updated["phase"], "state": updated}


def _action(
    state: dict[str, Any],
    *,
    next_action: str,
    priority: str,
    elapsed: float,
    remaining: float,
    blocked_by: list[str] | None = None,
    forbidden_actions: list[str] | None = None,
    work_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造统一、机器可消费的下一动作。"""
    return {
        "current_phase": state["phase"],
        "paper_revision": paper_revision_status(state),
        "next_action": next_action,
        "priority": priority,
        "elapsed_minutes": elapsed,
        "remaining_minutes": max(0.0, remaining),
        "blocked_by": blocked_by or [],
        "forbidden_actions": forbidden_actions or [],
        "work_summary": work_summary or {},
    }


def next_required_action(
    run_dir: Path, *, now: str | datetime | None = None
) -> dict[str, Any]:
    """返回当前唯一最高优先级动作，并让交付截止点覆盖普通阶段工作。"""
    state = read_simple_state(run_dir)
    control = _control(run_dir)
    current = _parse_time(now or utc_now())
    started = _parse_time(control["started_at"])
    elapsed = max(0.0, (current - started).total_seconds() / 60)
    plan = control["delivery_plan"]
    remaining = float(plan["final_deadline"]) - elapsed
    scope_frozen = elapsed >= plan["first_reviewable_pdf_deadline"] or _milestone_current(
        run_dir, "first_reviewable"
    )
    summary = work_log_summary(run_dir)
    source_lock = verify_workflow_source_lock(run_dir)
    if not source_lock["valid"]:
        return _action(
            state,
            next_action="restore_workflow_source_or_record_p0_patch",
            priority="P0_SCOPE",
            elapsed=elapsed,
            remaining=remaining,
            blocked_by=source_lock["changed_files"],
            forbidden_actions=_DELIVERY_FREEZE_ACTIONS,
            work_summary=summary,
        )
    if (
        summary["protocol_overhead_minutes"] > control["protocol_patch_budget_minutes"]
        or summary["protocol_overhead_ratio"] > control["protocol_overhead_ratio_limit"]
    ):
        return _action(
            state,
            next_action="return_to_competition_mainline",
            priority="P0_SCOPE",
            elapsed=elapsed,
            remaining=remaining,
            forbidden_actions=_DELIVERY_FREEZE_ACTIONS,
            work_summary=summary,
        )
    if elapsed >= plan["first_reviewable_pdf_deadline"] and not _milestone_current(
        run_dir, "first_reviewable"
    ):
        return _action(
            state,
            next_action="generate_first_reviewable_pdf",
            priority="P0_DELIVERY",
            elapsed=elapsed,
            remaining=remaining,
            forbidden_actions=_DELIVERY_FREEZE_ACTIONS,
            work_summary=summary,
        )
    if elapsed >= plan["candidate_pdf_deadline"] and not _milestone_current(run_dir, "candidate"):
        return _action(
            state,
            next_action="freeze_candidate_pdf",
            priority="P0_DELIVERY",
            elapsed=elapsed,
            remaining=remaining,
            forbidden_actions=_DELIVERY_FREEZE_ACTIONS,
            work_summary=summary,
        )
    if elapsed >= plan["blind_review_deadline"]:
        from shumozizi.simple.review import paper_blind_review_status

        blind = paper_blind_review_status(run_dir)
        if not blind["allowed"]:
            return _action(
                state,
                next_action="create_or_resume_independent_blind_review",
                priority="P0_DELIVERY",
                elapsed=elapsed,
                remaining=remaining,
                blocked_by=[blind.get("reason", "独立 PDF 盲评未完成")],
                forbidden_actions=_DELIVERY_FREEZE_ACTIONS,
                work_summary=summary,
            )
    if state["phase"] == "analysis":
        next_action = "freeze_route_and_start_experiment" if elapsed >= plan["analysis_soft_limit"] else "complete_problem_analysis"
    elif state["phase"] == "experiment":
        next_action = "qualify_answers_and_start_paper" if elapsed >= plan["experiment_soft_limit"] else "complete_answer_qualification"
    elif state["phase"] == "paper":
        if not _milestone_current(run_dir, "first_reviewable"):
            next_action = "write_compile_and_freeze_first_reviewable_pdf"
        elif not _milestone_current(run_dir, "candidate"):
            next_action = "revise_and_freeze_candidate_pdf"
        else:
            next_action = "advance_to_paper_review"
    elif state["phase"] == "paper_review":
        from shumozizi.knowledge.external_discussion import (
            web_paper_audit_started,
            web_paper_audit_status,
        )
        from shumozizi.simple.review import paper_blind_review_status

        blind = paper_blind_review_status(run_dir)
        if not blind["allowed"]:
            next_action = "create_or_resume_independent_blind_review"
        elif web_paper_audit_started(run_dir) and not web_paper_audit_status(run_dir)["allowed"]:
            next_action = "wait_for_or_close_manual_web_review"
        elif control["web_review"]["required"] and not web_paper_audit_started(run_dir):
            next_action = "start_manual_web_review"
        else:
            next_action = "advance_to_verify"
    elif state["phase"] == "verify":
        next_action = "run_mechanical_qa_and_complete"
    elif state["phase"] == "complete":
        next_action = "none"
    else:
        next_action = "repair_blocking_delivery_failure"
    return _action(
        state,
        next_action=next_action,
        priority="P0_DELIVERY" if elapsed >= plan["final_deadline"] else "P1_MAINLINE",
        elapsed=elapsed,
        remaining=remaining,
        forbidden_actions=_DELIVERY_FREEZE_ACTIONS if scope_frozen else [],
        work_summary=summary,
    )
