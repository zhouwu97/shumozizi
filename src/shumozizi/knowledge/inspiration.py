"""读取只影响表达、不承担当前题证据责任的 Inspiration Library。"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.core.schema import require_valid
from shumozizi.simple.state import read_simple_state, utc_now

INSPIRATION_CONTEXT_PATH = Path("paper/generated/inspiration-context.json")


def load_inspiration_library() -> dict[str, Any]:
    """读取仓内表达启发库；其 schema 无事实、公式和结果绑定字段。"""
    root = resolve_repo_root(Path(__file__))
    payload = load_json(root / "knowledge/inspiration/library.json")
    require_valid(payload, "inspiration_library")
    identifiers = [item["card_id"] for item in payload["cards"]]
    if len(identifiers) != len(set(identifiers)):
        raise ContractError("Inspiration card_id 必须唯一")
    return payload


def build_inspiration_context(
    run_dir: Path, card_ids: Iterable[str] | None = None
) -> dict[str, Any]:
    """为 Author 投影多张表达卡，不要求 current-result binding。"""
    root = run_dir.resolve()
    library = load_inspiration_library()
    selected = set(map(str, card_ids)) if card_ids is not None else None
    cards = [
        item
        for item in library["cards"]
        if selected is None or item["card_id"] in selected
    ]
    if selected is not None:
        missing = selected - {item["card_id"] for item in cards}
        if missing:
            raise ContractError("不存在的 Inspiration card: " + ", ".join(sorted(missing)))
    payload = {
        "schema_name": "inspiration_context",
        "schema_version": "1.0",
        "run_id": read_simple_state(root)["run_id"],
        "advisory_only": True,
        "cards": cards,
        "forbidden_transfers": ["facts", "data", "formulas", "parameters", "results", "citations", "conclusions"],
        "generated_at": utc_now(),
    }
    atomic_json(root / INSPIRATION_CONTEXT_PATH, payload)
    return payload
