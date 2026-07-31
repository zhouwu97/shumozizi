"""先审核独立图像候选，再晋级为论文 current 图。"""

from __future__ import annotations

import shutil
from math import isfinite
from pathlib import Path
from typing import Any

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    json_bytes,
    load_json,
    relative_inside,
    resolve_inside,
    sha256_bytes,
    sha256_file,
)
from shumozizi.simple.state import utc_now

_IMAGE_SUFFIXES = {".png", ".pdf"}
_FIGURE_ROLES = frozenset(
    {"model_understanding", "decisive_evidence", "insight", "stability"}
)
_PRESENTATION_ROLES = frozenset(
    {"data_portrait", "question_hero", "supporting", "appendix"}
)
_HUMAN_REVIEW_BOOLEAN_FIELDS = frozenset(
    {
        "reviewed",
        "paper_width_preview_checked",
        "mathematical_object_visible",
        "key_observation_visible",
        "mechanism_or_relation_visible",
        "constraint_or_boundary_visible",
        "decision_consequence_visible",
        "not_redundant_with_table",
        "caption_matches_figure",
        "font_readable",
        "panel_mapping_valid",
    }
)
_COMMON_HUMAN_REVIEW_REQUIREMENTS = frozenset(
    {
        "reviewed",
        "paper_width_preview_checked",
        "key_observation_visible",
        "not_redundant_with_table",
        "caption_matches_figure",
        "font_readable",
        "panel_mapping_valid",
    }
)
_ROLE_HUMAN_REVIEW_REQUIREMENTS = {
    "model_understanding": frozenset(
        {"mathematical_object_visible", "mechanism_or_relation_visible"}
    ),
    "decisive_evidence": frozenset(
        {"key_observation_visible", "constraint_or_boundary_visible"}
    ),
    "insight": frozenset(
        {
            "key_observation_visible",
            "mechanism_or_relation_visible",
            "decision_consequence_visible",
        }
    ),
    "stability": frozenset(
        {
            "key_observation_visible",
            "constraint_or_boundary_visible",
            "decision_consequence_visible",
        }
    ),
    "data_portrait": frozenset(
        {"mathematical_object_visible", "decision_consequence_visible"}
    ),
    "question_hero": frozenset(
        {"key_observation_visible", "decision_consequence_visible"}
    ),
    "supporting": frozenset(),
    "appendix": frozenset(),
}


def validate_human_figure_review(
    review: dict[str, Any],
    *,
    figure_role: str,
    presentation_role: str | None,
    require_element_binding: bool = True,
) -> dict[str, Any]:
    """验证人工复核已检查图的论证内容，而不只是文件可读性。

    Args:
        review: 人工检查结果。
        figure_role: 科学叙事角色。
        presentation_role: 可选呈现角色。
        require_element_binding: 是否要求 v1.2 的元素、面板与阅读顺序字段。

    Returns:
        可直接写入晋级回执的复核对象副本。

    Raises:
        ContractError: 角色无效、字段缺失或角色关键内容没有在图中兑现。
    """
    if not isinstance(review, dict):
        raise ContractError("human_review 必须是 JSON 对象")
    if figure_role not in _FIGURE_ROLES:
        raise ContractError("figure_role 必须是 " + "、".join(sorted(_FIGURE_ROLES)))
    if presentation_role is not None and presentation_role not in _PRESENTATION_ROLES:
        raise ContractError(
            "presentation_role 必须是 " + "、".join(sorted(_PRESENTATION_ROLES))
        )
    missing = sorted(_HUMAN_REVIEW_BOOLEAN_FIELDS - review.keys())
    if missing:
        raise ContractError("人工晋级复核缺少内容化字段: " + "、".join(missing))
    invalid = sorted(
        key for key in _HUMAN_REVIEW_BOOLEAN_FIELDS if not isinstance(review.get(key), bool)
    )
    if invalid:
        raise ContractError("人工晋级复核字段必须为布尔值: " + "、".join(invalid))
    issues = review.get("issues")
    if not isinstance(issues, list) or any(
        not isinstance(item, str) or not item.strip() for item in issues
    ):
        raise ContractError("人工晋级复核 issues 必须是字符串列表")
    if review.get("verdict") != "promote" or issues:
        raise ContractError("人工晋级复核必须 verdict=promote 且 issues 为空")
    normalized_visible: list[dict[str, str]] = []
    reading_order: list[str] = []
    panel_takeaways: dict[str, Any] = {}
    focal_claim = review.get("focal_claim", "")
    if require_element_binding:
        if not isinstance(focal_claim, str) or len(focal_claim.strip()) < 8:
            raise ContractError("人工晋级复核 focal_claim 必须是具体中心主张")
        visible_elements = review.get("visible_elements")
        if not isinstance(visible_elements, list) or not visible_elements:
            raise ContractError("人工晋级复核 visible_elements 必须是非空数组")
        for index, raw in enumerate(visible_elements):
            if not isinstance(raw, dict):
                raise ContractError(f"visible_elements[{index}] 必须是对象")
            normalized: dict[str, str] = {}
            for key in ("type", "label", "panel"):
                value = raw.get(key)
                if not isinstance(value, str) or not value.strip():
                    raise ContractError(
                        f"visible_elements[{index}].{key} 必须是非空文本"
                    )
                normalized[key] = value.strip()
            normalized_visible.append(normalized)
        raw_reading_order = review.get("reading_order")
        if (
            not isinstance(raw_reading_order, list)
            or not raw_reading_order
            or any(
                not isinstance(item, str) or not item.strip()
                for item in raw_reading_order
            )
            or len(raw_reading_order) != len(set(raw_reading_order))
        ):
            raise ContractError("人工晋级复核 reading_order 必须是唯一非空面板数组")
        reading_order = [item.strip() for item in raw_reading_order]
        raw_takeaways = review.get("panel_takeaways")
        if not isinstance(raw_takeaways, dict):
            raise ContractError("人工晋级复核 panel_takeaways 必须是对象")
        panel_takeaways = raw_takeaways
        for panel in reading_order:
            takeaway = panel_takeaways.get(panel)
            if not isinstance(takeaway, str) or len(takeaway.strip()) < 8:
                raise ContractError(f"人工晋级复核面板 {panel} 缺少具体 takeaway")
    required_true = set(_COMMON_HUMAN_REVIEW_REQUIREMENTS)
    required_true.update(_ROLE_HUMAN_REVIEW_REQUIREMENTS[figure_role])
    if presentation_role is not None:
        required_true.update(_ROLE_HUMAN_REVIEW_REQUIREMENTS[presentation_role])
    failed = sorted(key for key in required_true if review.get(key) is not True)
    if failed:
        roles = figure_role if presentation_role is None else f"{figure_role}/{presentation_role}"
        raise ContractError(
            f"{roles} 图未通过角色内容检查: " + "、".join(failed)
        )
    if not require_element_binding:
        return dict(review)
    return {
        **review,
        "focal_claim": focal_claim.strip(),
        "visible_elements": normalized_visible,
        "reading_order": reading_order,
        "panel_takeaways": {
            str(key): str(value).strip() for key, value in panel_takeaways.items()
        },
    }


def validate_visual_manifest(
    run_dir: Path,
    *,
    manifest_path: str,
    candidate_png: Path,
    human_review: dict[str, Any],
) -> dict[str, Any]:
    """把人工声明绑定到同版本 PNG 中登记的实际视觉元素。

    Args:
        run_dir: 当前运行目录。
        manifest_path: renderer 生成的视觉清单相对路径。
        candidate_png: 当前候选 PNG。
        human_review: 已规范化的人工复核对象。

    Returns:
        可写入晋级回执的 manifest 绑定摘要。

    Raises:
        ContractError: 哈希、面板、元素或边界框与当前候选不一致。
    """
    root = run_dir.resolve()
    path = resolve_inside(root, manifest_path, must_exist=True)
    if path.parent.resolve() != candidate_png.parent.resolve():
        raise ContractError("visual_manifest 必须与候选 PNG/PDF 位于同一版本目录")
    manifest = load_json(path)
    if manifest.get("schema_version") != "1.0":
        raise ContractError("visual_manifest.schema_version 必须为 1.0")
    output_sha256 = manifest.get("output_sha256")
    current_sha256 = sha256_file(candidate_png)
    if output_sha256 != current_sha256:
        raise ContractError("visual_manifest 的 output_sha256 与当前候选 PNG 不一致")
    canvas = manifest.get("canvas")
    if not isinstance(canvas, dict):
        raise ContractError("visual_manifest 缺少 canvas")
    try:
        from PIL import Image

        with Image.open(candidate_png) as image:
            png_size = image.size
    except OSError as exc:
        raise ContractError(f"无法复验 visual_manifest 画布: {exc}") from exc
    if [canvas.get("width"), canvas.get("height")] != list(png_size):
        raise ContractError("visual_manifest 的 canvas 与候选 PNG 尺寸不一致")
    panels = manifest.get("panels")
    if (
        not isinstance(panels, list)
        or not panels
        or any(not isinstance(item, str) or not item.strip() for item in panels)
        or len(panels) != len(set(panels))
    ):
        raise ContractError("visual_manifest.panels 必须是唯一非空面板数组")
    panel_set = set(panels)
    missing_reading_panels = sorted(set(human_review["reading_order"]) - panel_set)
    if missing_reading_panels:
        raise ContractError(
            "reading_order 引用了 manifest 中不存在的面板: "
            + "、".join(missing_reading_panels)
        )
    unknown_takeaway_panels = sorted(set(human_review["panel_takeaways"]) - panel_set)
    if unknown_takeaway_panels:
        raise ContractError(
            "panel_takeaways 引用了 manifest 中不存在的面板: "
            + "、".join(unknown_takeaway_panels)
        )
    elements = manifest.get("elements")
    if not isinstance(elements, list) or not elements:
        raise ContractError("visual_manifest.elements 必须是非空数组")
    keys: set[tuple[str, str, str]] = set()
    labels: set[str] = set()
    for index, raw in enumerate(elements):
        if not isinstance(raw, dict):
            raise ContractError(f"visual_manifest.elements[{index}] 必须是对象")
        element_type = raw.get("type")
        panel = raw.get("panel")
        label = raw.get("label")
        if not all(isinstance(value, str) and value.strip() for value in (element_type, panel, label)):
            raise ContractError(
                f"visual_manifest.elements[{index}] 需要非空 type、panel 和 label"
            )
        if panel not in panel_set:
            raise ContractError(f"visual_manifest 元素 {label} 引用了不存在的面板 {panel}")
        bbox = raw.get("bbox")
        if (
            not isinstance(bbox, list)
            or len(bbox) != 4
            or any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not isfinite(float(value))
                for value in bbox
            )
        ):
            raise ContractError(f"visual_manifest 元素 {label} 的 bbox 必须是四个有限数")
        x0, y0, x1, y1 = (float(value) for value in bbox)
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise ContractError(f"visual_manifest 元素 {label} 的 bbox 超出画布")
        if raw.get("paper_width_visible") is not True:
            raise ContractError(f"visual_manifest 元素 {label} 未通过论文宽度裁切检查")
        normalized_key = (element_type.strip(), label.strip(), panel.strip())
        if normalized_key in keys:
            raise ContractError(f"visual_manifest 元素重复: {normalized_key}")
        keys.add(normalized_key)
        labels.add(label.strip())
    declared_labels = manifest.get("labels")
    if not isinstance(declared_labels, list) or set(declared_labels) != labels:
        raise ContractError("visual_manifest.labels 必须与 elements 中的可见标签完全一致")
    for visible in human_review["visible_elements"]:
        key = (visible["type"], visible["label"], visible["panel"])
        if key not in keys:
            raise ContractError(
                "人工声明的可见元素未出现在 visual_manifest: " + "/".join(key)
            )
    return {
        "path": relative_inside(root, path).as_posix(),
        "sha256": sha256_file(path),
        "output_sha256": current_sha256,
        "panels": panels,
        "verified_element_types": sorted({key[0] for key in keys}),
        "verified_visible_elements": human_review["visible_elements"],
    }


def _required_learned_visual_elements(run_dir: Path, figure_id: str) -> set[str]:
    """返回当前图从论文视觉模式明确承诺的可见元素类型。"""
    plan_path = run_dir / "figures/FIGURE_PLAN.json"
    retrieval_path = run_dir / "knowledge/analysis-retrieval.json"
    if not plan_path.is_file() or not retrieval_path.is_file():
        return set()
    try:
        plan = load_json(plan_path)
        retrieval = load_json(retrieval_path)
    except (OSError, ValueError):
        return set()
    figure = next(
        (
            item
            for item in plan.get("figures", [])
            if isinstance(item, dict) and item.get("figure_id") == figure_id
        ),
        None,
    )
    if figure is None:
        return set()
    selected = {
        str(value)
        for value in figure.get("learned_pattern_ids", [])
        if isinstance(value, str)
    }
    if not selected:
        return set()
    return {
        str(element)
        for card in retrieval.get("matched_cards", [])
        if isinstance(card, dict)
        for pattern in card.get("visual_patterns", [])
        if isinstance(pattern, dict) and pattern.get("pattern_id") in selected
        for element in pattern.get("visible_elements", [])
        if isinstance(element, str)
    }


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


def _numeric_pair(
    item: dict[str, Any], key: str, *, label: str
) -> tuple[float, float] | None:
    """读取布局报告中的有限递增数值区间。"""
    value = item.get(key)
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(
            not isinstance(number, (int, float))
            or isinstance(number, bool)
            or not isfinite(float(number))
            for number in value
        )
    ):
        return None
    lower, upper = float(value[0]), float(value[1])
    if upper <= lower:
        return None
    return lower, upper


def _numeric_triple(item: dict[str, Any], key: str) -> tuple[float, float, float] | None:
    """读取布局报告中的三个有限数值。"""
    value = item.get(key)
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(
            not isinstance(number, (int, float))
            or isinstance(number, bool)
            or not isfinite(float(number))
            for number in value
        )
    ):
        return None
    return tuple(float(number) for number in value)


def _plot_layout_errors(
    report: dict[str, Any], *, png_ratio: float, minimum_font_size_pt: float
) -> list[str]:
    """检查统计图的论文尺寸、轴域利用、图例和结论强调。"""
    errors: list[str] = []
    paper_size = report.get("paper_size_cm")
    if not isinstance(paper_size, dict):
        errors.append("统计图 layout report 缺少 paper_size_cm")
    else:
        width = paper_size.get("width")
        height = paper_size.get("height")
        if (
            not isinstance(width, (int, float))
            or isinstance(width, bool)
            or not isinstance(height, (int, float))
            or isinstance(height, bool)
            or not 8 <= float(width) <= 20
            or not 5 <= float(height) <= 24
        ):
            errors.append("统计图论文尺寸必须位于宽 8--20 cm、高 5--24 cm")
        else:
            paper_ratio = float(width) / float(height)
            if abs(paper_ratio - png_ratio) / png_ratio > 0.05:
                errors.append("layout report 的论文尺寸比例与 PNG 不一致")
            if paper_ratio > 2.2 and len(str(report.get("wide_figure_reason", "")).strip()) < 12:
                errors.append("超宽统计图必须说明在论文页宽下仍可读的具体理由")

    reported_font = report.get("minimum_font_size_pt")
    if (
        not isinstance(reported_font, (int, float))
        or isinstance(reported_font, bool)
        or float(reported_font) < minimum_font_size_pt
    ):
        errors.append(f"统计图最小字号不得小于 {minimum_font_size_pt:g} pt")
    if report.get("colorblind_safe") is not True:
        errors.append("统计图必须声明并采用色盲安全配色")
    if report.get("locale_consistent") is not True:
        errors.append("统计图标题、坐标和标注语言必须与论文一致")

    axes = report.get("axes")
    if not isinstance(axes, list) or not axes:
        return [*errors, "统计图 layout report 缺少 axes"]
    if len(axes) > 4:
        errors.append("正文统计图最多使用四个具有连续论证关系的面板")
    primary_id = report.get("primary_panel_id")
    identifiers: set[str] = set()
    primary_found = False
    for index, axis in enumerate(axes):
        if not isinstance(axis, dict):
            errors.append(f"统计图 axes[{index}] 必须是对象")
            continue
        axis_id = axis.get("id")
        if not isinstance(axis_id, str) or not axis_id.strip() or axis_id in identifiers:
            errors.append(f"统计图 axes[{index}] 缺少唯一 id")
            continue
        identifiers.add(axis_id)
        is_primary = axis_id == primary_id and axis.get("role") == "primary"
        primary_found = primary_found or is_primary
        projection = axis.get("projection", "2d")
        if projection not in {"2d", "3d"}:
            errors.append(f"面板 {axis_id} 的 projection 必须为 2d 或 3d")
            projection = "2d"
        dimensions = [("x", "横轴"), ("y", "纵轴")]
        if projection == "3d":
            dimensions.append(("z", "纵深轴"))
        for dimension, title in dimensions:
            limits = _numeric_pair(axis, f"{dimension}_limits", label=axis_id)
            data_range = _numeric_pair(axis, f"{dimension}_data_range", label=axis_id)
            if limits is None or data_range is None:
                errors.append(f"面板 {axis_id} 的{title}范围必须是有限递增区间")
                continue
            tolerance = (limits[1] - limits[0]) * 1e-6
            if data_range[0] < limits[0] - tolerance or data_range[1] > limits[1] + tolerance:
                errors.append(f"面板 {axis_id} 的{title}数据范围超出显示范围")
                continue
            occupancy = (data_range[1] - data_range[0]) / (limits[1] - limits[0])
            if occupancy < 0.2:
                fixed_reason = str(axis.get("low_occupancy_reason", "")).strip()
                if axis.get("axis_policy") != "fixed_semantic" or len(fixed_reason) < 12:
                    errors.append(
                        f"面板 {axis_id} 的{title}数据占用率仅 {occupancy:.1%}，"
                        "应收紧轴域或说明固定语义范围"
                    )
        if projection == "3d":
            aspect = _numeric_triple(axis, "data_aspect_ratio")
            if aspect is None or min(aspect) <= 0 or max(aspect) / min(aspect) > 1.02:
                errors.append(f"三维面板 {axis_id} 必须使用 [1, 1, 1] 等比例坐标")
            if axis.get("camera_projection") != "orthographic":
                errors.append(f"三维面板 {axis_id} 必须使用正交投影避免透视距离错觉")
            camera_view = axis.get("camera_view")
            if not isinstance(camera_view, dict) or any(
                not isinstance(camera_view.get(key), (int, float))
                or isinstance(camera_view.get(key), bool)
                or not isfinite(float(camera_view[key]))
                for key in ("azimuth", "elevation")
            ):
                errors.append(f"三维面板 {axis_id} 必须声明有限的相机方位角和仰角")
            coordinate_unit = axis.get("coordinate_unit")
            if not isinstance(coordinate_unit, str) or not coordinate_unit.strip():
                errors.append(f"三维面板 {axis_id} 必须声明非空坐标单位")
            if axis.get("trajectory_direction_labeled") is not True:
                errors.append(f"三维面板 {axis_id} 必须标明轨迹方向或明确无轨迹")
        if axis.get("legend_overlaps_data") is not False:
            errors.append(f"面板 {axis_id} 的图例遮挡数据或未完成避让检查")
        if is_primary and axis.get("takeaway_annotation") is not True:
            errors.append(f"主面板 {axis_id} 缺少可直接识别的结论标注")
        if is_primary and axis.get("decision_markers_labeled") is False:
            errors.append(f"主面板 {axis_id} 的决策点没有直接标签")
    if not isinstance(primary_id, str) or not primary_found:
        errors.append("统计图必须指定一个 role=primary 的 primary_panel_id")
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
    """审核工作图的可读性，并检查流程图或统计图布局报告。

    Args:
        run_dir: 当前运行目录。
        figure_id: 稳定图 ID。
        candidate_outputs: 同一 work 版本目录内的 PNG 和 PDF。
        rendering_mode: ``diagram`` 或普通 ``plot``。
        layout_report: 与候选同目录的流程图几何或统计图语义布局 JSON。
        minimum_font_size_pt: 图内最小字号。
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
    expected_prefix = f"figures/work/{figure_id}/"
    legacy_prefix = f"figures/candidates/{figure_id}/"
    relatives = [relative_inside(root, path).as_posix() for path in outputs]
    if any(
        not value.startswith(expected_prefix) and not value.startswith(legacy_prefix)
        for value in relatives
    ):
        raise ContractError(f"工作图必须位于 {expected_prefix}<version>/")
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
    if layout_report is None:
        errors.append(f"{rendering_mode} 候选缺少 layout report")
    else:
        layout_path = resolve_inside(root, layout_report, must_exist=True)
        layout_relative = relative_inside(root, layout_path).as_posix()
        if layout_path.parent.resolve() not in parents:
            errors.append("layout report 必须与候选 PNG/PDF 位于同一版本目录")
        else:
            layout = load_json(layout_path)
            if layout.get("figure_id") != figure_id:
                errors.append("layout report 的 figure_id 与候选不一致")
            elif rendering_mode == "diagram":
                errors.extend(
                    _diagram_layout_errors(
                        layout,
                        png_size=png_size,
                        minimum_font_size_pt=minimum_font_size_pt,
                    )
                )
            else:
                errors.extend(
                    _plot_layout_errors(
                        layout,
                        png_ratio=png_ratio,
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
        "minimum_font_size_pt": minimum_font_size_pt,
    }


def promote_figure_candidate(
    run_dir: Path,
    *,
    figure_id: str,
    candidate_outputs: list[str],
    target_stem: str,
    rendering_mode: str,
    layout_report: str | None = None,
    figure_role: str,
    human_review: dict[str, Any],
    visual_manifest: str | None = None,
    presentation_role: str | None = None,
) -> dict[str, Any]:
    """在机械 QA 和内容化人工复核都通过后，将工作图晋级到 current。

    Args:
        run_dir: 当前运行目录。
        figure_id: 稳定图 ID。
        candidate_outputs: 版本化工作图 PNG/PDF。
        target_stem: 不含后缀的 ``figures/current/`` 目标。
        rendering_mode: ``diagram`` 或普通 ``plot``。
        layout_report: 与候选同目录的流程图几何或统计图语义布局报告。
        figure_role: model_understanding、decisive_evidence、insight 或 stability。
        human_review: 含论文宽度预览、对象、观察、机制、边界和决策检查的复核对象。
        visual_manifest: renderer 生成且与候选 PNG 同版本的视觉元素清单。
        presentation_role: 可选的 data_portrait、question_hero、supporting 或 appendix。

    Returns:
        晋级回执，后续图表登记可绑定该回执。
    """
    validated_review = validate_human_figure_review(
        human_review,
        figure_role=figure_role,
        presentation_role=presentation_role,
    )
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
        raise ContractError("工作图未通过版式 QA: " + "；".join(qa["errors"]))
    candidates = [resolve_inside(root, item["path"], must_exist=True) for item in qa["candidate_outputs"]]
    if visual_manifest is None:
        raise ContractError("高级或自定义工作图缺少 renderer 生成的 visual_manifest.json")
    candidate_png = next(path for path in candidates if path.suffix.casefold() == ".png")
    manifest_binding = validate_visual_manifest(
        root,
        manifest_path=visual_manifest,
        candidate_png=candidate_png,
        human_review=validated_review,
    )
    required_learned_elements = _required_learned_visual_elements(root, figure_id)
    manifest_types = set(manifest_binding["verified_element_types"])
    reviewed_types = {
        str(item["type"])
        for item in validated_review.get("visible_elements", [])
        if isinstance(item, dict) and isinstance(item.get("type"), str)
    }
    missing_manifest = sorted(required_learned_elements - manifest_types)
    missing_review = sorted(required_learned_elements - reviewed_types)
    if missing_manifest:
        raise ContractError(
            "学习视觉模式要求的元素未出现在 visual_manifest: "
            + "、".join(missing_manifest)
        )
    if missing_review:
        raise ContractError(
            "人工复核未确认学习视觉模式要求的可见元素: "
            + "、".join(missing_review)
        )
    version = candidates[0].parent.name
    work_digest = sha256_bytes(
        json_bytes(
            [
                item["sha256"]
                for item in qa["candidate_outputs"]
            ]
        )
    )[:12]
    receipt_path = (
        root
        / "figures"
        / "promotions"
        / f"{figure_id}-{version}-{work_digest}.json"
    )
    if receipt_path.exists():
        raise ContractError("该 work 内容已经晋级；继续修改后可在原 work 路径重新晋级")
    promoted: list[dict[str, str]] = []
    for source in candidates:
        destination = target.with_suffix(source.suffix.casefold())
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_file():
            archive = (
                root
                / "figures"
                / "archive"
                / figure_id
                / f"{utc_now().replace(':', '-').replace('+', '_')}-{version}"
                / destination.name
            )
            archive.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, archive)
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
        "schema_version": "1.2",
        "run_id": root.name,
        "figure_id": figure_id,
        "figure_role": figure_role,
        "presentation_role": presentation_role,
        "candidate_version": version,
        "qa": qa,
        "human_review": validated_review,
        "visual_manifest": manifest_binding,
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
