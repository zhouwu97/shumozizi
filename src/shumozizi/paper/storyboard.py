"""把素材池组织为跨问题研究故事板。

故事板不是论文正文，也不是检查清单；它回答评委在每个问题中需要先看到什么、
数学对象为什么出现、结果由什么机制决定，以及该问如何把困难传递给下一问。
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

STORYBOARD_MD_PATH = Path("paper/RESEARCH_STORYBOARD.md")
STORYBOARD_JSON_PATH = Path("paper/generated/research_storyboard.json")
STORYBOARD_FIELDS = (
    "reader_needs",
    "phenomenon",
    "why_math_object",
    "model_evolution",
    "key_derivation",
    "structural_finding",
    "decision_determinant",
    "mechanism",
    "contrast",
    "boundary",
    "best_media",
    "handoff_to_next",
)


def _atomic_text(path: Path, value: str) -> None:
    """在同目录原子替换故事板 Markdown。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _question_ids(run_dir: Path) -> list[str]:
    """读取状态中声明的必答问题，保持故事板与题面合同一致。"""
    return [str(item) for item in read_simple_state(run_dir.resolve()).get("required_questions", [])]


def _empty_card(question_id: str) -> dict[str, Any]:
    """生成可渐进填写的问题卡，而不是替作者编造结论。"""
    return {
        "question_id": question_id,
        "reader_needs": "待填写：评委首先需要知道本问的直接答案和决定它的数学量。",
        "phenomenon": "待填写：数据或题面现象，以及为什么朴素方法不足。",
        "why_math_object": "待填写：选择状态、集合、轨迹、网络或其他对象的理由。",
        "model_evolution": "待填写：相邻问题继承了什么，又新增了什么资源或约束。",
        "key_derivation": "待填写：正文必须保留的关键推导或判据。",
        "structural_finding": "待填写：结果中可解释的结构观察。",
        "decision_determinant": "待填写：哪一条证据真正决定方案或答案。",
        "mechanism": "待填写：活跃约束、边际收益、瓶颈或权衡机制。",
        "contrast": "待填写：baseline、替代解释或反事实对照。",
        "boundary": "待填写：适用范围、敏感性和不能外推的边界。",
        "best_media": [],
        "handoff_to_next": "待填写：本问输出如何成为下一问的输入。",
        "material_ids": [],
        "visual_opportunity_ids": [],
    }


def _coerce_cards(
    run_dir: Path, cards: Iterable[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """合并显式卡片和状态问题，保留多问继承骨架。"""
    supplied = {str(item.get("question_id")): item for item in (cards or [])}
    result: list[dict[str, Any]] = []
    for question_id in _question_ids(run_dir):
        card = _empty_card(question_id)
        raw = supplied.get(question_id, {})
        if not isinstance(raw, dict):
            raise ContractError(f"故事板问题卡必须是对象: {question_id}")
        for field in (*STORYBOARD_FIELDS, "material_ids", "visual_opportunity_ids"):
            if field in raw:
                card[field] = raw[field]
        result.append(card)
    unknown = sorted(set(supplied) - set(_question_ids(run_dir)))
    if unknown:
        raise ContractError("故事板包含未声明问题: " + ", ".join(unknown))
    return result


def build_research_storyboard(
    run_dir: Path,
    *,
    cards: Iterable[dict[str, Any]] | None = None,
    cross_question_links: Iterable[dict[str, Any]] = (),
    write: bool = True,
) -> dict[str, Any]:
    """创建研究故事板模板或写入作者提供的问题卡。"""
    root = run_dir.resolve()
    state = read_simple_state(root)
    pool_digest = material_pool_digest(root)
    payload: dict[str, Any] = {
        "schema_name": "research_storyboard",
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "policy_fingerprint": policy_fingerprint(resolve_repo_root(Path(__file__)), "paper"),
        "material_pool_digest": pool_digest,
        "generated_at": utc_now(),
        "status": "current" if cards is not None and pool_digest else "draft",
        "question_cards": _coerce_cards(root, cards),
        "cross_question_links": [dict(item) for item in cross_question_links],
    }
    require_valid(payload, "research_storyboard")
    if write:
        write_research_storyboard(root, payload)
    return payload


def _markdown(payload: dict[str, Any]) -> str:
    """渲染作者填写用的连续问题链，不暴露哈希或回执字段。"""
    lines = [
        "# RESEARCH_STORYBOARD",
        "",
        "这份故事板先于正文。每问都要说明现象、数学对象、推导、结构、机制、边界和下一问交接；"
        "它不是把结果压缩成三张图的固定版式。",
        "",
        f"状态：`{payload.get('status', 'draft')}`。答案预览可以先出现，但不能替代后续推导与机制解释。",
        "",
    ]
    labels = {
        "reader_needs": "评委首先需要什么",
        "phenomenon": "现象与困难",
        "why_math_object": "为什么需要这个数学对象",
        "model_evolution": "模型如何形成与继承",
        "key_derivation": "关键推导",
        "structural_finding": "结构观察",
        "decision_determinant": "决定答案的证据",
        "mechanism": "机制解释",
        "contrast": "对照与替代解释",
        "boundary": "边界与稳健性",
        "best_media": "最合适的媒介",
        "handoff_to_next": "交接到下一问",
    }
    for card in payload.get("question_cards", []):
        lines.extend([f"## {card['question_id']}", ""])
        for field in STORYBOARD_FIELDS:
            value = card.get(field, []) if field == "best_media" else card.get(field, "")
            if isinstance(value, list):
                rendered = "、".join(map(str, value)) or "待填写。"
            else:
                rendered = str(value).strip() or "待填写。"
            lines.extend([f"### {labels[field]}", "", rendered, ""])
    if payload.get("cross_question_links"):
        lines.extend(["## 跨问题链接", ""])
        for link in payload["cross_question_links"]:
            lines.append("- " + "；".join(f"{key}：{value}" for key, value in link.items()))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_research_storyboard(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """校验并原子写入故事板 JSON 与 Markdown。"""
    root = run_dir.resolve()
    if payload.get("run_id") != read_simple_state(root)["run_id"]:
        raise ContractError("故事板 run_id 与运行不一致")
    require_valid(payload, "research_storyboard")
    atomic_json(root / STORYBOARD_JSON_PATH, payload)
    target = root / STORYBOARD_MD_PATH
    _atomic_text(target, _markdown(payload))
    return payload


def read_research_storyboard(run_dir: Path) -> dict[str, Any]:
    """读取并验证故事板 JSON。"""
    payload = load_json(run_dir.resolve() / STORYBOARD_JSON_PATH)
    require_valid(payload, "research_storyboard")
    return payload


def validate_storyboard_freshness(run_dir: Path) -> dict[str, Any]:
    """判断故事板是否绑定当前素材池和论文政策。"""
    root = run_dir.resolve()
    payload = read_research_storyboard(root)
    current_policy = policy_fingerprint(resolve_repo_root(Path(__file__)), "paper")
    current_pool = material_pool_digest(root)
    stale_fields = []
    if payload.get("policy_fingerprint") != current_policy:
        stale_fields.append("policy_fingerprint")
    if payload.get("material_pool_digest") != current_pool:
        stale_fields.append("material_pool_digest")
    return {"current": not stale_fields, "stale_fields": stale_fields, "run_id": payload["run_id"]}


def require_research_storyboard(run_dir: Path, *, fresh: bool = True) -> dict[str, Any]:
    """要求故事板存在并可选地绑定当前素材。"""
    payload = read_research_storyboard(run_dir)
    if fresh:
        freshness = validate_storyboard_freshness(run_dir)
        if not freshness["current"]:
            raise ContractError("研究故事板已失效: " + "、".join(freshness["stale_fields"]))
    return payload
