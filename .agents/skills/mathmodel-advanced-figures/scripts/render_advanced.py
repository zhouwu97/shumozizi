"""竞赛高级图渲染：从 current production JSON 生成 seaborn 高级图。

这是 "SECOND STEP 高级图补充" 的实现层：初稿完成后，通读论文，按数据特征
从本脚本的模板目录挑图种，用 production 数据渲染，配图注与"展示了什么"的解读。
模板只增强表达，不修改数据、模型与结论。

用法：:

    python render_advanced.py --template <id> --input <document.json> --output <stem>

支持的模板（``--list`` 查看）：probability_curve / feasible_region /
pareto_frontier / ci_forest / group_violin。统一风格由 style.apply_competition_style 保证。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import BLUE, CORAL, GOLD, GRAY, PALE_GOLD, TEAL, apply_competition_style, clean_axes

apply_competition_style()


def _rows(value: Any, name: str) -> list[dict[str, Any]]:
    """规范 JSON 为对象行列表。"""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _pick(document: dict[str, Any], *names: str, default: Any = None) -> Any:
    """按优先顺序读取字段，支持嵌套路径 sub.field。"""
    for name in names:
        value: Any = document
        for part in name.split("."):
            if not isinstance(value, dict) or part not in value:
                value = None
                break
            value = value[part]  # 下钻到该字段
        if value is not None:
            return value
    return default


# ---------------------------------------------------------------------------
# 模板：概率转变曲线（Q2/Q3 高级版：CI 误差棒 + 阈值带 + 平滑拟合）
# ---------------------------------------------------------------------------
def _probability_curve(doc: dict[str, Any], out_stem: Path) -> dict[str, Any]:
    points = _rows(
        _pick(doc, "points", "results", "crn_curve.points", default=[]), "points"
    )
    if not points:
        raise ValueError("probability_curve 需要 points[]")
    threshold = float(_pick(doc, "threshold", "target", default=0.90))
    x = np.array([float(p.get("x", p.get("n", p.get("f_pct", p.get("volume_fraction", i))))) for i, p in enumerate(points)])
    prob = np.array([float(p.get("probability", p.get("p_estimate", p.get("prob_estimate", p.get("p", 0.0))))) for p in points])
    low = np.array([float(p.get("wilson_low", p.get("ci_lower", p.get("ci_lo", prob[i])))) for i, p in enumerate(points)])
    high = np.array([float(p.get("wilson_high", p.get("ci_upper", p.get("ci_hi", prob[i])))) for i, p in enumerate(points)])

    fig, ax = plt.subplots(figsize=(7.6, 4.6))
    # CI 误差带 + 点估计（seaborn 风格）
    ax.fill_between(x, low, high, color=TEAL, alpha=0.15, label="95% Wilson 区间")
    sns.lineplot(x=x, y=prob, ax=ax, color=TEAL, marker="o", linewidth=2.0, label="点估计")
    ax.errorbar(x, prob, yerr=[prob - low, high - prob], fmt="none", ecolor=GRAY, capsize=3, zorder=1)
    ax.axhline(threshold, color=GOLD, linewidth=1.6, linestyle="--", label=f"{threshold:.0%} 阈值")
    # 首次越过阈值带
    first_above = next((i for i, v in enumerate(low) if v >= threshold), None)
    if first_above is not None and first_above > 0:
        ax.axvspan(x[first_above - 1], x[first_above], color=PALE_GOLD, alpha=0.5, label="首次越过带")
    ax.set_xlabel(str(_pick(doc, "x_label", default="介质 A 数量 / 体积分数")))
    ax.set_ylabel("导通概率")
    ax.set_title(str(_pick(doc, "title", default="导通概率转变与可靠性阈值")))
    ax.legend(frameon=False, loc="best", fontsize=8)
    clean_axes(ax)
    return _save(fig, out_stem)


# ---------------------------------------------------------------------------
# 模板：整数可行域（Q4 高级版：seaborn 格点 + 等高线 + 选中点）
# ---------------------------------------------------------------------------
def _feasible_region(doc: dict[str, Any], out_stem: Path) -> dict[str, Any]:
    pts = _rows(_pick(doc, "lattice_points", "grid_points", "points", "phases.grid.points", default=[]), "points")
    if not pts:
        raise ValueError("feasible_region 需要 lattice_points[]")
    x = np.array([float(p.get("n_A", p.get("f_a_pct", p.get("x", 0.0)))) for p in pts])
    y = np.array([float(p.get("n_B", p.get("f_b_pct", p.get("y", 0.0)))) for p in pts])
    feasible = np.array([bool(p.get("feasible", True)) for p in pts])
    cost = np.array([float(p.get("cost", p.get("cost_yuan", np.nan))) for p in pts], dtype=float)

    fig, ax = plt.subplots(figsize=(7.6, 5.6))
    # 正式域/敏感性域背景
    ax.axvspan(-0.5, 0.5, color=GRAY, alpha=0.12)
    ax.axhspan(-0.5, 0.5, color=GRAY, alpha=0.12)
    # 等高线（规则格点时用 contourf，不规则用 tricontourf）
    valid = ~np.isnan(cost) & feasible
    if np.any(valid) and np.unique(x[valid]).size >= 2 and np.unique(y[valid]).size >= 2:
        levels = np.percentile(cost[valid], [20, 40, 60, 80, 95])
        ax.tricontourf(x[valid], y[valid], cost[valid], levels=levels, cmap="Greys", alpha=0.5)
        cs = ax.tricontour(x[valid], y[valid], cost[valid], levels=levels, colors=GRAY, linewidths=0.9)
        ax.clabel(cs, inline=True, fontsize=7, fmt="%.2f")
    # 格点分层
    if np.any(~feasible):
        ax.scatter(x[~feasible], y[~feasible], marker="x", s=70, color=CORAL, linewidth=1.6, label="不可行")
    formal = feasible & (x >= 1) & (y >= 1)
    sens = feasible & ~((x >= 1) & (y >= 1))
    ax.scatter(x[formal], y[formal], s=90, color=TEAL, edgecolor="white", linewidth=0.6, label="正式域可行")
    if np.any(sens):
        ax.scatter(x[sens], y[sens], s=70, marker="D", color=GRAY, label="零允许敏感性")
    sel = _pick(doc, "selected_point", "selected", default=None)
    if isinstance(sel, dict):
        sx = float(sel.get("n_A", sel.get("f_a_pct", 0.0)))
        sy = float(sel.get("n_B", sel.get("f_b_pct", 0.0)))
        ax.scatter([sx], [sy], marker="*", s=380, color=GOLD, edgecolor="black", linewidth=0.8, zorder=5, label="正式答案")
    ax.set_xlabel(str(_pick(doc, "x_label", default="介质 A 体积分数 f_A / %")))
    ax.set_ylabel(str(_pick(doc, "y_label", default="介质 B 体积分数 f_B / %")))
    ax.set_title(str(_pick(doc, "title", default="整数可行域与成本等高线")))
    ax.legend(frameon=False, loc="best", fontsize=8)
    clean_axes(ax)
    return _save(fig, out_stem)


# ---------------------------------------------------------------------------
# 模板：成本—可靠性前沿（Q4 高级版：分层散点 + 阈值 + 选中星）
# ---------------------------------------------------------------------------
def _pareto_frontier(doc: dict[str, Any], out_stem: Path) -> dict[str, Any]:
    pts = _rows(_pick(doc, "candidate_points", "candidates", "points", "refinement_points", default=[]), "candidate_points")
    if not pts:
        raise ValueError("pareto_frontier 需要 candidate_points[]")
    threshold = float(_pick(doc, "threshold", "target", default=0.90))
    cost = np.array([float(p["cost"]) for p in pts])
    prob = np.array([float(p.get("probability", p.get("p", p.get("p_estimate", 0.0)))) for p in pts])
    low = np.array([float(p.get("wilson_low", p.get("ci_lo", p.get("ci_lower", prob[i])))) for i, p in enumerate(pts)])
    high = np.array([float(p.get("wilson_high", p.get("ci_hi", p.get("ci_upper", prob[i])))) for i, p in enumerate(pts)])
    domains = [str(p.get("domain", p.get("region", "formal"))) for p in pts]
    labels = [str(p.get("label", "")) for p in pts]

    fig, ax = plt.subplots(figsize=(7.6, 4.8))
    ax.errorbar(cost, prob, yerr=[prob - low, high - prob], fmt="none", ecolor=GRAY, capsize=3, zorder=1)
    for i, (d, c, pr) in enumerate(zip(domains, cost, prob, strict=True)):
        sensitivity = "sens" in d or "zero" in d or "out" in d
        ax.scatter([c], [pr], marker="X" if sensitivity else "o", s=110 if not sensitivity else 60,
                   color=GRAY if sensitivity else TEAL, edgecolor="white", linewidth=0.6, zorder=3,
                   label="敏感性/域外" if sensitivity and i == next((j for j, dd in enumerate(domains) if "sens" in dd), -1) else
                         ("正式域" if not sensitivity and i == next((j for j, dd in enumerate(domains) if "sens" not in dd), -1) else None))
        if labels[i]:
            ax.annotate(labels[i], (c, pr), xytext=(5, 5), textcoords="offset points", fontsize=7.5)
    official = str(_pick(doc, "official", "selected", default=""))
    if official:
        for i, p in enumerate(pts):
            if str(p.get("label", "")) == official:
                ax.scatter([cost[i]], [prob[i]], marker="*", s=380, color=GOLD, edgecolor="black", linewidth=0.8, zorder=5, label="正式答案")
                break
    ax.axhline(threshold, color=GOLD, linewidth=1.5, linestyle="--", label=f"{threshold:.0%} 阈值")
    ax.set_xlabel("总成本 / 元")
    ax.set_ylabel("导通概率")
    ax.set_title(str(_pick(doc, "title", default="成本—可靠性前沿")))
    ax.legend(frameon=False, loc="best", fontsize=8)
    clean_axes(ax)
    return _save(fig, out_stem)


# ---------------------------------------------------------------------------
# 模板：置信区间森林图（多配置/多验证的 CI 对比）
# ---------------------------------------------------------------------------
def _ci_forest(doc: dict[str, Any], out_stem: Path) -> dict[str, Any]:
    rows = _rows(_pick(doc, "rows", "items", "points", default=[]), "rows")
    if not rows:
        raise ValueError("ci_forest 需要 rows[]")
    threshold = float(_pick(doc, "threshold", "target", default=0.90))
    labels = [str(r.get("label", r.get("name", f"配置{i + 1}"))) for i, r in enumerate(rows)]
    est = np.array([float(r.get("estimate", r.get("p", r.get("prob_estimate", 0.0)))) for r in rows])
    lo = np.array([float(r.get("low", r.get("ci_lower", r.get("ci_lo", est[i])))) for i, r in enumerate(rows)])
    hi = np.array([float(r.get("high", r.get("ci_upper", r.get("ci_hi", est[i])))) for i, r in enumerate(rows)])

    fig, ax = plt.subplots(figsize=(6.6, max(3.2, 0.55 * len(rows))))
    ypos = np.arange(len(rows))[::-1]
    for _i, (yp, e, lo_v, hi_v) in enumerate(zip(ypos, est, lo, hi, strict=True)):
        ax.plot([lo_v, hi_v], [yp, yp], color=TEAL if lo_v >= threshold else GRAY, linewidth=2.2, marker="|", markersize=10, zorder=2)
        ax.scatter([e], [yp], color=BLUE, s=40, zorder=3)
    ax.axvline(threshold, color=GOLD, linewidth=1.6, linestyle="--", label=f"{threshold:.0%} 阈值")
    ax.set_yticks(ypos)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("点估计与 95% 置信区间")
    ax.set_title(str(_pick(doc, "title", default="多配置置信区间森林图")))
    ax.legend(frameon=False, loc="best", fontsize=8)
    clean_axes(ax)
    return _save(fig, out_stem)


# ---------------------------------------------------------------------------
# 模板：分组分布小提琴/箱线图（组间统计对比）
# ---------------------------------------------------------------------------
def _group_violin(doc: dict[str, Any], out_stem: Path) -> dict[str, Any]:
    rows = _rows(_pick(doc, "groups", "items", "rows", default=[]), "groups")
    if not rows:
        raise ValueError("group_violin 需要 groups[]")
    value_key = str(_pick(doc, "value_key", default="value"))
    group_key = str(_pick(doc, "group_key", default="group"))
    records = []
    for r in rows:
        g = str(r.get(group_key, "?"))
        v = r.get(value_key)
        if isinstance(v, list):
            records.extend({"group": g, "value": float(x)} for x in v if isinstance(x, (int, float)))
    if not records:
        # 回退：只有标量时画每组的点估计 + 区间
        return _ci_forest(
            {
                "title": str(_pick(doc, "title", default="分组统计")),
                "rows": [
                    {"label": str(r.get(group_key, "?")), "estimate": r.get("estimate", r.get("p", 0)),
                     "low": r.get("low", r.get("ci_lower", 0)), "high": r.get("high", r.get("ci_upper", 0))}
                    for r in rows
                ],
            },
            out_stem,
        )
    import pandas as pd
    df = pd.DataFrame(records)
    fig, ax = plt.subplots(figsize=(7.0, 4.6))
    sns.violinplot(data=df, x="group", y="value", ax=ax, palette="deep", cut=0, inner="box")
    sns.stripplot(data=df, x="group", y="value", ax=ax, color="black", size=3, alpha=0.5, jitter=0.15)
    ax.set_xlabel(str(_pick(doc, "x_label", default="分组")))
    ax.set_ylabel(str(_pick(doc, "y_label", default="取值")))
    ax.set_title(str(_pick(doc, "title", default="分组分布小提琴图")))
    clean_axes(ax)
    return _save(fig, out_stem)


# ---------------------------------------------------------------------------
# 模板：生存/达标曲线（区间删失 AFT 的分组达标概率，CI 带 + 阈值）
# ---------------------------------------------------------------------------
def _survival_curve(doc: dict[str, Any], out_stem: Path) -> dict[str, Any]:
    groups = _rows(_pick(doc, "groups", "by_group", "curves", default=[]), "groups")
    if not groups:
        raise ValueError("survival_curve 需要 groups[]")
    threshold = float(_pick(doc, "threshold", "target", default=0.90))
    x_label = str(_pick(doc, "x_label", default="孕周"))
    y_label = str(_pick(doc, "y_label", default="达标比例"))
    fig, ax = plt.subplots(figsize=(7.8, 4.8))
    for i, g in enumerate(groups):
        label = str(g.get("label", g.get("name", f"组{i + 1}")))
        pts = _rows(g.get("points", []), "points")
        if not pts:
            continue
        x = np.array([float(p.get("x", p.get("week", p.get("t", i)))) for i, p in enumerate(pts)])
        prob = np.array([float(p.get("probability", p.get("p", p.get("p_estimate", 0.0)))) for p in pts])
        low = np.array([float(p.get("ci_lower", p.get("low", p.get("ci_lo", prob[j])))) for j, p in enumerate(pts)])
        high = np.array([float(p.get("ci_upper", p.get("high", p.get("ci_hi", prob[j])))) for j, p in enumerate(pts)])
        color = [TEAL, BLUE, GOLD, CORAL, GRAY][i % 5]
        ax.fill_between(x, low, high, color=color, alpha=0.12)
        ax.plot(x, prob, color=color, linewidth=2.0, label=label)
    ax.axhline(threshold, color=GOLD, linewidth=1.6, linestyle="--", label=f"{threshold:.0%} 达标阈值")
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_title(str(_pick(doc, "title", default="各组达标比例曲线与推荐时点")))
    ax.legend(frameon=False, loc="best", fontsize=8)
    clean_axes(ax)
    return _save(fig, out_stem)


# ---------------------------------------------------------------------------
# 模板：SHAP 组合图（特征重要性条形 + 蜂群贡献度）
# ---------------------------------------------------------------------------
def _shap_combo(doc: dict[str, Any], out_stem: Path) -> dict[str, Any]:
    shap_matrix = _pick(doc, "shap_values", "shap", default=None)
    feature_names = [str(f) for f in _pick(doc, "feature_names", "features", default=[])]
    feature_values = _pick(doc, "feature_values", "X", default=None)
    if not isinstance(shap_matrix, list) or not feature_names:
        raise ValueError("shap_combo 需要 shap_values[[]] 与 feature_names[]")
    arr = np.asarray([[float(v) for v in row] for row in shap_matrix], dtype=float)
    n_feat = arr.shape[1]
    if len(feature_names) != n_feat:
        feature_names = [f"特征{i + 1}" for i in range(n_feat)]
    mean_abs = np.abs(arr).mean(axis=0)
    order = np.argsort(mean_abs)[::-1]
    fig, (ax_bar, ax_swarm) = plt.subplots(1, 2, figsize=(10.6, 4.8),
                                           gridspec_kw={"width_ratios": [1, 2.2]})
    ax_bar.barh(np.arange(n_feat), mean_abs[order], color=TEAL, edgecolor="white")
    ax_bar.set_yticks(np.arange(n_feat))
    ax_bar.set_yticklabels([feature_names[i] for i in order], fontsize=8)
    ax_bar.invert_yaxis()
    ax_bar.set_xlabel("平均 |SHAP|")
    ax_bar.set_title("特征重要性")
    # 蜂群：行内按特征值着色（feature_values 提供颜色），x 为 SHAP 贡献
    colors = None
    if isinstance(feature_values, list) and len(feature_values) == arr.shape[0]:
        fv = np.asarray([[float(v) for v in row] for row in feature_values], dtype=float)
        colors = fv
    for rank, fi in enumerate(order):
        xvals = arr[:, fi]
        yvals = np.full(xvals.size, n_feat - rank) + np.random.default_rng(fi).uniform(-0.28, 0.28, xvals.size)
        if colors is not None:
            c = colors[:, fi]
            sc = ax_swarm.scatter(xvals, yvals, c=c, cmap="viridis", s=7, alpha=0.55, edgecolor="none")
        else:
            ax_swarm.scatter(xvals, yvals, color=TEAL, s=7, alpha=0.5, edgecolor="none")
    ax_swarm.axvline(0, color=GRAY, linewidth=1.2, linestyle="--")
    ax_swarm.set_yticks(np.arange(n_feat))
    ax_swarm.set_yticklabels([feature_names[i] for i in order], fontsize=8)
    ax_swarm.invert_yaxis()
    ax_swarm.set_xlabel("SHAP 值（贡献方向）")
    ax_swarm.set_title("蜂群贡献度")
    if colors is not None:
        fig.colorbar(sc, ax=ax_swarm, fraction=0.04, label="特征值")
    fig.suptitle(str(_pick(doc, "title", default="SHAP 特征贡献")), y=1.0, fontsize=12)
    clean_axes(ax_bar)
    clean_axes(ax_swarm)
    return _save(fig, out_stem)


# ---------------------------------------------------------------------------
# 模板：相关矩阵热力图（EDA）
# ---------------------------------------------------------------------------
def _correlation_heatmap(doc: dict[str, Any], out_stem: Path) -> dict[str, Any]:
    matrix = _pick(doc, "matrix", "corr", "correlation", default=None)
    labels = [str(f) for f in _pick(doc, "labels", "feature_names", "columns", default=[])]
    if not isinstance(matrix, list) or not matrix:
        raise ValueError("correlation_heatmap 需要 matrix[[]]")
    data = np.asarray([[float(v) for v in row] for row in matrix], dtype=float)
    n = data.shape[0]
    if len(labels) != n:
        labels = [f"变量{i + 1}" for i in range(n)]
    fig, ax = plt.subplots(figsize=(max(5.6, 0.42 * n), max(4.6, 0.38 * n)))
    sns.heatmap(data, annot=True, fmt=".2f", cmap="RdBu_r", center=0,
                xticklabels=labels, yticklabels=labels, ax=ax,
                cbar_kws={"shrink": 0.8}, square=True)
    ax.set_title(str(_pick(doc, "title", default="关键变量相关矩阵")))
    ax.tick_params(axis="x", rotation=45, labelsize=8)
    ax.tick_params(axis="y", rotation=0, labelsize=8)
    return _save(fig, out_stem)


# ---------------------------------------------------------------------------
# 模板：配对雨云图（半小提琴 + 箱线 + 抖动点）
# ---------------------------------------------------------------------------
def _paired_raincloud(doc: dict[str, Any], out_stem: Path) -> dict[str, Any]:
    groups = _rows(_pick(doc, "groups", "items", "rows", default=[]), "groups")
    if not groups:
        raise ValueError("paired_raincloud 需要 groups[]")
    records = []
    for i, g in enumerate(groups):
        label = str(g.get("label", g.get("name", f"组{i + 1}")))
        vals = g.get("values", g.get("data", []))
        if isinstance(vals, list):
            records.extend(
                {"group": label, "value": float(v)}
                for v in vals
                if isinstance(v, (int, float))
            )
    if not any(r["value"] for r in records):
        raise ValueError("paired_raincloud 需要每组的 values[]")
    import pandas as pd
    df = pd.DataFrame(records)
    fig, ax = plt.subplots(figsize=(7.6, 4.8))
    # 半小提琴 + 箱线 + 抖动点
    violin_parts = ax.violinplot(
        [df[df["group"] == g]["value"].to_numpy() for g in df["group"].unique()],
        positions=np.arange(len(df["group"].unique())), showmedians=False, showextrema=False,
    )
    for part, color in zip(violin_parts["bodies"], [TEAL, BLUE, GOLD, CORAL, GRAY], strict=False):
        part.set_facecolor(color)
        part.set_alpha(0.35)
        part.set_edgecolor(color)
        part.set_linewidth(1.0)
    order = list(df["group"].unique())
    sns.boxplot(data=df, x="group", y="value", order=order, ax=ax, width=0.16,
                boxprops=dict(facecolor="white", edgecolor="black", linewidth=1.0),
                whiskerprops=dict(color="black"), capprops=dict(color="black"),
                medianprops=dict(color="black", linewidth=1.4))
    sns.stripplot(data=df, x="group", y="value", order=order, ax=ax, color="black",
                  size=2.6, alpha=0.55, jitter=0.18)
    ax.set_xlabel(str(_pick(doc, "x_label", default="分组")))
    ax.set_ylabel(str(_pick(doc, "y_label", default="取值")))
    ax.set_title(str(_pick(doc, "title", default="分组分布雨云图")))
    clean_axes(ax)
    return _save(fig, out_stem)


# ---------------------------------------------------------------------------
# 模板：CV-ROC 曲线（置信带 + 操作点 + 随机基线）
# ---------------------------------------------------------------------------
def _cv_roc_ci(doc: dict[str, Any], out_stem: Path) -> dict[str, Any]:
    fpr = _pick(doc, "fpr", "fpr_mean", default=None)
    tpr = _pick(doc, "tpr", "tpr_mean", default=None)
    if not isinstance(fpr, list) or not isinstance(tpr, list) or len(fpr) != len(tpr):
        raise ValueError("cv_roc_ci 需要 fpr[] 与 tpr[] 等长")
    fpr = np.asarray([float(v) for v in fpr])
    tpr = np.asarray([float(v) for v in tpr])
    auc = float(_pick(doc, "auc", default=0.0))
    fig, ax = plt.subplots(figsize=(6.4, 5.2))
    lo = _pick(doc, "ci_lower", "tpr_low", default=None)
    hi = _pick(doc, "ci_upper", "tpr_high", default=None)
    if isinstance(lo, list) and isinstance(hi, list) and len(lo) == len(tpr):
        ax.fill_between(fpr, [float(v) for v in lo], [float(v) for v in hi],
                        color=TEAL, alpha=0.15, label="95% 置信带")
    ax.plot(fpr, tpr, color=TEAL, linewidth=2.2, label=f"AUC = {auc:.3f}")
    ax.plot([0, 1], [0, 1], color=GRAY, linewidth=1.2, linestyle="--", label="随机基线")
    op = _pick(doc, "operating_point", "operating", default=None)
    if isinstance(op, dict):
        op_fpr = float(op.get("fpr", op.get("x", 0.0)))
        op_tpr = float(op.get("tpr", op.get("sensitivity", op.get("y", 0.0))))
        ax.scatter([op_fpr], [op_tpr], marker="*", s=300, color=GOLD, edgecolor="black",
                   linewidth=0.7, zorder=5, label="操作点（特异性约束）")
    ax.set_xlabel("假阳性率（1 - 特异性）")
    ax.set_ylabel("真阳性率（敏感性）")
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)
    ax.set_title(str(_pick(doc, "title", default="分类器 ROC 曲线")))
    ax.legend(frameon=False, loc="lower right", fontsize=8)
    clean_axes(ax)
    return _save(fig, out_stem)


_TEMPLATES = {
    "probability_curve": _probability_curve,
    "feasible_region": _feasible_region,
    "pareto_frontier": _pareto_frontier,
    "ci_forest": _ci_forest,
    "group_violin": _group_violin,
    "survival_curve": _survival_curve,
    "shap_combo": _shap_combo,
    "correlation_heatmap": _correlation_heatmap,
    "paired_raincloud": _paired_raincloud,
    "cv_roc_ci": _cv_roc_ci,
}


def _save(fig, out_stem: Path) -> dict[str, Any]:
    """保存 PNG/PDF/SVG 并返回输出记录。"""
    out_stem.parent.mkdir(parents=True, exist_ok=True)
    outputs = []
    for suffix in (".png", ".pdf", ".svg"):
        path = out_stem.with_suffix(suffix)
        fig.savefig(path, bbox_inches="tight")
        outputs.append({"path": str(path), "kind": suffix.lstrip(".")})
    plt.close(fig)
    return {"outputs": outputs}


def main() -> int:
    parser = argparse.ArgumentParser(description="竞赛高级图渲染")
    parser.add_argument("--template", help="模板 id，--list 查看")
    parser.add_argument("--input", help="production 结果 JSON")
    parser.add_argument("--output", help="输出 stem（不含扩展名）")
    parser.add_argument("--list", action="store_true", help="列出模板")
    args = parser.parse_args()
    if args.list:
        for name in _TEMPLATES:
            print(name)
        return 0
    if args.template is None or args.template not in _TEMPLATES:
        print(f"未知模板: {args.template}；可用: {', '.join(_TEMPLATES)}", file=sys.stderr)
        return 2
    document = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = _TEMPLATES[args.template](document, Path(args.output))
    for item in result["outputs"]:
        print(item["path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
