"""结果准入前的语义级检查。

结构 Schema 只能确认字段存在；本模块检查目标/特征角色、模型族最低验证证据以及路线锁一致性。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, load_json, sha256_file
from shumozizi.core.schema import require_valid

MIN_VALIDATION_TOKENS = {
    "statistical": ("residual", "holdout", "cross", "bootstrap", "uncertainty"),
    "optimization": ("feasib", "constraint", "sensitivity", "robust", "optimality"),
    "prediction": ("holdout", "cross", "test", "residual", "forecast"),
    "simulation": ("replication", "seed", "sensitivity", "convergence", "scenario"),
    "classification": ("holdout", "cross", "confusion", "roc", "precision", "recall"),
}


def validate_candidate_semantics(run_dir: Path, candidate: dict[str, Any]) -> list[str]:
    """返回语义准入错误；没有 model_spec 的历史最小运行不强制升级。"""
    spec_path = run_dir / "brief" / "model_spec.json"
    lock_path = run_dir / "brief" / "ROUTE_LOCK.json"
    if not spec_path.is_file() and not lock_path.is_file():
        errors: list[str] = []
        targets = set(candidate.get("target_columns", []))
        features = set(candidate.get("feature_columns", []))
        if targets & features:
            errors.append("target_columns 与 feature_columns 有交集，疑似目标泄漏")
        if candidate.get("evaluation_source") in {"train", "training", "in_sample"}:
            errors.append("评价指标来自训练样本，禁止训练评价冒充泛化评价")
        return errors
    errors: list[str] = []
    targets = set(candidate.get("target_columns", []))
    features = set(candidate.get("feature_columns", []))
    if targets & features:
        errors.append("target_columns 与 feature_columns 有交集，疑似目标泄漏")
    if candidate.get("evaluation_source") in {"train", "training", "in_sample"}:
        errors.append("评价指标来自训练样本，禁止训练评价冒充泛化评价")
    if not lock_path.is_file():
        return ["存在 model_spec 时必须存在已批准 ROUTE_LOCK.json"]
    try:
        lock = load_json(lock_path)
        if lock.get("approved") is not True:
            errors.append("结果准入要求 ROUTE_LOCK.approved=true")
        route_hash = sha256_file(lock_path)
        declared_route = candidate.get("route_lock_sha256")
        if declared_route is not None and declared_route != route_hash:
            errors.append("候选结果引用的 route_lock_sha256 已失效")
        if spec_path.is_file():
            spec = load_json(spec_path)
            require_valid(spec, "model_spec")
            if spec["run_id"] != run_dir.name:
                errors.append("model_spec.run_id 与运行目录不一致")
            if spec["route_lock_sha256"] != route_hash:
                errors.append("model_spec 未绑定当前 ROUTE_LOCK")
            question = next((item for item in spec["questions"] if item["question_id"] == candidate.get("question_id")), None)
            if question is None:
                errors.append("候选结果 question_id 不在 model_spec 中")
            else:
                target = question["target_role"]
                features = set(question["feature_roles"])
                if target in features:
                    errors.append("目标变量同时出现在特征角色中，疑似目标泄漏")
                variable_names = {item["name"] for item in question["variables"]}
                if target not in variable_names:
                    errors.append("model_spec.target_role 未映射到变量")
                candidate_target = candidate.get("target_role")
                candidate_features = set(candidate.get("feature_roles", []))
                if candidate_target and candidate_target != target:
                    errors.append("候选结果目标角色与 model_spec 不一致")
                if candidate_features & ({target} | {candidate_target} if candidate_target else set()):
                    errors.append("候选结果特征角色包含目标角色")
                tokens = " ".join(str(item) for item in candidate.get("validation_checks", []))
                required = MIN_VALIDATION_TOKENS[question["model_family"]]
                if not any(token in tokens.lower() for token in required):
                    errors.append(f"{question['model_family']} 结果缺少最低验证证据")
    except (ContractError, OSError, KeyError) as exc:
        errors.append(str(exc))
    return errors


def require_candidate_semantics(run_dir: Path, candidate: dict[str, Any]) -> None:
    """以协议异常形式阻断不满足语义准入的候选结果。"""
    errors = validate_candidate_semantics(run_dir, candidate)
    if errors:
        raise ContractError("语义准入失败: " + "; ".join(errors))
