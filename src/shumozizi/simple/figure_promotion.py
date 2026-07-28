"""先审核独立图像候选，再晋级为论文 current 图。"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    load_json,
    relative_inside,
    resolve_inside,
    sha256_file,
)
from shumozizi.simple.state import utc_now

_IMAGE_SUFFIXES = {".png", ".pdf"}


def _box(item: dict[str, Any], label: str) -> tuple[float, float, float, float]:
    """读取 ``x/y/width/height`` 边界框。"""
    values = [item.get(key) for key in ("x", "y", "width", "height")]
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
        raise ContractError(f"{label} 必须包含数值 x、y、width、height")
    x, y, width, height = (float(value) for value in values)
    if width <= 0 or height <= 0:
        raise ContractError(f"{label} 的 width 和 height 必须大于零")
    return x, y, x + width, y + height


def _inside(inner: tuple[float, ...], outer: tuple[float, ...], tolerance: float = 1.0) -> bool:
    """判断内框是否位于外框中。"""
    return (
        inner[0] >= outer[0] - tolerance
        and inner[1] >= outer[1] - tolerance
        and inner[2] <= outer[2] + tolerance
        and inner[3] <= outer[3] + tolerance
    )


def _boxes_overlap(first: tuple[float, ...], second: tuple[float, ...]) -> bool:
    """判断两个边界框是否具有正面积交叠。"""
    return min(first[2], second[2]) > max(first[0], second[0]) and min(
        first[3], second[3]
    ) > max(first[1], second[1])


def _orientation(
    first: tuple[float, float], second: tuple[float, float], third: tuple[float, float]
) -> float:
    """返回三个点的二维有向面积。"""
    return (second[0] - first[0]) * (third[1] - first[1]) - (
        second[1] - first[1]
    ) * (third[0] - first[0])


def _segments_intersect(
    first: tuple[float, float],
    second: tuple[float, float],
    third: tuple[float, float],
    fourth: tuple[float, float],
) -> bool:
    """判断两条闭线段是否相交。"""
    values = (
        _orientation(first, second, third),
        _orientation(first, second, fourth),
        _orientation(third, fourth, first),
        _orientation(third, fourth, second),
    )
    epsilon = 1e-9

    def on_segment(
        start: tuple[float, float],
        point: tuple[float, float],
        end: tuple[float, float],
    ) -> bool:
        return (
            min(start[0], end[0]) - epsilon <= point[0] <= max(start[0], end[0]) + epsilon
            and min(start[1], end[1]) - epsilon
            <= point[1]
            <= max(start[1], end[1]) + epsilon
        )

    if values[0] * values[1] < 0 and values[2] * values[3] < 0:
        return True
    return (
        (abs(values[0]) <= epsilon and on_segment(first, third, second))
        or (abs(values[1]) <= epsilon and on_segment(first, fourth, second))
        or (abs(values[2]) <= epsilon and on_segment(third, first, fourth))
        or (abs(values[3]) <= epsilon and on_segment(third, second, fourth))
    )


def _segment_hits_box(
    first: tuple[float, float], second: tuple[float, float], box: tuple[float, ...]
) -> bool:
    """判断线段是否穿过矩形或落入矩形内部。"""
    x0, y0, x1, y1 = box
    if any(x0 <= point[0] <= x1 and y0 <= point[1] <= y1 for point in (first, second)):
        return True
    corners = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    edges = zip(corners, (*corners[1:], corners[0]), strict=True)
    return any(_segments_intersect(first, second, start, end) for start, end in edges)


def _endpoint_centered(
    point: tuple[float, float], box: tuple[float, ...], tolerance: float
) -> bool:
    """判断箭头端点是否靠近节点某条边的中点。"""
    x0, y0, x1, y1 = box
    centers = (
        (x0, (y0 + y1) / 2),
        (x1, (y0 + y1) / 2),
        ((x0 + x1) / 2, y0),
        ((x0 + x1) / 2, y1),
    )
    return min(((point[0] - x) ** 2 + (point[1] - y) ** 2) ** 0.5 for x, y in centers) <= tolerance


def _diagram_layout_errors(
    report: dict[str, Any], *, png_size: tuple[int, int], minimum_font_size_pt: float
) -> list[str]:
    """检查流程图几何报告中的边界、重叠和连线错误。"""
    errors: list[str] = []
    canvas = report.get("canvas")
    if not isinstance(canvas, dict):
        return ["流程图 layout report 缺少 canvas"]
    canvas_box = _box({"x": 0, "y": 0, **canvas}, "canvas")
    if abs(canvas_box[2] - png_size[0]) > 1 or abs(canvas_box[3] - png_size[1]) > 1:
        errors.append("layout report 的 canvas 尺寸与 PNG 像素尺寸不一致")

    raw_nodes = report.get("node_boxes", [])
    raw_text = report.get("text_boxes", [])
    raw_arrows = report.get("arrows", [])
    if not isinstance(raw_nodes, list) or not isinstance(raw_text, list) or not isinstance(raw_arrows, list):
        return [*errors, "流程图 layout report 的 node_boxes/text_boxes/arrows 必须是数组"]
    node_boxes: dict[str, tuple[float, ...]] = {}
    text_boxes: dict[str, tuple[float, ...]] = {}
    for item in raw_nodes:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            errors.append("node_boxes 每项必须有字符串 id")
            continue
        box = _box(item, f"node {item['id']}")
        node_boxes[item["id"]] = box
        if not _inside(box, canvas_box, tolerance=0):
            errors.append(f"节点 {item['id']} 超出画布")
    for item in raw_text:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            errors.append("text_boxes 每项必须有字符串 id")
            continue
        box = _box(item, f"text {item['id']}")
        text_boxes[item["id"]] = box
        if not _inside(box, canvas_box, tolerance=0):
            errors.append(f"文字 {item['id']} 超出画布")
        font_size = item.get("font_size_pt")
        if not isinstance(font_size, (int, float)) or isinstance(font_size, bool):
            errors.append(f"文字 {item['id']} 缺少 font_size_pt")
        elif float(font_size) < minimum_font_size_pt:
            errors.append(f"文字 {item['id']} 字号小于 {minimum_font_size_pt:g} pt")
        node_id = item.get("node_id")
        if isinstance(node_id, str):
            if node_id not in node_boxes:
                errors.append(f"文字 {item['id']} 引用了不存在的节点 {node_id}")
            elif not _inside(box, node_boxes[node_id]):
                errors.append(f"文字 {item['id']} 超出节点 {node_id}")
    text_items = list(text_boxes.items())
    for index, (first_id, first_box) in enumerate(text_items):
        for second_id, second_box in text_items[index + 1 :]:
            if _boxes_overlap(first_box, second_box):
                errors.append(f"文字框 {first_id} 与 {second_id} 重叠")

    alignment_tolerance = report.get("alignment_tolerance_px", 8)
    if not isinstance(alignment_tolerance, (int, float)) or alignment_tolerance <= 0:
        errors.append("alignment_tolerance_px 必须是正数")
        alignment_tolerance = 8
    for item in raw_arrows:
        arrow_id = str(item.get("id", "<unknown>")) if isinstance(item, dict) else "<unknown>"
        points = item.get("points") if isinstance(item, dict) else None
        if (
            not isinstance(points, list)
            or len(points) < 2
            or any(
                not isinstance(point, list)
                or len(point) != 2
                or not all(isinstance(value, (int, float)) for value in point)
                for point in points
            )
        ):
            errors.append(f"箭头 {arrow_id} 必须声明至少两个二维 points")
            continue
        normalized = [(float(point[0]), float(point[1])) for point in points]
        for text_id, text_box in text_boxes.items():
            if any(
                _segment_hits_box(start, end, text_box)
                for start, end in zip(normalized, normalized[1:], strict=False)
            ):
                errors.append(f"箭头 {arrow_id} 穿过文字 {text_id}")
        for endpoint, key in ((normalized[0], "source_node_id"), (normalized[-1], "target_node_id")):
            node_id = item.get(key)
            if not isinstance(node_id, str) or node_id not in node_boxes:
                errors.append(f"箭头 {arrow_id} 缺少有效 {key}")
            elif not _endpoint_centered(endpoint, node_boxes[node_id], float(alignment_tolerance)):
                errors.append(f"箭头 {arrow_id} 在节点 {node_id} 的连接点未居中")
    return errors


def audit_figure_candidate(
    run_dir: Path,
    *,
    figure_id: str,
    candidate_outputs: list[str],
    rendering_mode: str,
    layout_report: str | None = None,
    minimum_font_size_pt: float = 8.0,
    aspect_ratio_tolerance: float = 0.02,
) -> dict[str, Any]:
    """审核候选图的可读性，并对流程图执行几何碰撞检查。

    Args:
        run_dir: 当前运行目录。
        figure_id: 稳定图 ID。
        candidate_outputs: 同一版本目录内的 PNG 和 PDF。
        rendering_mode: ``diagram`` 或普通 ``plot``。
        layout_report: 流程图渲染器输出的几何 JSON。
        minimum_font_size_pt: 流程图最小字号。
        aspect_ratio_tolerance: PNG/PDF 宽高比相对容差。

    Returns:
        可持久化的 QA 结果；``success=false`` 时不得晋级。
    """
    if rendering_mode not in {"diagram", "plot"}:
        raise ContractError("candidate rendering_mode 必须为 diagram 或 plot")
    root = run_dir.resolve()
    outputs = [resolve_inside(root, value, must_exist=True) for value in candidate_outputs]
    if len(outputs) != 2 or {path.suffix.casefold() for path in outputs} != _IMAGE_SUFFIXES:
        raise ContractError("图像候选必须同时提供一份 PNG 和一份 PDF")
    expected_prefix = f"figures/candidates/{figure_id}/"
    relatives = [relative_inside(root, path).as_posix() for path in outputs]
    if any(not value.startswith(expected_prefix) for value in relatives):
        raise ContractError(f"候选图必须位于 {expected_prefix}<version>/")
    parents = {path.parent.resolve() for path in outputs}
    if len(parents) != 1:
        raise ContractError("同一候选版本的 PNG 和 PDF 必须位于同一目录")
    errors: list[str] = []
    png = next(path for path in outputs if path.suffix.casefold() == ".png")
    pdf = next(path for path in outputs if path.suffix.casefold() == ".pdf")
    try:
        from PIL import Image

        with Image.open(png) as image:
            image.verify()
        with Image.open(png) as image:
            png_size = image.size
    except (OSError, ValueError) as exc:
        raise ContractError(f"候选 PNG 不可读: {exc}") from exc
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        reader = PdfReader(pdf)
        page = reader.pages[0]
        pdf_size = (float(page.mediabox.width), float(page.mediabox.height))
    except (OSError, ValueError, IndexError, PdfReadError) as exc:
        raise ContractError(f"候选 PDF 不可读: {exc}") from exc
    png_ratio = png_size[0] / png_size[1]
    pdf_ratio = pdf_size[0] / pdf_size[1]
    ratio_error = abs(png_ratio - pdf_ratio) / png_ratio
    if ratio_error > aspect_ratio_tolerance:
        errors.append(
            f"PNG/PDF 宽高比不一致（{png_ratio:.4f} 对 {pdf_ratio:.4f}）"
        )
    layout_relative: str | None = None
    if rendering_mode == "diagram":
        if layout_report is None:
            errors.append("流程图候选缺少 layout report")
        else:
            layout_path = resolve_inside(root, layout_report, must_exist=True)
            layout_relative = relative_inside(root, layout_path).as_posix()
            if layout_path.parent.resolve() not in parents:
                errors.append("layout report 必须与候选 PNG/PDF 位于同一版本目录")
            else:
                layout = load_json(layout_path)
                if layout.get("figure_id") != figure_id:
                    errors.append("layout report 的 figure_id 与候选不一致")
                errors.extend(
                    _diagram_layout_errors(
                        layout,
                        png_size=png_size,
                        minimum_font_size_pt=minimum_font_size_pt,
                    )
                )
    return {
        "figure_id": figure_id,
        "rendering_mode": rendering_mode,
        "success": not errors,
        "errors": errors,
        "candidate_outputs": [
            {"path": relative, "sha256": sha256_file(path)}
            for relative, path in zip(relatives, outputs, strict=True)
        ],
        "layout_report": layout_relative,
        "png_size_px": list(png_size),
        "pdf_size_pt": list(pdf_size),
        "aspect_ratio_relative_error": ratio_error,
        "minimum_font_size_pt": minimum_font_size_pt if rendering_mode == "diagram" else None,
    }


def promote_figure_candidate(
    run_dir: Path,
    *,
    figure_id: str,
    candidate_outputs: list[str],
    target_stem: str,
    rendering_mode: str,
    layout_report: str | None = None,
    human_reviewed: bool,
    human_review_notes: str,
) -> dict[str, Any]:
    """在机械 QA 和人工看图都通过后，将版本化候选晋级到 current。

    Args:
        run_dir: 当前运行目录。
        figure_id: 稳定图 ID。
        candidate_outputs: 版本化候选 PNG/PDF。
        target_stem: 不含后缀的 ``figures/current/`` 目标。
        rendering_mode: ``diagram`` 或普通 ``plot``。
        layout_report: 流程图几何报告。
        human_reviewed: 是否已分别打开 PNG 和 PDF 检查。
        human_review_notes: 人工检查结论。

    Returns:
        晋级回执，后续图表登记可绑定该回执。
    """
    if human_reviewed is not True or len(human_review_notes.strip()) < 12:
        raise ContractError("晋级 current 前必须人工检查 PNG/PDF，并填写 12 字以上结论")
    root = run_dir.resolve()
    target = resolve_inside(root, target_stem, must_exist=False)
    target_relative = relative_inside(root, target).as_posix()
    if Path(target_relative).suffix or not target_relative.startswith("figures/current/"):
        raise ContractError("target_stem 必须位于 figures/current/ 且不含扩展名")
    qa = audit_figure_candidate(
        root,
        figure_id=figure_id,
        candidate_outputs=candidate_outputs,
        rendering_mode=rendering_mode,
        layout_report=layout_report,
    )
    if not qa["success"]:
        raise ContractError("候选图未通过版式 QA: " + "；".join(qa["errors"]))
    candidates = [resolve_inside(root, item["path"], must_exist=True) for item in qa["candidate_outputs"]]
    version = candidates[0].parent.name
    receipt_path = root / "figures" / "promotions" / f"{figure_id}-{version}.json"
    if receipt_path.exists():
        raise ContractError("该候选版本已经晋级；继续修改时必须生成新的版本目录")
    promoted: list[dict[str, str]] = []
    for source in candidates:
        destination = target.with_suffix(source.suffix.casefold())
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        shutil.copy2(source, temporary)
        temporary.replace(destination)
        promoted.append(
            {
                "path": relative_inside(root, destination).as_posix(),
                "sha256": sha256_file(destination),
            }
        )
    receipt = {
        "schema_version": "1.0",
        "run_id": root.name,
        "figure_id": figure_id,
        "candidate_version": version,
        "qa": qa,
        "human_review": {
            "reviewed": True,
            "notes": human_review_notes.strip(),
        },
        "promoted_outputs": promoted,
        "promoted_at": utc_now(),
    }
    atomic_json(receipt_path, receipt)
    return {
        **receipt,
        "receipt": {
            "path": relative_inside(root, receipt_path).as_posix(),
            "sha256": sha256_file(receipt_path),
        },
    }
