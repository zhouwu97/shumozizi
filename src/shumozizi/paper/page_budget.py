"""审计竞赛论文 PDF 页数，防止完整论证被压缩成短报告。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pypdf import PdfReader

from shumozizi.core.io import ContractError, atomic_json, sha256_file
from shumozizi.core.schema import require_valid
from shumozizi.simple.state import read_simple_state, utc_now

PAGE_BUDGET_PATH = Path("qa/paper-page-budget.json")
TARGET_PAGE_RANGE = (24, 30)
UNDERDEVELOPED_THRESHOLD = 18


def _assessment(page_count: int) -> tuple[str, str]:
    """把页数映射为竞赛编辑动作，而不是把页数当作质量证明。"""
    if page_count < UNDERDEVELOPED_THRESHOLD:
        return "under_18_review_required", "正文低于 18 页，必须补充论证或记录真实阻断原因。"
    if page_count < TARGET_PAGE_RANGE[0]:
        return "compression_review_required", "正文低于 24 页，需要检查是否压缩了推导、机制或验证。"
    if page_count <= TARGET_PAGE_RANGE[1]:
        return "normal_range", "正文页数位于国赛推荐的 24–30 页区间。"
    return "over_30_review_required", "正文超过 30 页，需要检查重复、附录边界和模板适配。"


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
        enforce_minimum: 是否把少于 18 页提升为编译阻断。

    Returns:
        含页数、目标区间、产物摘要和审计结论的回执。

    Raises:
        ContractError: PDF 无效、越过运行目录，或启用硬门时页数不足。
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
    if enforce_minimum and page_count < UNDERDEVELOPED_THRESHOLD:
        raise ContractError(
            f"论文页数门阻断：当前 {page_count} 页，低于 {UNDERDEVELOPED_THRESHOLD} 页；"
            "请展开问题分析、关键推导、机制解释和验证边界后再编译候选稿。"
        )
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
