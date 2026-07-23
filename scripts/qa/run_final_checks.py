"""运行 Capability-First v3 的一次机械终检。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from scripts.qa.check_numeric_consistency import check_numeric_consistency
from scripts.qa.check_placeholders import check_placeholders
from scripts.qa.check_result_references import check_result_references
from shumozizi.core.io import ContractError, atomic_json, sha256_file
from shumozizi.paper.compiler import verify_paper_compile_receipt
from shumozizi.paper.contributions import verify_contribution_ledger
from shumozizi.paper.references import verify_paper_references
from shumozizi.paper.sufficiency import run_paper_sufficiency_check
from shumozizi.paper.templates import require_materialized_template
from shumozizi.simple.figures import verify_current_figure_files
from shumozizi.simple.results import verify_current_result_files
from shumozizi.simple.review import (
    competition_submission_status,
    paper_blind_review_status,
    scientific_review_status,
)
from shumozizi.simple.state import read_simple_state
from shumozizi.simple.visualization import require_visualization_complete
from tools.qa.make_contact_sheet import make_contact_sheet
from tools.qa.pdf_qa import audit_pdf


def _utc_now() -> str:
    """返回当前 UTC 时间。

    Returns:
        RFC 3339 UTC 时间字符串。
    """
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _print_cli_payload(payload: dict[str, Any]) -> None:
    """以 UTF-8 输出终检摘要，避免 Windows 默认代码页截断检查结果。"""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            # 管道或测试替身可能不支持重配；此时仍交由其原始写入语义处理。
            pass
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _check(check_id: str, payload: dict[str, Any], details: str) -> dict[str, Any]:
    """将子检查标准化为报告条目。

    Args:
        check_id: 稳定检查 ID。
        payload: 子检查原始结果。
        details: 人类可读说明。

    Returns:
        统一的检查条目。
    """
    return {
        "id": check_id,
        "passed": bool(payload.get("success")),
        "details": details,
        "payload": payload,
    }


def _optional_paper_protocol_check(
    run_dir: Path,
    relative_path: Path,
    verifier: Any,
) -> dict[str, Any]:
    """复验已登记的论文协议文件，未使用接口时保持兼容。

    Args:
        run_dir: 当前 Capability-First v3 运行目录。
        relative_path: 运行目录内的可选协议文件。
        verifier: 返回 ``valid`` 与 ``errors`` 的复验函数。

    Returns:
        可直接传给机械 QA 的 ``success`` 结果。
    """
    if not (run_dir / relative_path).is_file():
        return {"success": True, "skipped": True, "errors": []}
    try:
        verification = verifier(run_dir)
    except (ContractError, OSError, TypeError, ValueError) as exc:
        return {"success": False, "errors": [str(exc)]}
    return {
        "success": verification.get("valid") is True,
        "errors": list(verification.get("errors", [])),
        "verification": verification,
    }


def run_final_checks(
    run_dir: Path,
    *,
    anonymous_required: bool = False,
    anonymous_terms: tuple[str, ...] = (),
) -> dict[str, Any]:
    """生成 v3 机械 QA JSON、联系表和简短验证报告。

    Args:
        run_dir: v3 运行目录。
        anonymous_required: 是否把匿名违规作为阻断项。
        anonymous_terms: 禁止出现在匿名稿中的身份词。

    Returns:
        完整机械检查结果。

    Raises:
        ContractError: 指定目录不是合法 v3 运行。
    """
    root = run_dir.resolve()
    state = read_simple_state(root)
    pdf = root / "paper" / "final.pdf"
    checks: list[dict[str, Any]] = []
    checks.append(
        {
            "id": "state-phase",
            "passed": state["phase"] != "blocked",
            "details": f"当前运行阶段：{state['phase']}",
            "payload": {"phase": state["phase"]},
        }
    )
    scientific_review = scientific_review_status(root)
    checks.append(
        _check(
            "scientific-review-release",
            {"success": scientific_review["allowed"], "reason": scientific_review["reason"]},
            "独立科学红队的冻结输入、报告和隔离声明仍有效",
        )
    )
    completion_release = competition_submission_status(root)
    checks.append(
        _check(
            "competition-submission-release",
            {
                "success": completion_release.get("submission_ready", False),
                "competition_strength": completion_release.get("competition_strength"),
                "reason": completion_release.get("reason", ""),
            },
            "生产模式仅允许 qualified 或 strong 的科学审查进入 complete",
        )
    )
    try:
        visualization = require_visualization_complete(root)
        visualization_payload = {
            "success": True,
            "contract_count": len(visualization["contracts"]),
        }
    except (ContractError, OSError, TypeError, ValueError) as exc:
        visualization_payload = {"success": False, "errors": [str(exc)]}
    checks.append(
        _check(
            "visualization-contract",
            visualization_payload,
            "能力路由要求的模型与求解视觉证据已完成且输出未漂移",
        )
    )
    template: dict[str, Any] = {}
    try:
        template = require_materialized_template(root)
        template_payload = {
            "success": True,
            "template_id": template["template_id"],
            "engine": template["engine"],
        }
    except (ContractError, OSError, TypeError, ValueError) as exc:
        template_payload = {"success": False, "errors": [str(exc)]}
    checks.append(
        _check(
            "paper-template-manifest",
            template_payload,
            "完整写作模板与比赛、语言和排版引擎仍匹配",
        )
    )
    if template_payload.get("success") and template.get("schema_version") == "1.2":
        compile_receipt = verify_paper_compile_receipt(root)
        compile_payload = {
            "success": compile_receipt["valid"],
            "errors": compile_receipt["errors"],
        }
    else:
        compile_payload = {
            "success": template_payload.get("success", False),
            "skipped": True,
            "reason": "历史模板清单未声明 v1.2 受控编译路径。",
        }
    checks.append(
        _check(
            "paper-compile-receipt",
            compile_payload,
            "最终 PDF 与当前模板、论文源文件和受控 LaTeX/Typst 编译记录一致",
        )
    )
    paper_blind_review = paper_blind_review_status(root)
    checks.append(
        _check(
            "paper-blind-review-release",
            {"success": paper_blind_review["allowed"], "reason": paper_blind_review["reason"]},
            "独立 PDF 盲审的冻结输入、报告和隔离声明仍有效",
        )
    )
    pdf_report = audit_pdf(
        pdf,
        anonymous_required=anonymous_required,
        anonymous_terms=anonymous_terms,
    )
    checks.append(_check("pdf", pdf_report, "PDF、空白页、裁切、文字重叠和重复编号"))
    try:
        content_report = run_paper_sufficiency_check(root)
        content_payload = {
            "success": content_report["status"] == "pass",
            "report": content_report,
        }
    except (ContractError, OSError) as exc:
        content_report = {"status": "blocked", "hard_failures": [str(exc)], "warnings": []}
        content_payload = {"success": False, "report": content_report}
    checks.append(
        _check(
            "paper-content-sufficiency",
            content_payload,
            "内容蓝图、逐问直接回答与 PDF 内容覆盖",
        )
    )
    paper_references = _optional_paper_protocol_check(
        root,
        Path("paper/paper_references.json"),
        verify_paper_references,
    )
    checks.append(
        _check(
            "paper-references",
            paper_references,
            "已登记离线论文卡的冻结、来源与哈希边界",
        )
    )
    contribution_ledger = _optional_paper_protocol_check(
        root,
        Path("paper/contribution_ledger.json"),
        verify_contribution_ledger,
    )
    checks.append(
        _check(
            "paper-contribution-ledger",
            contribution_ledger,
            "题目特定贡献、创新证据链与当前生产结果",
        )
    )
    placeholders = check_placeholders(root / "paper")
    checks.append(_check("placeholders", placeholders, "论文源文件占位符"))
    references = check_result_references(root)
    checks.append(_check("result-references", references, "论文显式结果引用"))
    numeric = check_numeric_consistency(root)
    checks.append(_check("numeric-consistency", numeric, "论文显式关键指标"))
    current_files = verify_current_result_files(root)
    checks.append(_check("current-result-files", current_files, "current 结果哈希与指标来源"))
    current_figures = verify_current_figure_files(root)
    checks.append(_check("current-figure-files", current_figures, "current 图表、源结果与输出哈希"))
    contact_sheet = root / "qa" / "contact-sheet.png"
    contact_error: str | None = None
    # 联系表用于人工定位 PDF 内的机械问题，因此只要文件可打开就应尽量生成。
    pdf_open = any(item["id"] == "pdf-open" and item["passed"] for item in pdf_report["checks"])
    if pdf_open:
        try:
            make_contact_sheet(pdf, contact_sheet)
        except Exception as exc:
            contact_error = str(exc)
    else:
        contact_error = "PDF 未通过基础读取检查，未生成联系表"
    checks.append(
        {
            "id": "contact-sheet",
            "passed": contact_error is None,
            "details": contact_error or str(contact_sheet.relative_to(root)),
        }
    )
    failed = [item["id"] for item in checks if not item["passed"]]
    report = {
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "workflow": "capability-first-v3",
        "status": "pass" if not failed else "blocked",
        "final_pdf": "paper/final.pdf",
        "final_pdf_sha256": sha256_file(pdf) if pdf.is_file() else None,
        "checks": checks,
        "hard_failures": failed,
        "warnings": [*pdf_report.get("warnings", []), *content_report.get("warnings", [])],
        "generated_at": _utc_now(),
    }
    atomic_json(root / "qa" / "mechanical-qa.json", report)
    lines = [
        "# 机械验证报告",
        "",
        f"- 状态：{report['status']}",
        f"- 运行：{state['run_id']}",
        "",
        "## 检查结果",
        "",
    ]
    for item in checks:
        lines.append(f"- {'通过' if item['passed'] else '失败'}｜{item['id']}：{item['details']}")
    (root / "reports" / "VERIFY_REPORT.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )
    return report


def main() -> int:
    """解析命令行并输出机械 QA 摘要。

    Returns:
        没有机械阻断项时为零。
    """
    parser = argparse.ArgumentParser(description="运行 Capability-First v3 机械终检")
    parser.add_argument("run_dir")
    parser.add_argument("--anonymous", action="store_true")
    parser.add_argument("--anonymous-term", action="append", default=[])
    args = parser.parse_args()
    try:
        payload = run_final_checks(
            Path(args.run_dir),
            anonymous_required=args.anonymous,
            anonymous_terms=tuple(args.anonymous_term),
        )
    except (ContractError, OSError) as exc:
        payload = {"status": "blocked", "hard_failures": [str(exc)]}
    _print_cli_payload(payload)
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
