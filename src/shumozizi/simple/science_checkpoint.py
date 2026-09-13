"""管理薄层科学检查点，避免探索阶段被交付协议牵着走。

检查点只记录正式实验前不可含糊的科学事实。其余运行元数据仍由旧协议维护，
但不会成为新策略的写作或探索阻断条件。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.simple.state import read_simple_state, utc_now

SCIENCE_CHECKPOINT_PATH = Path("analysis/science-checkpoint.json")


def is_science_first_run(run_dir: Path) -> bool:
    """判断运行是否启用科学优先语义（含兼容的旧策略名称）。"""
    state = read_simple_state(run_dir)
    if state.get("execution_policy") == "science-first-v1":
        return True
    if state.get("execution_policy") != "risk-adaptive-v1":
        return False
    snapshot_path = run_dir / "state/workflow-snapshot.json"
    if not snapshot_path.is_file():
        return False
    try:
        return load_json(snapshot_path).get("quality_policy") == "science-editorial-v1"
    except ContractError:
        return False


def initialize_science_checkpoint(run_dir: Path, question_ids: list[str]) -> dict[str, Any]:
    """创建可逐步填写的科学检查点，不预填结论。"""
    payload: dict[str, Any] = {
        "schema_name": "science_checkpoint",
        "schema_version": "1.0",
        "run_id": read_simple_state(run_dir)["run_id"],
        "status": "draft",
        "questions": question_ids,
        "semantic_contract": {
            "objective": "",
            "information_set": "",
            "time_and_units": "",
            "settlement_and_terminal_rules": "",
            "aggregation": "",
        },
        "routes": {
            "baseline": "",
            "challenger": "",
            "scorer": "",
        },
        "falsification": {"minimum_counterexample": "", "expected_result": ""},
        "human_decisions": [],
        "updated_at": utc_now(),
    }
    atomic_json(run_dir / SCIENCE_CHECKPOINT_PATH, payload)
    return payload


def read_science_checkpoint(run_dir: Path) -> dict[str, Any]:
    """读取并检查检查点属于当前运行。"""
    payload = load_json(run_dir / SCIENCE_CHECKPOINT_PATH)
    if payload.get("schema_name") != "science_checkpoint":
        raise ContractError("科学检查点 schema_name 无效")
    if payload.get("schema_version") != "1.0":
        raise ContractError("科学检查点版本不支持")
    if payload.get("run_id") != read_simple_state(run_dir)["run_id"]:
        raise ContractError("科学检查点 run_id 与当前运行不一致")
    return payload


def science_checkpoint_status(run_dir: Path) -> dict[str, Any]:
    """返回检查点缺口；探索阶段允许缺口，正式阶段不允许。"""
    payload = read_science_checkpoint(run_dir)
    contract = payload.get("semantic_contract", {})
    routes = payload.get("routes", {})
    falsification = payload.get("falsification", {})
    required = {
        "objective": contract.get("objective"),
        "information_set": contract.get("information_set"),
        "time_and_units": contract.get("time_and_units"),
        "settlement_and_terminal_rules": contract.get("settlement_and_terminal_rules"),
        "aggregation": contract.get("aggregation"),
        "baseline": routes.get("baseline"),
        "challenger": routes.get("challenger"),
        "scorer": routes.get("scorer"),
        "minimum_counterexample": falsification.get("minimum_counterexample"),
        "expected_result": falsification.get("expected_result"),
    }
    missing = [name for name, value in required.items() if not isinstance(value, str) or not value.strip()]
    return {"ready": not missing and payload.get("status") == "ready", "missing": missing, "payload": payload}


def require_science_checkpoint(run_dir: Path) -> dict[str, Any]:
    """要求薄层检查点闭合，作为 science-first 生产入口唯一前置科学门。"""
    status = science_checkpoint_status(run_dir)
    if not status["ready"]:
        raise ContractError("science_checkpoint 未闭合: " + ", ".join(status["missing"] or ["status 必须为 ready"]))
    return status["payload"]


def update_science_checkpoint(run_dir: Path, patch: dict[str, Any], *, status: str | None = None) -> dict[str, Any]:
    """合并少量科学判断并可显式标记 ready，避免手工改错运行 ID。"""
    payload = read_science_checkpoint(run_dir)
    for key in ("semantic_contract", "routes", "falsification"):
        value = patch.get(key)
        if isinstance(value, dict):
            current = payload.get(key)
            if not isinstance(current, dict):
                current = {}
            current.update(value)
            payload[key] = current
    if status is not None:
        if status not in {"draft", "ready"}:
            raise ContractError("science checkpoint status 必须为 draft 或 ready")
        payload["status"] = status
    payload["updated_at"] = utc_now()
    atomic_json(run_dir / SCIENCE_CHECKPOINT_PATH, payload)
    return payload
