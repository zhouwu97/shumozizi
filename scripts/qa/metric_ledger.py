"""论文核心数值账本：单一数值源的读取、校验与从答案图播种。

账本（``paper/generated/metric_ledger.json``）把论文反复引用的核心量登记为
指向 ``results/index.json`` 中 ``result_id.metric`` 的指针，并记录其正文别名、
单位与语义口径。真值不在账本内复制，检查时现取，故账本不会与结果漂移。

本模块只负责账本这一产物本身；跨章节数值自洽的判定在
``scripts.qa.check_central_metric_coherence``。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from shumozizi.core.io import load_json
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.simple.results import read_result_index

LEDGER_PATH = Path("paper/generated/metric_ledger.json")


def _schema() -> dict[str, Any]:
    """读取核心数值账本 Schema。

    Returns:
        JSON Schema 对象。
    """
    return load_json(resolve_repo_root(Path(__file__)) / "schemas/metric_ledger.schema.json")


def validate_ledger(payload: dict[str, Any]) -> list[str]:
    """校验账本结构。

    Args:
        payload: 待校验账本对象。

    Returns:
        全部校验错误；为空表示通过。
    """
    validator = Draft202012Validator(_schema())
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    ]


def read_ledger(run_dir: Path) -> dict[str, Any] | None:
    """读取核心数值账本，不存在时返回 None。

    Args:
        run_dir: v3 运行目录。

    Returns:
        账本对象；账本文件缺失时为 None（表示未启用该门禁）。
    """
    path = run_dir / LEDGER_PATH
    if not path.is_file():
        return None
    return load_json(path)


def _current_metrics(run_dir: Path) -> dict[str, dict[str, Any]]:
    """收集 current 结果的数值指标，供账本解析与旁证比对。

    Args:
        run_dir: v3 运行目录。

    Returns:
        result_id 到其数值指标映射的字典。
    """
    metrics: dict[str, dict[str, Any]] = {}
    for result in read_result_index(run_dir)["results"]:
        if result["status"] != "current":
            continue
        numeric = {
            key: float(value)
            for key, value in result["metrics"].items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        if numeric:
            metrics[result["result_id"]] = numeric
    return metrics


def resolve_ledger_value(
    current_metrics: dict[str, dict[str, Any]],
    source_result_id: str,
    source_metric: str,
) -> float | None:
    """从 current 指标解析账本条目指向的权威值。

    Args:
        current_metrics: :func:`_current_metrics` 的输出。
        source_result_id: 权威值所在结果 ID。
        source_metric: 该结果 metrics 下的键名。

    Returns:
        解析出的浮点值；结果或键缺失时为 None。
    """
    return current_metrics.get(source_result_id, {}).get(source_metric)


def known_values(run_dir: Path) -> list[tuple[float, str]]:
    """列出全部 current 数值指标，作为“合法数字全集”供旁证判定。

    Args:
        run_dir: v3 运行目录。

    Returns:
        (值, "result_id.metric") 列表。
    """
    pairs: list[tuple[float, str]] = []
    for result_id, metrics in _current_metrics(run_dir).items():
        for key, value in metrics.items():
            pairs.append((value, f"{result_id}.{key}"))
    return pairs


def seed_ledger_from_answers(run_dir: Path) -> dict[str, Any]:
    """从答案图与结果索引生成账本草稿（值/口径自动、别名待补、central 默认 False）。

    草稿把每个问题“直接答案结果”的数值指标各列为一条候选核心量，别名占位为指标
    键名、``central`` 一律为 False。写作者随后应：把真正反复引用的 1~3 个量置
    ``central=true``、补上中文别名与单位。未经确认的草稿是惰性的（不产生硬门）。

    Args:
        run_dir: v3 运行目录。

    Returns:
        账本草稿对象（未落盘）。

    Raises:
        ContractError: 答案图或结果索引不满足协议。
    """
    index = read_result_index(run_dir)
    run_id = index["run_id"]
    answer_map = load_json(run_dir / "paper" / "answer-map.json")
    current = _current_metrics(run_dir)
    metrics: list[dict[str, Any]] = []
    seen: set[str] = set()
    for question_id, answer in answer_map.get("answers", {}).items():
        for result_id in answer.get("result_ids", []):
            for metric_name in current.get(result_id, {}):
                metric_id = f"{question_id}.{metric_name}"
                if metric_id in seen:
                    continue
                seen.add(metric_id)
                metrics.append(
                    {
                        "metric_id": metric_id,
                        "name": "",
                        "aliases": [metric_name],
                        "source_result_id": result_id,
                        "source_metric": metric_name,
                        "unit": None,
                        "central": False,
                        "scope": {"question_id": question_id},
                    }
                )
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "note": (
            "草稿：请把真正反复引用的核心量置 central=true，补中文别名与单位；"
            "其余保持 central=false（仅告警，不阻断）。"
        ),
        "metrics": metrics,
    }
