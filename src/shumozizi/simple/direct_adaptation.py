"""sci-box 母版模板的“直接适配”渲染：复制原始模板脚本，只替换数据入口。

本模块实现 scibox-figure 的核心约定——**使用模板 = 复制原脚本 → 只换数据入口 →
尽量保留原绘图结构**，禁止默认重新实现。做法：

1. 把 ``skills/sci-box/scibox-figure/scripts/templates/make_<id>.py``（上游 jihe520/sci-box
   的原样副本；legacy 的 ``mathmodel-figure-templates`` 为同源兜底）原样复制到
   运行目录 ``code/figures/adapted_<id>.py``；
2. 生成 ``_real_data_<id>.py`` shim，把原脚本里的 ``simulate_*()`` 函数或模块级数据
   常量替换为真实结果 JSON 的转换结果；
3. 在**进程内**导入复制后的母版脚本，并在调用 ``make_figure()`` **之前**执行
   ``apply_real_data(globals())``——数据入口替换必然先于绘图，不存在“先画模拟数据、
   后注入真实数据”的顺序问题；
4. 其余绘图结构（``draw_*``、``fig.add_axes``、``fig.legend``、字号、轴线、面板几何）全部保留；
5. 渲染后从 Figure 机器提取 ``text-boxes.json``、``visual_manifest.json`` 与
   ``layout_report.json``（论文尺寸、字号、坐标范围、图例遮挡），供 work→promotion 闭环使用。

只有模板自动 shim 未覆盖、或需要拆/并/删面板时才使用 manual 模式（复制原脚本 +
写入标记好的数据入口 stub，由 Agent 手工完成替换），或 reimplemented 回退（本仓 v3
渲染器，是模板的简化重绘，只能作为最后一档 fallback）。
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.simple.figure_templates import (
    _figure_text_artists,
    _text_boxes,
    _write_visual_manifest,
    write_plot_layout_report,
)

# 模板 id -> 母版脚本文件名。只收录“直接复制 + 换数据入口”即可成立的模板；
# 其余模板走 manual-copy（复制原脚本由 Agent 手工换数据），默认不回退简化 reimplemented。
_SCRIPT_NAMES: dict[str, str] = {
    "correlation-pairgrid": "make_correlation_pairgrid.py",
    "grouped-circular-heatmap": "make_grouped_circular_heatmap.py",
    "grouped-corr-split-violin": "make_grouped_corr_split_violin.py",
    "nature-chord-diagram": "make_nature_chord_diagram.py",
    "rf-tpe-surface": "make_rf_tpe_surface.py",
    "taylor-diagram": "make_taylor_diagram.py",
}

DIRECT_ADAPTATION_READY = frozenset(_SCRIPT_NAMES)

_OUTPUT_STEM_RE = re.compile(r'make_figure\(\s*ROOT\s*/\s*"outputs"\s*/\s*"([^"]+)"\s*\)')


def _shim_safe(template_id: str) -> str:
    """把模板 id 转成合法的 Python 模块名（短横线 -> 下划线）。"""
    return f"_real_data_{template_id.replace('-', '_')}"


def _module_safe(template_id: str) -> str:
    """把模板 id 转成复制脚本的模块名。"""
    return f"shumozizi_adapted_{template_id.replace('-', '_')}"


def _shim_source(template_id: str) -> str:
    """生成 ``_real_data_<id>.py`` 的源码（真实数据入口转换，不重写绘图）。"""
    if template_id == "grouped-corr-split-violin":
        return _SHIM_GROUPED_CORR_SPLIT_VIOLIN
    if template_id == "correlation-pairgrid":
        return _SHIM_CORRELATION_PAIRGRID
    if template_id == "rf-tpe-surface":
        return _SHIM_RF_TPE_SURFACE
    if template_id == "grouped-circular-heatmap":
        return _SHIM_GROUPED_CIRCULAR_HEATMAP
    if template_id == "taylor-diagram":
        return _SHIM_TAYLOR_DIAGRAM
    if template_id == "nature-chord-diagram":
        return _SHIM_NATURE_CHORD_DIAGRAM
    raise ContractError(f"{template_id} 没有自动 direct 适配 shim")


# ---------------------------------------------------------------------------
# 各模板 shim：只做“真实 figure_data -> 原 simulate_* 返回形状”的转换。
# 数据由引擎在导入后写入 shim 模块的 _DATA，保证复制脚本可搬移、可重渲染。
# ---------------------------------------------------------------------------

_SHIM_HEADER = """\
# 本文件由 shumozizi direct adaptation 生成：只负责把真实结果 JSON 转成
# 原模板 simulate_* 函数的返回形状，绘图结构全部保留在原模板脚本中。
from shumozizi.core.io import ContractError

import numpy as np

_DATA = {}


def load_real_data(*args, **kwargs):
    raise SystemExit("load_real_data 应在导入后被引擎注入")
"""

_SHIM_GROUPED_CORR_SPLIT_VIOLIN = _SHIM_HEADER + """


def _real_data(*args, **kwargs):
    groups = _DATA["groups"]
    train = np.asarray(groups[0]["values"], dtype=float)
    test = np.asarray(groups[1]["values"], dtype=float)
    return train, test


def apply_real_data(g):
    expected = len(g["FEATURES"])
    features = _DATA.get("features") or [item.name for item in g["FEATURES"]]
    if len(features) != expected:
        raise ContractError(
            "grouped-corr-split-violin direct adaptation: 本题特征数 %d != 模板特征数 %d；"
            "请用 --adaptation manual 手工调整小提琴网格与分组括号位置"
            % (len(features), expected)
        )
    g["FEATURES"] = [g["FeatureSpec"](name=name, label=name) for name in features]
    g["simulate_feature_data"] = _real_data
"""

_SHIM_CORRELATION_PAIRGRID = _SHIM_HEADER + """


def _real_data(*args, **kwargs):
    return np.asarray(_DATA["values"], dtype=float)


def apply_real_data(g):
    columns = _DATA.get("columns")
    if columns:
        g["VARIABLES"] = [str(item) for item in columns]
    g["simulate_data"] = _real_data
"""

_SHIM_RF_TPE_SURFACE = _SHIM_HEADER + """


def _real_data(*args, **kwargs):
    trials = _DATA["trials"]
    return (
        np.asarray([item["x"] for item in trials], dtype=float),
        np.asarray([item["y"] for item in trials], dtype=float),
        np.asarray([item["metric"] for item in trials], dtype=float),
    )


def apply_real_data(g):
    g["simulate_tpe_trials"] = _real_data
"""

_SHIM_GROUPED_CIRCULAR_HEATMAP = _SHIM_HEADER + """

_TRAIT_COLORS = [
    "#51448a", "#606766", "#4e9568", "#bd454c",
    "#7b54b9", "#3d719b", "#e58a50", "#5d6a67",
]


def _real_data(*args, **kwargs):
    rings = _DATA["rings"]
    return np.asarray([ring["values"] for ring in rings], dtype=float)


def apply_real_data(g):
    items = _DATA["items"]
    rings = _DATA["rings"]
    g["TRAITS_OUTER_TO_INNER"] = [
        g["TraitSpec"](name=str(ring["name"]), color=_TRAIT_COLORS[i % len(_TRAIT_COLORS)], pale="#f0f0f0")
        for i, ring in enumerate(rings)
    ]
    g["PAIR_GROUPS"] = [
        g["PairGroup"](label=str(item), color="#c9d8e8", count=1) for item in items
    ]
    g["simulate_heatmap_values"] = _real_data
"""

_SHIM_TAYLOR_DIAGRAM = _SHIM_HEADER + """


def _neutral_header(fig):
    # 移除来源论文的题注/引用文字；正文 caption 由论文阶段提供。
    return None


def apply_real_data(g):
    panels = _DATA["panels"]
    reference_std = float(_DATA.get("reference_std") or 1.0)
    if reference_std <= 0:
        raise ContractError("taylor-diagram direct adaptation: reference_std 必须为正数")
    if len(panels) != 3:
        raise ContractError(
            "taylor-diagram direct adaptation: 需要恰好 3 个面板"
            "（模板 training/testing/full dataset 三个槽位）"
        )
    rebuilt = {}
    names: list[str] = []
    for key, panel in zip(("training", "testing", "full dataset"), panels, strict=True):
        points = panel["points"]
        # 用 reference_std 归一化标准差，母版 Observed 固定在 (1.0, 1.0) 不变。
        rebuilt[key] = [
            g["TaylorPoint"](
                model=str(point["name"]),
                std=float(point["std"]) / reference_std,
                corr=float(point["corr"]),
            )
            for point in points
        ]
        for point in points:
            if str(point["name"]) not in names:
                names.append(str(point["name"]))
    # 每个面板必须包含全部模型，否则原 draw_panel 的 next(...) 会 StopIteration。
    for key, points in rebuilt.items():
        have = {point.model for point in points}
        missing = set(names) - have
        if missing:
            raise ContractError(
                "taylor-diagram direct adaptation: 面板 %s 缺少模型 %s"
                % (key, "、".join(sorted(missing)))
            )
    g["PANELS"] = rebuilt
    colors = ["#f2a51a", "#d7191c", "#2222a0", "#36a852", "#0b6b20", "#7a4fbf", "#e377c2", "#17becf"]
    models = [(name, colors[i % len(colors)]) for i, name in enumerate(names)]
    if "Observed" not in names:
        models.append(("Observed", "#000000"))
    g["MODELS"] = models
    g["add_header_and_caption"] = _neutral_header
"""

_SHIM_NATURE_CHORD_DIAGRAM = _SHIM_HEADER + """

_PALETTE = [
    "#2f7fa7", "#b4162d", "#3f9d54", "#e58a50",
    "#7b54b9", "#6b248b", "#d3ba73", "#49a65a",
]


def apply_real_data(g):
    nodes_data = _DATA["nodes"]
    links = _DATA["links"]
    group_color: dict[str, str] = {}
    for node in nodes_data:
        group = str(node["group"])
        if group not in group_color:
            group_color[group] = _PALETTE[len(group_color) % len(_PALETTE)]
    label_of_id = {str(node["id"]): str(node["label"]) for node in nodes_data}
    degree: dict[str, float] = {}
    for link in links:
        degree[str(link["source"])] = degree.get(str(link["source"]), 0.0) + float(link["weight"])
        degree[str(link["target"])] = degree.get(str(link["target"]), 0.0) + float(link["weight"])
    weight_max = max(degree.values()) if degree else 1.0
    nodes = [
        g["NodeSpec"](
            label=str(node["label"]),
            color=group_color[str(node["group"])],
            weight=max(0.4, 1.0 + 3.0 * degree.get(str(node["id"]), 0.0) / max(weight_max, 1e-9)),
        )
        for node in nodes_data
    ]
    g["NODES"] = nodes

    def real_flows(nodes_list):
        return [
            (label_of_id[str(link["source"])], label_of_id[str(link["target"])], float(link["weight"]))
            for link in links
        ]

    g["build_flows"] = real_flows
"""


def _master_script_path(template_id: str) -> Path:
    """返回母版模板脚本的仓库路径。

    优先 sci-box 母版库（``skills/sci-box/scibox-figure/scripts/templates/``，即上游
    jihe520/sci-box 的原样副本）；本地 legacy 的 ``skills/mathmodel-figure-templates``
    保留同源脚本作为兜底（含 sci-box 未收录的 4 个本地扩展模板）。
    """
    repo_root = resolve_repo_root(Path(__file__))
    candidates = [
        repo_root / "skills" / "sci-box" / "scibox-figure" / "scripts" / "templates" / _SCRIPT_NAMES[template_id],
        repo_root / "skills" / "mathmodel-figure-templates" / "scripts" / "templates" / _SCRIPT_NAMES[template_id],
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def _patch_output_stem(text: str, output_stem: Path) -> str:
    """把原脚本 main() 里的输出 stem 替换为本次运行的真实目标路径。"""
    match = _OUTPUT_STEM_RE.search(text)
    if match is None:
        raise ContractError("母版脚本缺少可识别的 make_figure 输出语句，无法自动改输出路径")
    replacement = f"make_figure(Path({json.dumps(str(output_stem))}))"
    # 用函数式替换避免 re.sub 对 replacement 里的反斜杠做转义解释。
    return _OUTPUT_STEM_RE.sub(lambda _m: replacement, text, count=1)


def _apply_text_patches(text: str, template_id: str, data: dict[str, Any]) -> str:
    """替换来源论文残留文字与本题标签（只改字符串，不重写绘图函数）。"""
    if template_id == "rf-tpe-surface":
        x_label = str(data.get("x_label") or "X")
        y_label = str(data.get("y_label") or "Y")
        metric_label = str(data.get("metric_label") or "Metric")
        title = str(data.get("title") or f"{metric_label} response surface")
        text = text.replace('"Smooth 3D Surface Plot with RMSE"', json.dumps(title))
        text = text.replace('ax.set_xlabel("max_depth"', f'ax.set_xlabel({json.dumps(x_label)}')
        text = text.replace('ax.set_ylabel("n_estimators"', f'ax.set_ylabel({json.dumps(y_label)}')
        text = text.replace('ax.set_zlabel("RMSE"', f'ax.set_zlabel({json.dumps(metric_label)}')
        text = text.replace('cbar.set_label("RMSE"', f'cbar.set_label({json.dumps(metric_label)}')
        return text
    if template_id == "nature-chord-diagram":
        title = str(data.get("title") or "Chord Diagram")
        text = text.replace('"Circos Graph"', json.dumps(title))
        return text
    if template_id == "taylor-diagram":
        reference_std = float(data.get("reference_std") or 1.0)
        if reference_std != 1.0:
            text = text.replace(
                '"Standard Deviation"', '"Normalized Standard Deviation"'
            )
        return text
    return text


def _write_data_json(template_id: str, data: dict[str, Any], target_dir: Path) -> Path:
    """把规范化后的真实 figure_data 物化为 JSON，供复制脚本的 shim 读取。"""
    path = target_dir / f"figure_data_{template_id.replace('-', '_')}.json"
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def _import_module(module_name: str, path: Path) -> Any:
    """在进程内导入一个 Python 文件作为模块。"""
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ContractError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _render_in_process(
    template_id: str,
    data: dict[str, Any],
    output_stem: Path,
    target_dir: Path,
    data_path: Path,
    shim_path: Path,
    adapted_path: Path,
) -> Any:
    """进程内导入母版脚本：先注入真实数据，再调用 make_figure，返回渲染后的 Figure。"""
    try:
        # 先强制 Agg 并绑定 canvas 类，避免宿主默认后端（如 tkagg）污染母版脚本
        # 导入后创建的 Figure（否则 canvas 退化 FigureCanvasBase，无法做文字边界
        # 与布局提取）。
        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as _plt

        _plt.figure(figsize=(1, 1))
        _plt.close("all")

        shim_module = _import_module(_shim_safe(template_id), shim_path)
        shim_module._DATA = data
        module = _import_module(_module_safe(template_id), adapted_path)
        # 数据入口替换必须先于 make_figure（P0-1：不能先画模拟数据再注入）。
        shim_module.apply_real_data(module.__dict__)
        pyplot = module.plt
        real_close = pyplot.close
        captured: dict[str, Any] = {}

        def _capturing_close(fig: Any = None) -> Any:
            if fig is not None:
                captured["figure"] = fig
            return real_close(fig)

        pyplot.close = _capturing_close
        try:
            module.make_figure(Path(str(output_stem)))
        finally:
            pyplot.close = real_close
        figure = captured.get("figure") or pyplot.gcf()
        if figure is None:
            raise ContractError("direct adaptation 未能捕获渲染后的 Figure")
        return figure
    except ContractError:
        raise
    except Exception as exc:  # noqa: BLE001 - 转成协议异常，保留母版脚本的真实错误信息
        raise ContractError(f"direct adaptation 渲染失败 ({template_id}): {exc}") from exc


def _write_figure_artifacts(
    figure: Any,
    template_id: str,
    output_stem: Path,
    figure_id: str,
    run_dir: Path,
    adapted_path: Path,
    shim_path: Path,
) -> dict[str, str]:
    """从 Figure 机器提取 text-boxes、visual_manifest、layout_report。"""
    root = run_dir.resolve()
    # 母版脚本可能在宿主默认后端下创建 Figure，canvas 退化为 FigureCanvasBase，
    # 无法做文字边界/布局提取；这里显式挂上 Agg canvas 保证可渲染可测量。
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    if not isinstance(figure.canvas, FigureCanvasAgg):
        FigureCanvasAgg(figure)
    figure._shumozizi_panels = ["main"]
    elements: list[dict[str, str]] = []
    seen: set[str] = set()
    for artist in _figure_text_artists(figure):
        label = artist.get_text().strip()
        if label in seen:
            continue
        seen.add(label)
        elements.append({"type": "text", "label": label, "panel": "main"})
    if not elements:
        elements = [{"type": "figure", "label": template_id, "panel": "main"}]
    figure._shumozizi_elements = elements
    boxes_path = output_stem.with_suffix(".text-boxes.json")
    boxes_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "boxes": _text_boxes(figure),
                "adapted_script": adapted_path.relative_to(root).as_posix(),
                "data_shim": shim_path.relative_to(root).as_posix(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    manifest_path = _write_visual_manifest(figure, output_stem)
    layout_path = write_plot_layout_report(figure, output_stem, figure_id)
    return {
        "text_boxes": boxes_path.relative_to(root).as_posix(),
        "visual_manifest": manifest_path.relative_to(root).as_posix(),
        "layout_report": layout_path.relative_to(root).as_posix(),
    }


def adapt_and_render(
    template_id: str,
    data: dict[str, Any],
    output_stem: Path,
    run_dir: Path,
    figure_id: str | None = None,
) -> dict[str, Any]:
    """直接适配渲染：复制原模板脚本 -> 注入真实数据 shim -> 原样调用 make_figure。

    Args:
        template_id: 母版模板 ID。
        data: :func:`shumozizi.simple.figure_templates.load_data` 返回的真实数据。
        output_stem: 不含扩展名的绝对输出路径（对应 ``figures/work/<id>/<version>/...``）。
        run_dir: v3 运行目录。
        figure_id: 布局报告使用的图表 ID；缺省用输出前缀文件名。

    Returns:
        输出相对路径、text-boxes、visual_manifest、layout_report 与复制脚本的路径字典。

    Raises:
        ContractError: 模板不支持直接适配、脚本缺失或渲染失败。
    """
    if template_id not in DIRECT_ADAPTATION_READY:
        raise ContractError(
            f"{template_id} 尚无自动 direct 适配 shim；可用: "
            + ", ".join(sorted(DIRECT_ADAPTATION_READY))
            + "。其余模板请用 --adaptation manual（复制原脚本手工换数据入口），"
            "默认不会自动回退到简化 reimplemented 渲染器"
        )
    root = run_dir.resolve()
    output_stem = output_stem.resolve()
    target_dir = root / "code" / "figures"
    target_dir.mkdir(parents=True, exist_ok=True)

    source = _master_script_path(template_id)
    if not source.is_file():
        raise ContractError(f"母版模板脚本不存在: {source}")

    data_path = _write_data_json(template_id, data, target_dir)
    shim_path = target_dir / f"{_shim_safe(template_id)}.py"
    shim_path.write_text(_shim_source(template_id), encoding="utf-8", newline="\n")

    text = source.read_text(encoding="utf-8")
    text = _patch_output_stem(text, output_stem)
    text = _apply_text_patches(text, template_id, data)
    adapted_path = target_dir / f"adapted_{template_id}.py"
    adapted_path.write_text(text, encoding="utf-8", newline="\n")

    figure = _render_in_process(
        template_id, data, output_stem, target_dir, data_path, shim_path, adapted_path
    )

    relative = output_stem.relative_to(root).as_posix()
    outputs = [f"{relative}{suffix}" for suffix in (".png", ".pdf", ".svg")]
    for item in outputs:
        path = root / item
        if not path.is_file() or path.stat().st_size == 0:
            raise ContractError(f"direct adaptation 未产出有效输出: {item}")

    artifacts = _write_figure_artifacts(
        figure,
        template_id,
        output_stem,
        figure_id or output_stem.name,
        root,
        adapted_path,
        shim_path,
    )
    return {
        "outputs": outputs,
        "adapted_script": adapted_path.relative_to(root).as_posix(),
        "data_shim": shim_path.relative_to(root).as_posix(),
        **artifacts,
    }


def prepare_manual_adaptation(
    template_id: str,
    data: dict[str, Any],
    output_stem: Path,
    run_dir: Path,
) -> dict[str, Any]:
    """manual 模式：复制原模板脚本并写入标记好的数据入口 stub，不运行、不登记。

    由 Agent 在复制后的脚本里完成“模拟数据 -> 真实 loader”的替换（可拆/并/删面板），
    运行后通过正常的候选流程进入 ``figures/``。

    Args:
        template_id: 模板 ID（不要求有自动 shim）。
        data: 真实 figure_data。
        output_stem: 目标输出前缀（绝对路径）。
        run_dir: v3 运行目录。

    Returns:
        指引信息字典（含复制后的脚本路径、数据 JSON 路径和后续步骤）。
    """
    root = run_dir.resolve()
    output_stem = output_stem.resolve()
    repo_root = resolve_repo_root(Path(__file__))
    script_name = f"make_{template_id.replace('-', '_')}.py"
    source = next(
        (
            candidate
            for candidate in (
                repo_root / "skills" / "sci-box" / "scibox-figure" / "scripts" / "templates" / script_name,
                repo_root
                / "skills"
                / "mathmodel-figure-templates"
                / "scripts"
                / "templates"
                / script_name,
            )
            if candidate.is_file()
        ),
        None,
    )
    if source is None:
        raise ContractError(f"母版模板脚本不存在（manual 模式需要原脚本）: {script_name}")
    target_dir = root / "code" / "figures"
    target_dir.mkdir(parents=True, exist_ok=True)
    data_path = _write_data_json(template_id, data, target_dir)
    adapted_path = target_dir / f"adapted_{template_id}.py"
    text = source.read_text(encoding="utf-8")
    # manual 同样改写输出路径与来源论文残留文字，避免运行后写到模板默认 outputs/。
    text = _patch_output_stem(text, output_stem)
    text = _apply_text_patches(text, template_id, data)
    # 在数据入口行前插入标记，Agent 在此完成替换。
    text = text.replace(
        "def make_figure(output_stem: Path) -> None:",
        "def make_figure(output_stem: Path) -> None:\n"
        "    # TODO(manual adaptation): 用真实数据替换模拟数据入口。\n"
        f"    # 真实数据 JSON: {data_path.relative_to(root).as_posix()}\n"
        "    # 例：train, test = load_current_result()  # 实现真实 loader，保留后续 draw_* 调用",
        1,
    )
    adapted_path.write_text(text, encoding="utf-8", newline="\n")
    return {
        "mode": "manual",
        "adapted_script": adapted_path.relative_to(root).as_posix(),
        "figure_data": data_path.relative_to(root).as_posix(),
        "output_prefix": output_stem.relative_to(root).as_posix(),
        "instructions": (
            f"编辑 {adapted_path.relative_to(root).as_posix()}：把 simulate_* 数据入口换成真实 loader"
            f"（读 {data_path.relative_to(root).as_posix()}），允许拆/并/删面板；"
            f"输出路径已改写为 {output_stem.relative_to(root).as_posix()}.{{png,pdf,svg}}，"
            "运行后走候选与晋级流程。"
        ),
    }
