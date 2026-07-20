"""复验生产物引用的 accepted/sealed result。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, load_json
from shumozizi.core.schema import require_valid
from shumozizi.results.sealing import verify_sealed_result


def verify_referenced_result(
    run_dir: Path,
    registry: dict[str, Any],
    result_id: str,
    *,
    question_id: str | None = None,
    require_paper_allowed: bool = True,
) -> list[str]:
    """复验一个生产引用对应的注册记录和封存事实。"""
    errors: list[str] = []
    try:
        require_valid(registry, "result_registry")
    except ContractError as exc:
        return [f"result_registry 无效: {exc}"]
    if registry["run_id"] != run_dir.name:
        errors.append("result_registry.run_id 与运行目录不一致")

    item = next(
        (entry for entry in registry["results"] if entry["result_id"] == result_id),
        None,
    )
    if item is None:
        return [*errors, f"结果不存在: {result_id}"]
    if item["status"] != "accepted":
        errors.append(f"结果不是 accepted: {result_id}")
    if require_paper_allowed and item["paper_allowed"] is not True:
        errors.append(f"结果未允许写入论文: {result_id}")
    if question_id is not None and item["question_id"] != question_id:
        errors.append(
            f"结果 question_id 不匹配: {result_id} "
            f"({item['question_id']} != {question_id})"
        )

    try:
        verification = verify_sealed_result(run_dir, result_id)
        errors.extend(
            f"sealed result 复验失败 {result_id}: {message}"
            for message in verification["errors"]
        )
        sealed = load_json(run_dir / "results" / "sealed" / f"{result_id}.result.json")
        if sealed.get("result_id") != result_id:
            errors.append(f"sealed result_id 不匹配: {result_id}")
        if sealed.get("question_id") != item["question_id"]:
            errors.append(f"sealed result 与注册表 question_id 不一致: {result_id}")
        if question_id is not None and sealed.get("question_id") != question_id:
            errors.append(f"sealed result question_id 不匹配: {result_id}")
        if sealed.get("paper_allowed") is not item["paper_allowed"]:
            errors.append(f"sealed result 与注册表 paper_allowed 不一致: {result_id}")
    except (ContractError, KeyError, OSError) as exc:
        errors.append(f"sealed result 复验失败 {result_id}: {exc}")
    return errors
