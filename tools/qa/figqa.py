"""检查图像可读性及由绘图脚本导出的文字边界重叠。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError


def find_overlaps(boxes: list[dict[str, Any]]) -> list[dict[str, str]]:
    """找出任意两个相交的矩形文字边界。

    Args:
        boxes: 包含 ``id``、``x0``、``y0``、``x1`` 和 ``y1`` 的边界列表。

    Returns:
        所有相交边界对。
    """
    overlaps: list[dict[str, str]] = []
    for index, first in enumerate(boxes):
        for second in boxes[index + 1 :]:
            try:
                intersects = (
                    float(first["x0"]) < float(second["x1"])
                    and float(first["x1"]) > float(second["x0"])
                    and float(first["y0"]) < float(second["y1"])
                    and float(first["y1"]) > float(second["y0"])
                )
            except (KeyError, TypeError, ValueError):
                continue
            if intersects:
                overlaps.append({"first": str(first.get("id", index)), "second": str(second.get("id", index + 1))})
    return overlaps


def audit_figure(path: Path, boxes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """审计单个图像文件。

    Args:
        path: PNG、JPEG、TIFF 等 Pillow 可读取的图像。
        boxes: 可选的绘图文字边界；推荐由绘图脚本在保存前导出。

    Returns:
        图像尺寸、可读取性和文字重叠结果。
    """
    payload: dict[str, Any] = {
        "path": str(path),
        "readable": False,
        "width": None,
        "height": None,
        "overlaps": find_overlaps(boxes or []),
        "errors": [],
    }
    if not path.is_file():
        payload["errors"].append("图像不存在")
        return payload
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            payload["width"], payload["height"] = image.size
        payload["readable"] = True
    except (OSError, UnidentifiedImageError) as exc:
        payload["errors"].append(f"图像无法读取: {exc}")
    if payload["readable"] and (payload["width"] < 200 or payload["height"] < 120):
        payload["errors"].append("图像分辨率过低")
    if payload["overlaps"]:
        payload["errors"].append("检测到导出文字边界重叠")
    return payload


def main() -> int:
    """提供 Windows 可直接调用的图表 QA 入口。

    Returns:
        没有错误时为零。
    """
    parser = argparse.ArgumentParser(description="检查图像和可选的文字边界重叠")
    parser.add_argument("image", nargs="+")
    parser.add_argument("--boxes", help="包含 {figure_path: [bbox, ...]} 的 JSON 文件")
    args = parser.parse_args()
    box_map: dict[str, list[dict[str, Any]]] = {}
    if args.boxes:
        loaded = json.loads(Path(args.boxes).read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            box_map = {str(key): value for key, value in loaded.items() if isinstance(value, list)}
    reports = [audit_figure(Path(item), box_map.get(item, [])) for item in args.image]
    payload = {"figures": reports, "success": not any(item["errors"] for item in reports)}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
