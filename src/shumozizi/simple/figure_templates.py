"""以真实 JSON 结果渲染 v3 可用的科研图表模板。"""

from __future__ import annotations

import json
import os
import tempfile
import warnings
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError

SUPPORTED_TEMPLATES = (
    "correlation-pairgrid",
    "cv-roc-ci",
    "paired-raincloud",
    "prediction-marginal-grid",
)


def _plot_modules() -> tuple[Any, Any, Any]:
    """延迟加载无界面绘图库，避免导入时改变调用方的后端。

    Returns:
        ``matplotlib``、``pyplot`` 和 ``numpy`` 模块。

    Raises:
        ContractError: 未安装可选的真实绘图依赖。
    """
    os.environ.setdefault(
        "MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "shumozizi-matplotlib")
    )
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError as exc:
        raise ContractError(
            "缺少真实绘图依赖；请先执行 python -m pip install -e \".[figures]\""
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
            if not isinstance(name, str) or not name.strip() or not isinstance(folds, list) or not folds:
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
        axis.fill_between(grid, np.clip(mean - spread, 0, 1), np.clip(mean + spread, 0, 1), color=color, alpha=0.16)
        axis.plot(grid, mean, color=color, linewidth=1.8, label=f"{model['name']} (AUC={np.mean(aucs):.3f}±{np.std(aucs, ddof=1) if len(aucs) > 1 else 0:.3f})")
    axis.plot([0, 1], [0, 1], "--", color="#888888", linewidth=0.9, label="Random")
    axis.set(xlim=(0, 1), ylim=(0, 1), xlabel="False Positive Rate", ylabel="True Positive Rate", title="Cross-validation ROC with fold variability")
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
        lower, upper = float(min(actual.min(), predicted.min())), float(max(actual.max(), predicted.max()))
        axis.scatter(actual, predicted, s=20, alpha=0.68, edgecolors="none", color="#2474a6")
        axis.plot([lower, upper], [lower, upper], "--", color="#8d4b4b", linewidth=1)
        residual = predicted - actual
        rmse = float(np.sqrt(np.mean(residual**2)))
        ss_total = float(np.sum((actual - actual.mean()) ** 2))
        r_squared = 1 - float(np.sum(residual**2)) / ss_total if ss_total else float("nan")
        axis.text(0.03, 0.97, f"n={len(actual)}\\nR²={r_squared:.3f}\\nRMSE={rmse:.3g}", transform=axis.transAxes, va="top", fontsize=9, bbox={"facecolor": "white", "edgecolor": "#aaaaaa", "alpha": 0.9})
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
        violin = axis.violinplot([before, after], positions=[index - 0.18, index + 0.18], widths=0.30, showmeans=False, showmedians=True)
        for body_index, body in enumerate(violin["bodies"]):
            body.set_facecolor(colors[body_index])
            body.set_edgecolor(colors[body_index])
            body.set_alpha(0.24)
        rng = np.random.default_rng(index)
        jitter = rng.normal(0, 0.018, size=len(before))
        axis.plot(np.column_stack([np.full(len(before), index - 0.18) + jitter, np.full(len(after), index + 0.18) + jitter]).T, np.column_stack([before, after]).T, color="#777777", alpha=0.23, linewidth=0.7)
        axis.scatter(np.full(len(before), index - 0.18) + jitter, before, s=15, color=colors[0], alpha=0.72, label="Before" if index == 0 else None)
        axis.scatter(np.full(len(after), index + 0.18) + jitter, after, s=15, color=colors[1], alpha=0.72, label="After" if index == 0 else None)
        axis.text(index, max(before.max(), after.max()), f"Δ={np.mean(after - before):+.3g}", ha="center", va="bottom", fontsize=8)
    axis.set_xticks(positions, [item["name"] for item in groups])
    axis.set(title="Paired distribution and individual changes", ylabel="Measured value")
    axis.legend()
    axis.grid(axis="y", alpha=0.2)
    figure.tight_layout()
    return figure


def _render_correlation_pairgrid(data: dict[str, Any], plt: Any, np: Any) -> Any:
    """绘制真实变量数据的相关矩阵和下三角散点图。"""
    values = np.asarray(data["values"], dtype=float)
    names = data["columns"]
    count = len(names)
    figure, axes = plt.subplots(count, count, figsize=(max(6.5, count * 1.65), max(6.0, count * 1.55)), squeeze=False)
    correlation = np.corrcoef(values, rowvar=False)
    for row in range(count):
        for column in range(count):
            axis = axes[row, column]
            if row == column:
                axis.hist(values[:, row], bins=min(16, max(6, len(values) // 8)), color="#89b9ce", edgecolor="#366d89")
            elif row > column:
                axis.scatter(values[:, column], values[:, row], s=8, alpha=0.55, color="#287da1", edgecolors="none")
                slope, intercept = np.polyfit(values[:, column], values[:, row], 1)
                grid = np.linspace(values[:, column].min(), values[:, column].max(), 50)
                axis.plot(grid, slope * grid + intercept, color="#b65d7b", linewidth=1)
            else:
                value = float(correlation[row, column])
                axis.imshow([[value]], vmin=-1, vmax=1, cmap="RdBu_r")
                axis.text(0, 0, f"r={value:.2f}", ha="center", va="center", fontsize=8, color="white" if abs(value) > 0.45 else "#222222")
            if row == count - 1:
                axis.set_xlabel(names[column], fontsize=8)
            else:
                axis.set_xticks([])
            if column == 0:
                axis.set_ylabel(names[row], fontsize=8)
            else:
                axis.set_yticks([])
    figure.suptitle("Correlation pair grid from registered result data", y=1.002)
    figure.tight_layout()
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
        "prediction-marginal-grid": _render_prediction_marginal_grid,
        "paired-raincloud": _render_paired_raincloud,
        "correlation-pairgrid": _render_correlation_pairgrid,
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
        missing = [item for item in warnings_seen if "glyph" in item.lower() and "missing" in item.lower()]
        if missing:
            raise ContractError(f"图表出现字体缺字警告: {missing[0]}")
        boxes_path = output_stem.with_suffix(".text-boxes.json")
        boxes_path.write_text(
            json.dumps({"schema_version": "1.0", "boxes": _text_boxes(figure)}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return boxes_path
    finally:
        plt.close(figure)
