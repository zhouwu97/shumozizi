"""把审核失败确定性转换为最小影响范围的定向修复计划。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shumozizi.core.io import atomic_json, load_json, relative_inside, sha256_file
from shumozizi.core.schema import require_valid

CHANGE_LEVEL_ORDER = {f"L{level}": level for level in range(6)}
CHANGE_CLASS_DEFAULT_LEVEL = {
    "EVIDENCE_METADATA": "L2",
    "IMPLEMENTATION_DETAIL": "L3",
    "VALIDATION_DETAIL": "L3",
    "EXPERIMENT_DESIGN_CHANGE": "L3",
    "SPEC_CLARIFICATION": "L4",
    "SPEC_COMPLETION": "L4",
    "ROUTE_CORE_CHANGE": "L5",
    "PROBLEM_INTERPRETATION_CHANGE": "L5",
}

def _finding_change_level(finding: dict[str, Any]) -> str:
    declared = finding.get("change_level")
    if finding.get("route_impact") == "material" or finding.get("change_class") in {
        "ROUTE_CORE_CHANGE",
        "PROBLEM_INTERPRETATION_CHANGE",
    }:
        return "L5"
    return str(
        declared or CHANGE_CLASS_DEFAULT_LEVEL.get(finding.get("change_class", ""), "L2")
    )


def finding_requires_route_reapproval(finding: dict[str, Any]) -> bool:
    """只有 finding 的最终有效修改等级为 L5 时才重新批准路线。"""
    return _finding_change_level(finding) == "L5"


def _level_retests(change_level: str, questions: list[str]) -> list[str]:
    question_retests = [f"R2_EXPERIMENT_{question}" for question in questions]
    return {
        "L0": ["RECOMPILE", "DIFF_CHECK"],
        "L1": ["R4_FORMAT_VISUAL"],
        "L2": ["R3_PAPER_LOGIC"],
        "L3": [*question_retests, "R3_PAPER_LOGIC", "R4_FORMAT_VISUAL", "R5_COMPREHENSIVE"],
        "L4": [
            "R1_MODELING",
            *question_retests,
            "R3_PAPER_LOGIC",
            "R4_FORMAT_VISUAL",
            "R5_COMPREHENSIVE",
        ],
        "L5": ["HUMAN_ROUTE_REAPPROVAL"],
    }[change_level]


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
            "change_class": "EVIDENCE_METADATA",
            "change_level": "L2",
            "affected_questions": [],
            "route_impact": "none",
            "changed_route_core_fields": [],
        }
    ]
    scopes: list[dict[str, Any]] = []
    axes: set[str] = set()
    retests = set(report.get("required_retests", []))
    request_path = report_path.with_name("review_request.json")
    request_question = load_json(request_path).get("question_id") if request_path.is_file() else None
    affected_questions: set[str] = set()
    levels: list[str] = []
    for finding in findings:
        axis = finding.get("axis") or ("integrity" if finding.get("severity") == "P0" else "quality")
        axes.add(axis)
        affected = finding.get("affected_stage", stage)
        level = _finding_change_level(finding)
        levels.append(level)
        questions = [str(item) for item in finding.get("affected_questions", [])]
        if not questions and request_question:
            questions = [str(request_question)]
        affected_questions.update(questions)
        retests.update(finding.get("required_retests", _level_retests(level, questions)))
        scopes.append(
            {
                "finding_id": finding["finding_id"],
                "axis": axis,
                "affected_stage": affected,
                "files": finding.get("affected_files", []),
                "expected_improvement": finding.get("expected_improvement", finding["remediation"]),
                "change_level": level,
                "affected_questions": questions,
                "change_class": finding["change_class"],
                "route_impact": finding["route_impact"],
                "changed_route_core_fields": finding["changed_route_core_fields"],
            }
        )
    axis = "both" if len(axes) > 1 or "both" in axes else next(iter(axes))
    route_reapproval = any(finding_requires_route_reapproval(finding) for finding in findings)
    change_level = max(levels, key=CHANGE_LEVEL_ORDER.__getitem__)
    if change_level == "L5":
        route_reapproval = True
    document = {
        "schema_name": "repair_plan",
        "schema_version": "2.0",
        "run_id": run_dir.name,
        "source_report_path": relative_inside(run_dir, report_path).as_posix(),
        "source_report_sha256": sha256_file(report_path),
        "axis": axis,
        "change_level": change_level,
        "affected_questions": sorted(affected_questions),
        "repair_scope": scopes,
        "required_retests": sorted(retests),
        "route_reapproval_required": route_reapproval,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    require_valid(document, "repair_plan")
    path = report_path.with_name("REPAIR_PLAN.json")
    atomic_json(path, document)
    return path
