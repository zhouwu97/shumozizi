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


_TEMPLATES = {
    "probability_curve": _probability_curve,
    "feasible_region": _feasible_region,
    "pareto_frontier": _pareto_frontier,
    "ci_forest": _ci_forest,
    "group_violin": _group_violin,
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
    parser.add_argument("--template", required=True, help="模板 id，--list 查看")
    parser.add_argument("--input", required=True, help="production 结果 JSON")
    parser.add_argument("--output", required=True, help="输出 stem（不含扩展名）")
    parser.add_argument("--list", action="store_true", help="列出模板")
    args = parser.parse_args()
    if args.list:
        for name in _TEMPLATES:
            print(name)
        return 0
    if args.template not in _TEMPLATES:
        print(f"未知模板: {args.template}；可用: {', '.join(_TEMPLATES)}", file=sys.stderr)
        return 2
    document = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = _TEMPLATES[args.template](document, Path(args.output))
    for item in result["outputs"]:
        print(item["path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
