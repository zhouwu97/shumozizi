"""以真实 JSON 结果渲染 v3 可用的科研图表模板。"""

from __future__ import annotations

import json
import os
import tempfile
import warnings
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, sha256_file

SUPPORTED_TEMPLATES = (
    "correlation-pairgrid",
    "cv-roc-ci",
    "feasible-region-active-constraints",
    "interval-event-timeline",
    "multi-panel-evidence-chain",
    "paired-raincloud",
    "prediction-marginal-grid",
    "uncertainty-fan-threshold",
)


def _plot_modules() -> tuple[Any, Any, Any]:
    """延迟加载无界面绘图库，避免导入时改变调用方的后端。

    Returns:
        ``matplotlib``、``pyplot`` 和 ``numpy`` 模块。

    Raises:
        ContractError: 未安装可选的真实绘图依赖。
    """
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "shumozizi-matplotlib"))
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError as exc:
        raise ContractError(
            '缺少真实绘图依赖；请先执行 python -m pip install -e ".[figures]"'
        ) from exc
    matplotlib.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": [
                "Microsoft YaHei",
                "Noto Sans CJK SC",
                "SimHei",
                "Arial",
                "DejaVu Sans",
                "sans-serif",
            ],
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "axes.linewidth": 0.8,
            "figure.dpi": 130,
        }
    )
    return matplotlib, plt, np


def _number_list(value: Any, label: str, *, minimum: int = 2) -> list[float]:
    """验证一组有限实数。

    Args:
        value: JSON 中的数组值。
        label: 用于错误定位的字段名。
        minimum: 允许的最小元素数。

    Returns:
        已转换为浮点数的数组。

    Raises:
        ContractError: 输入不是足够长的有限数值数组。
    """
    if not isinstance(value, list) or len(value) < minimum:
        raise ContractError(f"{label} 必须是至少含 {minimum} 个数值的数组")
    try:
        values = [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{label} 必须全部为数值") from exc
    if any(not float("-inf") < item < float("inf") for item in values):
        raise ContractError(f"{label} 不能含 NaN 或无穷值")
    return values


def _object(value: Any, label: str) -> dict[str, Any]:
    """验证 JSON 对象。

    Args:
        value: 待检查值。
        label: 字段名。

    Returns:
        原始对象。

    Raises:
        ContractError: 值不是对象。
    """
    if not isinstance(value, dict):
        raise ContractError(f"{label} 必须是 JSON 对象")
    return value


def _point(value: Any, label: str) -> dict[str, Any]:
    """验证带可选标签的二维点。"""
    item = _object(value, label)
    try:
        x = float(item.get("x"))
        y = float(item.get("y"))
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{label}.x/y 必须是有限数值") from exc
    if not all(float("-inf") < number < float("inf") for number in (x, y)):
        raise ContractError(f"{label}.x/y 必须是有限数值")
    name = item.get("label", "")
    if not isinstance(name, str):
        raise ContractError(f"{label}.label 必须是文本")
    return {"x": x, "y": y, "label": name.strip()}


def _points(value: Any, label: str, *, minimum: int = 1) -> list[dict[str, Any]]:
    """验证二维点数组。"""
    if not isinstance(value, list) or len(value) < minimum:
        raise ContractError(f"{label} 必须至少包含 {minimum} 个点")
    return [_point(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _payload_from_file(path: Path) -> dict[str, Any]:
    """读取结果 JSON 中专门提供给图表的真实数据。

    Args:
        path: 结果执行产物。

    Returns:
        ``figure_data`` 对象；为兼容简洁输出，也接受整个根对象。

    Raises:
        ContractError: JSON 不可读或不含对象数据。
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"图表输入 JSON 不可读取: {path}") from exc
    root = _object(document, "图表输入")
    return _object(root.get("figure_data", root), "figure_data")


def load_data(template_id: str, path: Path) -> dict[str, Any]:
    """读取并验证指定模板的真实输入数据。

    Args:
        template_id: 受支持的模板 ID。
        path: 已登记结果的 JSON 输出路径。

    Returns:
        规范化后的模板数据。

    Raises:
        ContractError: 模板不受支持或输入不符合公开数据接口。
    """
    payload = _payload_from_file(path)
    if template_id == "cv-roc-ci":
        models = payload.get("models")
        if not isinstance(models, list) or not models:
            raise ContractError("cv-roc-ci 需要 figure_data.models 非空数组")
        normalized = []
        for index, model in enumerate(models):
            item = _object(model, f"models[{index}]")
            name = item.get("name")
            folds = item.get("folds")
            if (
                not isinstance(name, str)
                or not name.strip()
                or not isinstance(folds, list)
                or not folds
            ):
                raise ContractError(f"models[{index}] 需要 name 和非空 folds")
            normalized_folds = []
            for fold_index, fold in enumerate(folds):
                curve = _object(fold, f"models[{index}].folds[{fold_index}]")
                fpr = _number_list(curve.get("fpr"), f"models[{index}].folds[{fold_index}].fpr")
                tpr = _number_list(curve.get("tpr"), f"models[{index}].folds[{fold_index}].tpr")
                if len(fpr) != len(tpr) or any(item < 0 or item > 1 for item in [*fpr, *tpr]):
                    raise ContractError("ROC 的 fpr/tpr 必须等长且位于 [0, 1]")
                if any(fpr[index + 1] < fpr[index] for index in range(len(fpr) - 1)):
                    raise ContractError("ROC 的 fpr 必须单调不减")
                normalized_folds.append({"fpr": fpr, "tpr": tpr})
            normalized.append({"name": name.strip(), "folds": normalized_folds})
        return {"models": normalized}
    if template_id == "prediction-marginal-grid":
        series = payload.get("series")
        if not isinstance(series, list) or not series:
            raise ContractError("prediction-marginal-grid 需要 figure_data.series 非空数组")
        normalized = []
        for index, record in enumerate(series):
            item = _object(record, f"series[{index}]")
            actual = _number_list(item.get("actual"), f"series[{index}].actual")
            predicted = _number_list(item.get("predicted"), f"series[{index}].predicted")
            if len(actual) != len(predicted):
                raise ContractError("预测图的 actual 与 predicted 长度必须相同")
            name = item.get("name", f"Series {index + 1}")
            if not isinstance(name, str) or not name.strip():
                raise ContractError(f"series[{index}].name 必须是非空文本")
            normalized.append({"name": name.strip(), "actual": actual, "predicted": predicted})
        return {"series": normalized}
    if template_id == "paired-raincloud":
        groups = payload.get("groups")
        if not isinstance(groups, list) or not groups:
            raise ContractError("paired-raincloud 需要 figure_data.groups 非空数组")
        normalized = []
        for index, record in enumerate(groups):
            item = _object(record, f"groups[{index}]")
            before = _number_list(item.get("before"), f"groups[{index}].before")
            after = _number_list(item.get("after"), f"groups[{index}].after")
            if len(before) != len(after):
                raise ContractError("配对分布图的 before 与 after 长度必须相同")
            name = item.get("name", f"Group {index + 1}")
            if not isinstance(name, str) or not name.strip():
                raise ContractError(f"groups[{index}].name 必须是非空文本")
            normalized.append({"name": name.strip(), "before": before, "after": after})
        return {"groups": normalized}
    if template_id == "correlation-pairgrid":
        columns = payload.get("columns")
        values = payload.get("values")
        if not isinstance(columns, list) or len(columns) < 2 or not isinstance(values, list):
            raise ContractError("correlation-pairgrid 需要至少两列 columns 和 values")
        names = [str(item).strip() for item in columns]
        if any(not item for item in names) or len(set(names)) != len(names):
            raise ContractError("相关矩阵 columns 必须是唯一的非空名称")
        rows = [_number_list(row, f"values[{index}]") for index, row in enumerate(values)]
        if len(rows) < 3 or any(len(row) != len(names) for row in rows):
            raise ContractError("相关矩阵 values 至少三行，且每行必须与 columns 等长")
        return {"columns": names, "values": rows}
    if template_id == "feasible-region-active-constraints":
        points = _points(payload.get("points"), "points", minimum=3)
        feasible = payload.get("feasible_mask")
        if (
            not isinstance(feasible, list)
            or len(feasible) != len(points)
            or any(not isinstance(item, bool) for item in feasible)
        ):
            raise ContractError("feasible_mask 必须是与 points 等长的布尔数组")
        boundaries = payload.get("boundaries")
        if not isinstance(boundaries, list) or not boundaries:
            raise ContractError("boundaries 必须是非空约束边界数组")
        normalized_boundaries = []
        for index, raw in enumerate(boundaries):
            item = _object(raw, f"boundaries[{index}]")
            label = item.get("label")
            x = _number_list(item.get("x"), f"boundaries[{index}].x")
            y = _number_list(item.get("y"), f"boundaries[{index}].y")
            if not isinstance(label, str) or not label.strip() or len(x) != len(y):
                raise ContractError(f"boundaries[{index}] 需要非空 label 和等长 x/y")
            normalized_boundaries.append({"label": label.strip(), "x": x, "y": y})
        active = payload.get("active_constraints")
        if not isinstance(active, list) or not active or any(
            not isinstance(item, str) or not item.strip() for item in active
        ):
            raise ContractError("active_constraints 必须是非空约束标签数组")
        selected = _point(payload.get("selected_point"), "selected_point")
        alternatives = [
            _point(item, f"alternative_points[{index}]")
            for index, item in enumerate(payload.get("alternative_points", []))
        ]
        return {
            "points": points,
            "feasible_mask": feasible,
            "boundaries": normalized_boundaries,
            "active_constraints": [item.strip() for item in active],
            "selected_point": selected,
            "alternative_points": alternatives,
            "x_label": str(payload.get("x_label", "Decision x")),
            "y_label": str(payload.get("y_label", "Decision y")),
        }
    if template_id == "interval-event-timeline":
        intervals = payload.get("intervals")
        if not isinstance(intervals, list) or not intervals:
            raise ContractError("intervals 必须是非空时间区间数组")
        normalized_intervals = []
        for index, raw in enumerate(intervals):
            item = _object(raw, f"intervals[{index}]")
            label = item.get("label")
            group = item.get("group")
            try:
                start, end = float(item.get("start")), float(item.get("end"))
            except (TypeError, ValueError) as exc:
                raise ContractError(f"intervals[{index}].start/end 必须是数值") from exc
            if (
                not isinstance(label, str)
                or not label.strip()
                or not isinstance(group, str)
                or not group.strip()
                or not start < end
            ):
                raise ContractError(f"intervals[{index}] 需要 label、group 且 start < end")
            normalized_intervals.append(
                {"label": label.strip(), "group": group.strip(), "start": start, "end": end}
            )
        events = payload.get("events", [])
        if not isinstance(events, list):
            raise ContractError("events 必须是数组")
        normalized_events = []
        for index, raw in enumerate(events):
            item = _object(raw, f"events[{index}]")
            label = item.get("label")
            try:
                time = float(item.get("time"))
            except (TypeError, ValueError) as exc:
                raise ContractError(f"events[{index}].time 必须是数值") from exc
            if not isinstance(label, str) or not label.strip():
                raise ContractError(f"events[{index}].label 必须是非空文本")
            normalized_events.append({"label": label.strip(), "time": time})
        final_intervals = payload.get("final_intervals", [])
        if not isinstance(final_intervals, list):
            raise ContractError("final_intervals 必须是数组")
        normalized_final = []
        for index, raw in enumerate(final_intervals):
            item = _object(raw, f"final_intervals[{index}]")
            try:
                start, end = float(item.get("start")), float(item.get("end"))
            except (TypeError, ValueError) as exc:
                raise ContractError(f"final_intervals[{index}] 端点必须是数值") from exc
            if not start < end:
                raise ContractError(f"final_intervals[{index}] 必须满足 start < end")
            normalized_final.append({"start": start, "end": end})
        return {
            "intervals": normalized_intervals,
            "events": normalized_events,
            "final_intervals": normalized_final,
            "time_label": str(payload.get("time_label", "Time")),
        }
    if template_id == "uncertainty-fan-threshold":
        x = _number_list(payload.get("x"), "x", minimum=3)
        median = _number_list(payload.get("median"), "median", minimum=3)
        if len(x) != len(median):
            raise ContractError("x 与 median 必须等长")
        bands = payload.get("bands")
        if not isinstance(bands, list) or not bands:
            raise ContractError("bands 必须是非空分位带数组")
        normalized_bands = []
        for index, raw in enumerate(bands):
            item = _object(raw, f"bands[{index}]")
            label = item.get("label")
            lower = _number_list(item.get("lower"), f"bands[{index}].lower", minimum=3)
            upper = _number_list(item.get("upper"), f"bands[{index}].upper", minimum=3)
            if (
                not isinstance(label, str)
                or not label.strip()
                or len(lower) != len(x)
                or len(upper) != len(x)
                or any(left > right for left, right in zip(lower, upper, strict=True))
            ):
                raise ContractError(f"bands[{index}] 需要等长且 lower <= upper 的分位带")
            normalized_bands.append({"label": label.strip(), "lower": lower, "upper": upper})
        threshold = payload.get("threshold")
        if isinstance(threshold, list):
            normalized_threshold: float | list[float] = _number_list(
                threshold, "threshold", minimum=3
            )
            if len(normalized_threshold) != len(x):
                raise ContractError("threshold 数组必须与 x 等长")
        else:
            try:
                normalized_threshold = float(threshold)
            except (TypeError, ValueError) as exc:
                raise ContractError("threshold 必须是数值或与 x 等长的数组") from exc
        return {
            "x": x,
            "median": median,
            "bands": normalized_bands,
            "threshold": normalized_threshold,
            "threshold_label": str(payload.get("threshold_label", "Decision threshold")),
            "x_label": str(payload.get("x_label", "Scenario")),
            "y_label": str(payload.get("y_label", "Outcome")),
        }
    if template_id == "multi-panel-evidence-chain":
        panels = payload.get("panels")
        if not isinstance(panels, list) or not 2 <= len(panels) <= 4:
            raise ContractError("panels 必须包含 2--4 个连续论证面板")
        normalized_panels = []
        panel_ids: set[str] = set()
        for index, raw in enumerate(panels):
            item = _object(raw, f"panels[{index}]")
            panel = item.get("panel")
            title = item.get("title")
            takeaway = item.get("takeaway")
            argument_unit_id = item.get("argument_unit_id")
            kind = item.get("kind")
            if (
                not isinstance(panel, str)
                or not panel.strip()
                or panel in panel_ids
                or not isinstance(title, str)
                or not title.strip()
                or not isinstance(takeaway, str)
                or len(takeaway.strip()) < 8
                or not isinstance(argument_unit_id, str)
                or not argument_unit_id.strip()
                or kind not in {"line", "scatter", "bar", "interval"}
            ):
                raise ContractError(
                    f"panels[{index}] 需要唯一 panel、title、argument_unit_id、takeaway 和受支持 kind"
                )
            panel_ids.add(panel)
            panel_data = _object(item.get("data"), f"panels[{index}].data")
            normalized_panels.append(
                {
                    "panel": panel.strip(),
                    "title": title.strip(),
                    "takeaway": takeaway.strip(),
                    "argument_unit_id": argument_unit_id.strip(),
                    "kind": kind,
                    "data": panel_data,
                }
            )
        return {"panels": normalized_panels}
    raise ContractError(
        f"模板尚未接入真实数据接口: {template_id}；当前可用: {', '.join(SUPPORTED_TEMPLATES)}"
    )


def _auc(np: Any, fpr: Any, tpr: Any) -> float:
    """计算一条 ROC 曲线的面积。"""
    return float(np.trapezoid(tpr, fpr))


def _render_cv_roc_ci(data: dict[str, Any], plt: Any, np: Any) -> Any:
    """绘制由真实折 ROC 构成的均值曲线和标准差带。"""
    figure, axis = plt.subplots(figsize=(7.2, 6.3))
    grid = np.linspace(0.0, 1.0, 201)
    colors = plt.get_cmap("tab10").colors
    for index, model in enumerate(data["models"]):
        interpolated = []
        aucs = []
        for fold in model["folds"]:
            fpr = np.asarray(fold["fpr"], dtype=float)
            tpr = np.asarray(fold["tpr"], dtype=float)
            interpolated.append(np.interp(grid, fpr, tpr))
            aucs.append(_auc(np, fpr, tpr))
        matrix = np.vstack(interpolated)
        mean = matrix.mean(axis=0)
        spread = matrix.std(axis=0, ddof=1) if len(interpolated) > 1 else np.zeros_like(mean)
        color = colors[index % len(colors)]
        axis.fill_between(
            grid,
            np.clip(mean - spread, 0, 1),
            np.clip(mean + spread, 0, 1),
            color=color,
            alpha=0.16,
        )
        axis.plot(
            grid,
            mean,
            color=color,
            linewidth=1.8,
            label=f"{model['name']} (AUC={np.mean(aucs):.3f}±{np.std(aucs, ddof=1) if len(aucs) > 1 else 0:.3f})",
        )
    axis.plot([0, 1], [0, 1], "--", color="#888888", linewidth=0.9, label="Random")
    axis.set(
        xlim=(0, 1),
        ylim=(0, 1),
        xlabel="False Positive Rate",
        ylabel="True Positive Rate",
        title="Cross-validation ROC with fold variability",
    )
    axis.grid(alpha=0.24)
    axis.legend(loc="lower right", fontsize=8)
    figure.tight_layout()
    return figure


def _render_prediction_marginal_grid(data: dict[str, Any], plt: Any, np: Any) -> Any:
    """绘制真实预测值与观测值的多面板诊断图。"""
    series = data["series"]
    columns = min(2, len(series))
    rows = (len(series) + columns - 1) // columns
    figure, axes = plt.subplots(rows, columns, figsize=(6.2 * columns, 5.3 * rows), squeeze=False)
    for index, record in enumerate(series):
        axis = axes.ravel()[index]
        actual = np.asarray(record["actual"], dtype=float)
        predicted = np.asarray(record["predicted"], dtype=float)
        lower, upper = (
            float(min(actual.min(), predicted.min())),
            float(max(actual.max(), predicted.max())),
        )
        axis.scatter(actual, predicted, s=20, alpha=0.68, edgecolors="none", color="#2474a6")
        axis.plot([lower, upper], [lower, upper], "--", color="#8d4b4b", linewidth=1)
        residual = predicted - actual
        rmse = float(np.sqrt(np.mean(residual**2)))
        ss_total = float(np.sum((actual - actual.mean()) ** 2))
        r_squared = 1 - float(np.sum(residual**2)) / ss_total if ss_total else float("nan")
        axis.text(
            0.03,
            0.97,
            f"n={len(actual)}\\nR²={r_squared:.3f}\\nRMSE={rmse:.3g}",
            transform=axis.transAxes,
            va="top",
            fontsize=9,
            bbox={"facecolor": "white", "edgecolor": "#aaaaaa", "alpha": 0.9},
        )
        axis.set(title=record["name"], xlabel="Observed", ylabel="Predicted")
        axis.grid(alpha=0.2)
    for axis in axes.ravel()[len(series) :]:
        axis.remove()
    figure.suptitle("Prediction versus observed values", y=1.01)
    figure.tight_layout()
    return figure


def _render_paired_raincloud(data: dict[str, Any], plt: Any, np: Any) -> Any:
    """绘制真实配对样本的半小提琴、散点和连线。"""
    groups = data["groups"]
    figure, axis = plt.subplots(figsize=(max(7.2, len(groups) * 2.0), 6.2))
    colors = ("#3b7ea1", "#c86b4a")
    positions = np.arange(len(groups), dtype=float)
    for index, group in enumerate(groups):
        before = np.asarray(group["before"], dtype=float)
        after = np.asarray(group["after"], dtype=float)
        violin = axis.violinplot(
            [before, after],
            positions=[index - 0.18, index + 0.18],
            widths=0.30,
            showmeans=False,
            showmedians=True,
        )
        for body_index, body in enumerate(violin["bodies"]):
            body.set_facecolor(colors[body_index])
            body.set_edgecolor(colors[body_index])
            body.set_alpha(0.24)
        rng = np.random.default_rng(index)
        jitter = rng.normal(0, 0.018, size=len(before))
        axis.plot(
            np.column_stack(
                [
                    np.full(len(before), index - 0.18) + jitter,
                    np.full(len(after), index + 0.18) + jitter,
                ]
            ).T,
            np.column_stack([before, after]).T,
            color="#777777",
            alpha=0.23,
            linewidth=0.7,
        )
        axis.scatter(
            np.full(len(before), index - 0.18) + jitter,
            before,
            s=15,
            color=colors[0],
            alpha=0.72,
            label="Before" if index == 0 else None,
        )
        axis.scatter(
            np.full(len(after), index + 0.18) + jitter,
            after,
            s=15,
            color=colors[1],
            alpha=0.72,
            label="After" if index == 0 else None,
        )
        axis.text(
            index,
            max(before.max(), after.max()),
            f"Δ={np.mean(after - before):+.3g}",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    axis.set_xticks(positions, [item["name"] for item in groups])
    axis.set(title="Paired distribution and individual changes", ylabel="Measured value")
    axis.legend()
    axis.grid(axis="y", alpha=0.2)
    figure.tight_layout()
    return figure


def _wrap_pairgrid_label(value: str, *, threshold: int = 20) -> str:
    """在字段边界换行，避免相关矩阵的长轴标签发生相交。

    Args:
        value: 原始字段名。
        threshold: 超过该长度时才尝试换行。

    Returns:
        适合紧凑矩阵坐标轴展示的字段标签。
    """
    if len(value) <= threshold or "_" not in value:
        return value
    parts = value.split("_")
    if len(parts) < 2:
        return value
    midpoint = len(value) / 2
    split_at = min(
        range(1, len(parts)),
        key=lambda index: abs(len("_".join(parts[:index])) - midpoint),
    )
    return f"{'_'.join(parts[:split_at])}\n{'_'.join(parts[split_at:])}"


def _render_correlation_pairgrid(data: dict[str, Any], plt: Any, np: Any) -> Any:
    """绘制真实变量数据的相关矩阵和下三角散点图。"""
    values = np.asarray(data["values"], dtype=float)
    names = data["columns"]
    display_names = [_wrap_pairgrid_label(name) for name in names]
    count = len(names)
    figure, axes = plt.subplots(
        count, count, figsize=(max(6.5, count * 1.65), max(6.0, count * 1.55)), squeeze=False
    )
    correlation = np.corrcoef(values, rowvar=False)
    for row in range(count):
        for column in range(count):
            axis = axes[row, column]
            if row == column:
                axis.hist(
                    values[:, row],
                    bins=min(16, max(6, len(values) // 8)),
                    color="#89b9ce",
                    edgecolor="#366d89",
                )
            elif row > column:
                axis.scatter(
                    values[:, column],
                    values[:, row],
                    s=8,
                    alpha=0.55,
                    color="#287da1",
                    edgecolors="none",
                )
                slope, intercept = np.polyfit(values[:, column], values[:, row], 1)
                grid = np.linspace(values[:, column].min(), values[:, column].max(), 50)
                axis.plot(grid, slope * grid + intercept, color="#b65d7b", linewidth=1)
            else:
                value = float(correlation[row, column])
                axis.imshow([[value]], vmin=-1, vmax=1, cmap="RdBu_r")
                axis.text(
                    0,
                    0,
                    f"r={value:.2f}",
                    ha="center",
                    va="center",
                    fontsize=8,
                    color="white" if abs(value) > 0.45 else "#222222",
                )
            if row == count - 1:
                axis.set_xlabel(display_names[column], fontsize=8)
            else:
                axis.set_xticks([])
            if column == 0:
                axis.set_ylabel(display_names[row], fontsize=8)
            else:
                axis.set_yticks([])
    figure.suptitle("Correlation pair grid from registered result data", y=1.002)
    figure.tight_layout()
    return figure


def _render_feasible_region_active_constraints(
    data: dict[str, Any], plt: Any, np: Any
) -> Any:
    """绘制可行点、活跃约束、候选方案与最终选点。"""
    figure, axis = plt.subplots(figsize=(7.6, 6.2))
    points = np.asarray([[item["x"], item["y"]] for item in data["points"]])
    feasible = np.asarray(data["feasible_mask"], dtype=bool)
    axis.scatter(
        points[~feasible, 0], points[~feasible, 1], s=22, color="#c7c7c7", label="Infeasible"
    )
    axis.scatter(
        points[feasible, 0], points[feasible, 1], s=26, color="#4d9b78", label="Feasible"
    )
    active = set(data["active_constraints"])
    for boundary in data["boundaries"]:
        is_active = boundary["label"] in active
        axis.plot(
            boundary["x"],
            boundary["y"],
            linewidth=2.3 if is_active else 1.1,
            linestyle="-" if is_active else "--",
            label=f"{boundary['label']}{' (active)' if is_active else ''}",
        )
    for point in data["alternative_points"]:
        axis.scatter(point["x"], point["y"], marker="D", s=52, color="#d08a36")
        if point["label"]:
            axis.annotate(point["label"], (point["x"], point["y"]), xytext=(5, 5), textcoords="offset points")
    selected = data["selected_point"]
    selected_label = selected["label"] or "Selected"
    axis.scatter(
        selected["x"],
        selected["y"],
        marker="*",
        s=190,
        color="#b73333",
        zorder=6,
        label=selected_label,
    )
    axis.set(
        xlabel=data["x_label"],
        ylabel=data["y_label"],
        title="Feasible region and active constraints",
    )
    axis.grid(alpha=0.2)
    axis.legend(fontsize=8, loc="best")
    figure.tight_layout()
    figure._shumozizi_panels = ["main"]
    figure._shumozizi_elements = [
        {"type": "selected_point", "label": selected_label, "panel": "main"},
        *[
            {
                "type": "active_constraint",
                "label": f"{label} (active)",
                "panel": "main",
            }
            for label in data["active_constraints"]
        ],
    ]
    return figure


def _render_interval_event_timeline(data: dict[str, Any], plt: Any, np: Any) -> Any:
    """绘制多主体区间、关键事件与最终有效区间。"""
    groups = list(dict.fromkeys(item["group"] for item in data["intervals"]))
    figure, axis = plt.subplots(figsize=(9.2, max(4.4, 0.72 * len(groups) + 2.2)))
    colors = plt.get_cmap("tab10").colors
    y_by_group = {group: len(groups) - index for index, group in enumerate(groups)}
    for index, interval in enumerate(data["intervals"]):
        y = y_by_group[interval["group"]]
        axis.broken_barh(
            [(interval["start"], interval["end"] - interval["start"])],
            (y - 0.28, 0.56),
            facecolors=colors[index % len(colors)],
            alpha=0.72,
        )
        axis.text((interval["start"] + interval["end"]) / 2, y, interval["label"], ha="center", va="center", fontsize=8)
    for interval in data["final_intervals"]:
        axis.axvspan(interval["start"], interval["end"], color="#75b798", alpha=0.16)
    for event in data["events"]:
        axis.axvline(event["time"], color="#8c3f3f", linestyle="--", linewidth=1)
        axis.text(event["time"], len(groups) + 0.65, event["label"], rotation=90, ha="right", va="top", fontsize=8)
    axis.set_yticks([y_by_group[group] for group in groups], groups)
    axis.set(xlabel=data["time_label"], title="Intervals, events, and effective windows")
    axis.set_ylim(0.4, len(groups) + 0.9)
    axis.grid(axis="x", alpha=0.2)
    figure.tight_layout()
    figure._shumozizi_panels = ["main"]
    figure._shumozizi_elements = [
        {"type": "critical_event", "label": item["label"], "panel": "main"}
        for item in data["events"]
    ] or [{"type": "interval", "label": data["intervals"][0]["label"], "panel": "main"}]
    return figure


def _render_uncertainty_fan_threshold(data: dict[str, Any], plt: Any, np: Any) -> Any:
    """绘制多层不确定性带、中心估计与决策阈值。"""
    figure, axis = plt.subplots(figsize=(8.0, 5.8))
    x = np.asarray(data["x"], dtype=float)
    colors = ["#c9ddec", "#94bdd8", "#5d9bc3", "#367ea8"]
    for index, band in enumerate(reversed(data["bands"])):
        axis.fill_between(
            x,
            np.asarray(band["lower"]),
            np.asarray(band["upper"]),
            color=colors[index % len(colors)],
            alpha=0.38,
            label=band["label"],
        )
    axis.plot(x, data["median"], color="#1f5875", linewidth=2.0, label="Median")
    threshold = data["threshold"]
    if isinstance(threshold, list):
        axis.plot(x, threshold, "--", color="#ad3f3f", linewidth=1.5, label=data["threshold_label"])
    else:
        axis.axhline(threshold, linestyle="--", color="#ad3f3f", linewidth=1.5, label=data["threshold_label"])
    axis.set(
        xlabel=data["x_label"],
        ylabel=data["y_label"],
        title="Uncertainty fan and decision threshold",
    )
    axis.grid(alpha=0.2)
    axis.legend(fontsize=8)
    figure.tight_layout()
    figure._shumozizi_panels = ["main"]
    figure._shumozizi_elements = [
        {
            "type": "decision_threshold",
            "label": data["threshold_label"],
            "panel": "main",
        },
        {"type": "center_estimate", "label": "Median", "panel": "main"},
        *[
            {"type": "uncertainty_band", "label": band["label"], "panel": "main"}
            for band in data["bands"]
        ],
    ]
    return figure


def _render_multi_panel_evidence_chain(data: dict[str, Any], plt: Any, np: Any) -> Any:
    """按固定阅读顺序绘制 2--4 个相互关联的证据面板。"""
    panels = data["panels"]
    columns = 2 if len(panels) > 2 else len(panels)
    rows = (len(panels) + columns - 1) // columns
    figure, axes = plt.subplots(rows, columns, figsize=(6.0 * columns, 4.7 * rows), squeeze=False)
    for axis, panel in zip(axes.ravel(), panels, strict=False):
        values = panel["data"]
        kind = panel["kind"]
        if kind in {"line", "scatter"}:
            x = _number_list(values.get("x"), f"panel {panel['panel']}.data.x")
            y = _number_list(values.get("y"), f"panel {panel['panel']}.data.y")
            if len(x) != len(y):
                raise ContractError(f"panel {panel['panel']} 的 x/y 必须等长")
            if kind == "line":
                axis.plot(x, y, marker="o", linewidth=1.6, color="#2b7297")
            else:
                axis.scatter(x, y, s=28, color="#2b7297")
        elif kind == "bar":
            labels = values.get("labels")
            y = _number_list(values.get("values"), f"panel {panel['panel']}.data.values")
            if not isinstance(labels, list) or len(labels) != len(y):
                raise ContractError(f"panel {panel['panel']} 的 labels/values 必须等长")
            axis.bar([str(item) for item in labels], y, color="#5b9a78")
        else:
            intervals = values.get("intervals")
            if not isinstance(intervals, list) or not intervals:
                raise ContractError(f"panel {panel['panel']} 需要 intervals")
            for row_index, raw in enumerate(intervals):
                item = _object(raw, f"panel {panel['panel']}.intervals[{row_index}]")
                start, end = float(item["start"]), float(item["end"])
                axis.broken_barh([(start, end - start)], (row_index - 0.3, 0.6))
            axis.set_yticks([])
        axis.set_title(f"{panel['panel']}  {panel['title']}", loc="left", fontsize=10)
        axis.text(
            0.01,
            -0.20,
            panel["takeaway"],
            transform=axis.transAxes,
            fontsize=8,
            va="top",
            wrap=True,
        )
        axis.grid(alpha=0.18)
    for axis in axes.ravel()[len(panels) :]:
        axis.remove()
    figure.suptitle("Evidence chain", y=1.0)
    figure.tight_layout()
    figure._shumozizi_panels = [panel["panel"] for panel in panels]
    figure._shumozizi_elements = [
        {
            "type": "panel_takeaway",
            "label": panel["takeaway"],
            "panel": panel["panel"],
        }
        for panel in panels
    ]
    return figure


def _text_boxes(figure: Any) -> list[dict[str, float | str]]:
    """导出 Matplotlib 文字 artist 的像素边界，供图表 QA 检查。

    Args:
        figure: 已完成布局的 Matplotlib Figure。

    Returns:
        非空文字的边界列表。
    """
    figure.canvas.draw()
    renderer = figure.canvas.get_renderer()
    texts = list(figure.texts)
    for axis in figure.axes:
        texts.extend([axis.title, axis.xaxis.label, axis.yaxis.label, *axis.texts])
        legend = axis.get_legend()
        if legend is not None:
            texts.extend([legend.get_title(), *legend.get_texts()])
    boxes: list[dict[str, float | str]] = []
    for index, text in enumerate(texts):
        value = text.get_text().strip()
        if not value or not text.get_visible():
            continue
        extent = text.get_window_extent(renderer)
        if extent.width <= 0 or extent.height <= 0:
            continue
        boxes.append(
            {
                "id": f"text-{index}:{value[:32]}",
                "x0": round(float(extent.x0), 3),
                "y0": round(float(extent.y0), 3),
                "x1": round(float(extent.x1), 3),
                "y1": round(float(extent.y1), 3),
            }
        )
    return boxes


def _figure_text_artists(figure: Any) -> list[Any]:
    """收集实际参与当前渲染的文字 artist。"""
    texts = list(figure.texts)
    for axis in figure.axes:
        texts.extend([axis.title, axis.xaxis.label, axis.yaxis.label, *axis.texts])
        legend = axis.get_legend()
        if legend is not None:
            texts.extend([legend.get_title(), *legend.get_texts()])
    return [item for item in texts if item.get_visible() and item.get_text().strip()]


def _write_visual_manifest(figure: Any, output_stem: Path) -> Path:
    """把 renderer 声明绑定到实际文字 artist 与当前 PNG 哈希。"""
    from PIL import Image

    figure.canvas.draw()
    renderer = figure.canvas.get_renderer()
    width, height = figure.canvas.get_width_height()
    panels = list(getattr(figure, "_shumozizi_panels", []))
    if not panels:
        panels = ["main"] if len(figure.axes) == 1 else [chr(65 + index) for index in range(len(figure.axes))]
    declarations = list(getattr(figure, "_shumozizi_elements", []))
    if not declarations:
        declarations = [
            {
                "type": "panel_title",
                "label": axis.title.get_text().strip(),
                "panel": panels[index],
            }
            for index, axis in enumerate(figure.axes)
            if axis.title.get_text().strip()
        ]
    if not declarations:
        declarations = [
            {"type": "figure_title", "label": item.get_text().strip(), "panel": panels[0]}
            for item in figure.texts
            if item.get_visible() and item.get_text().strip()
        ][:1]
    if not declarations:
        raise ContractError("renderer 未生成可绑定 visual_manifest 的可见标签")
    text_artists = _figure_text_artists(figure)
    elements: list[dict[str, Any]] = []
    for declaration in declarations:
        label = str(declaration["label"]).strip()
        panel = str(declaration["panel"]).strip()
        artist = next(
            (item for item in text_artists if item.get_text().strip() == label),
            None,
        )
        if artist is None:
            raise ContractError(f"renderer 声明的视觉标签未实际绘制: {label}")
        extent = artist.get_window_extent(renderer)
        bbox = [
            float(extent.x0) / width,
            float(extent.y0) / height,
            float(extent.x1) / width,
            float(extent.y1) / height,
        ]
        visible = 0 <= bbox[0] < bbox[2] <= 1 and 0 <= bbox[1] < bbox[3] <= 1
        elements.append(
            {
                "type": str(declaration["type"]).strip(),
                "label": label,
                "panel": panel,
                "bbox": [round(value, 6) for value in bbox],
                "paper_width_visible": visible,
            }
        )
    png_path = output_stem.with_suffix(".png")
    with Image.open(png_path) as image:
        png_size = image.size
    manifest_path = output_stem.with_suffix(".visual_manifest.json")
    atomic_json(
        manifest_path,
        {
            "schema_version": "1.0",
            "output_sha256": sha256_file(png_path),
            "canvas": {"width": png_size[0], "height": png_size[1]},
            "panels": panels,
            "labels": [item["label"] for item in elements],
            "elements": elements,
        },
    )
    return manifest_path


def render(template_id: str, data: dict[str, Any], output_stem: Path) -> Path:
    """以已验证的真实数据生成 PNG、PDF、SVG 和文字边界文件。

    Args:
        template_id: 模板 ID。
        data: 由 :func:`load_data` 返回的真实数据。
        output_stem: 不含扩展名的运行目录内输出路径。

    Returns:
        文字边界 JSON 文件路径。

    Raises:
        ContractError: 绘图失败、中文字体缺字或模板未接入。
    """
    _, plt, np = _plot_modules()
    renderers = {
        "cv-roc-ci": _render_cv_roc_ci,
        "feasible-region-active-constraints": _render_feasible_region_active_constraints,
        "interval-event-timeline": _render_interval_event_timeline,
        "multi-panel-evidence-chain": _render_multi_panel_evidence_chain,
        "prediction-marginal-grid": _render_prediction_marginal_grid,
        "paired-raincloud": _render_paired_raincloud,
        "correlation-pairgrid": _render_correlation_pairgrid,
        "uncertainty-fan-threshold": _render_uncertainty_fan_threshold,
    }
    renderer = renderers.get(template_id)
    if renderer is None:
        raise ContractError(f"模板尚未接入真实数据接口: {template_id}")
    output_stem.parent.mkdir(parents=True, exist_ok=True)
    figure = renderer(data, plt, np)
    warnings_seen: list[str] = []
    try:
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            for suffix, options in ((".png", {"dpi": 300}), (".pdf", {}), (".svg", {})):
                figure.savefig(output_stem.with_suffix(suffix), bbox_inches="tight", **options)
        warnings_seen = [str(item.message) for item in captured]
        missing = [
            item for item in warnings_seen if "glyph" in item.lower() and "missing" in item.lower()
        ]
        if missing:
            raise ContractError(f"图表出现字体缺字警告: {missing[0]}")
        boxes_path = output_stem.with_suffix(".text-boxes.json")
        boxes_path.write_text(
            json.dumps(
                {"schema_version": "1.0", "boxes": _text_boxes(figure)},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        _write_visual_manifest(figure, output_stem)
        return boxes_path
    finally:
        plt.close(figure)
