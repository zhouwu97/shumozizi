"""记录多种论文主线并让独立读者选择，而不是生成唯一布局。"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.core.schema import require_valid
from shumozizi.paper.author_pass import RESEARCH_PACKAGE_PATH, require_author_pass
from shumozizi.simple.state import read_simple_state, utc_now

NARRATIVE_COMPETITION_PATH = Path("paper/generated/narrative-competition.json")


def write_narrative_candidates(
    run_dir: Path, candidates: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    """保存 Author 提出的叙事候选；候选数量只给建议，不设创作硬门。"""
    root = run_dir.resolve()
    require_author_pass(root)
    normalized = [dict(item) for item in candidates]
    identifiers = [str(item.get("candidate_id", "")) for item in normalized]
    if len(identifiers) != len(set(identifiers)):
        raise ContractError("narrative candidate_id 必须唯一")
    payload = {
        "schema_name": "narrative_competition",
        "schema_version": "1.0",
        "run_id": read_simple_state(root)["run_id"],
        "research_package_sha256": sha256_file(root / RESEARCH_PACKAGE_PATH),
        "status": "draft",
        "candidates": normalized,
        "updated_at": utc_now(),
    }
    require_valid(payload, "narrative_competition")
    atomic_json(root / NARRATIVE_COMPETITION_PATH, payload)
    return payload


def select_narrative_candidate(
    run_dir: Path,
    candidate_id: str,
    *,
    reviewer_context_id: str,
    selection_reason: str,
    revision_advice: str,
) -> dict[str, Any]:
    """记录 fresh reviewer 的叙事选择，不把选择升级为科学证据。"""
    root = run_dir.resolve()
    payload = load_json(root / NARRATIVE_COMPETITION_PATH)
    require_valid(payload, "narrative_competition")
    if payload.get("research_package_sha256") != sha256_file(root / RESEARCH_PACKAGE_PATH):
        raise ContractError("Research Package 已变化，叙事候选必须重建")
    if candidate_id not in {item["candidate_id"] for item in payload["candidates"]}:
        raise ContractError(f"找不到叙事候选: {candidate_id}")
    if not reviewer_context_id.strip():
        raise ContractError("叙事选择必须绑定 reviewer_context_id")
    payload.update(
        {
            "status": "reviewed",
            "selected_candidate_id": candidate_id,
            "reviewer_context_id": reviewer_context_id,
            "selection_reason": selection_reason,
            "revision_advice": revision_advice,
            "updated_at": utc_now(),
        }
    )
    require_valid(payload, "narrative_competition")
    atomic_json(root / NARRATIVE_COMPETITION_PATH, payload)
    return payload


def narrative_competition_freshness(run_dir: Path) -> dict[str, Any]:
    """检查叙事竞争是否仍绑定当前 Research Package。"""
    root = run_dir.resolve()
    try:
        payload = load_json(root / NARRATIVE_COMPETITION_PATH)
        require_valid(payload, "narrative_competition")
        current = payload.get("research_package_sha256") == sha256_file(
            root / RESEARCH_PACKAGE_PATH
        )
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return {"current": False, "reason": str(exc)}
    return {"current": current, "status": payload["status"], "advisory_only": True}
