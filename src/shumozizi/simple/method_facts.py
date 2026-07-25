"""汇总实验显式登记与可追溯静态信号的方法事实。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, resolve_inside
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import utc_now

METHOD_FACTS_PATH = Path("analysis/method_facts.json")
METHOD_FACT_DECLARATIONS_PATH = Path("analysis/method_facts.declared.json")
_FACT_NAMES = (
    "uses_stochastic_solver",
    "uses_proxy_objective",
    "uses_temporal_split",
    "uses_continuous_geometry",
    "uses_heuristic_optimization",
    "uses_continuous_time",
    "uses_discrete_approximation",
    "candidate_search_limited",
    "has_shared_downstream_dependency",
)


def _read_declared_facts(run_dir: Path) -> dict[str, bool | str]:
    """读取实验作者显式登记的事实，并拒绝未声明字段。"""
    path = run_dir / METHOD_FACT_DECLARATIONS_PATH
    if not path.is_file():
        return {}
    payload = load_json(path)
    facts = payload.get("facts") if isinstance(payload, dict) else None
    if not isinstance(facts, dict):
        raise ContractError("method_facts.declared.json 必须含 facts 对象")
    invalid = set(facts) - set(_FACT_NAMES)
    if invalid:
        raise ContractError("method_facts.declared.json 含未知事实: " + ", ".join(sorted(invalid)))
    for name, value in facts.items():
        if value not in {True, False, "unknown"}:
            raise ContractError(f"方法事实 {name} 必须为 true、false 或 unknown")
    return facts


def record_method_facts(run_dir: Path, facts: dict[str, bool | str]) -> Path:
    """登记由实验设计者确认的方法事实，供审查前的联合推断优先使用。"""
    payload = {"schema_version": "1.0", "run_id": run_dir.name, "facts": facts}
    # 复用读取器完成字段和值的严格校验，避免写入后才发现协议错误。
    temporary = run_dir / METHOD_FACT_DECLARATIONS_PATH
    atomic_json(temporary, payload)
    _read_declared_facts(run_dir)
    return temporary


def _source_text(run_dir: Path, results: list[dict[str, Any]]) -> str:
    """汇集当前执行命令、源码和 INSIGHTS 的只读静态提示。"""
    chunks: list[str] = []
    for result in results:
        chunks.append(str(result.get("command", "")))
        source = result.get("source_script")
        if not isinstance(source, str):
            continue
        try:
            path = resolve_inside(run_dir, source, must_exist=True)
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
        except (ContractError, OSError, ValueError):
            # 静态提示缺失不覆盖已有显式事实，也不将猜测写成 false。
            continue
    insights = run_dir / "analysis" / "INSIGHTS.md"
    if insights.is_file():
        chunks.append(insights.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks).lower()


def infer_method_facts(run_dir: Path) -> dict[str, Any]:
    """由当前真实结果推断少量方法事实，不能推断时显式保留 unknown。

    Args:
        run_dir: 当前运行目录。

    Returns:
        可写入 ``analysis/method_facts.json`` 的事实对象。
    """
    results = [
        item
        for item in read_result_index(run_dir)["results"]
        if item.get("status") == "current" and item.get("execution_mode") == "production"
    ]
    proxy = any({"proxy_score", "exact_score"} <= set(item.get("metrics", {})) for item in results)
    shared = any(item.get("dependency_scope") in {"shared", "global"} for item in results)
    source_text = _source_text(run_dir, results)
    facts: dict[str, bool | str] = {name: "unknown" for name in _FACT_NAMES}
    if results:
        facts["uses_proxy_objective"] = proxy
        facts["has_shared_downstream_dependency"] = shared
    static_rules = {
        "uses_continuous_time": ("continuous", "time", "trajectory", "ode"),
        "uses_discrete_approximation": ("linspace", "arange", "time_grid", "dt", "step="),
        "uses_heuristic_optimization": ("differential_evolution", "genetic", "pymoo", "simulated_annealing", "heuristic"),
        "candidate_search_limited": ("maxiter", "max_iter", "n_samples", "sample_count", "budget="),
        "uses_proxy_objective": ("proxy", "surrogate"),
        "uses_temporal_split": ("train_test_split", "time_split", "rolling", "walk_forward"),
    }
    for name, hints in static_rules.items():
        if any(hint in source_text for hint in hints):
            facts[name] = True
    registered = [
        item.get("method_facts", {})
        for item in results
        if isinstance(item.get("method_facts"), dict)
    ]
    for name in _FACT_NAMES:
        values = [entry[name] for entry in registered if name in entry]
        if True in values:
            facts[name] = True
        elif values and all(value is False for value in values):
            facts[name] = False
    declared = _read_declared_facts(run_dir)
    # 显式实验登记优先于指标名、命令行和源码关键词等不完整推断。
    facts.update(declared)
    return {
        "schema_version": "1.1",
        "run_id": run_dir.name,
        "facts": facts,
        "declared_facts": declared,
        "inference_sources": [
            "declared",
            "result_metrics",
            "result_registration_metadata",
            "execution_command",
            "source_static_hints",
            "insights",
        ],
        "result_ids": [item["result_id"] for item in results],
        "generated_at": utc_now(),
    }


def write_method_facts(run_dir: Path) -> dict[str, Any]:
    """生成并保存供全面审核后查漏使用的方法事实。

    Args:
        run_dir: 当前运行目录。

    Returns:
        已保存的方法事实。
    """
    payload = infer_method_facts(run_dir)
    atomic_json(run_dir / METHOD_FACTS_PATH, payload)
    return payload


def read_method_facts(run_dir: Path) -> dict[str, Any] | None:
    """读取方法事实；缺失只代表尚未生成，不是生产错误。

    Args:
        run_dir: 当前运行目录。

    Returns:
        已保存事实或 ``None``。
    """
    path = run_dir / METHOD_FACTS_PATH
    return load_json(path) if path.is_file() else None


def method_fact_advice(run_dir: Path) -> list[str]:
    """根据已知事实给出针对性验证建议。

    Args:
        run_dir: 当前运行目录。

    Returns:
        针对性建议列表。
    """
    payload = read_method_facts(run_dir)
    if payload is None:
        return ["未生成 method_facts；可在有真实结果后生成针对性验证建议。"]
    facts = payload.get("facts", {})
    advice: list[str] = []
    if facts.get("uses_stochastic_solver") is True:
        advice.append("随机求解器建议使用多个随机种子复验。")
    if facts.get("uses_proxy_objective") is True:
        advice.append("代理目标建议检查与 exact 目标的排序是否反转。")
    if facts.get("uses_temporal_split") is True:
        advice.append("时间切分建议检查未来信息泄漏。")
    if facts.get("uses_continuous_geometry") is True:
        advice.append("连续几何建议检查端点、切线和离散近似误差。")
    return advice
