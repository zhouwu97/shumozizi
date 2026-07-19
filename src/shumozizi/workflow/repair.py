"""把审核失败确定性转换为最小影响范围的定向修复计划。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shumozizi.core.io import atomic_json, load_json, relative_inside, sha256_file
from shumozizi.core.schema import require_valid

STAGE_RETESTS = {
    "R1_MODELING": ["R1_MODELING"],
    "R2_EXPERIMENT": ["R2_EXPERIMENT", "R3_PAPER_LOGIC", "R5_COMPREHENSIVE", "J0_FINAL_BLIND_JUDGE"],
    "R3_PAPER_LOGIC": ["R3_PAPER_LOGIC", "R4_FORMAT_VISUAL", "R5_COMPREHENSIVE", "J0_FINAL_BLIND_JUDGE"],
    "R4_FORMAT_VISUAL": ["R4_FORMAT_VISUAL", "R5_COMPREHENSIVE", "J0_FINAL_BLIND_JUDGE"],
    "R5_COMPREHENSIVE": ["R5_COMPREHENSIVE", "J0_FINAL_BLIND_JUDGE"],
    "J0_FINAL_BLIND_JUDGE": ["R5_COMPREHENSIVE", "J0_FINAL_BLIND_JUDGE"],
}


def create_repair_plan(run_dir: Path, report_path: Path) -> Path:
    """依据 finding 元数据生成可机器执行的最小重审范围。"""
    report = load_json(report_path)
    require_valid(report, "review_report")
    stage = report["stage"]
    findings = report["findings"] or [
        {
            "finding_id": f"{stage}-VERDICT",
            "title": f"{stage} 结论未通过",
            "remediation": "按审核结论修复后重新审核",
        }
    ]
    scopes: list[dict[str, Any]] = []
    axes: set[str] = set()
    retests = set(report.get("required_retests", STAGE_RETESTS[stage]))
    for finding in findings:
        axis = finding.get("axis") or ("integrity" if finding.get("severity") == "P0" else "quality")
        axes.add(axis)
        affected = finding.get("affected_stage", stage)
        retests.update(finding.get("required_retests", STAGE_RETESTS.get(affected, [affected])))
        scopes.append(
            {
                "finding_id": finding["finding_id"],
                "axis": axis,
                "affected_stage": affected,
                "files": finding.get("affected_files", []),
                "expected_improvement": finding.get("expected_improvement", finding["remediation"]),
            }
        )
    axis = "both" if len(axes) > 1 or "both" in axes else next(iter(axes))
    route_reapproval = any(scope["affected_stage"] == "R1_MODELING" for scope in scopes)
    document = {
        "schema_name": "repair_plan",
        "schema_version": "2.0",
        "run_id": run_dir.name,
        "source_report_path": relative_inside(run_dir, report_path).as_posix(),
        "source_report_sha256": sha256_file(report_path),
        "axis": axis,
        "repair_scope": scopes,
        "required_retests": sorted(retests),
        "route_reapproval_required": route_reapproval,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    require_valid(document, "repair_plan")
    path = report_path.with_name("REPAIR_PLAN.json")
    atomic_json(path, document)
    return path
