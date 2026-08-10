"""模型原生正式 renderer 组件库（ADVANCED_VISUAL_PAPER_WORKFLOW_PLAN 10.1）。

每个 renderer 从运行目录 ``results/raw`` 的结构化 JSON 读取数据并输出 PNG/PDF，
不重复底层样式与 QA 逻辑。颜色只作一层编码，同时使用线型、标记或区域边界，
保证灰度打印可辨（10.2）。3D 图必须附带 2D 剖面、投影或局部放大帮助精确读取
（10.3）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch, Rectangle

# 10.2 统一风格：安静、竞赛论文风格的多色系统。
INK = "#17212B"
TEAL = "#147D80"      # 正式答案：深青
GREEN = "#2E7D32"     # 正式答案备用：深绿
CORAL = "#D95D4F"     # 不可行/失败：暖红
GOLD = "#D6A420"      # 阈值与活跃边界：金色虚线
BLUE = "#3E6FB0"      # 网络骨架等高对比对象
GRAY = "#7A8793"      # 敏感性/域外：灰色
LIGHT = "#E7ECEF"     # 背景网络边等浅色元素
PALE_GOLD = "#F5E3B3" # 阈值带浅色

MIN_FONT_PT = 8.0
DPI = 260

_FONT_CANDIDATES = ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Arial")

RENDERER_REGISTRY: dict[str, str] = {
    "periodic_spatial_scene": "周期空间场景（3D 周期单元 + 正交剖面）",
    "spatial_scene_cross_section": "空间场景与正交剖面",
    "spatial_contact_backbone_triptych": "空间结构 + 接触网络 + 导电骨架三联图",
    "contact_network_backbone": "接触网络与导电骨架",
    "oracle_comparison_zoom": "几何 oracle 端部对比与伪边删除",
    "probability_threshold_curve": "概率转变曲线 + Wilson 区间 + 阈值带",
    "uncertainty_margin_ribbon": "区间下限裕量带",
    "integer_feasible_region": "整数格点可行域 + 成本等高线 + 活跃边界",
    "cost_reliability_frontier": "成本—可靠性分层前沿",
    "convergence_envelope": "多种子收敛包络",
    "implementation_agreement": "实现一致性对照",
    "shared_model_pipeline": "共享模型管线示意",
}


def _font_setup() -> None:
    """配置适合 Windows 中文论文的确定性字体与线宽。

    源字号按正文 0.85--0.98 页宽缩放后仍不低于 8 pt（100% A4），因此源字号
    取 10--13 pt，而不是 8--9 pt。
    """
    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": _FONT_CANDIDATES,
            "axes.unicode_minus": False,
            "font.size": 11,
            "axes.labelsize": 12,
            "axes.titlesize": 13,
            "xtick.labelsize": 10.5,
            "ytick.labelsize": 10.5,
            "legend.fontsize": 10.5,
            "axes.linewidth": 0.9,
            "savefig.facecolor": "white",
            "pdf.fonttype": 42,
        }
    )


_font_setup()


def _clean(ax: plt.Axes) -> None:
    """统一坐标轴视觉层级。"""
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color=LIGHT, linewidth=0.7, zorder=0)
    ax.tick_params(length=3, color=GRAY)


def _sha256(path: Path) -> str:
    """计算输出文件哈希，供来源绑定与 QA 使用。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _save(fig: plt.Figure, stem: Path) -> dict[str, Any]:
    """保存 PNG 与 PDF，并返回输出记录。"""
    stem.parent.mkdir(parents=True, exist_ok=True)
    png = stem.with_suffix(".png")
    pdf = stem.with_suffix(".pdf")
    fig.savefig(png, dpi=DPI, bbox_inches="tight")
    fig.savefig(pdf, bbox_inches="tight")
    plt.close(fig)
    return {
        "outputs": [
            {"path": str(png), "sha256": _sha256(png), "kind": "png"},
            {"path": str(pdf), "sha256": _sha256(pdf), "kind": "pdf"},
        ],
        "minimum_font_size_pt": MIN_FONT_PT,
    }


def _array(value: Any, name: str) -> np.ndarray:
    """把 JSON 列表转成确定 dtype 的数组。"""
    array = np.asarray(value, dtype=float)
    if array.ndim == 0:
        raise ValueError(f"{name} 必须是数值列表")
    return array


def _rows(value: Any, name: str) -> list[dict[str, Any]]:
    """把 JSON 列表规范为对象行列表。"""
    if not isinstance(value, list):
        raise ValueError(f"{name} 必须是列表")
    return [item for item in value if isinstance(item, dict)]


def _pick(document: dict[str, Any], *names: str, default: Any = None) -> Any:
    """按优先顺序读取字段；支持嵌套路径 ``sub.field``。"""
    for name in names:
        value: Any = document
        for part in name.split("."):
            if not isinstance(value, dict) or part not in value:
                value = None
                break
            value = value[part]
        if value is not None:
            return value
    return default


def _points(document: dict[str, Any], names: tuple[str, ...]) -> np.ndarray:
    """解析粒子/片段坐标（支持 starts/ends 或 particles 数组）。"""
    for name in names:
        value = _pick(document, name)
        if value is None:
            continue
        rows = _rows(value, name)
        if rows and all(isinstance(item.get("x"), (int, float)) for item in rows):
            return np.array(
                [[float(item.get(axis, 0.0)) for axis in ("x", "y", "z")] for item in rows]
            )
        array = np.asarray(value, dtype=float)
        if array.ndim == 2 and array.shape[1] == 3:
            return array
        if array.ndim == 2 and array.shape[1] == 2:
            return np.column_stack([array, np.zeros(array.shape[0])])
    return np.zeros((0, 3))


def _segments(value: Any) -> list[tuple[np.ndarray, np.ndarray]]:
    """解析带起点/终点的粒子线段（``particles: [{start: {x,y,z}, end: {x,y,z}}]``）。"""
    segments: list[tuple[np.ndarray, np.ndarray]] = []
    for row in _rows(value, "particles"):
        start = row.get("start")
        end = row.get("end")
        if isinstance(start, dict) and isinstance(end, dict):
            segments.append(
                (
                    np.array([float(start.get(a, 0.0)) for a in ("x", "y", "z")]),
                    np.array([float(end.get(a, 0.0)) for a in ("x", "y", "z")]),
                )
            )
        elif isinstance(row.get("sx"), (int, float)):
            segments.append(
                (
                    np.array([float(row[k]) for k in ("sx", "sy", "sz")]),
                    np.array([float(row[k]) for k in ("ex", "ey", "ez")]),
                )
            )
    return segments


def render_periodic_spatial_scene(
    document: dict[str, Any], output_stem: Path
) -> dict[str, Any]:
    """3D 周期单元内的有限圆柱与回绕片段，配 2D 正交剖面（图 2）。

    面板 A 为 3D 周期胞元（回绕身份用金色虚线）；面板 B 为 yz 正交剖面；
    当文档同时提供 nodes/edges/conductive_path 时扩展为三联图：面板 C 为
    左右贯通的导电骨架（图 2 完整 Hero 结构）。统一图例放在图底部，三面板
    共用同一套颜色语义，避免重复解释。
    """
    segments = _segments(_pick(document, "particles", "segments", default=[]))
    if not segments:
        starts = _points(document, ("starts", "particles"))
        segments = [
            (start, start + np.asarray([0.0, 0.0, 0.28]))
            for start in starts
        ]
    # 归一化：particles 为附件真实 nm 坐标（±5000），box 为归一化胞元（±1）。
    box_nm = _array(
        _pick(document, "box_nm", default=[5000.0, 5000.0, 5000.0]),
        "box_nm",
    )
    scale = float(box_nm[0]) if box_nm.shape[0] >= 1 and box_nm[0] > 0 else 5000.0
    segments = [
        (start / scale, end / scale)
        for start, end in segments
        if np.all(np.isfinite(start)) and np.all(np.isfinite(end))
    ]
    box = _array(_pick(document, "box", "half_box", "boundary", default=[1.0, 1.0, 1.0]), "box")
    identity_pairs = _rows(
        _pick(document, "identity_pairs_sample", "identity_pairs", "identity", default=[]),
        "identity_pairs",
    )
    if len(identity_pairs) > 24:
        identity_pairs = identity_pairs[:24]
    wrapped = _pick(document, "wrapped_fragments", "wrapped", default=[])
    network = _rows(_pick(document, "nodes", default=[]), "nodes")
    has_network = bool(network) and bool(_rows(_pick(document, "edges", "contact_edges", default=[]), "edges"))

    columns = 3 if has_network else 2
    fig = plt.figure(figsize=(8.4 if columns == 2 else 11.6, 5.0), constrained_layout=True)
    axis3d = fig.add_subplot(1, columns, 1, projection="3d")
    # 面板 A 先铺一层稀疏、低 alpha 的真实圆柱，再叠加骨架；这样背景保留
    # 空间密度而不吞没四个可追踪路径粒子。
    sample_step = max(1, (len(segments) + 89) // 90)
    backbone_ids: set[int] = set()
    backbone_edges = _rows(_pick(document, "conductive_path", "backbone", "conductive", default=[]), "conductive_path")
    for item in backbone_edges:
        for key in ("first", "second"):
            value = item.get(key)
            if isinstance(value, (int, float)):
                backbone_ids.add(int(value) - 1)
    for index, (start, end) in enumerate(segments):
        if index % sample_step != 0:
            continue
        direction = end - start
        norm = float(np.linalg.norm(direction))
        if norm < 1e-9:
            continue
        axis3d.plot(
            [start[0], end[0]], [start[1], end[1]], [start[2], end[2]],
            color=TEAL, linewidth=1.2, alpha=0.20,
            solid_capstyle="round", zorder=2,
        )
    for index in sorted(backbone_ids):
        if not 0 <= index < len(segments):
            continue
        start, end = segments[index]
        direction = end - start
        if float(np.linalg.norm(direction)) < 1e-9:
            continue
        axis3d.plot(
            [start[0], end[0]], [start[1], end[1]], [start[2], end[2]],
            color=BLUE, linewidth=4.8, alpha=0.98,
            solid_capstyle="round", zorder=5,
        )
        mid = (start + end) / 2.0
        label_z = mid[2] + {62: 0.08, 215: -0.08, 263: 0.08, 350: -0.08}.get(index, 0.0)
        axis3d.text(
            mid[0], mid[1], label_z,
            f"{index + 1}", color=INK, fontsize=12, ha="center", va="center",
            zorder=7,
        )
    if box.shape[0] >= 3:
        half = box[:3]
        corners = np.array(
            [[x, y, z] for x in (-half[0], half[0]) for y in (-half[1], half[1]) for z in (-half[2], half[2])]
        )
        for start, end in (
            (0, 1), (0, 2), (0, 4), (1, 3), (1, 5), (2, 3), (2, 6), (3, 7), (4, 5), (4, 6), (5, 7), (6, 7)
        ):
            axis3d.plot(
                [corners[start][0], corners[end][0]],
                [corners[start][1], corners[end][1]],
                [corners[start][2], corners[end][2]],
                color=GRAY, linewidth=1.1, zorder=1,
            )
    for pair in identity_pairs:
        first = int(pair.get("first", 0)) - 1
        second = int(pair.get("second", 0)) - 1
        if 0 <= first < len(segments) and 0 <= second < len(segments):
            axis3d.plot(
                [segments[first][0][0], segments[second][0][0]],
                [segments[first][0][1], segments[second][0][1]],
                [segments[first][0][2], segments[second][0][2]],
                color=GOLD, linewidth=2.0, linestyle="--", zorder=5,
            )
    axis3d.set_title("A 周期胞元内有限圆柱（金色虚线：回绕身份）", fontsize=11)
    axis3d.set_xlabel("x")
    axis3d.set_ylabel("y")
    axis3d.set_zlabel("z")
    axis3d.set_box_aspect((1, 1, 1))

    ax2 = fig.add_subplot(1, columns, 2)
    # B 只保留骨架及其邻近的少量真实片段，避免把完整接触候选集压成 spaghetti。
    path_centers = [
        (segments[index][0][1:3] + segments[index][1][1:3]) / 2.0
        for index in backbone_ids
        if 0 <= index < len(segments)
    ]
    local_ids = set(backbone_ids)
    if path_centers:
        candidates = []
        for index, (start, end) in enumerate(segments):
            if index in local_ids:
                continue
            center = (start[1:3] + end[1:3]) / 2.0
            distance = min(float(np.linalg.norm(center - anchor)) for anchor in path_centers)
            candidates.append((distance, index))
        local_ids.update(index for _, index in sorted(candidates)[:12])
    for index in sorted(local_ids):
        if not 0 <= index < len(segments):
            continue
        start, end = segments[index]
        direction = end - start
        norm = float(np.linalg.norm(direction))
        if norm < 1e-9:
            continue
        is_backbone = index in backbone_ids
        color = BLUE if is_backbone else TEAL
        ax2.plot(
            [start[1], end[1]], [start[2], end[2]],
            color=color, linewidth=3.8 if is_backbone else 1.6,
            alpha=0.98 if is_backbone else 0.32,
            solid_capstyle="round", zorder=3 if is_backbone else 2,
        )
    label_offsets = {62: (-28, -12), 215: (28, 22), 263: (-8, 22), 350: (30, -18)}
    for index, (start, end) in enumerate(segments):
        if index not in backbone_ids:
            continue
        mid = (start + end) / 2.0
        ax2.annotate(
            f"{index + 1}", (mid[1], mid[2]),
            xytext=label_offsets.get(index, (0, 0)), textcoords="offset points",
            ha="center", va="center", fontsize=10, fontweight="bold",
            zorder=6,
            color="white",
            bbox={"boxstyle": "circle,pad=0.25", "facecolor": BLUE, "edgecolor": INK, "linewidth": 0.8},
            arrowprops={"arrowstyle": "-", "color": BLUE, "linewidth": 0.8},
        )
    for pair in identity_pairs:
        first = int(pair.get("first", 0)) - 1
        second = int(pair.get("second", 0)) - 1
        if 0 <= first < len(segments) and 0 <= second < len(segments):
            ax2.plot(
                [segments[first][0][1], segments[second][0][1]],
                [segments[first][0][2], segments[second][0][2]],
                color=GOLD, linestyle="--", linewidth=1.8, zorder=5,
            )
    if box.shape[0] >= 2:
        ax2.add_patch(
            Rectangle(
                (-box[1], -box[2]), 2 * box[1], 2 * box[2],
                fill=False, edgecolor=INK, linewidth=1.3, linestyle=":",
            )
        )
    ax2.set_title("B 局部正交剖面（yz）：四个贯通粒子", fontsize=11)
    ax2.set_xlabel("y")
    ax2.set_ylabel("z")
    ax2.set_aspect("equal")
    ax2.grid(color=LIGHT, linewidth=0.6)
    if wrapped:
        ax2.text(
            0.98, 0.03, f"局部显示 {len(local_ids)} 个相关片段；回绕身份已合并",
            transform=ax2.transAxes, ha="right", fontsize=9, color=GRAY,
        )

    if has_network:
        ax3 = fig.add_subplot(1, columns, 3)
        edges = _rows(_pick(document, "edges", "contact_edges", default=[]), "edges")
        backbone = _rows(_pick(document, "conductive_path", "backbone", "conductive", default=[]), "conductive_path")
        electrodes = _rows(_pick(document, "electrodes", default=[]), "electrodes")

        def coordinate(item: dict[str, Any], default: tuple[float, float]) -> tuple[float, float]:
            if isinstance(item.get("x"), (int, float)) and isinstance(item.get("y"), (int, float)):
                return float(item["x"]), float(item["y"])
            return default

        positions = [coordinate(item, (0.0, 0.0)) for item in network]

        def endpoint(item: Any, fallback: tuple[float, float]) -> tuple[float, float]:
            """把边端点规范为坐标：1-based 索引、node 引用、L/R 电极或显式 x/y。"""
            if isinstance(item, str) and item in {"L", "R"}:
                for electrode in electrodes:
                    side = str(electrode.get("side", "")).casefold()
                    if (item == "L" and "left" in side) or (item == "R" and "right" in side):
                        return coordinate(electrode, fallback)
                return fallback
            if isinstance(item, (int, float)):
                index = int(item) - 1
                if 0 <= index < len(positions):
                    return positions[index]
                return fallback
            if isinstance(item, dict):
                if isinstance(item.get("node"), (int, float)):
                    index = int(item["node"]) - 1
                    if 0 <= index < len(positions):
                        return positions[index]
                if isinstance(item.get("x"), (int, float)) and isinstance(item.get("y"), (int, float)):
                    return float(item["x"]), float(item["y"])
            return fallback

        for first, second in edges:
            p1 = endpoint(first, (0.0, 0.0))
            p2 = endpoint(second, (0.0, 0.0))
            ax3.plot([p1[0], p2[0]], [p1[1], p2[1]], color=LIGHT, linewidth=2.2, zorder=1)
        for item in backbone:
            p1 = endpoint(item.get("first"), (0.0, 0.0))
            p2 = endpoint(item.get("second"), (0.0, 0.0))
            ax3.plot([p1[0], p2[0]], [p1[1], p2[1]], color=BLUE, linewidth=3.0, zorder=2)
        node_size = max(10, min(60, 2600 // max(len(positions), 1)))
        for x, y in positions:
            ax3.scatter(x, y, s=node_size, color=TEAL, alpha=0.8, edgecolor="none", zorder=3)
        # 骨架路径粒子用与 A/B 面板一致的编号标注，三面板可追踪同一路径。
        for item in backbone_edges:
            for key in ("first", "second"):
                value = item.get(key)
                if not isinstance(value, (int, float)):
                    continue
                node_index = int(value) - 1
                if 0 <= node_index < len(positions):
                    x, y = positions[node_index]
                    ax3.scatter(x, y, s=node_size * 1.6, color=BLUE, edgecolor=INK, linewidth=0.7, zorder=4)
                    ax3.annotate(
                        str(node_index + 1), (x, y), xytext=(0, 0),
                        textcoords="offset points", ha="center", va="center",
                        fontsize=7, color="white", zorder=5,
                    )
        for item in electrodes:
            side = str(item.get("side", item.get("electrode", "left"))).casefold()
            color = GOLD if "right" in side else BLUE
            x, y = coordinate(item, (0.0, 0.0))
            ax3.scatter(x, y, s=90, marker="s", color=color, edgecolor=INK, linewidth=0.6, zorder=4, alpha=0.95)
            ax3.annotate(
                "右电极" if "right" in side else "左电极",
                (x, y), xytext=(0, -14), textcoords="offset points",
                ha="center", fontsize=8, color=INK,
            )
        ax3.set_title("C 接触网络与左右贯通骨架（蓝色粗线）", fontsize=11)
        ax3.set_aspect("equal")
        ax3.axis("off")
    # 统一图例：三面板共用同一套颜色语义，直接标明对象身份。
    handles = [
        plt.Line2D([], [], color=TEAL, linewidth=4, marker="o", markersize=6, label="有限圆柱/粒子节点"),
        plt.Line2D([], [], color=BLUE, linewidth=4, marker="o", markersize=6, label="导电骨架粒子（编号可跨面板追踪）"),
        plt.Line2D([], [], color=GOLD, linestyle="--", linewidth=2, label="回绕身份（同一物理粒子）"),
        plt.Line2D([], [], color=LIGHT, linewidth=3.5, label="实体接触边（≤1.8 nm）"),
        plt.Line2D([], [], marker="s", linestyle="", color=BLUE, markersize=8, label="左右电极"),
    ]
    fig.legend(
        handles=handles, loc="lower center", ncol=3, frameon=False,
        fontsize=10, handlelength=1.6, columnspacing=1.6,
        bbox_to_anchor=(0.5, 0.0),
    )
    return _save(fig, output_stem)


def render_contact_network_backbone(
    document: dict[str, Any], output_stem: Path
) -> dict[str, Any]:
    """接触网络 + 左右电极 + 导电骨架（图 2 面板 B/C）。

    数据要求：nodes（x/y/z）、edges（first/second）、electrode_edges、
    conductive_path（骨架边索引或 first/second 对）。
    """
    nodes = _rows(_pick(document, "nodes", "particles", default=[]), "nodes")
    if not nodes:
        nodes = [
            {"x": float(value[0]), "y": float(value[1]), "z": float(value[2])}
            for value in _points(document, ("coordinates", "starts"))
        ]
    edges = _rows(_pick(document, "edges", "contact_edges", "contacts", default=[]), "edges")
    electrodes = _rows(_pick(document, "electrodes", "electrode_edges", default=[]), "electrodes")
    backbone = _rows(
        _pick(document, "conductive_path", "backbone", "conductive", default=[]), "conductive_path"
    )

    def coordinate(item: dict[str, Any], default: tuple[float, float]) -> tuple[float, float]:
        if isinstance(item.get("x"), (int, float)) and isinstance(item.get("y"), (int, float)):
            return float(item["x"]), float(item["y"])
        return default

    positions = [coordinate(item, (0.0, 0.0)) for item in nodes]
    center = np.mean(positions, axis=0)
    spacing = max(float(np.max(np.abs(np.array(positions) - center), axis=0).sum()), 1e-3)
    node_size = max(18, min(130, 9000 // max(len(positions), 1)))

    def endpoint(item: Any, fallback: tuple[float, float]) -> tuple[float, float]:
        """把边端点规范为坐标：1-based 索引、node 引用、L/R 电极或显式 x/y。"""
        if isinstance(item, str) and item in {"L", "R"}:
            for electrode in electrodes:
                side = str(electrode.get("side", "")).casefold()
                if (item == "L" and "left" in side) or (item == "R" and "right" in side):
                    return coordinate(electrode, fallback)
            return fallback
        if isinstance(item, (int, float)):
            index = int(item) - 1
            if 0 <= index < len(positions):
                return positions[index]
            return fallback
        if isinstance(item, dict):
            if isinstance(item.get("node"), (int, float)):
                index = int(item["node"]) - 1
                if 0 <= index < len(positions):
                    return positions[index]
            if isinstance(item.get("x"), (int, float)) and isinstance(item.get("y"), (int, float)):
                return float(item["x"]), float(item["y"])
        return fallback

    fig, axes = plt.subplots(1, 2, figsize=(8.4, 4.2), constrained_layout=True)
    for panel, (title, show_backbone) in (
        (0, ("A 接触网络（蓝：电极；灰：普通接触）", False)),
        (1, ("B 只保留左右贯通的导电骨架", True)),
    ):
        ax = axes[panel]
        for first, second in edges:
            p1 = endpoint(first, (0.0, 0.0))
            p2 = endpoint(second, (0.0, 0.0))
            ax.plot([p1[0], p2[0]], [p1[1], p2[1]], color=LIGHT, linewidth=3.5, zorder=1)
        backbone_pairs = backbone if backbone else []
        for item in backbone_pairs:
            first = endpoint(item.get("first"), (0.0, 0.0))
            second = endpoint(item.get("second"), (0.0, 0.0))
            ax.plot(
                [first[0], second[0]], [first[1], second[1]],
                color=BLUE if show_backbone else LIGHT, linewidth=2.6, zorder=2,
            )
        for index, (x, y) in enumerate(positions, start=1):
            ax.scatter(x, y, s=node_size, color=TEAL, edgecolor=INK, linewidth=0.5, zorder=3)
            ax.annotate(str(index), (x, y), xytext=(0, 0), textcoords="offset points", ha="center", va="center", fontsize=7.5, color="white")
        for item in electrodes:
            if not isinstance(item, dict):
                continue
            side = str(item.get("side", item.get("electrode", "left"))).casefold()
            color = GOLD if "right" in side else BLUE
            x, y = coordinate(item, (0.0, 0.0))
            ax.scatter(x, y, s=200, marker="s", color=color, edgecolor=INK, zorder=4, alpha=0.9)
        ax.set_title(title, fontsize=9)
        ax.set_aspect("equal")
        ax.axis("off")
        ax.set_xlim(center[0] - spacing, center[0] + spacing)
        ax.set_ylim(center[1] - spacing, center[1] + spacing)
    return _save(fig, output_stem)


def render_geometric_oracle_comparison(
    document: dict[str, Any], output_stem: Path
) -> dict[str, Any]:
    """端部局部放大：胶囊中心线距离 vs 平端实体距离，标出被删除伪边（图 3 右）。"""
    pairs = _rows(_pick(document, "candidate_pairs", "pairs", "candidates", default=[]), "candidate_pairs")
    gap = float(_pick(document, "gap", "GAP", default=0.0))
    fig, ax = plt.subplots(figsize=(7.2, 4.2), constrained_layout=True)
    labels: list[str] = []
    margins: list[float] = []
    removed: list[float] = []
    kept: list[float] = []
    for index, pair in enumerate(pairs, start=1):
        capsule = float(pair.get("capsule_distance", pair.get("axis_distance", 0.0)))
        exact = float(pair.get("exact_distance", pair.get("solid_distance", capsule)))
        labels.append(str(pair.get("label", f"候选边 {index}")))
        margins.append(exact - gap)
        (removed if exact > gap else kept).append(index)
    y = np.arange(len(pairs))
    ax.axvline(0, color=INK, linewidth=1.0)
    ax.axvspan(0, max(margins + [0.0]), color=TEAL, alpha=0.06)
    ax.axvspan(min(margins + [0.0]), 0, color=CORAL, alpha=0.06)
    colors = [CORAL if value > 0 else TEAL for value in margins]
    ax.hlines(y, 0, margins, color=colors, linewidth=2.2)
    ax.scatter(margins, y, c=colors, s=60, edgecolor=INK, zorder=3)
    for index, value in enumerate(margins):
        ax.annotate(f"{value:+.4f}", (value, index), xytext=(4, 0), textcoords="offset points", fontsize=8)
    ax.set(yticks=y, yticklabels=labels, ylabel="候选接触边", xlabel="平端实体距离相对间隙的裕量 / nm")
    ax.set_title("端部几何：胶囊候选边在平端实体口径下被删除", fontsize=9.5)
    _clean(ax)
    if removed:
        ax.text(0.99, 0.03, f"删除 {len(removed)} 条伪边（暖红）", transform=ax.transAxes, ha="right", fontsize=8, color=CORAL)
    if kept:
        ax.text(0.01, 0.03, f"保留 {len(kept)} 条真接触（深青）", transform=ax.transAxes, ha="left", fontsize=8, color=TEAL)
    return _save(fig, output_stem)


def render_probability_threshold_curve(
    document: dict[str, Any], output_stem: Path
) -> dict[str, Any]:
    """概率转变曲线 + Wilson 区间 + 阈值带 + 独立批次（图 4/图 5）。

    数据要求：points[{x|n, probability, wilson_low, wilson_high, successes,
    trials}]、threshold、extra_points（独立加密批次）。
    """
    points = _rows(_pick(document, "points", default=[]), "points")
    threshold = float(_pick(document, "threshold", "target", "p0", default=0.90))
    extra = _rows(_pick(document, "extra_points", "independent_points", default=[]), "extra_points")
    if not points:
        raise ValueError("probability_threshold_curve 需要 points")
    x = np.array([float(p.get("x", p.get("n", index))) for index, p in enumerate(points)])
    prob = np.array([float(p["probability"]) for p in points])
    low = np.array([float(p.get("wilson_low", p.get("interval_low", prob[index]))) for index, p in enumerate(points)])
    high = np.array([float(p.get("wilson_high", p.get("interval_high", prob[index]))) for index, p in enumerate(points)])

    fig, ax = plt.subplots(figsize=(7.6, 4.4), constrained_layout=True)
    ax.fill_between(x, low, high, color=TEAL, alpha=0.14, label="95% Wilson 区间", zorder=1)
    ax.plot(x, prob, color=TEAL, marker="o", linewidth=2.0, label="点估计", zorder=3)
    ax.axhline(threshold, color=GOLD, linewidth=1.5, linestyle="--", label=f"{threshold:.0%} 阈值", zorder=2)
    first_above = next((index for index, value in enumerate(low) if value >= threshold), None)
    if first_above is not None and first_above > 0:
        ax.axvspan(
            x[first_above - 1], x[first_above], color=PALE_GOLD, alpha=0.5, zorder=0,
            label="首次越过阈值带",
        )
    y_top = float(np.max(high)) + 0.04
    y_bottom = float(np.min(low)) - 0.04
    for item in extra:
        ex = float(item.get("x", item.get("n", 0.0)))
        ep = float(item.get("probability", item.get("point", 0.0)))
        el = float(item.get("wilson_low", ep))
        eh = float(item.get("wilson_high", ep))
        ax.errorbar(
            [ex], [ep], yerr=[[ep - el], [eh - ep]],
            fmt="D", ms=7, color=CORAL, ecolor=CORAL, capsize=4,
            label=item.get("label", "独立加密批次"), zorder=5,
        )
        if "label" in item:
            # 标注放在右上角空白区，避免压住区间带与曲线。
            ax.annotate(
                item["label"],
                (ex, ep),
                xytext=(0, 16),
                textcoords="offset points",
                ha="center", fontsize=8, color=CORAL,
                arrowprops={"arrowstyle": "->", "color": CORAL, "lw": 0.9},
            )
    ax.set_xlabel(str(_pick(document, "x_label", default="介质 A 数量 / 根")))
    ax.set_ylabel("导通概率")
    ax.set_ylim(y_bottom, y_top)
    ax.set_title(str(_pick(document, "title", default="导通概率转变与可靠性阈值")))
    _clean(ax)
    # 图例放右上空白（曲线从左侧低位上升，右上角无数据），并压缩条目字号。
    ax.legend(frameon=False, loc="upper left", fontsize=7.5, handlelength=1.4)
    return _save(fig, output_stem)


def render_integer_feasible_region(
    document: dict[str, Any], output_stem: Path
) -> dict[str, Any]:
    """整数格点可行域 + 成本等高线 + 活跃边界 + 选中点（图 7 Hero）。

    数据要求：lattice_points[{n_A, n_B, feasible, margin, cost}]、
    costs 网格或点级 cost、selected_point{n_A, n_B, label}、domain_boundary。
    """
    points = _rows(_pick(document, "lattice_points", "grid_points", "points", "candidates", default=[]), "lattice_points")
    selected = _pick(document, "selected_point", "selected", "official", default=None)
    if not points:
        raise ValueError("integer_feasible_region 需要 lattice_points")
    n_a = np.array([float(p.get("n_A", p.get("n_a", p.get("x", 0.0)))) for p in points])
    n_b = np.array([float(p.get("n_B", p.get("n_b", p.get("y", 0.0)))) for p in points])
    feasible = np.array([bool(p.get("feasible", p.get("is_feasible", True))) for p in points])
    costs = np.array(
        [float(p.get("cost", p.get("cost_yuan", np.nan))) for p in points],
        dtype=float,
    )

    fig, ax = plt.subplots(figsize=(7.6, 5.6), constrained_layout=True)
    # 零允许敏感性域：n_A=0 列与 n_B=0 行用灰色背景带，与正式域严格区分。
    ax.axvspan(-0.5, 0.5, color=GRAY, alpha=0.12, zorder=0)
    ax.axhspan(-1.0, 1.0, color=GRAY, alpha=0.12, zorder=0)
    formal_mask = (n_a >= 1) & (n_b >= 1) & feasible
    sensitivity_mask = feasible & ~((n_a >= 1) & (n_b >= 1))
    # 正式域可行格点：深青圆；零允许敏感性可行格点：灰色菱形（独立图例）。
    ax.scatter(
        n_a[formal_mask], n_b[formal_mask], s=110, color=TEAL, edgecolor=INK, linewidth=0.6,
        zorder=3,         label="正式域可行格点（$n_A\\geq1,\\ n_B\\geq1$）",
    )
    if np.any(sensitivity_mask):
        ax.scatter(
            n_a[sensitivity_mask], n_b[sensitivity_mask], s=90, marker="D",
            color=GRAY, edgecolor=INK, linewidth=0.6, zorder=3,
            label="零允许敏感性可行点（$n_A{=}0$ 或 $n_B{=}0$）",
        )
    if np.any(~feasible):
        ax.scatter(
            n_a[~feasible], n_b[~feasible], s=80, marker="x", color=CORAL, linewidth=1.6,
            zorder=3, label="不可行格点",
        )
    valid_cost = ~np.isnan(costs) & feasible
    if np.any(valid_cost):
        grid_a = np.unique(n_a[valid_cost])
        grid_b = np.unique(n_b[valid_cost])
        regular = len(grid_a) * len(grid_b) == int(np.sum(valid_cost))
        if regular and len(grid_a) >= 2 and len(grid_b) >= 2:
            z = np.full((len(grid_b), len(grid_a)), np.nan)
            for index in np.where(valid_cost)[0]:
                row = np.where(grid_b == n_b[index])[0][0]
                col = np.where(grid_a == n_a[index])[0][0]
                z[row, col] = costs[index]
            levels = np.percentile(z[~np.isnan(z)], [20, 40, 60, 80, 95])
            ax.contourf(
                grid_a, grid_b, z, levels=levels, colors=[GRAY], alpha=0.14, zorder=1,
            )
            contours = ax.contour(
                grid_a, grid_b, z, levels=levels, colors=GRAY, linewidths=0.9,
                linestyles=":", zorder=2,
            )
            ax.clabel(contours, inline=True, fontsize=7.5, fmt="%.3f")
        elif int(np.sum(valid_cost)) >= 6:
            # 不规则格点用三角网格等高线，仍保持成本结构可见。
            levels = np.percentile(costs[valid_cost], [20, 40, 60, 80, 95])
            ax.tricontourf(
                n_a[valid_cost], n_b[valid_cost], costs[valid_cost],
                levels=levels, colors=[GRAY], alpha=0.14, zorder=1,
            )
            contours = ax.tricontour(
                n_a[valid_cost], n_b[valid_cost], costs[valid_cost],
                levels=levels, colors=GRAY, linewidths=0.9, linestyles=":", zorder=2,
            )
            ax.clabel(contours, inline=True, fontsize=7.5, fmt="%.3f")
    # 活动边界：只取正式域（n_A>=1）内每列最小可行 n_B，零轴敏感性不参与边界。
    boundary: list[tuple[float, float]] = []
    for value_a in sorted(
        {float(item["n_A"]) for item in points if item["feasible"] and item["n_A"] >= 1}
    ):
        column = [
            float(item["n_B"])
            for item in points
            if item["feasible"] and float(item["n_A"]) == value_a
        ]
        if column:
            boundary.append((value_a, min(column)))
    if boundary:
        bx = [item[0] for item in boundary]
        by = [item[1] for item in boundary]
        ax.plot(bx, by, color=INK, linewidth=1.5, linestyle="-.", zorder=4, label="90% 可行边界")
    if isinstance(selected, dict):
        sx = float(selected.get("n_A", selected.get("x", 0.0)))
        sy = float(selected.get("n_B", selected.get("y", 0.0)))
        ax.scatter([sx], [sy], marker="*", s=420, color=GOLD, edgecolor=INK, linewidth=0.9, zorder=5)
        label = str(selected.get("label", f"{int(sx)}A+{int(sy)}B"))
        ax.annotate(label, (sx, sy), xytext=(10, 10), textcoords="offset points", fontsize=9, fontweight="bold", color=INK)
    ax.set_xlabel(r"介质 A 粒子数 $n_A$")
    ax.set_ylabel(r"介质 B 粒子数 $n_B$")
    ax.set_title(str(_pick(document, "title", default="整数可行域：成本等高线与活跃边界")))
    _clean(ax)
    ax.grid(axis="both", color=LIGHT, linewidth=0.6)
    # 图例移到右上空白区（n_A 大、n_B 大区域无格点），不遮挡 n_B=0 敏感性带。
    ax.legend(frameon=True, framealpha=0.9, loc="upper right", fontsize=9.5, handlelength=1.4)
    return _save(fig, output_stem)


def render_cost_reliability_frontier(
    document: dict[str, Any], output_stem: Path
) -> dict[str, Any]:
    """成本—可靠性分层前沿：正式域与敏感性域分开编码（图 8）。

    数据要求：candidate_points[{cost, probability, wilson_low, wilson_high,
    label, domain}]、threshold、official（选中点 label）。
    """
    points = _rows(_pick(document, "candidate_points", "candidates", "points", default=[]), "candidate_points")
    threshold = float(_pick(document, "threshold", "target", default=0.90))
    if not points:
        raise ValueError("cost_reliability_frontier 需要 candidate_points")
    costs = np.array([float(p["cost"]) for p in points])
    prob = np.array([float(p["probability"]) for p in points])
    low = np.array([float(p.get("wilson_low", p.get("interval_low", prob[index]))) for index, p in enumerate(points)])
    high = np.array([float(p.get("wilson_high", p.get("interval_high", prob[index]))) for index, p in enumerate(points)])
    domains = [str(p.get("domain", p.get("region", "formal"))) for p in points]
    official_label = str(_pick(document, "official", "selected", default=""))

    fig, ax = plt.subplots(figsize=(7.6, 4.8), constrained_layout=True)
    ax.errorbar(costs, prob, yerr=[prob - low, high - prob], fmt="none", ecolor=GRAY, capsize=3, linewidth=1, zorder=1)
    for index, (domain, x, y) in enumerate(zip(domains, costs, prob, strict=True)):
        sensitivity = "sensitivity" in domain or "zero" in domain or "out" in domain
        marker = "X" if sensitivity else "o"
        color = GRAY if sensitivity else TEAL
        size = 46 if sensitivity else 110
        ax.scatter([x], [y], marker=marker, s=size, color=color, edgecolor=INK, zorder=3)
        if str(points[index].get("label", "")):
            ax.annotate(points[index]["label"], (x, y), xytext=(5, 5), textcoords="offset points", fontsize=7.6, color=INK)
    if official_label:
        target = next((index for index, p in enumerate(points) if p.get("label") == official_label), None)
        if target is not None:
            ax.scatter([costs[target]], [prob[target]], marker="*", s=420, color=GOLD, edgecolor=INK, linewidth=0.9, zorder=5)
    ax.axhline(threshold, color=GOLD, linewidth=1.4, linestyle="--", label=f"{threshold:.0%} 阈值")
    ax.set_xlabel("总成本 / 元")
    ax.set_ylabel("导通概率")
    ax.set_title(str(_pick(document, "title", default="成本—可靠性前沿：正式域与敏感性域分层")))
    _clean(ax)
    handles = [
        plt.Line2D([], [], marker="o", linestyle="", color=TEAL, label="正式域（严格正域）"),
        plt.Line2D([], [], marker="X", linestyle="", color=GRAY, label="敏感性/域外"),
    ]
    ax.legend(handles=handles, frameon=False, loc="lower right")
    return _save(fig, output_stem)


def render_convergence_envelope(
    document: dict[str, Any], output_stem: Path
) -> dict[str, Any]:
    """多种子收敛包络：分位带 + 停止样本量（附录图 A）。"""
    samples = _rows(_pick(document, "envelope", "quantile_bands", default=[]), "envelope")
    if not samples:
        raise ValueError("convergence_envelope 需要 envelope")
    x = np.array([float(s.get("sample", s.get("budget", index + 1))) for index, s in enumerate(samples)])
    median = np.array([float(s.get("median", s.get("p50", np.nan))) for s in samples])
    low = np.array([float(s.get("low", s.get("p5", np.nan))) for s in samples])
    high = np.array([float(s.get("high", s.get("p95", np.nan))) for s in samples])
    stop = _pick(document, "stopping_point", "stop", default=None)

    fig, ax = plt.subplots(figsize=(7.4, 4.4), constrained_layout=True)
    valid = ~np.isnan(low) & ~np.isnan(high)
    ax.fill_between(x[valid], low[valid], high[valid], color=TEAL, alpha=0.18, label="5%–95% 多种子包络")
    ax.plot(x, median, color=TEAL, linewidth=2.0, label="中位数")
    if isinstance(stop, dict):
        sx = float(stop.get("sample", stop.get("x", 0.0)))
        ax.axvline(sx, color=GOLD, linewidth=1.4, linestyle="--", label="停止样本量")
        ax.annotate(str(stop.get("label", f"n={int(sx)}")), (sx, ax.get_ylim()[1]), xytext=(6, -2), textcoords="offset points", fontsize=8, color=GOLD)
    ax.set_xlabel("样本量")
    ax.set_ylabel(str(_pick(document, "y_label", default="指标估计")))
    ax.set_title(str(_pick(document, "title", default="Monte Carlo 收敛包络（多种子）")))
    _clean(ax)
    ax.legend(frameon=False, loc="upper right")
    return _save(fig, output_stem)


def render_implementation_agreement(
    document: dict[str, Any], output_stem: Path
) -> dict[str, Any]:
    """Python/MATLAB 或主实现与独立 oracle 的分类一致对照（图 10）。"""
    rows = _rows(_pick(document, "classifications", "rows", default=[]), "classifications")
    if not rows:
        raise ValueError("implementation_agreement 需要 classifications")
    labels = [str(row.get("label", f"行 {index + 1}")) for index, row in enumerate(rows)]
    primary = [float(row.get("primary", row.get("python", 0.0))) for row in rows]
    independent = [float(row.get("independent", row.get("matlab", 0.0))) for row in rows]
    differences = [
        float(row.get("difference", row.get("diff", abs(primary[index] - independent[index]))))
        for index, row in enumerate(rows)
    ]

    fig, axes = plt.subplots(1, 2, figsize=(8.0, 4.2), constrained_layout=True)
    ax = axes[0]
    y = np.arange(len(rows))
    ax.hlines(y, 0, primary, color=TEAL, linewidth=3.0, label="主实现")
    ax.hlines(y, 0, independent, color=BLUE, linewidth=1.2, linestyle="--", label="独立 oracle")
    for index, (pv, iv) in enumerate(zip(primary, independent, strict=True)):
        ax.plot([pv, iv], [index, index], marker="o", color=INK, markersize=3, zorder=4)
    ax.set(yticks=y, yticklabels=labels, ylabel="验证对象", xlabel="分类/距离数值")
    ax.set_title("A 主实现与独立 oracle 一致", fontsize=9)
    _clean(ax)
    ax.legend(frameon=False, loc="lower right")
    ax2 = axes[1]
    ax2.barh(y, differences, color=[CORAL if value > 1e-9 else TEAL for value in differences], height=0.55)
    for index, value in enumerate(differences):
        ax2.text(value + max(differences) * 0.01, index, f"{value:.2e}", va="center", fontsize=7.6)
    ax2.set(yticks=y, yticklabels=labels, xlabel="绝对差异")
    ax2.set_title("B 差异明细（接近零=一致）", fontsize=9)
    _clean(ax2)
    return _save(fig, output_stem)


def render_shared_model_pipeline(
    document: dict[str, Any], output_stem: Path
) -> dict[str, Any]:
    """共享模型管线：物理粒子 -> 身份恢复 -> 接触图 -> 导通事件 -> 概率 -> 阈值（图 1）。"""
    stages = _rows(_pick(document, "stages", "nodes", default=[]), "stages")
    relations = _rows(_pick(document, "relations", "edges", default=[]), "relations")
    if not stages:
        raise ValueError("shared_model_pipeline 需要 stages")
    fig, ax = plt.subplots(figsize=(8.6, 2.6), constrained_layout=True)
    n = len(stages)
    x = np.linspace(0.05, 0.95, n)
    for index, stage in enumerate(stages):
        color = GRAY if str(stage.get("kind", "")).casefold() in {"derivation", "support"} else TEAL
        box = FancyBboxPatch(
            (x[index] - 0.055, 0.28), 0.11, 0.44,
            boxstyle="round,pad=0.012", facecolor=color, alpha=0.16, edgecolor=color, linewidth=1.2,
        )
        ax.add_patch(box)
        ax.text(x[index], 0.50, str(stage.get("label", f"阶段 {index + 1}")), ha="center", va="center", fontsize=8.2, color=INK)
    for relation in relations:
        source = int(relation.get("source", relation.get("first", 1))) - 1
        target = int(relation.get("target", relation.get("second", 2))) - 1
        if not (0 <= source < n and 0 <= target < n):
            continue
        ax.annotate(
            "", xy=(x[target], 0.50), xytext=(x[source], 0.50),
            arrowprops=dict(arrowstyle="->", color=INK, linewidth=1.1),
        )
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_title(str(_pick(document, "title", default="共享模型管线：同一原子事件连接四问")))
    return _save(fig, output_stem)


def render_figure(
    document: dict[str, Any], archetype: str, output_stem: Path
) -> dict[str, Any]:
    """按 archetype 分发到正式 renderer；未知 archetype 明确失败。"""
    renderers = {
        "periodic_spatial_scene": render_periodic_spatial_scene,
        "spatial_scene_cross_section": render_periodic_spatial_scene,
        "spatial_contact_backbone_triptych": render_periodic_spatial_scene,
        "contact_network_backbone": render_contact_network_backbone,
        "oracle_comparison_zoom": render_geometric_oracle_comparison,
        "probability_threshold_curve": render_probability_threshold_curve,
        "uncertainty_margin_ribbon": render_probability_threshold_curve,
        "integer_feasible_region": render_integer_feasible_region,
        "cost_reliability_frontier": render_cost_reliability_frontier,
        "convergence_envelope": render_convergence_envelope,
        "implementation_agreement": render_implementation_agreement,
        "shared_model_pipeline": render_shared_model_pipeline,
    }
    if archetype not in renderers:
        raise ValueError(f"未注册正式 renderer archetype: {archetype}")
    return renderers[archetype](document, output_stem)


__all__ = [
    "INK", "TEAL", "GREEN", "CORAL", "GOLD", "BLUE", "GRAY", "LIGHT",
    "MIN_FONT_PT", "RENDERER_REGISTRY", "render_figure",
    "render_periodic_spatial_scene",
    "render_contact_network_backbone",
    "render_geometric_oracle_comparison",
    "render_probability_threshold_curve",
    "render_integer_feasible_region",
    "render_cost_reliability_frontier",
    "render_convergence_envelope",
    "render_implementation_agreement",
    "render_shared_model_pipeline",
]
