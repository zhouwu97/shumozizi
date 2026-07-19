"""聚合 PDF、封存结果、证据和配置锁的基础硬检查。"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from shumozizi.core.io import atomic_json, load_json, sha256_file
from shumozizi.core.schema import require_valid
from shumozizi.evidence.adapters import audit_paper_evidence
from shumozizi.evidence.validator import validate_evidence
from shumozizi.profiles.lock import verify_run_config_lock
from shumozizi.qa.adapters import run_mechanical_qa
from shumozizi.qa.visual import inspect_pdf_visual
from shumozizi.results.sealing import verify_sealed_result
from shumozizi.workflow.source_package import SOURCE_MANIFEST_PATH, verify_source_manifest

PLACEHOLDER = re.compile(r"\b(?:TODO|TBD|PLACEHOLDER)\b", re.IGNORECASE)


def utc_now() -> str:
    """返回 RFC 3339 UTC 时间。"""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def run_submission_qa(run_id: str, final_pdf: Path) -> dict[str, Any]:
    """从锁定配置运行基础提交 QA；不接受临时 Profile 参数。"""
    pdf = final_pdf.resolve()
    run_dir = pdf.parent
    while run_dir.name != run_id and run_dir != run_dir.parent:
        run_dir = run_dir.parent
    checks: list[dict[str, Any]] = []

    def check(check_id: str, passed: bool, details: str, *, hard: bool = True) -> None:
        checks.append({"check_id": check_id, "passed": passed, "hard": hard, "details": details})

    try:
        verify_run_config_lock(run_dir.parents[1], run_dir)
        check("run-config-lock", True, "配置锁与 Profile 哈希有效")
    except Exception as exc:
        check("run-config-lock", False, str(exc))
    pdf_text = ""
    if not pdf.is_file():
        check("pdf-exists", False, f"最终 PDF 不存在: {pdf}")
    else:
        check("pdf-exists", True, str(pdf))
        try:
            reader = PdfReader(str(pdf))
            check("pdf-open", True, "PDF 可打开")
            check("pdf-pages", len(reader.pages) > 0, f"页数: {len(reader.pages)}")
            pdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)
            content_bytes = sum(
                len(page.get_contents().get_data()) if page.get_contents() else 0
                for page in reader.pages
            )
            check(
                "pdf-not-blank",
                bool(pdf_text.strip()) or content_bytes > 128,
                "PDF 含文本或页面绘制内容",
            )
        except Exception as exc:
            check("pdf-open", False, f"PDF 无法打开: {exc}")
    registry_path = run_dir / "results" / "result_registry.json"
    try:
        registry = load_json(registry_path)
        require_valid(registry, "result_registry")
        accepted = [item for item in registry["results"] if item["status"] == "accepted"]
        result_errors = []
        for item in accepted:
            verification = verify_sealed_result(run_dir, item["result_id"])
            result_errors.extend(verification["errors"])
        check(
            "sealed-results",
            not result_errors,
            "; ".join(result_errors) or f"{len(accepted)} 个 accepted 结果通过",
        )
    except Exception as exc:
        check("sealed-results", False, str(exc))
    source_package = verify_source_manifest(run_dir, expected_final_pdf=pdf)
    check(
        "source-package",
        source_package["valid"],
        "; ".join(source_package["errors"])
        or "Python 与 MATLAB/Octave 源码包及其事实绑定通过",
    )
    evidence = validate_evidence(run_dir, pdf)
    check(
        "paper-evidence",
        evidence["status"] == "pass",
        "; ".join(evidence["errors"]) or "论文证据实值通过",
    )
    evidence_adapter = audit_paper_evidence(run_dir, pdf)
    check(
        "paper-evidence-adapter",
        evidence_adapter["status"] == "pass",
        "; ".join(evidence_adapter["errors"]) or "增强证据审计通过",
    )
    mechanical_adapter = run_mechanical_qa(run_id, pdf)
    check(
        "mechanical-qa-adapter",
        mechanical_adapter["status"] == "pass",
        "; ".join(mechanical_adapter["errors"]) or "机械提交检查通过",
    )
    try:
        lock = load_json(run_dir / "config" / "RUN_CONFIG_LOCK.json")
        profile = load_json(run_dir.parents[1] / lock["competition_profile"]["profile_path"])
        visual = inspect_pdf_visual(
            pdf,
            max_bytes=profile.get("max_file_size_bytes"),
            enforce_a4=bool(profile.get("a4_required", False)),
        )
    except Exception as exc:
        visual = {"status": "blocked", "errors": [str(exc)], "warnings": [], "checks": []}
    check(
        "pdf-visual",
        visual["status"] == "pass",
        "; ".join(visual["errors"]) or "A4 页面、字体资源和绘制内容检查通过",
    )
    source_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted((run_dir / "paper").rglob("*.typ"))
    )
    matches = sorted(set(PLACEHOLDER.findall(source_text + "\n" + pdf_text)))
    check(
        "placeholders",
        not matches,
        "未发现占位符" if not matches else f"发现占位符: {', '.join(matches)}",
    )
    hard_failures = [item["check_id"] for item in checks if item["hard"] and not item["passed"]]
    report = {
        "schema_name": "qa_report",
        "schema_version": "2.0",
        "run_id": run_id,
        "status": "blocked" if hard_failures else "pass",
        "final_pdf_path": pdf.relative_to(run_dir).as_posix() if pdf.is_file() else str(pdf),
        "final_pdf_sha256": sha256_file(pdf) if pdf.is_file() else "0" * 64,
        "run_config_lock_sha256": sha256_file(run_dir / "config" / "RUN_CONFIG_LOCK.json")
        if (run_dir / "config" / "RUN_CONFIG_LOCK.json").is_file()
        else "0" * 64,
        "evidence_report_sha256": sha256_file(run_dir / "review" / "EVIDENCE_VALIDATION.json"),
        "source_manifest_path": SOURCE_MANIFEST_PATH,
        "source_manifest_sha256": source_package["manifest_sha256"] or "0" * 64,
        "checks": checks,
        "hard_failures": hard_failures,
        "warnings": [*evidence_adapter["warnings"], *mechanical_adapter["warnings"], *visual["warnings"]],
        "generated_at": utc_now(),
    }
    require_valid(report, "qa_report")
    atomic_json(run_dir / "review" / "QA_AGGREGATE.json", report)
    return report
