"""把独立 PDF 冷读意见转为可执行的论文编辑动作。

冷读器拥有扩展、压缩、重排、补推导/机制/对照/边界、加图/拆图/删图和移附录的
权限，但不会直接修改科学事实。动作被关闭前，候选稿不应被当作编辑完成。
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, resolve_inside, sha256_file
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.core.schema import require_valid
from shumozizi.paper.policy import policy_fingerprint
from shumozizi.simple.state import read_simple_state, utc_now
from shumozizi.simple.visual_opportunities import add_companion_figure_opportunity

EDITORIAL_ACTIONS_PATH = Path("review/PAPER_COLD_READER_EDITORIAL.json")
EDITORIAL_WAIVER_PATH = Path("review/PAPER_COLD_READER_WAIVER.json")
EDITORIAL_ACTIONS = frozenset(
    {
        "EXPAND",
        "COMPRESS",
        "REORDER",
        "ADD_DERIVATION",
        "ADD_MECHANISM",
        "ADD_COMPARISON",
        "ADD_BOUNDARY",
        "ADD_FIGURE",
        "ADD_COMPANION_FIGURE",
        "SPLIT_FIGURE",
        "DROP_FIGURE",
        "MOVE_TO_APPENDIX",
        "MERGE_PARAGRAPHS",
    }
)


def _require_action(raw: dict[str, Any]) -> dict[str, Any]:
    """校验一条冷读动作的最小编辑语义。"""
    action = raw.get("action")
    if action not in EDITORIAL_ACTIONS:
        raise ContractError(f"未知论文编辑动作: {action}")
    required = ("action_id", "target_id", "reason", "expected_benefit")
    if any(not isinstance(raw.get(field), str) or not raw[field].strip() for field in required):
        raise ContractError(f"编辑动作 {action} 缺少 action_id、target_id、reason 或 expected_benefit")
    return {
        **raw,
        "action_id": raw["action_id"].strip(),
        "target_id": raw["target_id"].strip(),
        "reason": raw["reason"].strip(),
        "expected_benefit": raw["expected_benefit"].strip(),
        "status": raw.get("status", "open"),
        "blocking": bool(raw.get("blocking", False)),
    }


def record_paper_cold_reader_actions(
    run_dir: Path,
    *,
    actions: Iterable[dict[str, Any]],
    reviewer_context_id: str,
    source_pdf: str = "paper/longform-draft.pdf",
) -> dict[str, Any]:
    """记录新鲜冷读动作，并为所有新增图动作创建视觉机会。"""
    if not isinstance(reviewer_context_id, str) or not reviewer_context_id.strip():
        raise ContractError("论文冷读必须绑定独立 reviewer_context_id")
    root = run_dir.resolve()
    normalized = [_require_action(dict(item)) for item in actions]
    action_ids = [item["action_id"] for item in normalized]
    if len(action_ids) != len(set(action_ids)):
        raise ContractError("论文编辑 action_id 必须唯一")
    if any(item["status"] not in {"open", "closed"} for item in normalized):
        raise ContractError("论文编辑动作 status 必须为 open 或 closed")
    for item in normalized:
        if item["action"] not in {"ADD_FIGURE", "ADD_COMPANION_FIGURE"}:
            continue
        payload = item.get("companion_figure", item.get("figure"))
        if not isinstance(payload, dict):
            raise ContractError(
                f"{item['action']} 必须提供 figure 或 companion_figure 对象"
            )
        add_companion_figure_opportunity(
            root,
            opportunity_id=str(payload.get("opportunity_id", item["action_id"])),
            question_id=payload.get("question_id") if isinstance(payload.get("question_id"), str) else None,
            visual_question=str(payload.get("visual_question", "")),
            atomic_claim=str(payload.get("atomic_claim", "")),
            candidate_archetypes=payload.get("candidate_archetypes", ["multi_panel_evidence_chain"]),
            reviewer_context_id=reviewer_context_id,
            finding_id=item["action_id"],
        )
    pdf_path = resolve_inside(root, source_pdf)
    payload = {
        "schema_name": "paper_editorial_actions",
        "schema_version": "1.0",
        "run_id": read_simple_state(root)["run_id"],
        "reviewer_context_id": reviewer_context_id,
        "source_pdf": source_pdf,
        "source_pdf_sha256": sha256_file(pdf_path) if pdf_path.is_file() else None,
        "paper_policy_fingerprint": policy_fingerprint(resolve_repo_root(Path(__file__)), "paper"),
        "actions": normalized,
        "recorded_at": utc_now(),
    }
    require_valid(payload, "paper_editorial_actions")
    atomic_json(root / EDITORIAL_ACTIONS_PATH, payload)
    return payload


def close_editorial_action(
    run_dir: Path, action_id: str, *, closure_evidence: str
) -> dict[str, Any]:
    """用具体关闭证据结束一条编辑动作。"""
    if not closure_evidence.strip():
        raise ContractError("编辑动作关闭必须提供 closure_evidence")
    root = run_dir.resolve()
    path = root / EDITORIAL_ACTIONS_PATH
    payload = load_json(path)
    target = next((item for item in payload.get("actions", []) if item.get("action_id") == action_id), None)
    if target is None:
        raise ContractError(f"找不到论文编辑动作: {action_id}")
    target["status"] = "closed"
    target["closure_evidence"] = closure_evidence.strip()
    target["closed_at"] = utc_now()
    atomic_json(path, payload)
    return target


def _valid_editorial_waiver(run_dir: Path) -> dict[str, Any] | None:
    """读取明确的应急/回退冷读豁免，不把缺失冷读伪装成完成。"""
    root = run_dir.resolve()
    path = root / EDITORIAL_WAIVER_PATH
    if not path.is_file():
        return None
    payload = load_json(path)
    require_valid(payload, "paper_cold_reader_waiver")
    if payload.get("run_id") != read_simple_state(root)["run_id"]:
        raise ContractError("冷读豁免 run_id 与当前运行不一致")
    if payload.get("mode") not in {"emergency", "fallback"}:
        raise ContractError("冷读豁免 mode 必须为 emergency 或 fallback")
    reason = payload.get("reason")
    if not isinstance(reason, str) or len(reason.strip()) < 20:
        raise ContractError("冷读豁免必须记录不少于 20 个字符的具体原因")
    return payload


def editorial_readiness(
    run_dir: Path, *, require_record: bool = False
) -> dict[str, Any]:
    """返回冷读编辑动作、来源 PDF 和政策绑定是否满足候选稿门。"""
    root = run_dir.resolve()
    path = root / EDITORIAL_ACTIONS_PATH
    if not path.is_file():
        if not require_record:
            return {"ready": True, "open_actions": [], "reason": "尚未记录冷读编辑动作"}
        try:
            waiver = _valid_editorial_waiver(root)
        except (ContractError, OSError, ValueError) as exc:
            return {
                "ready": False,
                "open_actions": [],
                "errors": [str(exc)],
                "reason": "冷读记录缺失且豁免无效",
            }
        if waiver is not None:
            return {
                "ready": True,
                "open_actions": [],
                "waiver": waiver,
                "reason": "使用明确记录的应急/回退冷读豁免",
            }
        return {
            "ready": False,
            "open_actions": [],
            "errors": ["缺少 PAPER_COLD_READER_EDITORIAL.json，且没有有效豁免"],
            "reason": "正常竞赛候选稿必须有独立冷读记录",
        }
    try:
        payload = load_json(path)
        require_valid(payload, "paper_editorial_actions")
    except (ContractError, OSError, ValueError) as exc:
        return {"ready": False, "open_actions": [], "errors": [str(exc)], "reason": "冷读记录无效"}
    errors: list[str] = []
    state = read_simple_state(root)
    if payload.get("run_id") != state["run_id"]:
        errors.append("冷读记录 run_id 与当前运行不一致")
    if not str(payload.get("reviewer_context_id", "")).strip():
        errors.append("冷读记录缺少 reviewer_context_id")
    if require_record:
        source_pdf = payload.get("source_pdf")
        try:
            pdf_path = resolve_inside(root, str(source_pdf), must_exist=True)
            if payload.get("source_pdf_sha256") != sha256_file(pdf_path):
                errors.append("冷读来源 PDF 已变化，必须重新冷读")
        except (ContractError, OSError, ValueError) as exc:
            errors.append(f"冷读来源 PDF 无效: {exc}")
        expected_policy = policy_fingerprint(resolve_repo_root(Path(__file__)), "paper")
        if payload.get("paper_policy_fingerprint") != expected_policy:
            errors.append("冷读记录未绑定当前论文政策")
    open_actions = [
        item.get("action_id")
        for item in payload.get("actions", [])
        if isinstance(item, dict)
        and item.get("blocking") is True
        and item.get("status") != "closed"
    ]
    advisory_actions = [
        item.get("action_id")
        for item in payload.get("actions", [])
        if isinstance(item, dict)
        and item.get("blocking") is not True
        and item.get("status") != "closed"
    ]
    return {
        "ready": not open_actions and not errors,
        "open_actions": open_actions,
        "advisory_actions": advisory_actions,
        "errors": errors,
        "source_pdf": payload.get("source_pdf"),
        "source_pdf_sha256": payload.get("source_pdf_sha256"),
        "reviewer_context_id": payload.get("reviewer_context_id"),
        "reason": "存在未关闭 P0/P1 动作" if open_actions else ("可进入候选稿" if not errors else "冷读绑定无效"),
    }


def require_editorial_readiness(run_dir: Path, *, require_record: bool = False) -> None:
    """要求独立冷读已完成，且其明确标记为阻断的动作已经关闭。"""
    status = editorial_readiness(run_dir, require_record=require_record)
    if not status["ready"]:
        details = [*map(str, status.get("open_actions", [])), *map(str, status.get("errors", []))]
        raise ContractError("论文冷读门未通过: " + "；".join(details))
