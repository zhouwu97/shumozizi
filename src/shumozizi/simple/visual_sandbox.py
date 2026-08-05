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
_PENDING_PROMOTION_STATUS = "selected_pending_promotion"


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
                "figure_tier": str(raw.get("figure_tier", "supporting_figure")),
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
    candidate_structures: dict[str, str] | None = None,
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
    structures = candidate_structures or {}
    relative_candidates = [relative_inside(root, path).as_posix() for path in candidates]
    if target.get("figure_tier") == "hero_figure":
        if len(candidates) < 2:
            raise ContractError("hero_figure 至少需要两个候选设计")
        missing = [path for path in relative_candidates if not str(structures.get(path, "")).strip()]
        if missing:
            raise ContractError("hero_figure 必须为每个候选声明 visual_structure")
        if len({str(structures[path]).strip() for path in relative_candidates}) < 2:
            raise ContractError("hero_figure 候选必须包含至少两种不同 visual_structure")
    records = [
        {
            "path": relative_inside(root, path).as_posix(),
            "sha256": sha256_file(path),
            **(
                {"visual_structure": str(structures[relative_inside(root, path).as_posix()]).strip()}
                if relative_inside(root, path).as_posix() in structures
                else {}
            ),
        }
        for path in candidates
    ]
    payload = {
        "schema_name": "visual_competition",
        "schema_version": "1.0",
        "run_id": ideas["run_id"],
        "idea_id": idea_id,
        "figure_tier": target.get("figure_tier", "supporting_figure"),
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


def _current_figure_version(root: Path, figure_id: str) -> str | None:
    """从 current 图索引或其晋级回执中读取当前候选版本。

    旧图可能没有版本字段；此时明确返回 ``None``，避免把不存在的版本号伪造为
    已完成闭环的证据。
    """
    index_path = root / "figures" / "index.json"
    if not index_path.is_file():
        return None
    try:
        index = load_json(index_path)
        current = [
            item
            for item in index.get("figures", [])
            if isinstance(item, dict)
            and item.get("figure_id") == figure_id
            and item.get("status") == "current"
        ]
        if not current:
            return None
        entry = current[-1]
        version = entry.get("selected_version")
        if isinstance(version, str) and version.strip():
            return version
        receipt = entry.get("promotion_receipt")
        if not isinstance(receipt, dict) or not isinstance(receipt.get("path"), str):
            return None
        receipt_path = resolve_inside(root, receipt["path"], must_exist=True)
        recorded = load_json(receipt_path).get("candidate_version")
        return recorded if isinstance(recorded, str) and recorded.strip() else None
    except (ContractError, OSError, TypeError, ValueError):
        return None


def pending_visual_promotions(run_dir: Path) -> list[dict[str, Any]]:
    """返回尚未晋级为 current 的 Sandbox 选图记录。

    缺少 Sandbox 文件表示尚无草图流程，不能视为错误；调用方可据此决定是否需要
    阻断最终 Candidate。损坏的已存在文档仍由 ``read_visual_ideas`` 显式报错。
    """
    root = run_dir.resolve()
    if not (root / VISUAL_IDEAS_PATH).is_file():
        return []
    ideas = read_visual_ideas(root)
    pending: list[dict[str, Any]] = []
    for item in ideas["ideas"]:
        record = item.get("pending_promotion")
        if item.get("status") != _PENDING_PROMOTION_STATUS or not isinstance(record, dict):
            continue
        pending.append({"idea_id": item["id"], **record})
    return pending


def close_pending_visual_promotion(
    run_dir: Path,
    *,
    figure_id: str,
    candidate_version: str,
    promotion_receipt_path: str,
) -> list[str]:
    """在正式图晋级后关闭匹配的 Sandbox pending 状态。

    只关闭图 ID 和候选版本同时匹配的记录，避免较早版本的 promotion 意外覆盖
    已选中的更新设计。
    """
    root = run_dir.resolve()
    if not (root / VISUAL_IDEAS_PATH).is_file():
        return []
    ideas = read_visual_ideas(root)
    receipt = resolve_inside(root, promotion_receipt_path, must_exist=True)
    closed: list[str] = []
    for item in ideas["ideas"]:
        pending = item.get("pending_promotion")
        if (
            item.get("status") != _PENDING_PROMOTION_STATUS
            or not isinstance(pending, dict)
            or pending.get("figure_id") != figure_id
            or pending.get("candidate_version") != candidate_version
        ):
            continue
        item["status"] = "promoted"
        item.pop("pending_promotion", None)
        item["promotion_receipt"] = {
            "path": relative_inside(root, receipt).as_posix(),
            "sha256": sha256_file(receipt),
            "candidate_version": candidate_version,
            "promoted_at": utc_now(),
        }
        closed.append(str(item["id"]))
    if closed:
        ideas["updated_at"] = utc_now()
        require_valid(ideas, "visual_ideas")
        atomic_json(root / VISUAL_IDEAS_PATH, ideas)
    return closed


def graduate_visual_candidate(
    run_dir: Path,
    idea_id: str,
    *,
    candidate_version: str = "v1",
    figure_id: str | None = None,
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
    target_figure_id = figure_id or idea_id
    if not target_figure_id.replace("-", "").replace("_", "").replace(".", "").isalnum():
        raise ContractError("figure_id 必须是字母、数字、点、连字符或下划线")
    target_dir = root / "figures/work" / target_figure_id / candidate_version
    ideas = read_visual_ideas(root)
    item = next(raw for raw in ideas["ideas"] if raw["id"] == idea_id)
    selected_reference = relative_inside(root, source).as_posix()
    selected_sha256 = sha256_file(source)
    item["status"] = _PENDING_PROMOTION_STATUS
    item["pending_promotion"] = {
        "status": _PENDING_PROMOTION_STATUS,
        "figure_id": target_figure_id,
        "candidate_version": candidate_version,
        "selected_design_reference": selected_reference,
        "selected_design_sha256": selected_sha256,
        "current_version": _current_figure_version(root, target_figure_id),
        "target_work_dir": relative_inside(root, target_dir).as_posix(),
        "selected_at": utc_now(),
    }
    ideas["updated_at"] = utc_now()
    require_valid(ideas, "visual_ideas")
    atomic_json(root / VISUAL_IDEAS_PATH, ideas)
    return {
        "idea_id": idea_id,
        "figure_id": target_figure_id,
        "candidate_version": candidate_version,
        "selected_design_reference": selected_reference,
        "selected_design_sha256": selected_sha256,
        "current_version": item["pending_promotion"]["current_version"],
        "status": _PENDING_PROMOTION_STATUS,
        "formal_render_required": True,
        "target_work_dir": relative_inside(root, target_dir).as_posix(),
        "next_action": "regenerate_from_current_sources",
    }
