"""从研究素材生成视觉机会池，并记录逐图新鲜评阅者的动作。

视觉机会先回答“图要让评委看懂什么”，再选择图形原型；因此它不再假设每个
问题必须有一张 hero 图，也允许一个机会拆成互补图或被明确放弃。
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.core.schema import require_valid
from shumozizi.paper.materials import read_material_pool
from shumozizi.paper.policy import policy_fingerprint
from shumozizi.simple.state import read_simple_state, utc_now

VISUAL_OPPORTUNITY_POOL_PATH = Path("figures/visual-opportunities.json")
VISUAL_REVIEW_ROOT = Path("figures/reviews")
VISUAL_VERDICTS = frozenset({"PROMOTE", "REVISE", "SPLIT", "DROP"})
_STATUS_BY_VERDICT = {"PROMOTE": "promote", "REVISE": "revise", "SPLIT": "split", "DROP": "drop"}


def _atomic_text(path: Path, value: str) -> None:
    """在同目录原子替换视觉批评 Markdown。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _repo_root_for_run(run_dir: Path) -> Path:
    """返回包含政策文件的代码仓库根，测试运行目录不影响指纹。"""
    del run_dir
    return resolve_repo_root(Path(__file__))


def _opportunity(
    *,
    opportunity_id: str,
    question_id: str | None,
    visual_question: str,
    atomic_claim: str,
    source_result_ids: Iterable[str] = (),
    source_figure_ids: Iterable[str] = (),
    candidate_archetypes: Iterable[str] = ("multi_panel_evidence_chain",),
    paper_location: str | None = None,
) -> dict[str, Any]:
    """构造一条不绑定具体渲染脚本的视觉机会。"""
    if not opportunity_id.strip() or not visual_question.strip() or not atomic_claim.strip():
        raise ContractError("视觉机会 ID、视觉问题和原子主张不能为空")
    archetypes = sorted({str(item) for item in candidate_archetypes if str(item).strip()})
    if not archetypes:
        raise ContractError("视觉机会至少需要一个候选图形原型")
    return {
        "opportunity_id": opportunity_id,
        "question_id": question_id,
        "visual_question": visual_question.strip(),
        "atomic_claim": atomic_claim.strip(),
        "source_result_ids": sorted({str(item) for item in source_result_ids}),
        "source_figure_ids": sorted({str(item) for item in source_figure_ids}),
        "candidate_archetypes": archetypes,
        "selected_archetype": None,
        "paper_location": paper_location,
        "status": "candidate",
        "critic_verdict": None,
        "critic_path": None,
    }


def _from_materials(run_dir: Path) -> list[dict[str, Any]]:
    """把素材池中适合视觉化的内容转换为候选机会。"""
    try:
        pool = read_material_pool(run_dir)
    except ContractError:
        return []
    opportunities: list[dict[str, Any]] = []
    for item in pool.get("items", []):
        category = item.get("category")
        if category not in {"Structural Observation", "Mechanism", "Boundary/Robustness", "Visual Opportunity"}:
            continue
        question_id = item.get("question_id")
        question = str(question_id) if isinstance(question_id, str) else None
        archetypes = item.get("media_candidates") or ("multi_panel_evidence_chain",)
        opportunities.append(
            _opportunity(
                opportunity_id=f"visual-{item['material_id']}",
                question_id=question,
                visual_question=f"如何让评委直接看到：{item['title']}？",
                atomic_claim=item["content"],
                source_result_ids=item.get("source_result_ids", []),
                source_figure_ids=item.get("source_figure_ids", []),
                candidate_archetypes=archetypes,
            )
        )
    return opportunities


def build_visual_opportunity_pool(
    run_dir: Path,
    *,
    opportunities: Iterable[dict[str, Any]] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """生成视觉机会池；显式机会优先于自动候选。"""
    root = run_dir.resolve()
    state = read_simple_state(root)
    raw_items = list(opportunities) if opportunities is not None else _from_materials(root)
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise ContractError("视觉机会必须是对象")
        item = _opportunity(
            opportunity_id=str(raw.get("opportunity_id", "")),
            question_id=raw.get("question_id") if isinstance(raw.get("question_id"), str) else None,
            visual_question=str(raw.get("visual_question", "")),
            atomic_claim=str(raw.get("atomic_claim", "")),
            source_result_ids=raw.get("source_result_ids", []),
            source_figure_ids=raw.get("source_figure_ids", []),
            candidate_archetypes=raw.get("candidate_archetypes", []),
            paper_location=raw.get("paper_location") if isinstance(raw.get("paper_location"), str) else None,
        )
        for field in ("selected_archetype", "status", "critic_verdict", "critic_path", "decision_note"):
            if field in raw:
                item[field] = raw[field]
        if item["opportunity_id"] in seen:
            raise ContractError(f"视觉机会 ID 重复: {item['opportunity_id']}")
        seen.add(item["opportunity_id"])
        normalized.append(item)
    payload: dict[str, Any] = {
        "schema_name": "visual_opportunity_pool",
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "policy_fingerprint": policy_fingerprint(_repo_root_for_run(root), "visual"),
        "generated_at": utc_now(),
        "status": "current" if opportunities is not None and normalized else "draft",
        "opportunities": normalized,
    }
    require_valid(payload, "visual_opportunity_pool")
    if write:
        write_visual_opportunity_pool(root, payload)
    return payload


def write_visual_opportunity_pool(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """校验并原子保存视觉机会池。"""
    root = run_dir.resolve()
    if payload.get("run_id") != read_simple_state(root)["run_id"]:
        raise ContractError("视觉机会池 run_id 与运行不一致")
    require_valid(payload, "visual_opportunity_pool")
    atomic_json(root / VISUAL_OPPORTUNITY_POOL_PATH, payload)
    return payload


def read_visual_opportunity_pool(run_dir: Path) -> dict[str, Any]:
    """读取并验证视觉机会池。"""
    payload = load_json(run_dir.resolve() / VISUAL_OPPORTUNITY_POOL_PATH)
    require_valid(payload, "visual_opportunity_pool")
    return payload


def _review_markdown(opportunity: dict[str, Any], review: dict[str, Any], verdict: str) -> str:
    """把批评意见渲染成作者可读的评阅记录。"""
    lines = [
        f"# Visual critic: {opportunity['opportunity_id']}",
        "",
        f"结论：**{verdict}**",
        "",
        f"视觉问题：{opportunity['visual_question']}",
        f"原子主张：{opportunity['atomic_claim']}",
        "",
    ]
    for key, label in (
        ("observed", "图上实际看到什么"),
        ("mechanism", "机制是否可解释"),
        ("boundary", "边界是否诚实"),
        ("action", "下一步动作"),
    ):
        lines.extend([f"## {label}", "", str(review.get(key, "待填写。")), ""])
    return "\n".join(lines)


def record_visual_critic(
    run_dir: Path,
    opportunity_id: str,
    *,
    verdict: str,
    review: dict[str, Any],
    reviewer_context_id: str,
    fresh: bool = True,
) -> dict[str, Any]:
    """记录一次新鲜视觉批评并把 PROMOTE/REVISE/SPLIT/DROP 写回机会池。"""
    if verdict not in VISUAL_VERDICTS:
        raise ContractError("visual critic verdict 必须为 PROMOTE、REVISE、SPLIT 或 DROP")
    if fresh and (not isinstance(reviewer_context_id, str) or not reviewer_context_id.strip()):
        raise ContractError("新鲜视觉批评必须绑定独立 reviewer_context_id")
    if not isinstance(review, dict):
        raise ContractError("视觉批评 review 必须是对象")
    required = ("observed", "mechanism", "boundary", "action")
    missing = [key for key in required if not isinstance(review.get(key), str) or not review[key].strip()]
    if missing:
        raise ContractError("视觉批评缺少实质字段: " + "、".join(missing))
    root = run_dir.resolve()
    payload = read_visual_opportunity_pool(root)
    target = next(
        (item for item in payload["opportunities"] if item.get("opportunity_id") == opportunity_id),
        None,
    )
    if target is None:
        raise ContractError(f"找不到视觉机会: {opportunity_id}")
    version = str(review.get("candidate_version", "v1"))
    review_dir = root / VISUAL_REVIEW_ROOT / opportunity_id
    review_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "1.0",
        "run_id": payload["run_id"],
        "opportunity_id": opportunity_id,
        "candidate_version": version,
        "verdict": verdict,
        "reviewer_context_id": reviewer_context_id,
        "fresh": fresh,
        "review": review,
        "recorded_at": utc_now(),
    }
    json_path = review_dir / f"{version}.json"
    atomic_json(json_path, record)
    md_path = review_dir / f"{version}.md"
    _atomic_text(md_path, _review_markdown(target, review, verdict))
    target["status"] = _STATUS_BY_VERDICT[verdict]
    target["critic_verdict"] = verdict
    target["critic_path"] = md_path.relative_to(root).as_posix()
    target["critic_context_id"] = reviewer_context_id
    write_visual_opportunity_pool(root, payload)
    return record


def validate_visual_critic_record(run_dir: Path, opportunity_id: str, version: str) -> dict[str, Any]:
    """复验指定视觉批评记录仍存在且绑定当前机会池。"""
    root = run_dir.resolve()
    path = root / VISUAL_REVIEW_ROOT / opportunity_id / f"{version}.json"
    payload = load_json(path)
    pool = read_visual_opportunity_pool(root)
    if payload.get("run_id") != pool.get("run_id") or payload.get("opportunity_id") != opportunity_id:
        raise ContractError("视觉批评回执与当前机会池不一致")
    if payload.get("verdict") not in VISUAL_VERDICTS:
        raise ContractError("视觉批评回执 verdict 无效")
    return payload


def visual_opportunity_pool_freshness(run_dir: Path) -> dict[str, Any]:
    """判断机会池是否仍绑定当前视觉政策。"""
    root = run_dir.resolve()
    payload = read_visual_opportunity_pool(root)
    current = policy_fingerprint(_repo_root_for_run(root), "visual")
    return {
        "current": payload.get("policy_fingerprint") == current,
        "stale_fields": [] if payload.get("policy_fingerprint") == current else ["policy_fingerprint"],
        "run_id": payload["run_id"],
    }
