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
from shumozizi.simple.figures import verify_current_figure_files
from shumozizi.simple.results import verify_current_result_files
from shumozizi.simple.state import read_simple_state
from tools.qa.make_contact_sheet import make_contact_sheet
from tools.qa.pdf_qa import audit_pdf


def _utc_now() -> str:
    """返回当前 UTC 时间。

    Returns:
        RFC 3339 UTC 时间字符串。
    """
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _check(check_id: str, payload: dict[str, Any], details: str) -> dict[str, Any]:
    """将子检查标准化为报告条目。

    Args:
        check_id: 稳定检查 ID。
        payload: 子检查原始结果。
        details: 人类可读说明。

    Returns:
        统一的检查条目。
    """
    return {"id": check_id, "passed": bool(payload.get("success")), "details": details, "payload": payload}


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
    pdf_report = audit_pdf(
        pdf,
        anonymous_required=anonymous_required,
        anonymous_terms=anonymous_terms,
    )
    checks.append(_check("pdf", pdf_report, "PDF、空白页、裁切、文字重叠和重复编号"))
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
    pdf_open = any(
        item["id"] == "pdf-open" and item["passed"] for item in pdf_report["checks"]
    )
    if pdf_open:
        try:
            make_contact_sheet(pdf, contact_sheet)
        except Exception as exc:
            contact_error = str(exc)
    else:
        contact_error = "PDF 未通过基础读取检查，未生成联系表"
    checks.append({"id": "contact-sheet", "passed": contact_error is None, "details": contact_error or str(contact_sheet.relative_to(root))})
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
        "warnings": pdf_report.get("warnings", []),
        "generated_at": _utc_now(),
    }
    atomic_json(root / "qa" / "mechanical-qa.json", report)
    lines = ["# 机械验证报告", "", f"- 状态：{report['status']}", f"- 运行：{state['run_id']}", "", "## 检查结果", ""]
    for item in checks:
        lines.append(f"- {'通过' if item['passed'] else '失败'}｜{item['id']}：{item['details']}")
    (root / "reports" / "VERIFY_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
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
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
