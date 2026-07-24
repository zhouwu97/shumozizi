"""管理 Competition-First 科学挑战的一次专项追问。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, json_bytes, load_json, sha256_bytes
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import utc_now

FOCUSED_FOLLOWUP_PATH = Path("review/FOCUSED_FOLLOWUP.md")
SCIENTIFIC_CHALLENGE_EVIDENCE_PATH = Path("review/scientific-challenge-evidence.json")


def write_focused_followup(run_dir: Path, content: str) -> Path:
    """创建唯一允许的专项追问记录。

    Args:
        run_dir: 当前运行目录。
        content: 包含待验证问题、证据和结论的 Markdown 内容。

    Returns:
        已写入的追问路径。

    Raises:
        ContractError: 已经存在追问或内容过短。
    """
    path = run_dir / FOCUSED_FOLLOWUP_PATH
    if path.exists():
        raise ContractError("每轮科学审核最多允许一个 FOCUSED_FOLLOWUP.md")
    if len(content.strip()) < 32:
        raise ContractError("专项追问必须说明决定性缺口及其验证结论")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8", newline="\n")
    return path


def record_scientific_challenge_evidence(
    run_dir: Path, *, result_ids: list[str], attack_description: str
) -> dict[str, Any]:
    """绑定科学挑战实际使用的当前执行结果。

    Args:
        run_dir: 当前运行目录。
        result_ids: 实际攻击或复算产生的 current production 结果。
        attack_description: 该攻击试图推翻的具体结论。

    Returns:
        已写入的轻量挑战证据收据。

    Raises:
        ContractError: 结果不存在、已失效或描述为空。
    """
    if not attack_description.strip():
        raise ContractError("科学挑战必须说明实际攻击要推翻的具体结论")
    if not result_ids:
        raise ContractError("科学挑战必须绑定至少一个真实执行结果")
    results = {
        item["result_id"]: item
        for item in read_result_index(run_dir)["results"]
        if item.get("status") == "current"
        and item.get("execution_mode") == "production"
        and item.get("execution_valid") is True
    }
    missing = [result_id for result_id in result_ids if result_id not in results]
    if missing:
        raise ContractError("科学挑战绑定了非 current production 结果: " + ", ".join(missing))
    records = [
        {"result_id": result_id, "sha256": sha256_bytes(json_bytes(results[result_id]))}
        for result_id in dict.fromkeys(result_ids)
    ]
    payload = {
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "attack_description": attack_description.strip(),
        "results": records,
        "recorded_at": utc_now(),
    }
    atomic_json(run_dir / SCIENTIFIC_CHALLENGE_EVIDENCE_PATH, payload)
    return payload


def verify_scientific_challenge_evidence(run_dir: Path) -> dict[str, Any]:
    """确认科学挑战仍绑定未漂移的真实执行结果。

    Args:
        run_dir: 当前运行目录。

    Returns:
        有效性和错误列表。
    """
    path = run_dir / SCIENTIFIC_CHALLENGE_EVIDENCE_PATH
    if not path.is_file():
        return {"valid": False, "errors": ["缺少 review/scientific-challenge-evidence.json"]}
    try:
        payload = load_json(path)
        if payload.get("run_id") != run_dir.name or not payload.get("attack_description"):
            raise ContractError("科学挑战证据 run_id 或攻击描述无效")
        results = {
            item["result_id"]: item
            for item in read_result_index(run_dir)["results"]
            if item.get("status") == "current"
            and item.get("execution_mode") == "production"
            and item.get("execution_valid") is True
        }
        errors = [
            f"科学挑战结果已失效或漂移: {item.get('result_id')}"
            for item in payload.get("results", [])
            if item.get("result_id") not in results
            or item.get("sha256") != sha256_bytes(json_bytes(results[item["result_id"]]))
        ]
        if not payload.get("results"):
            errors.append("科学挑战没有绑定任何执行结果")
        return {"valid": not errors, "errors": errors, "evidence": payload}
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return {"valid": False, "errors": [str(exc)]}
