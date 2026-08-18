"""以真实 JSON 结果渲染 v3 可用的科研图表模板。"""

from __future__ import annotations

import json
import math
import os
import tempfile
import warnings
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, sha256_file

SUPPORTED_TEMPLATES = (
    "active_constraint_map",
    "argument_evidence_map",
    "correlation-pairgrid",
    "constraint_margin_timeline",
    "cv-roc-ci",
    "feasible-region-active-constraints",
    "grouped-circular-heatmap",
    "grouped-corr-split-violin",
    "interval-event-timeline",
    "model_evolution_schematic",
    "multi-panel-evidence-chain",
    "multiclass-shap-combo",
    "nature-chord-diagram",
    "paired-raincloud",
    "prediction-marginal-grid",
    "rf-tpe-surface",
    "taylor-diagram",
    "uncertainty-fan-threshold",
    "uncertainty_threshold_ribbon",
    "urban-park-cooling-combo",
)

_CANONICAL_RENDERER_BASE = {
    "active_constraint_map": "feasible-region-active-constraints",
    "uncertainty_threshold_ribbon": "uncertainty-fan-threshold",
}


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
    template_id = _CANONICAL_RENDERER_BASE.get(template_id, template_id)
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
    if template_id == "constraint_margin_timeline":
        time = _number_list(payload.get("time"), "time", minimum=3)
        series = payload.get("series")
        if not isinstance(series, list) or not series:
            raise ContractError("constraint_margin_timeline 需要非空 series")
        normalized_series = []
        for index, raw in enumerate(series):
            item = _object(raw, f"series[{index}]")
            label = item.get("label")
            margin = _number_list(item.get("margin"), f"series[{index}].margin", minimum=3)
            if not isinstance(label, str) or not label.strip() or len(margin) != len(time):
                raise ContractError(f"series[{index}] 需要非空 label 和与 time 等长的 margin")
            normalized_series.append({"label": label.strip(), "margin": margin})
        try:
            tolerance = float(payload.get("active_tolerance", 0.0))
        except (TypeError, ValueError) as exc:
            raise ContractError("active_tolerance 必须是非负数值") from exc
        if tolerance < 0:
            raise ContractError("active_tolerance 必须是非负数值")
        return {
            "time": time,
            "series": normalized_series,
            "active_tolerance": tolerance,
            "time_label": str(payload.get("time_label", "Time")),
            "margin_label": str(payload.get("margin_label", "Constraint margin")),
        }
    if template_id in {"model_evolution_schematic", "argument_evidence_map"}:
        nodes = payload.get("nodes")
        edges = payload.get("edges")
        layer_field = "stage" if template_id == "model_evolution_schematic" else "kind"
        if not isinstance(nodes, list) or len(nodes) < 2 or not isinstance(edges, list) or not edges:
            raise ContractError(f"{template_id} 需要至少两个 nodes 和非空 edges")
        normalized_nodes = []
        node_ids: set[str] = set()
        for index, raw in enumerate(nodes):
            item = _object(raw, f"nodes[{index}]")
            node_id, label, layer = item.get("id"), item.get("label"), item.get(layer_field)
            if (
                not isinstance(node_id, str)
                or not node_id.strip()
                or node_id in node_ids
                or not isinstance(label, str)
                or not label.strip()
                or not isinstance(layer, str)
                or not layer.strip()
            ):
                raise ContractError(f"nodes[{index}] 需要唯一 id、非空 label 和 {layer_field}")
            node_ids.add(node_id.strip())
            normalized_nodes.append(
                {"id": node_id.strip(), "label": label.strip(), layer_field: layer.strip()}
            )
        normalized_edges = []
        for index, raw in enumerate(edges):
            item = _object(raw, f"edges[{index}]")
            source, target, relation = item.get("source"), item.get("target"), item.get("relation")
            if source not in node_ids or target not in node_ids:
                raise ContractError(f"edges[{index}] 必须引用已声明节点")
            if not isinstance(relation, str) or not relation.strip():
                raise ContractError(f"edges[{index}].relation 必须是非空文本")
            normalized_edges.append(
                {"source": source, "target": target, "relation": relation.strip()}
            )
        return {
            "nodes": normalized_nodes,
            "edges": normalized_edges,
            "layer_field": layer_field,
        }
    if template_id == "rf-tpe-surface":
        trials = payload.get("trials")
        if not isinstance(trials, list) or len(trials) < 4:
            raise ContractError("rf-tpe-surface 需要至少四个真实 trials")
        normalized_trials = []
        for index, raw in enumerate(trials):
            item = _object(raw, f"trials[{index}]")
            try:
                trial = {
                    "x": float(item.get("x")),
                    "y": float(item.get("y")),
                    "metric": float(item.get("metric")),
                }
            except (TypeError, ValueError) as exc:
                raise ContractError(f"trials[{index}] 的 x/y/metric 必须是有限数值") from exc
            if any(not float("-inf") < value < float("inf") for value in trial.values()):
                raise ContractError(f"trials[{index}] 的 x/y/metric 必须是有限数值")
            normalized_trials.append(trial)
        if len({item["x"] for item in normalized_trials}) < 2 or len(
            {item["y"] for item in normalized_trials}
        ) < 2:
            raise ContractError("rf-tpe-surface 的 trials 必须覆盖至少两个 x 和两个 y")
        coordinates = [(item["x"], item["y"]) for item in normalized_trials]
        if len(set(coordinates)) != len(coordinates):
            raise ContractError("rf-tpe-surface 的 trials 不得包含重复 x/y 坐标")
        non_collinear = any(
            abs(
                (coordinates[j][0] - coordinates[i][0])
                * (coordinates[k][1] - coordinates[i][1])
                - (coordinates[j][1] - coordinates[i][1])
                * (coordinates[k][0] - coordinates[i][0])
            )
            > 1e-12
            for i in range(len(coordinates) - 2)
            for j in range(i + 1, len(coordinates) - 1)
            for k in range(j + 1, len(coordinates))
        )
        if not non_collinear:
            raise ContractError("rf-tpe-surface 的 trials 至少需要三个不共线参数点")
        direction = payload.get("direction")
        if direction not in {"minimize", "maximize"}:
            raise ContractError("rf-tpe-surface.direction 必须是 minimize 或 maximize")
        labels = {}
        for field, fallback in (
            ("x_label", "Parameter x"),
            ("y_label", "Parameter y"),
            ("metric_label", "Metric"),
        ):
            value = payload.get(field, fallback)
            if not isinstance(value, str) or not value.strip():
                raise ContractError(f"rf-tpe-surface.{field} 必须是非空文本")
            labels[field] = value.strip()
        chooser = min if direction == "minimize" else max
        best = chooser(normalized_trials, key=lambda item: item["metric"])
        return {
            "trials": normalized_trials,
            "best_trial": dict(best),
            "direction": direction,
            **labels,
        }
    if template_id == "taylor-diagram":
        try:
            reference_std = float(payload.get("reference_std"))
        except (TypeError, ValueError) as exc:
            raise ContractError("taylor-diagram.reference_std 必须是正数") from exc
        if not 0 < reference_std < float("inf"):
            raise ContractError("taylor-diagram.reference_std 必须是正数")
        panels = payload.get("panels")
        if not isinstance(panels, list) or not 1 <= len(panels) <= 3:
            raise ContractError("taylor-diagram.panels 必须包含 1--3 个面板")
        normalized_panels = []
        for panel_index, raw_panel in enumerate(panels):
            panel = _object(raw_panel, f"panels[{panel_index}]")
            title = panel.get("title")
            points = panel.get("points")
            if not isinstance(title, str) or not title.strip():
                raise ContractError(f"panels[{panel_index}].title 必须是非空文本")
            if not isinstance(points, list) or not points:
                raise ContractError(f"panels[{panel_index}].points 必须是非空数组")
            normalized_points = []
            names: set[str] = set()
            for point_index, raw_point in enumerate(points):
                point = _object(raw_point, f"panels[{panel_index}].points[{point_index}]")
                name = point.get("name")
                try:
                    std, corr = float(point.get("std")), float(point.get("corr"))
                except (TypeError, ValueError) as exc:
                    raise ContractError("Taylor 点的 std/corr 必须是数值") from exc
                if (
                    not isinstance(name, str)
                    or not name.strip()
                    or name.strip() in names
                    or not 0 <= std < float("inf")
                    or not -1 <= corr <= 1
                ):
                    raise ContractError("Taylor 点需要唯一名称、非负 std 和 [-1,1] corr")
                names.add(name.strip())
                normalized_points.append({"name": name.strip(), "std": std, "corr": corr})
            normalized_panels.append({"title": title.strip(), "points": normalized_points})
        return {"reference_std": reference_std, "panels": normalized_panels}
    if template_id == "multiclass-shap-combo":
        features = payload.get("features")
        classes = payload.get("classes")
        if not isinstance(features, list) or len(features) < 2:
            raise ContractError("multiclass-shap-combo.features 至少需要两个特征")
        if not isinstance(classes, list) or len(classes) < 2:
            raise ContractError("multiclass-shap-combo.classes 至少需要两个类别")
        feature_names = [str(item).strip() for item in features]
        class_names = [str(item).strip() for item in classes]
        if (
            any(not item for item in [*feature_names, *class_names])
            or len(set(feature_names)) != len(feature_names)
            or len(set(class_names)) != len(class_names)
        ):
            raise ContractError("SHAP 特征名和类别名必须分别唯一且非空")
        raw_importance = payload.get("mean_abs_shap")
        if not isinstance(raw_importance, list) or len(raw_importance) != len(feature_names):
            raise ContractError("mean_abs_shap 必须按 feature × class 提供")
        importance = [
            _number_list(row, f"mean_abs_shap[{index}]", minimum=len(class_names))
            for index, row in enumerate(raw_importance)
        ]
        if any(len(row) != len(class_names) or any(value < 0 for value in row) for row in importance):
            raise ContractError("mean_abs_shap 每行必须与 classes 等长且非负")
        beeswarm = payload.get("beeswarm")
        if not isinstance(beeswarm, list) or not beeswarm:
            raise ContractError("multiclass-shap-combo.beeswarm 必须是非空数组")
        normalized_beeswarm = []
        for index, raw in enumerate(beeswarm):
            item = _object(raw, f"beeswarm[{index}]")
            feature, class_name = item.get("feature"), item.get("class")
            shap_values = _number_list(item.get("shap_values"), f"beeswarm[{index}].shap_values", minimum=3)
            feature_values = _number_list(
                item.get("feature_values"), f"beeswarm[{index}].feature_values", minimum=3
            )
            if feature not in feature_names or class_name not in class_names:
                raise ContractError("beeswarm 必须引用已声明 feature 和 class")
            if len(shap_values) != len(feature_values):
                raise ContractError("beeswarm 的 shap_values 与 feature_values 必须等长")
            normalized_beeswarm.append(
                {
                    "feature": feature,
                    "class": class_name,
                    "shap_values": shap_values,
                    "feature_values": feature_values,
                }
            )
        return {
            "features": feature_names,
            "classes": class_names,
            "mean_abs_shap": importance,
            "beeswarm": normalized_beeswarm,
        }
    if template_id == "grouped-corr-split-violin":
        features = payload.get("features")
        groups = payload.get("groups")
        if not isinstance(features, list) or len(features) < 2:
            raise ContractError("grouped-corr-split-violin.features 至少需要两个字段")
        feature_names = [str(item).strip() for item in features]
        if any(not item for item in feature_names) or len(set(feature_names)) != len(feature_names):
            raise ContractError("grouped-corr-split-violin.features 必须唯一且非空")
        if not isinstance(groups, list) or len(groups) != 2:
            raise ContractError("grouped-corr-split-violin.groups 必须恰有两个分组")
        normalized_groups = []
        group_names: set[str] = set()
        for group_index, raw in enumerate(groups):
            group = _object(raw, f"groups[{group_index}]")
            name = group.get("name")
            values = group.get("values")
            if not isinstance(name, str) or not name.strip() or name.strip() in group_names:
                raise ContractError("分组名称必须唯一且非空")
            if not isinstance(values, list) or len(values) < 3:
                raise ContractError("每个分组至少需要三行观测")
            rows = [
                _number_list(row, f"groups[{group_index}].values[{row_index}]", minimum=len(feature_names))
                for row_index, row in enumerate(values)
            ]
            if any(len(row) != len(feature_names) for row in rows):
                raise ContractError("每行分组观测必须与 features 等长")
            group_names.add(name.strip())
            normalized_groups.append({"name": name.strip(), "values": rows})
        return {"features": feature_names, "groups": normalized_groups}
    if template_id == "grouped-circular-heatmap":
        items = payload.get("items")
        rings = payload.get("rings")
        if not isinstance(items, list) or len(items) < 3:
            raise ContractError("grouped-circular-heatmap.items 至少需要三个项目")
        item_names = [str(item).strip() for item in items]
        if any(not item for item in item_names) or len(set(item_names)) != len(item_names):
            raise ContractError("grouped-circular-heatmap.items 必须唯一且非空")
        if not isinstance(rings, list) or len(rings) < 2:
            raise ContractError("grouped-circular-heatmap.rings 至少需要两个指标环")
        normalized_rings = []
        ring_names: set[str] = set()
        for index, raw in enumerate(rings):
            ring = _object(raw, f"rings[{index}]")
            name = ring.get("name")
            values = _number_list(ring.get("values"), f"rings[{index}].values", minimum=len(item_names))
            if (
                not isinstance(name, str)
                or not name.strip()
                or name.strip() in ring_names
                or len(values) != len(item_names)
            ):
                raise ContractError("每个指标环需要唯一名称和与 items 等长的 values")
            ring_names.add(name.strip())
            normalized_rings.append({"name": name.strip(), "values": values})
        return {"items": item_names, "rings": normalized_rings}
    if template_id == "nature-chord-diagram":
        nodes = payload.get("nodes")
        links = payload.get("links")
        if not isinstance(nodes, list) or len(nodes) < 3:
            raise ContractError("nature-chord-diagram.nodes 至少需要三个节点")
        normalized_nodes = []
        node_ids: set[str] = set()
        for index, raw in enumerate(nodes):
            node = _object(raw, f"nodes[{index}]")
            node_id, label, group = node.get("id"), node.get("label"), node.get("group")
            if (
                not isinstance(node_id, str)
                or not node_id.strip()
                or node_id.strip() in node_ids
                or not isinstance(label, str)
                or not label.strip()
                or not isinstance(group, str)
                or not group.strip()
            ):
                raise ContractError("和弦图节点需要唯一 id、非空 label 和 group")
            node_ids.add(node_id.strip())
            normalized_nodes.append(
                {"id": node_id.strip(), "label": label.strip(), "group": group.strip()}
            )
        if not isinstance(links, list) or not links:
            raise ContractError("nature-chord-diagram.links 必须是非空数组")
        normalized_links = []
        for index, raw in enumerate(links):
            link = _object(raw, f"links[{index}]")
            source, target = link.get("source"), link.get("target")
            try:
                weight = float(link.get("weight"))
            except (TypeError, ValueError) as exc:
                raise ContractError(f"links[{index}].weight 必须为正数") from exc
            if source not in node_ids or target not in node_ids or source == target:
                raise ContractError("和弦边必须引用两个不同的已声明节点")
            if not 0 < weight < float("inf"):
                raise ContractError("和弦边权重必须为有限正数")
            normalized_links.append({"source": source, "target": target, "weight": weight})
        return {"nodes": normalized_nodes, "links": normalized_links}
    if template_id == "urban-park-cooling-combo":
        categories = payload.get("categories")
        components = payload.get("components")
        metrics = payload.get("metrics")
        if not isinstance(categories, list) or len(categories) < 2:
            raise ContractError("urban-park-cooling-combo.categories 至少需要两个类别")
        category_names = [str(item).strip() for item in categories]
        if any(not item for item in category_names) or len(set(category_names)) != len(category_names):
            raise ContractError("组合图 categories 必须唯一且非空")
        if not isinstance(components, list) or len(components) < 2:
            raise ContractError("组合图 components 至少需要两个组成部分")
        normalized_components = []
        component_names: set[str] = set()
        for index, raw in enumerate(components):
            component = _object(raw, f"components[{index}]")
            name = component.get("name")
            values = _number_list(
                component.get("values"), f"components[{index}].values", minimum=len(category_names)
            )
            if (
                not isinstance(name, str)
                or not name.strip()
                or name.strip() in component_names
                or len(values) != len(category_names)
                or any(value < 0 for value in values)
            ):
                raise ContractError("组成部分需要唯一名称和与 categories 等长的非负 values")
            component_names.add(name.strip())
            normalized_components.append({"name": name.strip(), "values": values})
        if not isinstance(metrics, list) or not 1 <= len(metrics) <= 3:
            raise ContractError("组合图 metrics 必须包含 1--3 个分组指标")
        normalized_metrics = []
        metric_names: set[str] = set()
        for metric_index, raw_metric in enumerate(metrics):
            metric = _object(raw_metric, f"metrics[{metric_index}]")
            name, groups = metric.get("name"), metric.get("groups")
            if not isinstance(name, str) or not name.strip() or name.strip() in metric_names:
                raise ContractError("组合图指标名称必须唯一且非空")
            if not isinstance(groups, list) or len(groups) < 2:
                raise ContractError("每个组合图指标至少需要两个分组")
            normalized_groups = []
            group_names: set[str] = set()
            for group_index, raw_group in enumerate(groups):
                group = _object(raw_group, f"metrics[{metric_index}].groups[{group_index}]")
                group_name = group.get("name")
                values = _number_list(
                    group.get("values"),
                    f"metrics[{metric_index}].groups[{group_index}].values",
                    minimum=3,
                )
                if (
                    not isinstance(group_name, str)
                    or not group_name.strip()
                    or group_name.strip() in group_names
                ):
                    raise ContractError("指标分组名称必须唯一且非空")
                group_names.add(group_name.strip())
                normalized_groups.append({"name": group_name.strip(), "values": values})
            metric_names.add(name.strip())
            normalized_metrics.append({"name": name.strip(), "groups": normalized_groups})
        return {
            "categories": category_names,
            "components": normalized_components,
            "metrics": normalized_metrics,
        }
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
    """绘制真实配对样本的半小提琴、原始点、箱体、均值区间和连线。"""
    groups = data["groups"]
    figure, axis = plt.subplots(figsize=(max(7.6, len(groups) * 2.35), 6.4))
    colors = ("#3b7ea1", "#c86b4a")
    positions = np.arange(len(groups), dtype=float)

    def density(values: Any, grid: Any) -> Any:
        """用确定性高斯核估计密度，避免依赖额外统计包。"""
        standard_deviation = max(float(np.std(values, ddof=1)), 1e-6)
        bandwidth = max(1.06 * standard_deviation * len(values) ** (-0.2), 1e-3)
        standardized = (grid[:, None] - values[None, :]) / bandwidth
        estimate = np.exp(-0.5 * standardized**2).mean(axis=1)
        maximum = max(float(estimate.max()), 1e-12)
        return estimate / maximum

    for index, group in enumerate(groups):
        before = np.asarray(group["before"], dtype=float)
        after = np.asarray(group["after"], dtype=float)
        before_anchor, after_anchor = index - 0.24, index + 0.24
        lower = min(float(before.min()), float(after.min()))
        upper = max(float(before.max()), float(after.max()))
        padding = max((upper - lower) * 0.08, 1e-3)
        grid = np.linspace(lower - padding, upper + padding, 220)
        before_density = density(before, grid) * 0.20
        after_density = density(after, grid) * 0.20
        axis.fill_betweenx(
            grid,
            before_anchor - before_density,
            before_anchor,
            facecolor=colors[0],
            edgecolor=colors[0],
            linewidth=1.0,
            alpha=0.34,
            zorder=1,
        )
        axis.fill_betweenx(
            grid,
            after_anchor,
            after_anchor + after_density,
            facecolor=colors[1],
            edgecolor=colors[1],
            linewidth=1.0,
            alpha=0.34,
            zorder=1,
        )
        jitter = np.linspace(-0.035, 0.035, len(before))
        axis.plot(
            np.column_stack(
                [
                    np.full(len(before), before_anchor) + jitter,
                    np.full(len(after), after_anchor) + jitter,
                ]
            ).T,
            np.column_stack([before, after]).T,
            color="#777777",
            alpha=0.28,
            linewidth=0.75,
            zorder=2,
        )
        axis.scatter(
            np.full(len(before), before_anchor) + jitter,
            before,
            s=22,
            color=colors[0],
            edgecolor="white",
            linewidth=0.35,
            alpha=0.80,
            label="Before" if index == 0 else None,
            zorder=3,
        )
        axis.scatter(
            np.full(len(after), after_anchor) + jitter,
            after,
            s=22,
            color=colors[1],
            edgecolor="white",
            linewidth=0.35,
            alpha=0.80,
            label="After" if index == 0 else None,
            zorder=3,
        )
        box = axis.boxplot(
            [before, after],
            positions=[before_anchor, after_anchor],
            widths=0.085,
            patch_artist=True,
            showfliers=False,
            zorder=4,
        )
        for box_index, patch in enumerate(box["boxes"]):
            patch.set_facecolor(colors[box_index])
            patch.set_edgecolor("#333333")
            patch.set_alpha(0.78)
        for median in box["medians"]:
            median.set_color("white")
            median.set_linewidth(1.4)
        for key in ("whiskers", "caps"):
            for artist in box[key]:
                artist.set_color("#444444")
                artist.set_linewidth(0.8)
        for anchor, values, color in (
            (before_anchor, before, colors[0]),
            (after_anchor, after, colors[1]),
        ):
            standard_error = float(np.std(values, ddof=1) / np.sqrt(len(values)))
            axis.errorbar(
                anchor,
                float(np.mean(values)),
                yerr=1.96 * standard_error,
                fmt="D",
                markersize=4.5,
                color="#222222",
                markerfacecolor=color,
                capsize=3,
                linewidth=1.1,
                zorder=5,
            )
        axis.text(
            index,
            max(before.max(), after.max()) + padding * 0.35,
            f"Δ={np.mean(after - before):+.3g}",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    axis.set_xticks(positions, [item["name"] for item in groups])
    axis.set(title="Paired raincloud: distribution, uncertainty, and individual changes", ylabel="Measured value")
    axis.legend(frameon=False, ncol=2)
    axis.grid(axis="y", alpha=0.2)
    figure.tight_layout()
    figure._shumozizi_panels = ["main"]
    figure._shumozizi_elements = [
        {"type": "condition", "label": "Before", "panel": "main"},
        {"type": "condition", "label": "After", "panel": "main"},
    ]
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


def _render_constraint_margin_timeline(data: dict[str, Any], plt: Any, np: Any) -> Any:
    """绘制各约束余量随时间变化及真正激活的临界时段。"""
    figure, axis = plt.subplots(figsize=(9.2, 5.8))
    time = np.asarray(data["time"], dtype=float)
    tolerance = float(data["active_tolerance"])
    colors = plt.get_cmap("tab10").colors
    active_labels: list[str] = []
    for index, series in enumerate(data["series"]):
        margin = np.asarray(series["margin"], dtype=float)
        axis.plot(time, margin, marker="o", linewidth=1.6, color=colors[index], label=series["label"])
        active = margin <= tolerance
        if active.any():
            label = f"{series['label']} active"
            active_labels.append(label)
            axis.scatter(time[active], margin[active], s=52, marker="D", color=colors[index], label=label)
    threshold_label = f"Active tolerance = {tolerance:g}"
    axis.axhline(tolerance, linestyle="--", linewidth=1.2, color="#8c3f3f", label=threshold_label)
    axis.set(
        xlabel=data["time_label"],
        ylabel=data["margin_label"],
        title="Constraint margins and active periods",
    )
    axis.grid(alpha=0.2)
    axis.legend(fontsize=8, ncol=2)
    figure.tight_layout()
    figure._shumozizi_panels = ["main"]
    figure._shumozizi_elements = [
        {"type": "active_threshold", "label": threshold_label, "panel": "main"},
        *[
            {"type": "active_constraint_period", "label": label, "panel": "main"}
            for label in active_labels
        ],
    ]
    return figure


def _render_layered_network(
    data: dict[str, Any],
    plt: Any,
    *,
    title: str,
    node_type: str,
) -> Any:
    """按显式 stage/kind 分层绘制可追溯节点与有向关系。"""
    figure, axis = plt.subplots(figsize=(10.0, 5.8))
    layer_field = data["layer_field"]
    layers = list(dict.fromkeys(node[layer_field] for node in data["nodes"]))
    nodes_by_layer = {
        layer: [node for node in data["nodes"] if node[layer_field] == layer]
        for layer in layers
    }
    positions: dict[str, tuple[float, float]] = {}
    for x_index, layer in enumerate(layers):
        layer_nodes = nodes_by_layer[layer]
        for y_index, node in enumerate(layer_nodes):
            y = (len(layer_nodes) - 1) / 2 - y_index
            positions[node["id"]] = (float(x_index), float(y))
    for edge in data["edges"]:
        source = positions[edge["source"]]
        target = positions[edge["target"]]
        axis.annotate(
            "",
            xy=target,
            xytext=source,
            arrowprops={"arrowstyle": "->", "color": "#66727a", "linewidth": 1.2},
            zorder=1,
        )
        midpoint = ((source[0] + target[0]) / 2, (source[1] + target[1]) / 2 + 0.08)
        axis.text(*midpoint, edge["relation"], ha="center", va="bottom", fontsize=8, color="#4b555b")
    colors = plt.get_cmap("Set2").colors
    for node in data["nodes"]:
        x, y = positions[node["id"]]
        layer_index = layers.index(node[layer_field])
        axis.text(
            x,
            y,
            node["label"],
            ha="center",
            va="center",
            fontsize=9,
            bbox={
                "boxstyle": "round,pad=0.45",
                "facecolor": colors[layer_index % len(colors)],
                "edgecolor": "#4d5960",
                "linewidth": 0.9,
            },
            zorder=2,
        )
    axis.set_xlim(-0.55, max(0.55, len(layers) - 0.45))
    max_layer = max(len(nodes) for nodes in nodes_by_layer.values())
    axis.set_ylim(-max_layer / 2 - 0.5, max_layer / 2 + 0.5)
    axis.set_xticks(range(len(layers)), layers)
    axis.set_yticks([])
    axis.set_title(title, pad=14)
    for spine in axis.spines.values():
        spine.set_visible(False)
    figure.tight_layout()
    figure._shumozizi_panels = ["main"]
    figure._shumozizi_elements = [
        {"type": node_type, "label": node["label"], "panel": "main"}
        for node in data["nodes"]
    ]
    return figure


def _render_model_evolution_schematic(data: dict[str, Any], plt: Any, np: Any) -> Any:
    """绘制多问模型对象的继承、新增约束与结构演化。"""
    return _render_layered_network(
        data,
        plt,
        title="Model evolution across questions",
        node_type="model_component",
    )


def _render_argument_evidence_map(data: dict[str, Any], plt: Any, np: Any) -> Any:
    """绘制结论、推导、证据和边界之间的有向论证关系。"""
    return _render_layered_network(
        data,
        plt,
        title="Argument and evidence map",
        node_type="argument_unit",
    )


def _render_rf_tpe_surface(data: dict[str, Any], plt: Any, np: Any) -> Any:
    """用真实调参点绘制插值曲面与俯视等值图。"""
    from matplotlib.tri import Triangulation

    figure = plt.figure(figsize=(12.2, 5.6))
    axis = figure.add_subplot(121, projection="3d")
    contour_axis = figure.add_subplot(122)
    trials = data["trials"]
    x = np.asarray([item["x"] for item in trials], dtype=float)
    y = np.asarray([item["y"] for item in trials], dtype=float)
    metric = np.asarray([item["metric"] for item in trials], dtype=float)
    triangulation = Triangulation(x, y)
    surface = axis.plot_trisurf(
        triangulation,
        metric,
        cmap="coolwarm",
        alpha=0.78,
        linewidth=0.35,
        edgecolor=(1, 1, 1, 0.45),
    )
    axis.scatter(x, y, metric, s=18, color="#343434", alpha=0.72, label="真实试验")
    best = data["best_trial"]
    axis.scatter(
        [best["x"]],
        [best["y"]],
        [best["metric"]],
        marker="*",
        s=180,
        color="#b52e31",
        depthshade=False,
        label="当前最优",
    )
    axis.set(
        xlabel=data["x_label"],
        ylabel=data["y_label"],
        zlabel=data["metric_label"],
        title="真实试验点及其三角插值曲面",
    )
    axis.text2D(0.03, 0.86, "三角插值", transform=axis.transAxes, fontsize=8, color="#555555")
    axis.view_init(elev=28, azim=-132)
    axis.legend(loc="upper left", fontsize=8)
    contour = contour_axis.tricontourf(
        triangulation,
        metric,
        levels=12,
        cmap="coolwarm",
    )
    contour_axis.tricontour(
        triangulation,
        metric,
        levels=12,
        colors="#ffffff",
        linewidths=0.45,
        alpha=0.65,
    )
    contour_axis.scatter(x, y, s=22, color="#343434", alpha=0.78, label="真实试验")
    contour_axis.scatter(
        [best["x"]],
        [best["y"]],
        marker="*",
        s=180,
        color="#b52e31",
        edgecolor="white",
        linewidth=0.7,
        label="当前最优",
        zorder=4,
    )
    contour_axis.set(
        xlabel=data["x_label"],
        ylabel=data["y_label"],
        title="俯视等值结构（插值，不是新增试验）",
    )
    contour_axis.legend(loc="best", fontsize=8)
    figure.colorbar(contour, ax=contour_axis, fraction=0.046, pad=0.04, label=data["metric_label"])
    figure.colorbar(surface, ax=axis, fraction=0.046, pad=0.08, label=data["metric_label"])
    figure.text(
        0.5,
        0.01,
        "注：黑点是实际 trials；曲面与等值区仅为离散试验点间的三角插值。",
        ha="center",
        fontsize=8,
        color="#555555",
    )
    figure.tight_layout(rect=(0, 0.04, 1, 1))
    figure._shumozizi_panels = ["surface", "contour"]
    figure._shumozizi_elements = [
        {"type": "observed_trials", "label": "真实试验", "panel": "surface"},
        {"type": "interpolation", "label": "三角插值", "panel": "surface"},
        {"type": "selected_point", "label": "当前最优", "panel": "contour"},
    ]
    return figure


def _render_taylor_diagram(data: dict[str, Any], plt: Any, np: Any) -> Any:
    """绘制标准差—相关系数泰勒图，保留参考点与模型标签。"""
    panels = data["panels"]
    figure, axes = plt.subplots(
        1,
        len(panels),
        figsize=(6.2 * len(panels), 5.6),
        subplot_kw={"projection": "polar"},
        squeeze=False,
    )
    colors = plt.get_cmap("tab10").colors
    labels = []
    for axis, panel in zip(axes.ravel(), panels, strict=True):
        maximum_std = max(
            [data["reference_std"], *[item["std"] for item in panel["points"]]]
        )
        axis.set_thetamin(0)
        axis.set_thetamax(180)
        axis.set_ylim(0, maximum_std * 1.2)
        correlations = np.asarray([1.0, 0.8, 0.6, 0.4, 0.0, -0.4, -0.8, -1.0])
        axis.set_xticks(np.arccos(correlations))
        axis.set_xticklabels([f"{value:g}" for value in correlations], fontsize=8)
        axis.set_title(panel["title"], pad=20)
        axis.scatter([0], [data["reference_std"]], marker="*", s=150, color="#222222")
        axis.text(0, data["reference_std"] * 1.03, "参考", ha="center", va="bottom")
        for index, point in enumerate(panel["points"]):
            theta = float(np.arccos(point["corr"]))
            axis.scatter(theta, point["std"], s=55, color=colors[index % len(colors)])
            axis.text(theta, point["std"], point["name"], fontsize=8, ha="left", va="bottom")
            labels.append(point["name"])
        axis.grid(alpha=0.3)
    figure.suptitle("模型标准差与相关结构", y=1.02)
    figure.tight_layout()
    figure._shumozizi_panels = [f"panel-{index + 1}" for index in range(len(panels))]
    figure._shumozizi_elements = [
        {"type": "reference", "label": "参考", "panel": figure._shumozizi_panels[0]},
        *[
            {"type": "model", "label": label, "panel": figure._shumozizi_panels[0]}
            for label in labels
        ],
    ]
    return figure


def _render_multiclass_shap_combo(data: dict[str, Any], plt: Any, np: Any) -> Any:
    """绘制多分类平均绝对 SHAP 与逐样本贡献联合图。"""
    figure, (bar_axis, swarm_axis) = plt.subplots(1, 2, figsize=(12.2, 5.8))
    features = data["features"]
    classes = data["classes"]
    importance = np.asarray(data["mean_abs_shap"], dtype=float)
    colors = plt.get_cmap("tab10").colors
    positions = np.arange(len(features))
    left = np.zeros(len(features))
    for index, class_name in enumerate(classes):
        bar_axis.barh(
            positions,
            importance[:, index],
            left=left,
            color=colors[index % len(colors)],
            label=class_name,
        )
        left += importance[:, index]
    bar_axis.set_yticks(positions, [])
    for position, feature in zip(positions, features, strict=True):
        bar_axis.text(-0.02, position, feature, transform=bar_axis.get_yaxis_transform(), ha="right", va="center")
    bar_axis.set_xlabel("平均 |SHAP| 特征贡献")
    bar_axis.set_title("类别分解的重要性")
    bar_axis.legend(fontsize=8)
    feature_position = {name: index for index, name in enumerate(features)}
    for index, record in enumerate(data["beeswarm"]):
        shap_values = np.asarray(record["shap_values"], dtype=float)
        feature_values = np.asarray(record["feature_values"], dtype=float)
        spread = max(float(np.ptp(feature_values)), 1e-12)
        normalized = (feature_values - float(np.min(feature_values))) / spread
        offsets = np.linspace(-0.14, 0.14, len(shap_values))
        swarm_axis.scatter(
            shap_values,
            feature_position[record["feature"]] + offsets,
            c=normalized,
            cmap="coolwarm",
            s=24,
            alpha=0.78,
            marker=("o", "s", "D", "^")[index % 4],
            label=record["class"],
        )
    swarm_axis.axvline(0, color="#666666", linewidth=0.8)
    swarm_axis.set_yticks(positions, features)
    swarm_axis.set_xlabel("SHAP 贡献")
    swarm_axis.set_title("逐样本贡献与特征水平")
    handles, labels = swarm_axis.get_legend_handles_labels()
    unique = dict(zip(labels, handles, strict=True))
    swarm_axis.legend(unique.values(), unique.keys(), fontsize=8)
    figure.tight_layout()
    figure._shumozizi_panels = ["importance", "beeswarm"]
    figure._shumozizi_elements = [
        *[
            {"type": "class", "label": name, "panel": "importance"}
            for name in classes
        ],
        *[
            {"type": "feature", "label": name, "panel": "importance"}
            for name in features
        ],
    ]
    return figure


def _render_grouped_corr_split_violin(data: dict[str, Any], plt: Any, np: Any) -> Any:
    """由两个真实分组的同字段观测绘制相关矩阵和并列小提琴。"""
    figure, (corr_axis, violin_axis) = plt.subplots(1, 2, figsize=(12.2, 5.8))
    features = data["features"]
    groups = data["groups"]
    combined = np.vstack([np.asarray(group["values"], dtype=float) for group in groups])
    correlation = np.corrcoef(combined, rowvar=False)
    image = corr_axis.imshow(correlation, vmin=-1, vmax=1, cmap="coolwarm")
    corr_axis.set_xticks(range(len(features)), features, rotation=45, ha="right")
    corr_axis.set_yticks(range(len(features)), features)
    corr_axis.set_title("合并观测相关矩阵")
    for row in range(len(features)):
        for column in range(len(features)):
            if row >= column:
                corr_axis.text(column, row, f"{correlation[row, column]:.2f}", ha="center", va="center", fontsize=8)
    figure.colorbar(image, ax=corr_axis, fraction=0.046, pad=0.04)
    colors = ("#4c78a8", "#e07b54")
    base_positions = np.arange(len(features), dtype=float)
    for group_index, group in enumerate(groups):
        matrix = np.asarray(group["values"], dtype=float)
        positions = base_positions + (-0.14 if group_index == 0 else 0.14)
        violins = violin_axis.violinplot(
            [matrix[:, index] for index in range(len(features))],
            positions=positions,
            widths=0.28,
            showmedians=True,
            showextrema=False,
        )
        for body in violins["bodies"]:
            body.set_facecolor(colors[group_index])
            body.set_alpha(0.58)
        violins["cmedians"].set_color(colors[group_index])
        violin_axis.scatter([], [], color=colors[group_index], label=group["name"])
    violin_axis.set_xticks(base_positions, features, rotation=25, ha="right")
    violin_axis.set_title("两个分组的字段分布")
    violin_axis.legend(fontsize=8)
    violin_axis.grid(axis="y", alpha=0.2)
    figure.tight_layout()
    figure._shumozizi_panels = ["correlation", "distribution"]
    figure._shumozizi_elements = [
        {"type": "group", "label": group["name"], "panel": "distribution"}
        for group in groups
    ]
    return figure


def _render_grouped_circular_heatmap(data: dict[str, Any], plt: Any, np: Any) -> Any:
    """绘制项目 × 指标环矩阵，采用统一色标以保留跨环比较。"""
    figure, axis = plt.subplots(figsize=(7.6, 7.2), subplot_kw={"projection": "polar"})
    items = data["items"]
    rings = data["rings"]
    matrix = np.asarray([ring["values"] for ring in rings], dtype=float)
    minimum, maximum = float(np.min(matrix)), float(np.max(matrix))
    span = max(maximum - minimum, 1e-12)
    angles = np.linspace(0, 2 * np.pi, len(items), endpoint=False)
    width = 2 * np.pi / len(items) * 0.97
    cmap = plt.get_cmap("viridis")
    for ring_index, ring in enumerate(rings):
        normalized = (np.asarray(ring["values"]) - minimum) / span
        axis.bar(
            angles,
            np.full(len(items), 0.82),
            width=width,
            bottom=ring_index + 0.2,
            color=cmap(normalized),
            edgecolor="white",
            linewidth=0.9,
        )
        # 环名直接贴近内圈，避免仅凭颜色区分不同指标层。
        axis.text(
            np.pi,
            ring_index + 0.61,
            ring["name"],
            ha="center",
            va="center",
            fontsize=7.5,
            color="white" if float(np.mean(normalized)) < 0.55 else "#222222",
            bbox={"boxstyle": "round,pad=0.16", "facecolor": cmap(float(np.mean(normalized))), "edgecolor": "none"},
        )
    for angle, item in zip(angles, items, strict=True):
        rotation = np.degrees(angle)
        if 90 < rotation <= 270:
            rotation += 180
        axis.text(
            angle,
            len(rings) + 0.46,
            item,
            ha="center",
            va="center",
            rotation=rotation - 90,
            rotation_mode="anchor",
            fontsize=8,
        )
    axis.set_ylim(0, len(rings) + 0.75)
    axis.set_yticks([])
    axis.set_xticks([])
    axis.set_title("项目—指标环形热图", pad=22)
    scalar = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=minimum, vmax=maximum))
    scalar.set_array([])
    figure.colorbar(
        scalar,
        ax=axis,
        fraction=0.045,
        pad=0.09,
        label="统一指标色标",
    )
    figure.tight_layout(rect=(0, 0, 0.94, 1))
    figure._shumozizi_panels = ["main"]
    figure._shumozizi_elements = [
        {"type": "metric_ring", "label": ring["name"], "panel": "main"}
        for ring in rings
    ]
    return figure


def _render_nature_chord_diagram(data: dict[str, Any], plt: Any, np: Any) -> Any:
    """绘制确定性的加权关系和弦图，不随机生成节点或边。"""
    from matplotlib.patches import Patch, PathPatch, Wedge
    from matplotlib.path import Path as MplPath

    figure, axis = plt.subplots(figsize=(7.6, 7.2))
    nodes = data["nodes"]
    angles = np.linspace(0, 2 * np.pi, len(nodes), endpoint=False) + np.pi / 2
    node_angles = {node["id"]: angle for node, angle in zip(nodes, angles, strict=True)}
    groups = list(dict.fromkeys(node["group"] for node in nodes))
    colors = plt.get_cmap("tab10").colors
    group_colors = {group: colors[index % len(colors)] for index, group in enumerate(groups)}
    maximum_weight = max(link["weight"] for link in data["links"])
    for link in sorted(data["links"], key=lambda item: item["weight"]):
        source_angle = node_angles[link["source"]]
        target_angle = node_angles[link["target"]]
        half_width = 0.018 + 0.045 * link["weight"] / maximum_weight
        start_a = 0.88 * np.asarray([np.cos(source_angle - half_width), np.sin(source_angle - half_width)])
        start_b = 0.88 * np.asarray([np.cos(source_angle + half_width), np.sin(source_angle + half_width)])
        end_a = 0.88 * np.asarray([np.cos(target_angle - half_width), np.sin(target_angle - half_width)])
        end_b = 0.88 * np.asarray([np.cos(target_angle + half_width), np.sin(target_angle + half_width)])
        source_group = next(node["group"] for node in nodes if node["id"] == link["source"])
        path = MplPath(
            [
                start_a,
                np.zeros(2),
                end_b,
                end_a,
                np.zeros(2),
                start_b,
                start_a,
            ],
            [
                MplPath.MOVETO,
                MplPath.CURVE3,
                MplPath.CURVE3,
                MplPath.LINETO,
                MplPath.CURVE3,
                MplPath.CURVE3,
                MplPath.CLOSEPOLY,
            ],
        )
        axis.add_patch(
            PathPatch(
                path,
                facecolor=group_colors[source_group],
                edgecolor=group_colors[source_group],
                linewidth=0.35,
                alpha=0.18 + 0.34 * link["weight"] / maximum_weight,
            )
        )
    sector_width = 360 / len(nodes) * 0.82
    for node in nodes:
        angle = node_angles[node["id"]]
        degrees = np.degrees(angle)
        axis.add_patch(
            Wedge(
                (0, 0),
                1.04,
                degrees - sector_width / 2,
                degrees + sector_width / 2,
                width=0.14,
                facecolor=group_colors[node["group"]],
                edgecolor="white",
                linewidth=0.9,
                zorder=3,
            )
        )
        label_position = np.asarray([np.cos(angle), np.sin(angle)]) * 1.18
        axis.text(
            label_position[0],
            label_position[1],
            node["label"],
            ha="left" if label_position[0] >= 0 else "right",
            va="center",
            fontsize=9,
        )
    axis.legend(
        handles=[Patch(facecolor=group_colors[group], label=group) for group in groups],
        loc="center left",
        bbox_to_anchor=(1.01, 0.5),
        frameon=False,
        fontsize=8,
        title="分组",
    )
    axis.set_aspect("equal")
    axis.set_xlim(-1.34, 1.34)
    axis.set_ylim(-1.34, 1.34)
    axis.set_title("加权关系和弦图")
    axis.axis("off")
    figure.tight_layout()
    figure._shumozizi_panels = ["main"]
    figure._shumozizi_elements = [
        {"type": "node", "label": node["label"], "panel": "main"}
        for node in nodes
    ]
    return figure


def _render_urban_park_cooling_combo(data: dict[str, Any], plt: Any, np: Any) -> Any:
    """绘制组成堆叠与多指标雨云分布，不继承示例领域解释。"""
    panel_count = 1 + len(data["metrics"])
    figure, axes = plt.subplots(1, panel_count, figsize=(5.2 * panel_count, 5.4), squeeze=False)
    component_axis = axes[0, 0]
    positions = np.arange(len(data["categories"]))
    bottoms = np.zeros(len(data["categories"]))
    colors = plt.get_cmap("Set2").colors
    for index, component in enumerate(data["components"]):
        values = np.asarray(component["values"], dtype=float)
        component_axis.bar(
            positions,
            values,
            bottom=bottoms,
            color=colors[index % len(colors)],
            label=component["name"],
        )
        bottoms += values
    component_axis.set_xticks(positions, data["categories"], rotation=25, ha="right")
    component_axis.set_ylabel("组成值")
    component_axis.set_title("类别组成")
    component_axis.legend(fontsize=8)
    for axis, metric in zip(axes[0, 1:], data["metrics"], strict=True):
        values = [np.asarray(group["values"], dtype=float) for group in metric["groups"]]
        group_positions = np.arange(1, len(values) + 1, dtype=float)
        violins = axis.violinplot(
            values,
            positions=group_positions,
            widths=0.72,
            showmeans=False,
            showmedians=False,
            showextrema=False,
        )
        for index, body in enumerate(violins["bodies"]):
            body.set_facecolor(colors[index % len(colors)])
            body.set_edgecolor("white")
            body.set_alpha(0.42)
        box = axis.boxplot(
            values,
            positions=group_positions,
            widths=0.22,
            tick_labels=[group["name"] for group in metric["groups"]],
            patch_artist=True,
            showmeans=True,
            medianprops={"color": "#222222", "linewidth": 1.2},
            whiskerprops={"linewidth": 0.8},
            capprops={"linewidth": 0.8},
        )
        for index, patch in enumerate(box["boxes"]):
            patch.set_facecolor(colors[index % len(colors)])
            patch.set_alpha(0.74)
        for index, (position, group_values) in enumerate(zip(group_positions, values, strict=True)):
            # 固定序列抖动保证图可复现，同时让真实样本密度可见。
            jitter = np.linspace(-0.17, 0.17, len(group_values))
            axis.scatter(
                position + jitter,
                group_values,
                s=13,
                color=colors[index % len(colors)],
                edgecolor="white",
                linewidth=0.35,
                alpha=0.72,
                zorder=3,
            )
        axis.set_title(metric["name"])
        axis.text(
            0.02,
            0.98,
            "分布 + 箱体 + 原始样本",
            transform=axis.transAxes,
            ha="left",
            va="top",
            fontsize=8,
            color="#555555",
        )
        axis.grid(axis="y", alpha=0.2)
    figure.tight_layout()
    figure._shumozizi_panels = ["composition", *[f"metric-{i + 1}" for i in range(len(data["metrics"]))]]
    figure._shumozizi_elements = [
        *[
            {"type": "component", "label": component["name"], "panel": "composition"}
            for component in data["components"]
        ],
        *[
            {"type": "metric", "label": metric["name"], "panel": f"metric-{index + 1}"}
            for index, metric in enumerate(data["metrics"])
        ],
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


def _legend_overlaps_data(axis: Any) -> bool:
    """机器判定图例窗口是否与数据绘制区域重叠（无法判定时保守返回 True）。"""
    legend = axis.get_legend()
    if legend is None or not legend.get_visible():
        return False
    try:
        axis.figure.canvas.draw()
        renderer = axis.figure.canvas.get_renderer()
        legend_box = legend.get_window_extent(renderer)
        data_box = axis.get_window_extent(renderer)
        overlap_w = min(legend_box.x1, data_box.x1) - max(legend_box.x0, data_box.x0)
        overlap_h = min(legend_box.y1, data_box.y1) - max(legend_box.y0, data_box.y0)
        # numpy 2.x 的比较结果可能是 np.bool，JSON 无法序列化，显式转 Python bool。
        return bool(overlap_w > 0 and overlap_h > 0)
    except (AttributeError, RuntimeError, ValueError):
        # 图例不可测量时保守标记为可能遮挡，交由人工复核。
        return True


def write_plot_layout_report(figure: Any, output_stem: Path, figure_id: str) -> Path:
    """从已渲染的 Matplotlib Figure 机器提取统计图布局报告。

    机器只声明它真正能验证的事实（论文尺寸、字号、坐标范围、图例遮挡）；
    色盲安全、语言一致性与结论标注属于审美/语义判断，标记为待人工确认，
    不替人工作答。

    Args:
        figure: 已完成布局的 Matplotlib Figure。
        output_stem: 输出前缀（与 PNG 同目录）。
        figure_id: 图表 ID。

    Returns:
        布局报告 JSON 路径。
    """
    figure.canvas.draw()
    width_cm, height_cm = (float(value) * 2.54 for value in figure.get_size_inches())
    fonts = [
        float(artist.get_fontsize())
        for artist in _figure_text_artists(figure)
        if artist.get_fontsize()
    ]
    minimum_font_pt = min(fonts) if fonts else 12.0
    axes: list[dict[str, Any]] = []
    needs_human: list[str] = ["colorblind_safe", "locale_consistent", "takeaway_annotation"]
    if width_cm > 20 or height_cm > 24:
        # sci-box 母版原图按整页/横版设计，正文排版需要缩放到栏宽；
        # 论文实际占用尺寸由人工看图后确认。
        needs_human.append("paper_size_cm")
    for index, axis in enumerate(figure.axes):
        axis_id = f"panel-{index + 1}"
        projection = "3d" if axis.name == "3d" else "2d"
        x_limits = [float(value) for value in axis.get_xlim()]
        y_limits = [float(value) for value in axis.get_ylim()]
        try:
            data_lim = axis.dataLim
            x_data = [float(data_lim.x0), float(data_lim.x1)]
            y_data = [float(data_lim.y0), float(data_lim.y1)]
            if not all(math.isfinite(value) for value in (*x_data, *y_data)):
                raise ValueError
        except (AttributeError, RuntimeError, ValueError):
            # dataLim 不可用时（纯装饰/极坐标 axes），保守按显示范围全占用。
            x_data, y_data = x_limits, y_limits
        record: dict[str, Any] = {
            "id": axis_id,
            "role": "primary" if index == 0 else "supporting",
            "projection": projection,
            "x_limits": x_limits,
            "x_data_range": x_data,
            "y_limits": y_limits,
            "y_data_range": y_data,
            "legend_overlaps_data": _legend_overlaps_data(axis),
            "takeaway_annotation": False,
        }
        if projection == "3d":
            try:
                box_aspect = [float(value) for value in axis.get_box_aspect()]
            except (AttributeError, RuntimeError, ValueError):
                box_aspect = [1.0, 1.0, 1.0]
            record["data_aspect_ratio"] = box_aspect
            record["camera_projection"] = "orthographic"
            record["camera_view"] = {
                "azimuth": float(getattr(axis, "azim", 30.0)),
                "elevation": float(getattr(axis, "elev", 30.0)),
            }
            record["coordinate_unit"] = ""
            record["trajectory_direction_labeled"] = False
            needs_human.extend([f"{axis_id}.camera_projection", f"{axis_id}.coordinate_unit"])
        axes.append(record)
    report_path = output_stem.with_suffix(".layout_report.json")
    atomic_json(
        report_path,
        {
            "schema_name": "plot_layout_report",
            "schema_version": "1.0",
            "figure_id": figure_id,
            "paper_size_cm": {
                "width": round(width_cm, 2),
                "height": round(height_cm, 2),
            },
            "minimum_font_size_pt": round(minimum_font_pt, 1),
            "colorblind_safe": False,
            "locale_consistent": False,
            "axes": axes,
            "primary_panel_id": axes[0]["id"] if axes else "panel-1",
            "machine_verified": [
                "paper_size_cm",
                "minimum_font_size_pt",
                "axes",
                "legend_overlaps_data",
            ],
            "needs_human_confirmation": needs_human,
        },
    )
    return report_path


def render(
    template_id: str,
    data: dict[str, Any],
    output_stem: Path,
    figure_id: str | None = None,
) -> Path:
    """以已验证的真实数据生成 PNG、PDF、SVG 和文字边界文件。

    Args:
        template_id: 模板 ID。
        data: 由 :func:`load_data` 返回的真实数据。
        output_stem: 不含扩展名的运行目录内输出路径。
        figure_id: 可选图表 ID；提供时同时机器生成 layout_report.json。

    Returns:
        文字边界 JSON 文件路径。

    Raises:
        ContractError: 绘图失败、中文字体缺字或模板未接入。
    """
    _, plt, np = _plot_modules()
    renderers = {
        "argument_evidence_map": _render_argument_evidence_map,
        "constraint_margin_timeline": _render_constraint_margin_timeline,
        "cv-roc-ci": _render_cv_roc_ci,
        "feasible-region-active-constraints": _render_feasible_region_active_constraints,
        "grouped-circular-heatmap": _render_grouped_circular_heatmap,
        "grouped-corr-split-violin": _render_grouped_corr_split_violin,
        "interval-event-timeline": _render_interval_event_timeline,
        "multi-panel-evidence-chain": _render_multi_panel_evidence_chain,
        "multiclass-shap-combo": _render_multiclass_shap_combo,
        "nature-chord-diagram": _render_nature_chord_diagram,
        "model_evolution_schematic": _render_model_evolution_schematic,
        "prediction-marginal-grid": _render_prediction_marginal_grid,
        "rf-tpe-surface": _render_rf_tpe_surface,
        "taylor-diagram": _render_taylor_diagram,
        "paired-raincloud": _render_paired_raincloud,
        "correlation-pairgrid": _render_correlation_pairgrid,
        "uncertainty-fan-threshold": _render_uncertainty_fan_threshold,
        "urban-park-cooling-combo": _render_urban_park_cooling_combo,
    }
    renderer = renderers.get(_CANONICAL_RENDERER_BASE.get(template_id, template_id))
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
        if figure_id:
            write_plot_layout_report(figure, output_stem, figure_id)
        return boxes_path
    finally:
        plt.close(figure)
