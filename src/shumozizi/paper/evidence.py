"""按证据功能审查验证冗余，而不是机械地限制每个结论只能有一条验证。"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.core.schema import require_valid
from shumozizi.simple.state import read_simple_state

EVIDENCE_FUNCTION_CONTRACT_PATH = Path("paper/generated/evidence_functions.json")
EVIDENCE_FUNCTIONS = frozenset(
    {
        "lower_bound",
        "construction",
        "active_constraint",
        "perturbation",
        "independent_recompute",
        "baseline_contrast",
        "illustrative_case",
        "boundary",
    }
)


def review_evidence_functions(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """检查证据是否承担不同功能，并对同功能重复给出压缩建议。"""
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for entry in entries:
        if not isinstance(entry, dict):
            raise ContractError("证据条目必须是对象")
        function = entry.get("function")
        if function not in EVIDENCE_FUNCTIONS:
            raise ContractError(f"未知证据功能: {function}")
        evidence_id = entry.get("evidence_id")
        claim_id = entry.get("claim_id")
        if not all(isinstance(value, str) and value.strip() for value in (evidence_id, claim_id)):
            raise ContractError("证据 ID 和 claim_id 必须是非空文本")
        groups[(claim_id, function)].append(evidence_id)
    duplicate_groups = [
        {"claim_id": claim_id, "function": function, "evidence_ids": ids}
        for (claim_id, function), ids in sorted(groups.items())
        if len(ids) > 1
    ]
    distinct_function_groups = [
        {"claim_id": claim_id, "functions": sorted(function for group_claim, function in groups if group_claim == claim_id)}
        for claim_id in sorted({claim for claim, _ in groups})
    ]
    return {
        "legal": True,
        "distinct_function_groups": distinct_function_groups,
        "duplicate_groups": duplicate_groups,
        "recommendations": [
            f"主张 {item['claim_id']} 的 {item['function']} 证据重复，建议合并呈现或移入附录。"
            for item in duplicate_groups
        ],
    }


def write_evidence_function_contract(
    run_dir: Path, entries: list[dict[str, Any]]
) -> dict[str, Any]:
    """保存证据功能合同和非阻断冗余审查结果。"""
    root = run_dir.resolve()
    state = read_simple_state(root)
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ContractError("证据条目必须是对象")
        item = {
            "evidence_id": str(entry.get("evidence_id", "")),
            "claim_id": str(entry.get("claim_id", "")),
            "function": str(entry.get("function", "")),
            "description": str(entry.get("description", "")),
        }
        for field in ("source_result_ids", "source_figure_ids"):
            if field in entry:
                item[field] = entry[field]
        normalized.append(item)
    payload = {
        "schema_name": "evidence_function_contract",
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "entries": normalized,
    }
    require_valid(payload, "evidence_function_contract")
    review = review_evidence_functions(normalized)
    payload["review"] = review
    atomic_json(root / EVIDENCE_FUNCTION_CONTRACT_PATH, payload)
    return {"contract": payload, "review": review}


def read_evidence_function_contract(run_dir: Path) -> dict[str, Any]:
    """读取证据功能合同并复核其运行绑定。"""
    root = run_dir.resolve()
    payload = load_json(root / EVIDENCE_FUNCTION_CONTRACT_PATH)
    base = {key: value for key, value in payload.items() if key != "review"}
    require_valid(base, "evidence_function_contract")
    if payload["run_id"] != read_simple_state(root)["run_id"]:
        raise ContractError("证据功能合同 run_id 与运行不一致")
    return payload
