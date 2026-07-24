"""Competition-First v3.1 的路线、实验价值和洞察产物。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json
from shumozizi.simple.state import read_simple_state, utc_now

ROUTE_COMPETITION_PATH = Path("analysis/ROUTE_COMPETITION.md")
NEXT_EXPERIMENTS_PATH = Path("analysis/NEXT_EXPERIMENTS.md")
INSIGHTS_PATH = Path("analysis/INSIGHTS.md")
ANSWER_MAP_PATH = Path("analysis/answer_map.json")


def _require_text(value: object, label: str) -> str:
    """验证非空文本字段。"""
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} 必须是非空文本")
    return value.strip()


def validate_route_competition(payload: dict[str, Any]) -> list[str]:
    """校验路线竞争至少存在基线和真正不同的比较路线。

    Args:
        payload: 路线竞争的结构化输入。

    Returns:
        可读错误列表，空列表表示通过。
    """
    errors: list[str] = []
    baseline = payload.get("baseline")
    candidates = payload.get("candidates")
    if not isinstance(baseline, dict):
        return ["ROUTE_COMPETITION 必须包含 baseline"]
    try:
        baseline_structure = _require_text(baseline.get("mathematical_structure"), "baseline.mathematical_structure")
    except ContractError as exc:
        errors.append(str(exc))
        baseline_structure = ""
    if not isinstance(candidates, list) or not candidates:
        errors.append("至少需要一条与 baseline 真正不同的竞争路线或反证路线")
        return errors
    distinct = False
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            errors.append(f"candidates[{index}] 必须是对象")
            continue
        try:
            structure = _require_text(candidate.get("mathematical_structure"), f"candidates[{index}].mathematical_structure")
            _require_text(candidate.get("probe"), f"candidates[{index}].probe")
        except ContractError as exc:
            errors.append(str(exc))
            continue
        if structure != baseline_structure:
            distinct = True
    if not distinct:
        errors.append("仅替换遗传算法、粒子群或差分进化等求解器不构成不同路线")
    return errors


def validate_next_experiments(payload: dict[str, Any]) -> list[str]:
    """检查实验队列是否说明能够改变的决定，而非收集装饰性结果。

    Args:
        payload: 实验队列对象。

    Returns:
        警告列表；实验价值不足不阻断工作流。
    """
    warnings: list[str] = []
    experiments = payload.get("experiments", [])
    if not isinstance(experiments, list):
        return ["NEXT_EXPERIMENTS 的 experiments 必须是数组"]
    for index, experiment in enumerate(experiments):
        if not isinstance(experiment, dict):
            warnings.append(f"experiments[{index}] 不是对象")
            continue
        decision = experiment.get("decision")
        if not isinstance(decision, str) or not decision.strip():
            warnings.append(f"experiments[{index}] 未说明会改变哪项路线、模型或结论决定")
    return warnings


def write_answer_map(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """保存逐问直接答案映射，不把它提升为贡献主张合同。

    Args:
        run_dir: 当前运行目录。
        payload: 以问题 ID 为键的答案映射。

    Returns:
        已写入的规范对象。
    """
    state = read_simple_state(run_dir)
    questions = set(state["required_questions"])
    mapping = payload.get("answers", payload)
    if not isinstance(mapping, dict):
        raise ContractError("answer_map 必须是问题 ID 到答案位置的对象")
    missing = sorted(questions - set(mapping))
    if missing:
        raise ContractError("answer_map 缺少必答问题: " + ", ".join(missing))
    for question_id in questions:
        item = mapping[question_id]
        if not isinstance(item, dict):
            raise ContractError(f"{question_id} 的 answer_map 条目必须是对象")
        result_ids = item.get("result_ids")
        location = item.get("direct_answer_location")
        if not isinstance(result_ids, list) or not result_ids or not all(isinstance(value, str) for value in result_ids):
            raise ContractError(f"{question_id} 必须绑定至少一个 result_id")
        _require_text(location, f"{question_id}.direct_answer_location")
    document = {
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "answers": mapping,
        "generated_at": utc_now(),
    }
    atomic_json(run_dir / ANSWER_MAP_PATH, document)
    return document
