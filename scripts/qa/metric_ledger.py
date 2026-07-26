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

from shumozizi.core.io import ContractError, atomic_json, load_json
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
    """从答案图与结果索引生成账本草稿（每题首个量置 central=True，定性题自动豁免）。

    每个问题的首个数值指标自动置 ``central=True`` 作为自洽检查基准，其余置
    ``central=False``（仅告警）。没有数值直接答案的定性题自动写入
    ``qualitative_exemptions``，避免 ``v32_ledger_requirements`` 因缺豁免而拒绝。

    写作者应随后确认：真正反复引用的核心量保持 ``central=true``、别名改为中文、
    补充单位；定性题的豁免原因替换为具体描述；与中心论证无关的量可置 ``central=false``。

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
    qualitative_exemptions: list[dict[str, str]] = []
    seen: set[str] = set()
    for question_id, answer in answer_map.get("answers", {}).items():
        # 每题首个出现的数值量置 central=True，确保账本具有至少一个硬门候选。
        question_has_central = False
        question_has_metrics = False
        for result_id in answer.get("result_ids", []):
            for metric_name in current.get(result_id, {}):
                question_has_metrics = True
                metric_id = f"{question_id}.{metric_name}"
                if metric_id in seen:
                    continue
                seen.add(metric_id)
                # 首个量升为 central；其余保持 False（告警不阻断）。
                is_central = not question_has_central
                if is_central:
                    question_has_central = True
                metrics.append(
                    {
                        "metric_id": metric_id,
                        "name": "",
                        "aliases": [metric_name],
                        "source_result_id": result_id,
                        "source_metric": metric_name,
                        "unit": None,
                        "central": is_central,
                        "scope": {"question_id": question_id},
                    }
                )
        # 无数值直接答案的定性题：自动写豁免占位，禁止静默跳过。
        if not question_has_metrics:
            qualitative_exemptions.append(
                {
                    "question_id": question_id,
                    "reason": (
                        "播种草稿：该题在 results/index.json 中无 current 数值指标，"
                        "需人工确认是否属定性问题并补充具体原因。"
                    ),
                }
            )
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "note": (
            "已按每题首个数值量置 central=true，作为自洽检查基准。"
            "核对后应将真正反复引用的核心量保持或补充 central=true、别名改为中文、补充单位；"
            "确认与中心论证无关的量可置 central=false（仅告警，不阻断）。"
        ),
        "metrics": metrics,
        "qualitative_exemptions": qualitative_exemptions,
    }


def ensure_v32_metric_ledger(run_dir: Path) -> tuple[dict[str, Any] | None, bool]:
    """为 v3.2 生产论文自动播种账本，并返回是否在本次调用中新建。

    播种草稿已包含每题首个量 ``central=true`` 与定性题豁免占位，可直接通过
    ``v32_ledger_requirements`` 校验。作者仍应核实并替换占位内容后再提交。

    Args:
        run_dir: 当前 v3.2 运行目录。

    Returns:
        ``(账本, 是否新建)``；非 v3.2 生产论文阶段或已有账本以外的历史运行返回
        ``(None, False)``。
    """
    from shumozizi.simple.state import read_simple_state

    try:
        state = read_simple_state(run_dir)
    except (ContractError, OSError):
        return None, False
    if (
        state.get("schema_version") != "3.2"
        or state.get("execution_mode") != "production"
        or state.get("phase") not in {"paper", "paper_review", "verify", "complete"}
    ):
        return None, False
    existing = read_ledger(run_dir)
    if existing is not None:
        return existing, False
    draft = seed_ledger_from_answers(run_dir)
    atomic_json(run_dir / LEDGER_PATH, draft)
    return draft, True


def v32_ledger_requirements(ledger: dict[str, Any], run_dir: Path) -> list[str]:
    """验证 v3.2 生产论文账本的硬门完整性。

    每个直接答案结果中的数值指标都必须可追溯到账本。纯定性问题没有数值时必须有
    显式豁免；这种豁免仅适用于没有可登记数字的题目，不能覆盖已有主指标。
    """
    from shumozizi.simple.state import read_simple_state

    try:
        state = read_simple_state(run_dir)
    except (ContractError, OSError):
        return []
    if (
        state.get("schema_version") != "3.2"
        or state.get("execution_mode") != "production"
        or state.get("phase") not in {"paper", "paper_review", "verify", "complete"}
    ):
        return []
    answer_map = load_json(run_dir / "paper" / "answer-map.json")
    current = _current_metrics(run_dir)
    registered = {
        (entry["source_result_id"], entry["source_metric"])
        for entry in ledger.get("metrics", [])
    }
    exemptions = {
        item["question_id"]: item["reason"]
        for item in ledger.get("qualitative_exemptions", [])
        if isinstance(item, dict) and isinstance(item.get("question_id"), str)
    }
    errors: list[str] = []
    if not any(item.get("central") is True for item in ledger.get("metrics", [])):
        errors.append("v3.2 production 账本至少需要一个 central=true 核心指标")
    for question_id, answer in answer_map.get("answers", {}).items():
        numeric_pairs = [
            (result_id, metric_name)
            for result_id in answer.get("result_ids", [])
            for metric_name in current.get(result_id, {})
        ]
        if not numeric_pairs:
            if question_id not in exemptions:
                errors.append(f"{question_id} 没有可量化直接答案，必须提供 qualitative_exemptions 原因")
            continue
        if question_id in exemptions:
            errors.append(f"{question_id} 已有数值直接答案，不能使用 qualitative_exemptions")
        for result_id, metric_name in numeric_pairs:
            if (result_id, metric_name) not in registered:
                errors.append(f"{question_id} 直接答案指标未进入账本: {result_id}.{metric_name}")
    return errors


def require_v32_metric_ledger_for_paper(run_dir: Path) -> None:
    """在 v3.2 production 进入论文阶段前播种并验证核心指标账本。"""
    from shumozizi.simple.state import read_simple_state

    state = read_simple_state(run_dir)
    if state.get("schema_version") != "3.2" or state.get("execution_mode") != "production":
        return
    ledger = read_ledger(run_dir)
    if ledger is None:
        ledger = seed_ledger_from_answers(run_dir)
        atomic_json(run_dir / LEDGER_PATH, ledger)
    errors = validate_ledger(ledger)
    # 进入 paper 前当前 state 仍是 experiment；临时以论文阶段的完整性规则验证。
    answer_map = load_json(run_dir / "paper" / "answer-map.json")
    current = _current_metrics(run_dir)
    registered = {
        (entry["source_result_id"], entry["source_metric"])
        for entry in ledger.get("metrics", [])
    }
    exemptions = {
        item["question_id"]
        for item in ledger.get("qualitative_exemptions", [])
        if isinstance(item, dict) and isinstance(item.get("question_id"), str)
    }
    if not any(item.get("central") is True for item in ledger.get("metrics", [])):
        errors.append("v3.2 production 账本至少需要一个 central=true 核心指标")
    for question_id, answer in answer_map.get("answers", {}).items():
        pairs = [
            (result_id, metric_name)
            for result_id in answer.get("result_ids", [])
            for metric_name in current.get(result_id, {})
        ]
        if not pairs and question_id not in exemptions:
            errors.append(f"{question_id} 没有可量化直接答案，必须提供 qualitative_exemptions 原因")
        if pairs and question_id in exemptions:
            errors.append(f"{question_id} 已有数值直接答案，不能使用 qualitative_exemptions")
        for result_id, metric_name in pairs:
            if (result_id, metric_name) not in registered:
                errors.append(f"{question_id} 直接答案指标未进入账本: {result_id}.{metric_name}")
    if errors:
        raise ContractError("不能进入论文阶段：" + "；".join(errors))
