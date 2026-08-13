"""把 production 结果 JSON 适配为高级渲染器的模板输入文档。

render_advanced.py 的模板各自声明了严格的字段契约（如 survival_curve 读
``groups[].points[]{x,probability,ci_lower,ci_upper}``）。而实验生产结果
（``results/raw/*.json``）的形状由模型自由决定，两者并不天然对齐。本模块
提供一组**确定性适配器**：识别常见生产结果形状，构造高级模板可直接消费的
文档，从而让"同一份 current 数据"能渲染出国奖级图，而不是退回朴素单面板。

所有适配器只读真实 production 数据，不模拟、不硬编码、不改结论。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


class AdapterError(ValueError):
    """数据形状不满足该高级模板的最小契约。"""


# 每个适配器：给定 production 文档和输出 stem，构造高级模板输入文档。
# 返回 None 表示数据形状不支持；抛 AdapterError 说明缺什么字段。
Adapter = Callable[[dict[str, Any], Path], dict[str, Any] | None]


def _dig(document: dict[str, Any], path: str) -> Any:
    """按点路径读取字段；缺任一层返回 None。"""
    value: Any = document
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _floatable(value: Any) -> bool:
    """值可安全转换为有限浮点数。"""
    if isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return float("-inf") < number < float("inf")


def _points_from_curve(curve: list[dict[str, Any]]) -> list[dict[str, float]]:
    """把 curve 列表规范为 ``{x, probability, ci_lower, ci_upper}``。"""
    points: list[dict[str, float]] = []
    for item in curve:
        if not isinstance(item, dict):
            continue
        x = item.get("week", item.get("x", item.get("t", item.get("n"))))
        prob = item.get("probability", item.get("p", item.get("p_estimate")))
        low = item.get("lcb", item.get("ci_lower", item.get("low", item.get("ci_lo", prob))))
        high = item.get("ucb", item.get("ci_upper", item.get("high", item.get("ci_hi", prob))))
        if not all(_floatable(value) for value in (x, prob, low, high)):
            continue
        points.append(
            {
                "x": float(x),
                "probability": float(prob),
                "ci_lower": float(low),
                "ci_upper": float(high),
            }
        )
    return points


def adapt_survival_curve(document: dict[str, Any], output: Path) -> dict[str, Any] | None:
    """达标/生存曲线 ← ``recommendation.groups[].curve[]``（如 Q2/Q3 可靠性）。

    多组达标比例曲线，带 CI 带与可靠性阈值，是朴素单面板 reliability 曲线的
    高级替代。阈值优先读显式 ``reliability_assumption``，回退 0.90。
    """
    groups = _dig(document, "recommendation.groups")
    if not isinstance(groups, list) or not groups:
        return None
    threshold = document.get("reliability_assumption", 0.90)
    if not _floatable(threshold):
        threshold = 0.90
    series: list[dict[str, Any]] = []
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            continue
        points = _points_from_curve(group.get("curve", []))
        if not points:
            continue
        bmi_low = group.get("bmi_lower")
        bmi_high = group.get("bmi_upper")
        if _floatable(bmi_low) and _floatable(bmi_high):
            label = f"BMI {float(bmi_low):.1f}–{float(bmi_high):.1f}"
        else:
            label = str(group.get("label", group.get("name", f"组 {index + 1}")))
        status = group.get("status")
        if status:
            label += f"（{'可行' if group.get('feasible') else '窗口内不可行'}）"
        series.append({"label": label, "points": points})
    if not series:
        raise AdapterError("recommendation.groups[].curve[] 无可用达标曲线")
    question_id = str(document.get("question_id", ""))
    return {
        "template": "survival_curve",
        "document": {
            "threshold": float(threshold),
            "x_label": "孕周" if question_id in {"Q2", "Q3", "Q1"} else "时间",
            "y_label": "达标比例",
            "title": "分组建模可靠性达标曲线与阈值",
            "groups": series,
        },
        "question_id": question_id,
    }


def adapt_ci_forest(document: dict[str, Any], output: Path) -> dict[str, Any] | None:
    """置信区间森林图 ← ``coefficients`` + ``confidence_intervals``（如 Q1 回归）。

    系数点估计与 95% 置信区间，零线作阈值；比朴素系数表更直观地暴露哪些
    变量区间跨零、哪些不跨。
    """
    coefficients = _dig(document, "coefficients")
    intervals = _dig(document, "confidence_intervals")
    if not isinstance(coefficients, dict) or not isinstance(intervals, dict):
        return None
    rows: list[dict[str, Any]] = []
    for name, estimate in coefficients.items():
        bounds = intervals.get(name)
        if not isinstance(bounds, (list, tuple)) or len(bounds) < 2:
            continue
        if not all(_floatable(value) for value in (estimate, bounds[0], bounds[1])):
            continue
        rows.append(
            {
                "label": str(name),
                "estimate": float(estimate),
                "low": float(bounds[0]),
                "high": float(bounds[1]),
            }
        )
    if not rows:
        raise AdapterError("coefficients/confidence_intervals 无可用的数值行")
    return {
        "template": "ci_forest",
        "document": {
            "threshold": 0.0,
            "title": "模型系数点估计与 95% 置信区间",
            "rows": rows,
        },
        "question_id": str(document.get("question_id", "")),
    }


def adapt_roc_ci(document: dict[str, Any], output: Path) -> dict[str, Any] | None:
    """ROC 曲线与置信带 ← ``targets``/``predictions``（如 Q4 分类器）。

    朴素 pr_roc 曲线只能给单条 ROC；这里按真实标签与预测分数计算 ROC 并给出
    操作点，让决定性证据带上判别性能与阈值取舍。曲线本身由 production 数据
    确定性计算，不引入模型外的假设。
    """
    targets = _dig(document, "targets")
    predictions = _dig(document, "predictions")
    if not isinstance(targets, list) or not isinstance(predictions, list):
        return None
    if len(targets) != len(predictions) or not targets:
        raise AdapterError("targets/predictions 必须等长且非空")
    pairs = [
        (float(p), int(t))
        for p, t in zip(predictions, targets, strict=False)
        if _floatable(p) and t in {0, 1}
    ]
    if not pairs:
        raise AdapterError("targets/predictions 无有效二分类样本")
    # 按预测分数降序扫阈值，计算 TPR/FPR 曲线（确定性、可复现）。
    pairs.sort(key=lambda item: item[0], reverse=True)
    total_positive = sum(1 for _, t in pairs if t == 1)
    total_negative = len(pairs) - total_positive
    if total_positive == 0 or total_negative == 0:
        return None
    fpr: list[float] = [0.0]
    tpr: list[float] = [0.0]
    tp = fp = 0
    for _, label in pairs:
        if label == 1:
            tp += 1
        else:
            fp += 1
        fpr.append(fp / total_negative)
        tpr.append(tp / total_positive)
    fpr.append(1.0)
    tpr.append(1.0)
    # 梯形法 AUC。
    auc = sum(
        (fpr[i + 1] - fpr[i]) * (tpr[i + 1] + tpr[i]) / 2.0
        for i in range(len(fpr) - 1)
    )
    return {
        "template": "cv_roc_ci",
        "document": {
            "fpr": fpr,
            "tpr": tpr,
            "auc": auc,
            "title": "分类器 ROC 曲线与操作点",
        },
        "question_id": str(document.get("question_id", "")),
    }


ADAPTERS: tuple[Adapter, ...] = (
    adapt_survival_curve,
    adapt_ci_forest,
    adapt_roc_ci,
)


# 各 archetype → 应升级到的适配器。旧图登记为朴素 archetype 时，用同一份
# production 数据渲染高级版并替换。
ARCHETYPE_TO_ADAPTER: dict[str, Adapter] = {
    "probability_curve": adapt_survival_curve,
    "survival_curve": adapt_survival_curve,
    "ci_forest": adapt_ci_forest,
    "pr_roc": adapt_roc_ci,
    "roc_curve": adapt_roc_ci,
    "calibration_curve": adapt_survival_curve,
}


def _figure_source_results(index: dict[str, Any], root: Path) -> list[Path]:
    """收集论文 current 图实际引用的结果文件路径（去重、保序）。"""
    seen: set[str] = set()
    paths: list[Path] = []
    for item in index.get("figures", []):
        if not isinstance(item, dict) or item.get("status") != "current":
            continue
        candidates: list[Any] = []
        if isinstance(item.get("input_result"), dict):
            candidates.append(item["input_result"].get("path"))
        if isinstance(item.get("source_files"), list):
            candidates.extend(
                entry.get("path")
                for entry in item["source_files"]
                if isinstance(entry, dict)
            )
        for raw in candidates:
            if not isinstance(raw, str) or not raw:
                continue
            path = (root / raw).resolve()
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            paths.append(path)
    return paths


def hero_figure_upgrades(
    index: dict[str, Any],
    plan: list[dict[str, Any]],
) -> dict[str, str]:
    """找出应晋升为 question_hero 的高级图计划项。

    若某问已有 question_hero，且其 archetype 在 ``ARCHETYPE_TO_ADAPTER``
    中（说明有更好的高级模板版本），则同一问生成的高级图应接替 hero 角色，
    旧朴素 hero 降为 supporting，避免"hero 仍是单面板曲线"的审计告警。

    Args:
        index: 图索引。
        plan: 高级图计划项。

    Returns:
        映射 ``figure_id -> question_id``，表示这些计划项应登记为 question_hero。
    """
    if not index.get("figures"):
        return {}
    current = [
        item for item in index["figures"]
        if isinstance(item, dict) and item.get("status") == "current"
    ]
    hero_by_question: dict[str, str] = {}
    for item in current:
        if item.get("presentation_role") not in {"question_hero", "data_portrait"}:
            continue
        archetype = str(item.get("visual_archetype") or item.get("template_id") or "")
        if archetype not in ARCHETYPE_TO_ADAPTER:
            continue
        question_id = str(item.get("question_id", ""))
        if question_id:
            hero_by_question[question_id] = archetype
    return {
        item["output"].rsplit("/", 1)[-1]: item["question_id"]
        for item in plan
        if item["question_id"] in hero_by_question
    }


def build_advanced_figures(
    run_dir: Path,
    *,
    results_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """为论文 current 图引用的生产结果生成高级模板计划项。

    从 ``figures/index.json`` 出发，只适配正文实际使用的 production 结果，
    从而把"朴素单面板图"升级为同一数据渲染的高级图，而不是无差别扫描
    ``results/raw`` 里所有历史版本。

    Args:
        run_dir: 当前运行目录。
        results_dir: 结果目录；默认 ``<run_dir>/results/raw``。

    Returns:
        计划项列表，每项含 ``template``、``document``、``input``、``output``、
        ``question_id`` 与 ``adapter``；``output`` 为 ``figures/current/``
        下的 stem。
    """
    root = run_dir.resolve()
    index_path = root / "figures/index.json"
    index = json_load(index_path) if index_path.is_file() else {}
    sources = _figure_source_results(index, root)
    plan: list[dict[str, Any]] = []
    for path in sources:
        try:
            document = json_load(path)
        except (OSError, ValueError):
            continue
        if not isinstance(document, dict):
            continue
        name = path.stem
        for adapter in ADAPTERS:
            output_stem = f"figures/current/adv_{name}_{adapter.__name__.replace('adapt_', '')}"
            try:
                built = adapter(document, root / output_stem)
            except AdapterError:
                continue
            if built is None:
                continue
            plan.append(
                {
                    "template": built["template"],
                    "document": built["document"],
                    "input": path.relative_to(root).as_posix(),
                    "output": output_stem,
                    "question_id": built["question_id"],
                    "adapter": adapter.__name__,
                }
            )
    return plan


def json_load(path: Path) -> dict[str, Any]:
    """读取 JSON 对象（缺失/损坏时抛错给调用方处理）。"""
    import json

    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} 不是 JSON 对象")
    return payload
