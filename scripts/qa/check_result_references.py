"""检查论文显式结果引用是否指向仍可使用的 v3 结果。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.qa.provenance_markers import RESULT_REFERENCE, paper_sources
from shumozizi.core.io import ContractError, load_json
from shumozizi.simple.quality import quality_allows_paper
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import read_simple_state


def _question_evidence_requirements(run_dir: Path) -> tuple[dict[str, set[str]], list[str]]:
    """读取内容蓝图中已允许写入生产事实的逐问结果要求。"""
    blueprint_path = run_dir / "paper" / "content_blueprint.json"
    if not blueprint_path.is_file():
        return {}, []
    try:
        blueprint = load_json(blueprint_path)
        sections = blueprint["sections"]
        if not isinstance(sections, list):
            raise ContractError("内容蓝图 sections 必须是数组")
        requirements: dict[str, set[str]] = {}
        for section in sections:
            if not isinstance(section, dict) or section.get("kind") != "question":
                continue
            question_id = section.get("question_id")
            evidence = section.get("evidence_result_ids")
            if (
                not isinstance(question_id, str)
                or not section.get("draft_allowed")
                or not isinstance(evidence, list)
            ):
                continue
            result_ids = {item for item in evidence if isinstance(item, str) and item}
            if result_ids:
                requirements[question_id] = result_ids
        return requirements, []
    except (ContractError, KeyError, OSError, TypeError, ValueError) as exc:
        return {}, [f"内容蓝图无法读取逐问结果要求: {exc}"]


def check_result_references(run_dir: Path) -> dict[str, Any]:
    """验证结果注释只引用 current 且执行事实有效的结果。

    Args:
        run_dir: v3 运行目录。

    Returns:
        引用列表、失效引用和通过状态。
    """
    state = read_simple_state(run_dir)
    index = read_result_index(run_dir)
    results = {item["result_id"]: item for item in index["results"]}
    references: list[dict[str, str]] = []
    for path in paper_sources(run_dir):
        for result_id in RESULT_REFERENCE.findall(path.read_text(encoding="utf-8", errors="replace")):
            references.append({"file": path.relative_to(run_dir).as_posix(), "result_id": result_id})
    invalid: list[dict[str, str]] = []
    for reference in references:
        result = results.get(reference["result_id"])
        reason = None
        if state["phase"] == "blocked":
            reason = "运行处于 blocked 状态"
        elif result is None:
            reason = "结果不存在"
        elif result["status"] != "current" or not result["execution_valid"]:
            reason = "结果不是 current 且 execution_valid=true"
        elif not quality_allows_paper(run_dir, reference["result_id"]):
            reason = "结果未通过质量层放行"
        if reason is not None:
            invalid.append({**reference, "reason": reason})
    requirements, blueprint_errors = _question_evidence_requirements(run_dir)
    referenced_ids = {reference["result_id"] for reference in references}
    missing_question_references = sorted(
        question_id
        for question_id, evidence_ids in requirements.items()
        if not (referenced_ids & evidence_ids)
    )
    return {
        "success": not invalid and not blueprint_errors and not missing_question_references,
        "references": references,
        "invalid": invalid,
        "question_evidence_requirements": {
            question_id: sorted(evidence_ids)
            for question_id, evidence_ids in sorted(requirements.items())
        },
        "missing_question_references": missing_question_references,
        "blueprint_errors": blueprint_errors,
    }
