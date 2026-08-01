"""生成不改变科学内容的论文版面建议。

v3.4 的版面优化只安排论证节拍、图机会与跨问交接，不替作者决定页数，
也不把建议分数当成论文质量结论。这样可以在长篇首稿阶段主动暴露过密段落，
同时保留冷读器对争议项的最终裁量。
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, json_bytes, load_json, sha256_bytes
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.core.schema import require_valid
from shumozizi.paper.policy import policy_fingerprint
from shumozizi.paper.storyboard import require_research_storyboard
from shumozizi.simple.state import read_simple_state, utc_now
from shumozizi.simple.visual_opportunities import read_visual_opportunity_pool

LAYOUT_OPTIMIZATION_PATH = Path("paper/generated/layout-optimization.json")
_PLACEHOLDER_PREFIXES = ("待填写", "未填写", "TODO", "TBD")


def _substantive(value: Any) -> bool:
    """判断故事板字段是否有可安排的作者内容。"""
    if isinstance(value, list):
        return bool(value)
    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(text) and not text.startswith(_PLACEHOLDER_PREFIXES)


def _question_order(
    cards: list[dict[str, Any]], requested: Iterable[str] | None
) -> list[str]:
    """确定稳定的问题顺序，拒绝漏写或凭空增加题面问题。"""
    declared = [str(card.get("question_id", "")) for card in cards]
    if requested is None:
        return declared
    order = [str(item) for item in requested]
    if len(order) != len(set(order)):
        raise ContractError("版面优化的问题顺序不能包含重复问题")
    if set(order) != set(declared):
        raise ContractError("版面优化的问题顺序必须覆盖且仅覆盖故事板问题")
    return order


def _block(
    *,
    sequence: int,
    question_id: str,
    role: str,
    media: str,
    density_hint: str,
    rationale: str,
    material_ids: Iterable[str] = (),
    visual_opportunity_ids: Iterable[str] = (),
    candidate_archetypes: Iterable[str] = (),
    recommended_location: str | None = None,
) -> dict[str, Any]:
    """构造一条可读的版面块，不写入任何正文内容。"""
    item: dict[str, Any] = {
        "block_id": f"{question_id}-{role}-{sequence}",
        "sequence": sequence,
        "question_id": question_id,
        "role": role,
        "media": media,
        "density_hint": density_hint,
        "rationale": rationale,
        "material_ids": sorted({str(item) for item in material_ids}),
        "visual_opportunity_ids": sorted({str(item) for item in visual_opportunity_ids}),
    }
    archetypes = sorted({str(item) for item in candidate_archetypes if str(item).strip()})
    if archetypes:
        item["candidate_archetypes"] = archetypes
    if recommended_location is not None:
        item["recommended_location"] = recommended_location
    return item


def build_layout_optimization(
    run_dir: Path,
    *,
    question_order: Iterable[str] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """从故事板和视觉机会生成高级版面建议。"""
    root = run_dir.resolve()
    state = read_simple_state(root)
    storyboard = require_research_storyboard(root, fresh=True)
    opportunities_payload = read_visual_opportunity_pool(root)
    policy = policy_fingerprint(resolve_repo_root(Path(__file__)), "paper")
    cards_by_question = {
        str(card.get("question_id")): card
        for card in storyboard.get("question_cards", [])
        if isinstance(card, dict)
    }
    cards = list(cards_by_question.values())
    order = _question_order(cards, question_order)
    opportunities_by_question: dict[str, list[dict[str, Any]]] = {item: [] for item in order}
    for raw in opportunities_payload.get("opportunities", []):
        if not isinstance(raw, dict):
            continue
        question_id = raw.get("question_id")
        if isinstance(question_id, str) and question_id in opportunities_by_question:
            opportunities_by_question[question_id].append(raw)

    blocks: list[dict[str, Any]] = []
    warnings: list[str] = []
    sequence = 1
    field_roles = (
        ("reader_needs", "answer_preview", "prose", "normal", "先给出本问答案和读者定位。"),
        ("phenomenon", "phenomenon", "prose", "normal", "先说明现象，再解释朴素方法为何不足。"),
        ("why_math_object", "math_object", "prose_and_figure", "expand", "数学对象必须在推导前完成语义落地。"),
        ("key_derivation", "derivation", "equation", "expand", "把决定答案的推导留在正文，不压缩成方法名。"),
        ("mechanism", "mechanism", "prose_and_figure", "expand", "图或反事实应紧跟机制解释，而不是孤立出现。"),
        ("boundary", "boundary", "prose", "light", "在结论旁边声明适用范围和不能外推之处。"),
    )
    for question_id in order:
        card = cards_by_question[question_id]
        material_ids = card.get("material_ids", []) if isinstance(card.get("material_ids"), list) else []
        for field, role, media, density_hint, rationale in field_roles:
            if _substantive(card.get(field)):
                blocks.append(
                    _block(
                        sequence=sequence,
                        question_id=question_id,
                        role=role,
                        media=media,
                        density_hint=density_hint,
                        rationale=rationale,
                        material_ids=material_ids,
                    )
                )
                sequence += 1
        if _substantive(card.get("handoff_to_next")):
            blocks.append(
                _block(
                    sequence=sequence,
                    question_id=question_id,
                    role="handoff",
                    media="prose",
                    density_hint="light",
                    rationale="在本问结尾明确下一问继承的对象与新增困难。",
                    material_ids=material_ids,
                )
            )
            sequence += 1
        else:
            warnings.append(f"{question_id} 缺少跨问交接，版面只能保持并列而不能证明递进。")
        for opportunity in opportunities_by_question[question_id]:
            opportunity_id = str(opportunity.get("opportunity_id", ""))
            status = str(opportunity.get("status", "candidate"))
            location = opportunity.get("paper_location")
            if location not in {"body", "appendix"}:
                location = "body" if status == "promote" else "candidate"
            blocks.append(
                _block(
                    sequence=sequence,
                    question_id=question_id,
                    role="visual_opportunity",
                    media="figure",
                    density_hint="normal",
                    rationale="把独立视觉问题放在其机制或边界论证之后；不预设每问一张 hero 图。",
                    material_ids=material_ids,
                    visual_opportunity_ids=[opportunity_id],
                    candidate_archetypes=opportunity.get("candidate_archetypes", []),
                    recommended_location=location,
                )
            )
            sequence += 1

    if not blocks:
        warnings.append("故事板尚无可展开内容，版面优化仅保留空骨架。")
    hints = [
        "正文先按答案—数学对象—推导—机制—边界形成节拍，再由冷读决定删补。",
        "图应紧邻它回答的读者问题；多个独立问题可拆成互补图，不为满足图数强行合并。",
        "连续高密度推导后优先安排机制段、图或短过渡，避免结果表和公式堆叠。",
        "stability 与纯审计图优先放入附录；正文位置留给机制、权衡和决定性证据。",
        "本文件是 advisory layout contract，不把推荐顺序、页数或图数写成科学硬约束。",
    ]
    payload: dict[str, Any] = {
        "schema_name": "paper_layout_optimization",
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "status": "advisory",
        "policy_fingerprint": policy,
        "storyboard_digest": sha256_bytes(json_bytes(storyboard)),
        "visual_opportunity_digest": sha256_bytes(json_bytes(opportunities_payload)),
        "question_order": order,
        "blocks": blocks,
        "hints": hints,
        "warnings": warnings,
        "generated_at": utc_now(),
    }
    require_valid(payload, "paper_layout_optimization")
    if write:
        target = root / LAYOUT_OPTIMIZATION_PATH
        atomic_json(target, payload)
    return payload


def read_layout_optimization(run_dir: Path) -> dict[str, Any]:
    """读取并验证版面优化建议。"""
    payload = load_json(run_dir.resolve() / LAYOUT_OPTIMIZATION_PATH)
    require_valid(payload, "paper_layout_optimization")
    return payload


def layout_optimization_freshness(run_dir: Path) -> dict[str, Any]:
    """检查版面建议是否仍绑定当前故事板、视觉机会和论文政策。"""
    root = run_dir.resolve()
    payload = read_layout_optimization(root)
    storyboard = require_research_storyboard(root, fresh=True)
    opportunities = read_visual_opportunity_pool(root)
    stale_fields: list[str] = []
    if payload.get("policy_fingerprint") != policy_fingerprint(
        resolve_repo_root(Path(__file__)), "paper"
    ):
        stale_fields.append("policy_fingerprint")
    if payload.get("storyboard_digest") != sha256_bytes(json_bytes(storyboard)):
        stale_fields.append("storyboard_digest")
    if payload.get("visual_opportunity_digest") != sha256_bytes(json_bytes(opportunities)):
        stale_fields.append("visual_opportunity_digest")
    return {
        "current": not stale_fields,
        "stale_fields": stale_fields,
        "run_id": payload.get("run_id"),
    }
