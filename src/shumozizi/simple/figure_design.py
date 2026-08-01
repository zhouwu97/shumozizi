"""视觉机会的设计系统合同。

该合同描述图要回答的读者问题、候选原型、面板和边界，不把“勾选了多少义务”
当作视觉充分性证明；真正的 PNG/PDF 仍须经过 renderer、机械 QA 和人工看图。
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.core.schema import require_valid
from shumozizi.paper.materials import material_pool_digest
from shumozizi.paper.policy import policy_fingerprint
from shumozizi.simple.state import read_simple_state, utc_now

FIGURE_DESIGN_CONTRACT_SCHEMA = "figure_design_contract"
FIGURE_DESIGN_ROOT = Path("figures/work")


def _storyboard_digest(run_dir: Path) -> str | None:
    """返回设计合同所依赖的故事板摘要。"""
    path = run_dir.resolve() / "paper/generated/research_storyboard.json"
    from shumozizi.core.io import sha256_file

    return sha256_file(path) if path.is_file() else None


def _atomic_text(path: Path, value: str) -> None:
    """为设计合同提供同目录原子替换的最小文本原语。"""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


def build_figure_design_contract(
    run_dir: Path,
    opportunity_id: str,
    *,
    candidate_version: str,
    selected_archetype: str,
    renderer: str,
    panels: Iterable[dict[str, Any]],
    paper_location: str | None = None,
    mechanism_annotation: str = "",
    boundary_annotation: str = "",
    decision_annotation: str = "",
) -> dict[str, Any]:
    """从视觉机会生成设计合同并保存到候选版本目录。"""
    root = run_dir.resolve()
    pool_path = root / "figures/visual-opportunities.json"
    if not pool_path.is_file():
        raise ContractError("生成设计合同前必须存在视觉机会池")
    pool = load_json(pool_path)
    opportunity = next(
        (
            item
            for item in pool.get("opportunities", [])
            if isinstance(item, dict) and item.get("opportunity_id") == opportunity_id
        ),
        None,
    )
    if opportunity is None:
        raise ContractError(f"找不到视觉机会: {opportunity_id}")
    if selected_archetype not in set(map(str, opportunity.get("candidate_archetypes", []))):
        raise ContractError("选择的视觉原型不在该机会的候选集合中")
    panel_list = [dict(item) for item in panels]
    if not panel_list:
        raise ContractError("视觉设计至少需要一个面板")
    payload: dict[str, Any] = {
        "schema_name": FIGURE_DESIGN_CONTRACT_SCHEMA,
        "schema_version": "1.0",
        "run_id": read_simple_state(root)["run_id"],
        "opportunity_id": opportunity_id,
        "visual_question": opportunity["visual_question"],
        "atomic_claim": opportunity["atomic_claim"],
        "source_result_ids": opportunity.get("source_result_ids", []),
        "source_figure_ids": opportunity.get("source_figure_ids", []),
        "candidate": {
            "archetype": selected_archetype,
            "renderer": renderer,
            "version": candidate_version,
        },
        "selected_version": None,
        "paper_location": paper_location,
        "review_verdict": None,
        "policy_fingerprint": policy_fingerprint(resolve_repo_root(Path(__file__)), "visual"),
        "material_pool_digest": material_pool_digest(root),
        "storyboard_digest": _storyboard_digest(root),
        "panels": panel_list,
        "mechanism_annotation": mechanism_annotation,
        "boundary_annotation": boundary_annotation,
        "decision_annotation": decision_annotation,
        "generated_at": utc_now(),
    }
    require_valid(payload, FIGURE_DESIGN_CONTRACT_SCHEMA)
    target = root / FIGURE_DESIGN_ROOT / opportunity_id / candidate_version / "design-contract.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(target, payload)
    return payload


def read_figure_design_contract(run_dir: Path, opportunity_id: str, candidate_version: str) -> dict[str, Any]:
    """读取并验证某个候选版本的设计合同。"""
    root = run_dir.resolve()
    path = root / FIGURE_DESIGN_ROOT / opportunity_id / candidate_version / "design-contract.json"
    payload = load_json(path)
    require_valid(payload, FIGURE_DESIGN_CONTRACT_SCHEMA)
    if payload.get("run_id") != read_simple_state(root)["run_id"]:
        raise ContractError("设计合同 run_id 与运行不一致")
    return payload


def figure_design_contract_freshness(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """复验设计合同仍绑定当前素材、故事板和视觉政策。"""
    root = run_dir.resolve()
    expected = {
        "policy_fingerprint": policy_fingerprint(resolve_repo_root(Path(__file__)), "visual"),
        "material_pool_digest": material_pool_digest(root),
        "storyboard_digest": _storyboard_digest(root),
    }
    stale_fields = [key for key, value in expected.items() if payload.get(key) != value]
    return {"current": not stale_fields, "stale_fields": stale_fields, "run_id": payload.get("run_id")}
