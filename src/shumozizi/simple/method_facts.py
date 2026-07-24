"""从真实执行事实提取可选的方法提示，不把元数据变成阶段门禁。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import atomic_json, load_json
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import utc_now

METHOD_FACTS_PATH = Path("analysis/method_facts.json")
_FACT_NAMES = (
    "uses_stochastic_solver",
    "uses_proxy_objective",
    "uses_temporal_split",
    "uses_continuous_geometry",
    "uses_heuristic_optimization",
    "has_shared_downstream_dependency",
)


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
    facts: dict[str, bool | str] = {name: "unknown" for name in _FACT_NAMES}
    facts["uses_proxy_objective"] = proxy if results else "unknown"
    facts["has_shared_downstream_dependency"] = shared if results else "unknown"
    return {
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "facts": facts,
        "result_ids": [item["result_id"] for item in results],
        "generated_at": utc_now(),
    }


def write_method_facts(run_dir: Path) -> dict[str, Any]:
    """生成并保存可选方法事实。

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
        非阻断建议列表。
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
