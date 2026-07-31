"""记录并复验论文蓝图审核与第一版 PDF 冷读 checkpoint。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    load_json,
    relative_inside,
    resolve_inside,
    sha256_file,
)
from shumozizi.core.schema import require_valid
from shumozizi.paper.paper_review import load_paper_review, merge_paper_review_findings
from shumozizi.simple.state import read_simple_state

BLUEPRINT_CHECKPOINT_PATH = Path("review/paper-blueprint-review-checkpoint.json")
COLD_READ_CHECKPOINT_PATH = Path("review/first-draft-cold-read-checkpoint.json")


def _timestamp() -> str:
    """返回 JSON Schema 可校验的 UTC 时间。"""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _review_report(run_dir: Path, report_path: str, expected_name: str) -> tuple[Path, dict[str, Any]]:
    """读取运行内独立审核输出并校验最小结构。"""
    report = resolve_inside(run_dir, report_path, must_exist=True)
    payload = load_json(report)
    if payload.get("schema_name") != expected_name or payload.get("schema_version") != "1.0":
        raise ContractError(
            f"审核输出必须声明 schema_name={expected_name}、schema_version=1.0"
        )
    findings = payload.get("findings")
    if not isinstance(findings, list) or len(findings) > 5:
        raise ContractError("审核输出 findings 必须是最多 5 项的数组")
    if not all(isinstance(item, dict) for item in findings):
        raise ContractError("审核输出 findings[] 必须全部是对象")
    return report, payload


def _finding_ids(payload: dict[str, Any]) -> list[str]:
    """读取审核输出中的唯一 finding ID。"""
    finding_ids = [item.get("finding_id") for item in payload["findings"]]
    if not all(isinstance(item, str) and item for item in finding_ids):
        raise ContractError("审核输出每项 finding 都必须有非空 finding_id")
    if len(finding_ids) != len(set(finding_ids)):
        raise ContractError("审核输出 finding_id 不得重复")
    return finding_ids


def _record_import(
    run_dir: Path,
    *,
    report: Path,
    payload: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    """把审核 finding 合入 PAPER_REVIEW；空数组也物化完成记录区块。"""
    relative_report = relative_inside(run_dir, report).as_posix()
    document = merge_paper_review_findings(
        run_dir,
        input_path=relative_report,
        source=source,
    )
    finding_ids = _finding_ids(payload)
    imported = {item["finding_id"] for item in document["findings"]}
    missing = sorted(set(finding_ids) - imported)
    if missing:
        raise ContractError(f"审核 finding 未完整导入 PAPER_REVIEW: {', '.join(missing)}")
    return {
        "confirmed": True,
        "paper_review_path": "paper/PAPER_REVIEW.md",
        "paper_review_sha256_at_import": sha256_file(run_dir / "paper/PAPER_REVIEW.md"),
        "finding_ids": finding_ids,
        "finding_count": len(finding_ids),
    }


def record_paper_blueprint_review_checkpoint(
    run_dir: Path,
    *,
    report_path: str,
    reviewer_context_id: str,
) -> dict[str, Any]:
    """记录写作前蓝图审核，并绑定三项当前作者输入。

    Args:
        run_dir: 当前运行目录。
        report_path: 运行目录内的独立蓝图审核 JSON。
        reviewer_context_id: 独立审核上下文标识。

    Returns:
        已原子写入的蓝图审核 checkpoint。
    """
    root = run_dir.resolve()
    report, payload = _review_report(root, report_path, "paper_blueprint_review")
    if payload.get("decision") != "continue_writing":
        raise ContractError("蓝图审核仅在 decision=continue_writing 时可记录完成 checkpoint")
    if not reviewer_context_id.strip():
        raise ContractError("蓝图审核必须提供 reviewer_context_id")
    review_import = _record_import(
        root,
        report=report,
        payload=payload,
        source="paper_blueprint_review",
    )
    inputs = {
        "paper_blueprint": "paper/PAPER_BLUEPRINT.md",
        "paper_blueprint_sha256": sha256_file(root / "paper/PAPER_BLUEPRINT.md"),
        "answer_map": "paper/answer-map.json",
        "answer_map_sha256": sha256_file(root / "paper/answer-map.json"),
        "figure_plan": "figures/FIGURE_PLAN.json",
        "figure_plan_sha256": sha256_file(root / "figures/FIGURE_PLAN.json"),
    }
    document = {
        "schema_name": "paper_review_checkpoint",
        "schema_version": "2.0",
        "run_id": root.name,
        "kind": "paper_blueprint_review",
        "decision": "continue_writing",
        "reviewer_context_id": reviewer_context_id,
        "source_report": {
            "path": relative_inside(root, report).as_posix(),
            "sha256": sha256_file(report),
        },
        "inputs": inputs,
        "paper_review_import": review_import,
        "recorded_at": _timestamp(),
    }
    require_valid(document, "paper_review_checkpoint")
    atomic_json(root / BLUEPRINT_CHECKPOINT_PATH, document)
    return document


def record_first_draft_cold_read_checkpoint(
    run_dir: Path,
    *,
    report_path: str,
    reviewer_context_id: str,
    pdf_path: str = "paper/draft-1.pdf",
) -> dict[str, Any]:
    """导入首稿冷读 finding，并绑定 PDF 与当前论证修订号。

    Args:
        run_dir: 当前运行目录。
        report_path: 运行目录内的独立冷读 JSON。
        reviewer_context_id: 独立冷读上下文标识。
        pdf_path: 运行目录 ``paper/`` 内的第一版 PDF。

    Returns:
        已原子写入的首稿冷读 checkpoint。
    """
    root = run_dir.resolve()
    report, payload = _review_report(root, report_path, "first_draft_cold_read")
    decision = payload.get("decision")
    if decision not in {"continue_revision", "ready_for_candidate"}:
        raise ContractError(
            "首稿冷读 decision 必须是 continue_revision 或 ready_for_candidate"
        )
    if not reviewer_context_id.strip():
        raise ContractError("首稿冷读必须提供 reviewer_context_id")
    pdf = resolve_inside(root, pdf_path, must_exist=True)
    relative_pdf = relative_inside(root, pdf).as_posix()
    if not relative_pdf.startswith("paper/") or pdf.suffix.lower() != ".pdf":
        raise ContractError("首稿冷读输入必须是运行目录 paper/ 下的 PDF")
    declared_pdf = payload.get("pdf_path")
    if declared_pdf not in {None, relative_pdf}:
        raise ContractError("首稿冷读报告声明的 pdf_path 与实际冻结 PDF 不一致")
    review_import = _record_import(
        root,
        report=report,
        payload=payload,
        source="first_draft_cold_read",
    )
    state = read_simple_state(root)
    argument_revision = state.get("argument_revision", 0)
    if not isinstance(argument_revision, int) or argument_revision < 0:
        raise ContractError("当前 state.argument_revision 非法")
    document = {
        "schema_name": "paper_review_checkpoint",
        "schema_version": "2.0",
        "run_id": root.name,
        "kind": "first_draft_cold_read",
        "decision": decision,
        "reviewer_context_id": reviewer_context_id,
        "source_report": {
            "path": relative_inside(root, report).as_posix(),
            "sha256": sha256_file(report),
        },
        "inputs": {
            "pdf": relative_pdf,
            "pdf_sha256": sha256_file(pdf),
            "argument_revision": argument_revision,
        },
        "paper_review_import": review_import,
        "recorded_at": _timestamp(),
    }
    require_valid(document, "paper_review_checkpoint")
    atomic_json(root / COLD_READ_CHECKPOINT_PATH, document)
    return document


def _checkpoint_base_errors(
    run_dir: Path, path: Path, *, expected_kind: str
) -> tuple[dict[str, Any] | None, list[str]]:
    """复验 checkpoint 公共字段与源报告绑定。"""
    if not path.is_file():
        return None, [f"缺少 {path.relative_to(run_dir).as_posix()}"]
    try:
        document = load_json(path)
        require_valid(document, "paper_review_checkpoint")
    except (ContractError, OSError) as exc:
        return None, [str(exc)]
    errors: list[str] = []
    if document.get("run_id") != run_dir.name:
        errors.append(f"{expected_kind} checkpoint.run_id 与运行目录不一致")
    if document.get("kind") != expected_kind:
        errors.append(f"checkpoint.kind 应为 {expected_kind}")
    source = document["source_report"]
    try:
        report = resolve_inside(run_dir, source["path"], must_exist=True)
        if sha256_file(report) != source["sha256"]:
            errors.append(f"{expected_kind} 源审核报告已变化")
    except (ContractError, OSError, KeyError, TypeError) as exc:
        errors.append(f"{expected_kind} 源审核报告绑定无效: {exc}")
    return document, errors


def _paper_review_import_errors(run_dir: Path, document: dict[str, Any]) -> list[str]:
    """确认 checkpoint 中的 finding 已导入当前 PAPER_REVIEW。"""
    record = document.get("paper_review_import", {})
    if record.get("confirmed") is not True:
        return [f"{document.get('kind')} 未确认导入 PAPER_REVIEW"]
    try:
        review = load_paper_review(run_dir)
    except (ContractError, OSError) as exc:
        return [f"无法复验 PAPER_REVIEW 导入: {exc}"]
    current_ids = {item["finding_id"] for item in review["findings"]}
    missing = sorted(set(record.get("finding_ids", [])) - current_ids)
    return (
        [f"PAPER_REVIEW 缺少已导入 finding: {', '.join(missing)}"] if missing else []
    )


def validate_paper_blueprint_review_checkpoint(run_dir: Path) -> list[str]:
    """复验蓝图审核决定及三项作者输入是否仍为审核时版本。"""
    root = run_dir.resolve()
    document, errors = _checkpoint_base_errors(
        root, root / BLUEPRINT_CHECKPOINT_PATH, expected_kind="paper_blueprint_review"
    )
    if document is None:
        return errors
    if document.get("decision") != "continue_writing":
        errors.append("蓝图审核 checkpoint.decision 不是 continue_writing")
    inputs = document["inputs"]
    bindings = (
        ("paper_blueprint", "paper_blueprint_sha256"),
        ("answer_map", "answer_map_sha256"),
        ("figure_plan", "figure_plan_sha256"),
    )
    for path_key, hash_key in bindings:
        try:
            path = resolve_inside(root, inputs[path_key], must_exist=True)
            if sha256_file(path) != inputs[hash_key]:
                errors.append(f"蓝图审核后 {inputs[path_key]} 已变化，必须重新审核")
        except (ContractError, OSError, KeyError, TypeError) as exc:
            errors.append(f"蓝图审核输入绑定无效: {exc}")
    errors.extend(_paper_review_import_errors(root, document))
    return errors


def validate_first_draft_cold_read_checkpoint(run_dir: Path) -> list[str]:
    """复验首稿 PDF、argument_revision 与 PAPER_REVIEW 导入记录。"""
    root = run_dir.resolve()
    document, errors = _checkpoint_base_errors(
        root, root / COLD_READ_CHECKPOINT_PATH, expected_kind="first_draft_cold_read"
    )
    if document is None:
        return errors
    inputs = document["inputs"]
    try:
        pdf = resolve_inside(root, inputs["pdf"], must_exist=True)
        if sha256_file(pdf) != inputs["pdf_sha256"]:
            errors.append("首稿冷读绑定的 PDF 已变化，必须重新冷读")
    except (ContractError, OSError, KeyError, TypeError) as exc:
        errors.append(f"首稿冷读 PDF 绑定无效: {exc}")
    state = read_simple_state(root)
    if state.get("argument_revision", 0) != inputs.get("argument_revision"):
        errors.append("argument_revision 已变化，旧首稿冷读失效")
    errors.extend(_paper_review_import_errors(root, document))
    return errors


def paper_checkpoint_errors(run_dir: Path, *, candidate: bool = True) -> list[str]:
    """返回两个论文 checkpoint 的候选门禁错误。

    旧 FIGURE_PLAN 保持兼容；只有 2.4 候选稿启用这一硬门。调用者可用
    ``candidate=False`` 显式执行诊断而不触发版本门。
    """
    root = run_dir.resolve()
    figure_plan_path = root / "figures/FIGURE_PLAN.json"
    if candidate:
        try:
            if load_json(figure_plan_path).get("schema_version") != "2.4":
                return []
        except (ContractError, OSError):
            return []
    errors: list[str] = []
    for path, kind in (
        (root / BLUEPRINT_CHECKPOINT_PATH, "paper_blueprint_review"),
        (root / COLD_READ_CHECKPOINT_PATH, "first_draft_cold_read"),
    ):
        document, current = _checkpoint_base_errors(root, path, expected_kind=kind)
        errors.extend(current)
        if document is None:
            continue
        errors.extend(_paper_review_import_errors(root, document))
        if kind == "first_draft_cold_read":
            reviewed_revision = document.get("inputs", {}).get("argument_revision")
            current_revision = read_simple_state(root).get("argument_revision", 0)
            if not isinstance(reviewed_revision, int) or reviewed_revision > current_revision:
                errors.append("首稿冷读绑定了晚于当前正文的 argument_revision")
    return errors


def require_paper_checkpoints_for_candidate(run_dir: Path) -> None:
    """要求两个审核动作可追溯且 finding 已导入当前返修包。

    蓝图审核的输入绑定在写作前检查，首稿 PDF 绑定在记录时检查。候选稿允许
    按 finding 修改蓝图、图表和正文，否则批量返修本身会使 checkpoint 永久失效。
    最终 PDF 盲评仍由独立的 ``argument_revision`` 绑定规则控制。
    """
    errors = paper_checkpoint_errors(run_dir, candidate=True)
    if errors:
        raise ContractError("论文审核 checkpoint 未就绪: " + "；".join(errors))
