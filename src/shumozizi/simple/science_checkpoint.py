"""管理薄层科学检查点，避免探索阶段被交付协议牵着走。

检查点只记录正式实验前不可含糊的科学事实。其余运行元数据仍由旧协议维护，
但不会成为新策略的写作或探索阻断条件。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.simple.state import read_simple_state, utc_now

SCIENCE_CHECKPOINT_PATH = Path("analysis/science-checkpoint.json")


def is_science_first_run(run_dir: Path) -> bool:
    """判断运行是否启用科学优先语义（含兼容的旧策略名称）。"""
    state = read_simple_state(run_dir)
    # 新运行以 profile 为主，策略字段作一致性确认；旧快照仅作最后兼容回退。
    if state.get("workflow_profile") == "science-first":
        return True
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
        "schema_version": "1.1",
        "run_id": read_simple_state(run_dir)["run_id"],
        "status": "draft",
        "questions": question_ids,
        "shared_context": {
            "global_time_basis": "",
            "shared_units": "",
            "shared_constraints": "",
        },
        "question_contracts": {
            question_id: {
                "objective": "",
                "required_output": "",
                "mathematical_object": "",
                "information_set": "",
                "aggregation": "",
                "boundary_conditions": "",
                "baseline": "",
                "scorer": "",
                "falsification": "",
                "challenge": {
                    "required": False,
                    "route": "",
                    "reason_if_not_required": "",
                },
            }
            for question_id in question_ids
        },
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
    if payload.get("schema_version") not in {"1.0", "1.1"}:
        raise ContractError("科学检查点版本不支持")
    if payload.get("run_id") != read_simple_state(run_dir)["run_id"]:
        raise ContractError("科学检查点 run_id 与当前运行不一致")
    return payload


def science_checkpoint_status(run_dir: Path) -> dict[str, Any]:
    """返回检查点缺口；探索阶段允许缺口，正式阶段不允许。"""
    payload = read_science_checkpoint(run_dir)
    has_new_contract = any(
        isinstance(item, dict)
        and any(str(value).strip() for key, value in item.items() if key != "challenge" and isinstance(value, str))
        for item in (payload.get("question_contracts", {}) or {}).values()
    ) if isinstance(payload.get("question_contracts"), dict) else False
    if payload.get("schema_version") == "1.1" and has_new_contract:
        missing: list[str] = []
        shared = payload.get("shared_context", {})
        for key in ("global_time_basis", "shared_units", "shared_constraints"):
            if not isinstance(shared.get(key), str) or not shared.get(key, "").strip():
                missing.append(f"shared_context.{key}")
        for question_id in payload.get("questions", []):
            contract = payload["question_contracts"].get(question_id, {})
            for key in ("objective", "required_output", "mathematical_object", "information_set", "aggregation", "boundary_conditions", "baseline", "scorer", "falsification"):
                if not isinstance(contract.get(key), str) or not contract.get(key, "").strip():
                    missing.append(f"{question_id}.{key}")
            challenge = contract.get("challenge", {})
            if challenge.get("required") is True:
                if not isinstance(challenge.get("route"), str) or not challenge.get("route", "").strip():
                    missing.append(f"{question_id}.challenge.route")
            elif not isinstance(challenge.get("reason_if_not_required"), str) or not challenge.get("reason_if_not_required", "").strip():
                missing.append(f"{question_id}.challenge.reason_if_not_required")
        return {"ready": not missing and payload.get("status") == "ready", "missing": missing, "payload": payload}
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
    for key in ("semantic_contract", "routes", "falsification", "shared_context", "question_contracts"):
        value = patch.get(key)
        if isinstance(value, dict):
            current = payload.get(key)
            if not isinstance(current, dict):
                current = {}
            current.update(value)
            payload[key] = current
    if isinstance(patch.get("human_decisions"), list):
        payload["human_decisions"] = patch["human_decisions"]
    if status is not None:
        if status not in {"draft", "ready"}:
            raise ContractError("science checkpoint status 必须为 draft 或 ready")
        payload["status"] = status
    payload["updated_at"] = utc_now()
    atomic_json(run_dir / SCIENCE_CHECKPOINT_PATH, payload)
    return payload


def science_checkpoint_digest(run_dir: Path, question_id: str | None = None) -> str:
    """返回当前检查点科学事实的稳定摘要，供 production 结果绑定。

    ``updated_at`` 与运行状态不参与摘要；只要目标、聚合、信息集或反例改变，
    摘要就会改变，从而使旧 production 自动失去冻结资格。
    """
    payload = read_science_checkpoint(run_dir)
    has_new_contract = (
        isinstance(payload.get("question_contracts"), dict)
        and any(
            isinstance(item, dict)
            and any(
                isinstance(value, str) and value.strip()
                for key, value in item.items()
                if key != "challenge"
            )
            for item in payload.get("question_contracts", {}).values()
        )
    )
    if payload.get("schema_version") == "1.1" and has_new_contract:
        relevant: dict[str, Any] = {
            "schema_version": payload.get("schema_version"),
            "shared_context": payload.get("shared_context", {}),
            "human_decisions": payload.get("human_decisions", []),
        }
        contracts = payload["question_contracts"]
        relevant["question_contracts"] = (
            {question_id: contracts.get(question_id, {})}
            if question_id is not None
            else contracts
        )
    else:
        relevant = {
            "schema_version": payload.get("schema_version"),
            "semantic_contract": payload.get("semantic_contract", {}),
            "routes": payload.get("routes", {}),
            "falsification": payload.get("falsification", {}),
        }
    encoded = json.dumps(relevant, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
