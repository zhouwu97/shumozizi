"""提供无需正式 Figure Contract 的视觉草图、竞争和晋级入口。"""

from __future__ import annotations

from collections.abc import Iterable
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
from shumozizi.core.schema import require_valid
from shumozizi.simple.state import read_simple_state, utc_now

VISUAL_IDEAS_PATH = Path("figures/visual-ideas.json")
VISUAL_SANDBOX_ROOT = Path("figures/sandbox")
VISUAL_COMPETITION_ROOT = Path("figures/reviews/sandbox")


def write_visual_ideas(run_dir: Path, ideas: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """原子写入轻量视觉想法，不要求结果、脚本或最终版式绑定。"""
    root = run_dir.resolve()
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in ideas:
        if not isinstance(raw, dict):
            raise ContractError("visual idea 必须是对象")
        identifier = str(raw.get("id", "")).strip()
        if not identifier or identifier in seen:
            raise ContractError("visual idea id 必须非空且唯一")
        seen.add(identifier)
        normalized.append(
            {
                "id": identifier,
                "question": str(raw.get("question", "")).strip(),
                "sources": list(dict.fromkeys(map(str, raw.get("sources", [])))),
                "idea": str(raw.get("idea", "")).strip(),
                "status": str(raw.get("status", "sketch")),
                **(
                    {"selected_candidate": str(raw["selected_candidate"])}
                    if raw.get("selected_candidate")
                    else {}
                ),
            }
        )
    payload = {
        "schema_name": "visual_ideas",
        "schema_version": "1.0",
        "run_id": read_simple_state(root)["run_id"],
        "ideas": normalized,
        "updated_at": utc_now(),
    }
    require_valid(payload, "visual_ideas")
    atomic_json(root / VISUAL_IDEAS_PATH, payload)
    return payload


def read_visual_ideas(run_dir: Path) -> dict[str, Any]:
    """读取并校验视觉想法。"""
    payload = load_json(run_dir.resolve() / VISUAL_IDEAS_PATH)
    require_valid(payload, "visual_ideas")
    return payload


def sandbox_candidates(run_dir: Path, idea_id: str) -> list[Path]:
    """列出某想法的草图文件；草图可只有 PNG、PDF 或其他静态图格式。"""
    root = run_dir.resolve()
    directory = resolve_inside(root, (VISUAL_SANDBOX_ROOT / idea_id).as_posix())
    if not directory.is_dir():
        return []
    return sorted(
        path for path in directory.iterdir() if path.is_file() and path.suffix.casefold() in {".png", ".pdf", ".jpg", ".jpeg", ".webp"}
    )


def record_visual_competition(
    run_dir: Path,
    idea_id: str,
    *,
    selected_candidate: str,
    reviewer_context_id: str,
    fastest_mechanism: str,
    full_width_value: str,
    table_redundancy: str,
    rationale: str,
) -> dict[str, Any]:
    """记录候选图竞争结论，不把草图误登记为 current 证据。"""
    root = run_dir.resolve()
    ideas = read_visual_ideas(root)
    target = next((item for item in ideas["ideas"] if item["id"] == idea_id), None)
    if target is None:
        raise ContractError(f"找不到 visual idea: {idea_id}")
    candidates = sandbox_candidates(root, idea_id)
    selected = resolve_inside(root, selected_candidate, must_exist=True)
    if selected not in candidates:
        raise ContractError("selected_candidate 必须位于对应 figures/sandbox 目录")
    records = [
        {"path": relative_inside(root, path).as_posix(), "sha256": sha256_file(path)}
        for path in candidates
    ]
    payload = {
        "schema_name": "visual_competition",
        "schema_version": "1.0",
        "run_id": ideas["run_id"],
        "idea_id": idea_id,
        "reviewer_context_id": reviewer_context_id,
        "candidates": records,
        "selected_candidate": relative_inside(root, selected).as_posix(),
        "fastest_mechanism": fastest_mechanism,
        "full_width_value": full_width_value,
        "table_redundancy": table_redundancy,
        "rationale": rationale,
        "recorded_at": utc_now(),
    }
    require_valid(payload, "visual_competition")
    target["status"] = "selected"
    target["selected_candidate"] = payload["selected_candidate"]
    ideas["updated_at"] = utc_now()
    require_valid(ideas, "visual_ideas")
    atomic_json(root / VISUAL_IDEAS_PATH, ideas)
    atomic_json(root / VISUAL_COMPETITION_ROOT / f"{idea_id}.json", payload)
    return payload


def graduate_visual_candidate(
    run_dir: Path, idea_id: str, *, candidate_version: str = "v1"
) -> dict[str, Any]:
    """冻结胜出设计参考，并要求从 current 数据重新生成正式图。

    Sandbox 文件只证明视觉方向被选中，不具备 renderer、源码和结果绑定，
    因此不能复制进 ``figures/work`` 冒充正式候选。
    """
    root = run_dir.resolve()
    review = load_json(root / VISUAL_COMPETITION_ROOT / f"{idea_id}.json")
    require_valid(review, "visual_competition")
    source = resolve_inside(root, review["selected_candidate"], must_exist=True)
    if sha256_file(source) != next(
        item["sha256"] for item in review["candidates"] if item["path"] == review["selected_candidate"]
    ):
        raise ContractError("胜出草图已变化，必须重新视觉竞争")
    target_dir = root / "figures/work" / idea_id / candidate_version
    ideas = read_visual_ideas(root)
    item = next(raw for raw in ideas["ideas"] if raw["id"] == idea_id)
    item["status"] = "selected"
    ideas["updated_at"] = utc_now()
    atomic_json(root / VISUAL_IDEAS_PATH, ideas)
    return {
        "idea_id": idea_id,
        "candidate_version": candidate_version,
        "selected_design_reference": relative_inside(root, source).as_posix(),
        "selected_design_sha256": sha256_file(source),
        "formal_render_required": True,
        "target_work_dir": relative_inside(root, target_dir).as_posix(),
        "next_action": "regenerate_from_current_sources",
    }
