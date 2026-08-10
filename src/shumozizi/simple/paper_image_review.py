"""论文解释图候选的确定性状态机。

审图结果可以来自人工或视觉模型，但只有 Hard 全部 PASS 才能进入选择；
该模块不会把候选 PNG 直接伪装成正式论文图。
"""

from __future__ import annotations

import shutil
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
from shumozizi.simple.figures import read_figure_index, require_figure_index
from shumozizi.simple.paper_image_types import (
    GENERIC_BOX_LEVELS,
    HARD_REVIEW_CHECKS,
    MIN_NON_TEXT_VISUAL_ELEMENTS,
    REVIEW_OUTCOMES,
    REVIEW_VERDICTS,
    SOFT_REVIEW_CHECKS,
)
from shumozizi.simple.state import utc_now
from shumozizi.simple.visual_sandbox import read_visual_ideas

HARD_CHECKS = HARD_REVIEW_CHECKS
SOFT_CHECKS = SOFT_REVIEW_CHECKS


def validate_review(review: dict[str, Any]) -> dict[str, Any]:
    """规范并验证一份候选审图结果。"""
    if not isinstance(review, dict):
        raise ContractError("paper image review 必须是对象")
    normalized = dict(review)
    hard = normalized.get("hard_checks")
    if not isinstance(hard, dict):
        raise ContractError("hard_checks 必须是对象")
    elements = normalized.get("non_text_visual_elements")
    if not isinstance(elements, list) or any(
        not isinstance(item, str) or not item.strip() for item in elements
    ):
        raise ContractError("non_text_visual_elements 必须是非空字符串列表")
    issues = normalized.get("issues", [])
    if not isinstance(issues, list) or any(
        not isinstance(item, str) or not item.strip() for item in issues
    ):
        raise ContractError("issues 必须是字符串列表")
    if len(elements) < MIN_NON_TEXT_VISUAL_ELEMENTS:
        issues.append(f"非文字视觉元素少于 {MIN_NON_TEXT_VISUAL_ELEMENTS} 种")
    normalized["issues"] = issues
    hard = dict(hard)
    hard["minimum_non_text_visuals"] = (
        "PASS" if len(elements) >= MIN_NON_TEXT_VISUAL_ELEMENTS else "FAIL"
    )
    normalized["hard_checks"] = hard
    missing = [key for key in HARD_CHECKS if key not in hard]
    if missing:
        raise ContractError("hard_checks 缺少: " + ", ".join(missing))
    invalid = [key for key in HARD_CHECKS if hard[key] not in REVIEW_OUTCOMES]
    if invalid:
        raise ContractError("hard check 状态无效: " + ", ".join(invalid))
    score = normalized.get("soft_score", 0.0)
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= float(score) <= 10:
        raise ContractError("soft_score 必须位于 0 到 10")
    richness = normalized.get("academic_visual_richness")
    if isinstance(richness, bool) or not isinstance(richness, (int, float)) or not 0 <= float(richness) <= 10:
        raise ContractError("academic_visual_richness 必须位于 0 到 10")
    generic_score = normalized.get("generic_box_diagram_score")
    if isinstance(generic_score, bool) or not isinstance(generic_score, (int, float)) or not 0 <= float(generic_score) <= 10:
        raise ContractError("generic_box_diagram_score 必须位于 0 到 10")
    generic_level = normalized.get("generic_box_diagram_level")
    if generic_level not in GENERIC_BOX_LEVELS:
        raise ContractError("generic_box_diagram_level 必须是 LOW、MEDIUM 或 HIGH")
    raw_score = float(score)
    cap_reasons: list[str] = []
    if generic_level == "HIGH" or float(generic_score) >= 7:
        raw_score = min(raw_score, 6.5)
        cap_reasons.append("generic_box_diagram=HIGH")
    if float(richness) < 4:
        raw_score = min(raw_score, 5.5)
        cap_reasons.append("academic_visual_richness<4")
    elif float(richness) < 7:
        raw_score = min(raw_score, 7.5)
        cap_reasons.append("academic_visual_richness<7")
    normalized["raw_soft_score"] = float(score)
    normalized["soft_score"] = round(raw_score, 2)
    if cap_reasons:
        normalized["score_cap_reasons"] = cap_reasons
        normalized.setdefault("issues", []).extend(cap_reasons)
    normalized["hard_pass"] = all(hard[key] == "PASS" for key in HARD_CHECKS)
    normalized["verdict"] = "KEEP" if normalized["hard_pass"] else "RETRY"
    if normalized.get("attempt", 1) >= 2 and not normalized["hard_pass"]:
        normalized["verdict"] = "DROP_AI_IMAGE"
    if normalized["verdict"] not in REVIEW_VERDICTS:
        raise ContractError("审图 verdict 无效")
    return normalized


def select_review(reviewed: list[dict[str, Any]]) -> dict[str, Any]:
    """在 Hard PASS 候选中按 soft score 选择最高者。"""
    valid = [validate_review(item) for item in reviewed]
    passed = [item for item in valid if item["hard_pass"]]
    if not passed:
        return {"verdict": "RETRY", "selected_candidate": None, "candidates": valid}
    selected = max(passed, key=lambda item: float(item.get("soft_score", 0.0)))
    return {
        "verdict": "KEEP",
        "selected_candidate": selected.get("candidate"),
        "candidates": valid,
    }


def invalidate_promoted_candidate(
    run_dir: Path,
    *,
    figure_id: str,
    image_id: str,
    opportunity_id: str | None = None,
    reason: str,
    review_path: str | None = None,
) -> dict[str, Any]:
    """撤销未达到论文信息图质量门的 current 图并保留可恢复归档。

    该动作只处理视觉晋级状态，不修改模型、结果或正式数字。旧输出会复制到
    ``figures/archive`` 后从 ``figures/current`` 移出，避免论文继续静默消费。
    """
    if not reason.strip():
        raise ContractError("撤销图的 reason 不能为空")
    root = run_dir.resolve()
    index = read_figure_index(root)
    targets = [
        item
        for item in index["figures"]
        if item.get("figure_id") == figure_id and item.get("status") == "current"
    ]
    if not targets:
        raise ContractError(f"找不到 current 图: {figure_id}")
    archive_dir = root / "figures/archive" / figure_id / "quality-gate-v2"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived: list[dict[str, str]] = []
    for item in targets:
        for output in item.get("outputs", []):
            if not isinstance(output, dict) or not isinstance(output.get("path"), str):
                continue
            source = resolve_inside(root, output["path"], must_exist=True)
            destination = archive_dir / source.name
            shutil.copy2(source, destination)
            archived.append(
                {
                    "original": relative_inside(root, source).as_posix(),
                    "archive": relative_inside(root, destination).as_posix(),
                    "sha256": sha256_file(destination),
                }
            )
    quality_path = root / "figures/reviews/sandbox" / image_id / "quality-gate-v2.json"
    old_review = root / review_path if review_path else None
    evidence = {
        "schema_name": "paper_image_quality_gate",
        "schema_version": "2.0",
        "run_id": root.name,
        "image_id": image_id,
        "figure_id": figure_id,
        "verdict": "DROP_AI_IMAGE",
        "reason": reason.strip(),
        "review_path": review_path,
        "review_sha256": sha256_file(old_review) if old_review and old_review.is_file() else None,
        "invalidated_at": utc_now(),
        "archived_outputs": archived,
        "quality_requirements": {
            "style_reference": "academic_bilingual_infographic_v1",
            "minimum_non_text_visual_elements": 2,
            "required_soft_check": "academic_visual_richness",
            "generic_box_diagram_cap": 6.5,
        },
    }
    atomic_json(quality_path, evidence)
    current_paths: list[Path] = []
    for item in targets:
        item["status"] = "superseded"
        item["paper_allowed"] = False
        item["superseded_reason"] = reason.strip()
        for output in item.get("outputs", []):
            if isinstance(output, dict) and isinstance(output.get("path"), str):
                source = resolve_inside(root, output["path"], must_exist=False)
                current_paths.append(source)
    require_figure_index(index)
    atomic_json(root / "figures/index.json", index)
    for source in current_paths:
        if source.is_file():
            source.unlink()
    ideas_path = root / "figures/visual-ideas.json"
    if ideas_path.is_file():
        ideas = read_visual_ideas(root)
        for idea in ideas["ideas"]:
            if idea.get("id") == image_id:
                idea["status"] = "dropped"
        atomic_json(ideas_path, ideas)
    opportunities_path = root / "figures/visual-opportunities.json"
    if opportunities_path.is_file() and opportunity_id:
        opportunities = load_json(opportunities_path)
        for opportunity in opportunities.get("opportunities", []):
            if (
                isinstance(opportunity, dict)
                and opportunity.get("opportunity_id") == opportunity_id
            ):
                opportunity["status"] = "drop"
                opportunity["critic_verdict"] = "DROP"
                opportunity["critic_path"] = relative_inside(root, quality_path).as_posix()
        atomic_json(opportunities_path, opportunities)
    return evidence
