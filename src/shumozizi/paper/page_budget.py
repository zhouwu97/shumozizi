"""审计竞赛论文 PDF 页数，记录上限风险而不鼓励人为做长。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pypdf import PdfReader

from shumozizi.core.io import ContractError, atomic_json, sha256_file
from shumozizi.core.schema import require_valid
from shumozizi.simple.state import read_simple_state, utc_now

PAGE_BUDGET_PATH = Path("qa/paper-page-budget.json")
TARGET_PAGE_RANGE = (1, 30)
UNDERDEVELOPED_THRESHOLD = 1


def _assessment(page_count: int) -> tuple[str, str]:
    """把页数映射为竞赛编辑动作，而不是把页数当作质量证明。"""
    if page_count <= TARGET_PAGE_RANGE[1]:
        return "normal_range", "页数不超过 30 页；内容充分性由论证覆盖和独立审阅判断。"
    return "over_30_review_required", "页数超过 30 页，需要按赛事正文/附录口径处理。"


def audit_page_budget(
    run_dir: Path,
    pdf_path: Path,
    *,
    enforce_minimum: bool = False,
) -> dict[str, Any]:
    """读取 PDF 页数并写入可复验页数审计。

    Args:
        run_dir: 当前运行目录。
        pdf_path: 待审计的 PDF，必须位于运行目录内。
        enforce_minimum: 已弃用；页数只作为竞赛编辑信号，不再硬阻断。

    Returns:
        含页数、目标区间、产物摘要和审计结论的回执。

    Raises:
        ContractError: PDF 无效或越过运行目录。
    """
    root = run_dir.resolve()
    artifact = pdf_path.resolve()
    try:
        artifact.relative_to(root)
    except ValueError as exc:
        raise ContractError("页数审计 PDF 必须位于当前运行目录内") from exc
    if not artifact.is_file() or artifact.stat().st_size == 0:
        raise ContractError(f"页数审计 PDF 不存在或为空: {artifact}")
    try:
        page_count = len(PdfReader(str(artifact)).pages)
    except Exception as exc:  # pypdf 对损坏 PDF 的异常类型随版本变化。
        raise ContractError(f"无法读取论文 PDF 页数: {exc}") from exc
    if page_count < 1:
        raise ContractError("论文 PDF 至少应包含一页")
    status, explanation = _assessment(page_count)
    report = {
        "schema_name": "paper_page_budget",
        "schema_version": "1.0",
        "run_id": read_simple_state(root)["run_id"],
        "artifact_path": artifact.relative_to(root).as_posix(),
        "artifact_sha256": sha256_file(artifact),
        "page_count": page_count,
        "target_page_range": list(TARGET_PAGE_RANGE),
        "inspect_below_pages": UNDERDEVELOPED_THRESHOLD,
        "enforce_minimum": enforce_minimum,
        "status": status,
        "explanation": explanation,
        "generated_at": utc_now(),
    }
    require_valid(report, "paper_page_budget")
    atomic_json(root / PAGE_BUDGET_PATH, report)
    # 页数只回答"这篇论文是否值得进一步检查"，不回答"是否合格"。
    # 内容是否充分由 content coverage + Fresh Reviewer + Adjudicator 判断，
    # 不再从低页数反推应扩写。enforce_minimum 参数仅保留兼容。
    return report


def verify_page_budget(run_dir: Path, *, pdf_path: Path | None = None) -> dict[str, Any]:
    """复验页数回执和 PDF 摘要，供最终编译回执检查。"""
    root = run_dir.resolve()
    report_path = root / PAGE_BUDGET_PATH
    errors: list[str] = []
    try:
        from shumozizi.core.io import load_json

        report = load_json(report_path)
        require_valid(report, "paper_page_budget")
        artifact = (root / report["artifact_path"]).resolve()
        if pdf_path is not None and artifact != pdf_path.resolve():
            errors.append("页数审计未绑定当前 PDF")
        if not artifact.is_file() or report.get("artifact_sha256") != sha256_file(artifact):
            errors.append("页数审计 PDF 缺失或摘要已变化")
        actual_count = len(PdfReader(str(artifact)).pages)
        if report.get("page_count") != actual_count:
            errors.append("页数审计记录与当前 PDF 页数不一致")
    except (ContractError, KeyError, OSError, ValueError, TypeError) as exc:
        errors.append(str(exc))
        report = None
    return {
        "valid": not errors,
        "errors": errors,
        "report": report,
        "report_path": PAGE_BUDGET_PATH.as_posix(),
    }
