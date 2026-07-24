"""提供逐问目标语义哈希，供生产产物建立精确依赖。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, json_bytes, load_json, sha256_bytes


def build_question_objective_bindings(
    assessment: dict[str, Any], decisions: dict[str, Any] | None = None
) -> dict[str, str]:
    """从选定目标、约束与用户裁决构造逐问稳定哈希。"""
    decision_by_question = {
        item["question_id"]: item
        for item in (decisions or {}).get("decisions", [])
        if isinstance(item, dict) and isinstance(item.get("question_id"), str)
    }
    bindings: dict[str, str] = {}
    for question in assessment.get("questions", []):
        qid = question["question_id"]
        selected_id = question["selected_objective_id"]
        selected = next(
            (
                item
                for item in question.get("interpretations", [])
                if item.get("objective_id") == selected_id
            ),
            None,
        )
        if selected is None:
            raise ContractError(f"{qid} 的选定目标不在 interpretations 中")
        semantic_fact = {
            "question_id": qid,
            "selected_objective": selected,
            "decision_space": question.get("decision_space"),
            "selection_basis": question.get("selection_basis"),
            "user_decision": decision_by_question.get(qid),
        }
        bindings[qid] = sha256_bytes(json_bytes(semantic_fact))
    return bindings


def read_question_objective_bindings(run_dir: Path) -> dict[str, str]:
    """读取并返回当前目标语义收据中的逐问哈希。"""
    receipt_path = run_dir / "review" / "objective-semantics.json"
    if not receipt_path.is_file():
        return {}
    receipt = load_json(receipt_path)
    bindings = receipt.get("question_bindings")
    if not isinstance(bindings, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in bindings.items()
    ):
        raise ContractError("目标语义收据缺少合法 question_bindings")
    return dict(bindings)


def objective_semantics_for_question(run_dir: Path, question_id: str) -> str:
    """返回生产结果必须绑定的本问目标哈希。"""
    bindings = read_question_objective_bindings(run_dir)
    if question_id in bindings:
        return bindings[question_id]
    problem_files = [
        path for path in (run_dir / "problem").rglob("*")
        if path.is_file()
    ] if (run_dir / "problem").is_dir() else []
    if problem_files:
        raise ContractError(f"正式题面中的 {question_id} 缺少目标语义绑定")
    return sha256_bytes(
        json_bytes({"question_id": question_id, "objective_semantics": "not_required"})
    )


def objective_semantics_digest(run_dir: Path) -> str:
    """返回全部逐问目标绑定的稳定摘要。"""
    bindings = read_question_objective_bindings(run_dir)
    if bindings:
        return sha256_bytes(json_bytes(bindings))
    receipt_path = run_dir / "review" / "objective-semantics.json"
    if receipt_path.is_file():
        receipt = load_json(receipt_path)
        legacy = receipt.get("selected_objectives_sha256")
        if isinstance(legacy, str):
            return legacy
    return sha256_bytes(json_bytes({"objective_semantics": "not_required"}))
