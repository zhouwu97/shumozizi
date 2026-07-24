"""管理与方法画像分离的高价值关键主张。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import ContractError, load_json, sha256_file
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.simple.method_profile import METHOD_PROFILE_PATH
from shumozizi.simple.objective_semantics import objective_semantics_digest
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import read_simple_state

CRITICAL_CLAIMS_PATH = Path("analysis/critical_claims.json")


def _schema() -> dict[str, Any]:
    """返回关键主张 Schema。"""
    return load_json(resolve_repo_root(Path(__file__)) / "schemas/simple_critical_claims.schema.json")


def read_critical_claims(run_dir: Path) -> dict[str, Any]:
    """读取独立关键主张合同。"""
    path = run_dir / CRITICAL_CLAIMS_PATH
    if not path.is_file():
        raise ContractError("缺少 analysis/critical_claims.json")
    return load_json(path)


def critical_claim_digest(run_dir: Path) -> str:
    """返回当前关键主张文件摘要。"""
    return sha256_file(run_dir / CRITICAL_CLAIMS_PATH)


def claims_by_question(run_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """按显式 question_id 分组，禁止根据 claim_id 前缀猜测归属。"""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for claim in read_critical_claims(run_dir)["claims"]:
        grouped.setdefault(claim["question_id"], []).append(claim)
    return grouped


def require_critical_claims(run_dir: Path) -> dict[str, Any]:
    """核验关键主张只绑定本问当前 production 结果。"""
    payload = read_critical_claims(run_dir)
    validator = Draft202012Validator(_schema(), format_checker=FormatChecker())
    errors = [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    ]
    if payload.get("run_id") != run_dir.name:
        errors.append("critical_claims run_id 与运行目录不一致")
    expected_bindings = {
        "method_profile_sha256": sha256_file(run_dir / METHOD_PROFILE_PATH),
        "objective_semantics_sha256": objective_semantics_digest(run_dir),
        "result_index_sha256": sha256_file(run_dir / "results" / "index.json"),
    }
    for name, digest in expected_bindings.items():
        if payload.get("bindings", {}).get(name) != digest:
            errors.append(f"critical_claims 绑定已失效: {name}")

    index = read_result_index(run_dir)
    current = {
        item["result_id"]: item for item in index["results"]
        if item.get("status") == "current"
        and item.get("execution_mode") == "production"
        and item.get("execution_valid") is True
    }
    seen: set[str] = set()
    primary_questions: set[str] = set()
    invalidated = set(payload.get("invalidated_claims", []))
    for claim in payload.get("claims", []):
        claim_id = claim.get("claim_id")
        if claim_id in invalidated:
            errors.append(f"关键主张 {claim_id} 已被独立负面证据失效")
        if claim_id in seen:
            errors.append(f"重复 claim_id: {claim_id}")
        seen.add(claim_id)
        qid = claim.get("question_id")
        if claim.get("importance") == "primary":
            primary_questions.add(qid)
            if claim.get("blocking_if_fails") is not True:
                errors.append(f"primary claim {claim_id} 必须 blocking_if_fails=true")
        for result_id in claim.get("result_ids", []):
            result = current.get(result_id)
            if result is None:
                errors.append(f"主张 {claim_id} 绑定了非当前 production 结果: {result_id}")
            elif result.get("question_id") != qid and not (
                result.get("dependency_scope") in {"shared", "global"}
                and qid in result.get("affected_question_ids", [])
            ):
                errors.append(f"主张 {claim_id} 不能由其他问题结果 {result_id} 背书")
    required = set(read_simple_state(run_dir).get("required_questions", []))
    missing = sorted(required - primary_questions)
    if missing:
        errors.append("必答问题缺少 primary claim: " + ", ".join(missing))
    if errors:
        raise ContractError("关键主张不满足进入科学审核的条件: " + "；".join(errors))
    return payload
