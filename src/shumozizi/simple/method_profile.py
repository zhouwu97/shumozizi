"""读取并核验首轮真实实验后生成的方法画像。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import ContractError, load_json, sha256_file
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.simple.capabilities import ROUTE_PATH, read_capability_route
from shumozizi.simple.objective_semantics import objective_semantics_digest
from shumozizi.simple.results import read_result_index

METHOD_PROFILE_PATH = Path("analysis/method_profile.json")
_SCRIPT_ENGINES = {".py": "python", ".m": "matlab", ".r": "r", ".jl": "julia"}


def _schema() -> dict[str, Any]:
    """返回方法画像 Schema。"""
    return load_json(resolve_repo_root(Path(__file__)) / "schemas/simple_method_profile.schema.json")


def build_method_profile_bindings(run_dir: Path) -> dict[str, str]:
    """从当前路线、结果和目标语义构建画像绑定。"""
    route_path = run_dir / ROUTE_PATH
    result_path = run_dir / "results" / "index.json"
    read_capability_route(run_dir)
    read_result_index(run_dir)
    return {
        "capability_route_sha256": sha256_file(route_path),
        "result_index_sha256": sha256_file(result_path),
        "objective_semantics_sha256": objective_semantics_digest(run_dir),
    }


def read_method_profile(run_dir: Path) -> dict[str, Any]:
    """读取方法画像，不把它当作分析前模板。"""
    path = run_dir / METHOD_PROFILE_PATH
    if not path.is_file():
        raise ContractError("缺少 analysis/method_profile.json")
    return load_json(path)


def _property_value(properties: dict[str, Any], name: str) -> bool | None:
    """读取布尔或显式 declared 布尔属性。"""
    value = properties.get(name)
    if isinstance(value, bool):
        return value
    if isinstance(value, dict) and isinstance(value.get("value"), bool):
        return value["value"]
    return None


def validate_method_profile(run_dir: Path, payload: dict[str, Any] | None = None) -> list[str]:
    """交叉核验方法画像与本轮真实执行事实。"""
    profile = payload if payload is not None else read_method_profile(run_dir)
    validator = Draft202012Validator(_schema(), format_checker=FormatChecker())
    errors = [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(profile), key=lambda item: list(item.path))
    ]
    if errors:
        return errors
    if profile["run_id"] != run_dir.name:
        errors.append("method_profile run_id 与运行目录不一致")
    try:
        expected = build_method_profile_bindings(run_dir)
    except (ContractError, OSError) as exc:
        return [str(exc)]
    for name, digest in expected.items():
        if profile["bindings"].get(name) != digest:
            errors.append(f"method_profile 绑定已失效: {name}")

    index = read_result_index(run_dir)
    current = [
        item for item in index["results"]
        if item.get("status") == "current"
        and item.get("execution_mode") == "production"
        and item.get("execution_valid") is True
    ]
    by_question: dict[str, list[dict[str, Any]]] = {}
    for item in current:
        by_question.setdefault(item["question_id"], []).append(item)
    route_engine = read_capability_route(run_dir)["toolchain"]["production_engine"]
    seen: set[str] = set()
    for question in profile["questions"]:
        qid = question["question_id"]
        if qid in seen:
            errors.append(f"method_profile 重复 question_id: {qid}")
            continue
        seen.add(qid)
        receipts = by_question.get(qid, [])
        if not receipts:
            errors.append(f"{qid} 尚无首轮真实 production 执行")
            continue
        for group_name in (
            "solver_properties",
            "data_properties",
            "mathematical_properties",
        ):
            properties = question.get(group_name, {})
            if properties and all(
                _property_value(properties, name) is False for name in properties
            ):
                errors.append(
                    f"{qid} 的 {group_name} 不得为字段齐全而只登记 false；不适用字段应省略"
                )
        declared_engine = question.get("production_engine")
        observed_engines = {
            _SCRIPT_ENGINES.get(Path(item.get("source_script", "")).suffix.lower())
            for item in receipts
            if item.get("source_script")
        } - {None}
        if declared_engine and observed_engines and declared_engine not in observed_engines:
            errors.append(f"{qid} 声明的 production_engine 与执行收据冲突")
        if declared_engine and declared_engine != route_engine:
            errors.append(f"{qid} 声明的 production_engine 与能力路由冲突")
        solver = question.get("solver_properties", {})
        proxy_declared = _property_value(solver, "uses_proxy_objective")
        has_proxy = any(
            {"proxy_score", "exact_score"}.issubset(set(item.get("metrics", {})))
            for item in receipts
        )
        if proxy_declared is False and has_proxy:
            errors.append(f"{qid} 收据同时登记 proxy_score/exact_score，不能声明未使用代理目标")
    return errors


def require_method_profile(run_dir: Path) -> dict[str, Any]:
    """要求当前方法画像存在、来自真实实验且绑定未漂移。"""
    profile = read_method_profile(run_dir)
    errors = validate_method_profile(run_dir, profile)
    if errors:
        raise ContractError("方法画像不满足进入科学审核的条件: " + "；".join(errors))
    return profile
