"""scibox-diagram 生产桥：content JSON → 原 sci-box 生成器 → .drawio → 机器提取 → work 候选。

原则：**机器能从 DrawIO XML 知道的全部机器做**（节点框、文字框、箭头、画布、字号），
Agent 只负责“这张图好不好看、表达对不对”。产出 ``figures/work/<id>/<version>/`` 下的
``.drawio`` + PNG/PDF + 机器生成的 ``layout_report.json``（diagram 几何格式）与
``visual_manifest.json``，随后用 ``promote_figure_candidate.py --rendering-mode diagram``
晋级（命令由本脚本输出）。

PNG/PDF 导出依赖 draw.io 命令行（上游 ``export_figure.py`` 的要求）；未安装时只产出
``.drawio`` 与布局/清单，导出与晋级留待人工在 diagrams.net 导出后执行。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError, atomic_json, resolve_inside  # noqa: E402

_GENERATORS = {
    "roadmap-5band": ("roadmap_5band.py", "roadmap-5band"),
    "framework-3col": ("framework_3col.py", "framework-3col"),
    "stageflow-3col": ("stageflow_3col.py", "stageflow-3col"),
    "taskflow-land": ("taskflow_land.py", "taskflow-land"),
}

_FONT_SIZE_RE = re.compile(r"fontSize=([0-9.]+)")


def _style_font_size(style: str, default: float = 12.0) -> float:
    match = _FONT_SIZE_RE.search(style or "")
    return float(match.group(1)) if match else default


def _float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def generate_drawio(template_id: str, content_json: Path, out_drawio: Path) -> Path:
    """调用原 sci-box 生成器产出 .drawio（不重写上游逻辑）。"""
    if template_id not in _GENERATORS:
        raise ContractError(
            f"scibox-diagram 生成器仅支持 {', '.join(sorted(_GENERATORS))}；"
            "custom/replica 请直接提供 .drawio"
        )
    script_name, _ = _GENERATORS[template_id]
    script = (
        REPO_ROOT
        / "skills"
        / "sci-box"
        / "scibox-diagram"
        / "scripts"
        / script_name
    )
    if not script.is_file():
        raise ContractError(f"scibox-diagram 生成器缺失: {script}")
    out_drawio.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, str(script), str(content_json), "-o", str(out_drawio)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    if proc.returncode != 0 or not out_drawio.is_file():
        raise ContractError(
            f"scibox-diagram 生成失败 ({template_id}): {proc.stderr[-1500:]}"
        )
    return out_drawio


def parse_drawio(drawio_path: Path) -> dict[str, Any]:
    """从 .drawio XML 机器提取画布、节点框、文字框与箭头。"""
    tree = ET.parse(drawio_path)
    root = tree.getroot()
    model = root.find(".//mxGraphModel")
    if model is None:
        raise ContractError("drawio 缺少 mxGraphModel")
    page_width = _float(model.get("pageWidth"), 1000.0)
    page_height = _float(model.get("pageHeight"), 800.0)
    cells: dict[str, dict[str, Any]] = {}
    for cell in model.findall(".//mxCell"):
        cell_id = cell.get("id")
        if cell_id is None:
            continue
        geometry = cell.find("mxGeometry")
        style = cell.get("style") or ""
        is_edge = cell.get("edge") == "1"
        record: dict[str, Any] = {
            "id": cell_id,
            "edge": is_edge,
            "value": (cell.get("value") or "").strip(),
            "style": style,
        }
        if geometry is not None:
            record["x"] = _float(geometry.get("x"))
            record["y"] = _float(geometry.get("y"))
            record["width"] = _float(geometry.get("width"))
            record["height"] = _float(geometry.get("height"))
            point = geometry.find("mxPoint")
            if point is not None:
                record["point"] = [_float(point.get("x")), _float(point.get("y"))]
        if is_edge:
            record["source"] = cell.get("source")
            record["target"] = cell.get("target")
        cells[cell_id] = record

    node_boxes: list[dict[str, Any]] = []
    text_boxes: list[dict[str, Any]] = []
    for cell_id, record in cells.items():
        if record["edge"]:
            continue
        if record["value"]:
            text_boxes.append(
                {
                    "id": f"text-{cell_id}",
                    "x": record.get("x", 0),
                    "y": record.get("y", 0),
                    "width": record.get("width", 10),
                    "height": record.get("height", 10),
                    "font_size_pt": _style_font_size(record["style"]),
                    "node_id": cell_id,
                }
            )
        if record.get("width", 0) > 0 and record.get("height", 0) > 0:
            node_boxes.append(
                {
                    "id": cell_id,
                    "x": record.get("x", 0),
                    "y": record.get("y", 0),
                    "width": record["width"],
                    "height": record["height"],
                }
            )

    node_centers = {
        item["id"]: (
            item["x"] + item["width"] / 2,
            item["y"] + item["height"] / 2,
        )
        for item in node_boxes
    }
    arrows: list[dict[str, Any]] = []
    for cell_id, record in cells.items():
        if not record["edge"]:
            continue
        source_id = record.get("source")
        target_id = record.get("target")
        if source_id not in node_centers or target_id not in node_centers:
            continue
        source_point = record.get("point") or list(node_centers[source_id])
        target_point = list(node_centers[target_id])
        arrows.append(
            {
                "id": cell_id,
                "source_node_id": source_id,
                "target_node_id": target_id,
                "points": [source_point, target_point],
            }
        )

    return {
        "canvas": {"width": page_width, "height": page_height},
        "node_boxes": node_boxes,
        "text_boxes": text_boxes,
        "arrows": arrows,
        "alignment_tolerance_px": 8,
    }


def write_diagram_layout_report(drawio_path: Path, figure_id: str) -> dict[str, Any]:
    """从 .drawio 机器生成 diagram 布局报告，返回提取结构。"""
    extracted = parse_drawio(drawio_path)
    report = {
        "schema_name": "diagram_layout_report",
        "schema_version": "1.0",
        "figure_id": figure_id,
        "canvas": extracted["canvas"],
        "node_boxes": extracted["node_boxes"],
        "text_boxes": extracted["text_boxes"],
        "arrows": extracted["arrows"],
        "alignment_tolerance_px": extracted["alignment_tolerance_px"],
        "machine_extracted": True,
    }
    layout_path = drawio_path.with_suffix(".layout_report.json")
    atomic_json(layout_path, report)
    return extracted


def write_diagram_visual_manifest(drawio_path: Path, png_path: Path, extracted: dict[str, Any]) -> Path:
    """从提取结构生成与候选 PNG 哈希绑定的最小 visual_manifest。"""
    from shumozizi.core.io import sha256_file

    canvas = extracted["canvas"]
    width, height = float(canvas["width"]), float(canvas["height"])
    elements: list[dict[str, Any]] = []
    seen: set[str] = set()
    for text in extracted["text_boxes"]:
        label = text["id"]
        if label in seen:
            continue
        seen.add(label)
        elements.append(
            {
                "type": "text",
                "label": label,
                "panel": "main",
                "bbox": [
                    round(text["x"] / width, 6),
                    round(text["y"] / height, 6),
                    round((text["x"] + text["width"]) / width, 6),
                    round((text["y"] + text["height"]) / height, 6),
                ],
                "paper_width_visible": True,
            }
        )
    if not elements:
        elements = [
            {
                "type": "diagram",
                "label": "diagram",
                "panel": "main",
                "bbox": [0.0, 0.0, 1.0, 1.0],
                "paper_width_visible": True,
            }
        ]
    manifest_path = drawio_path.with_suffix(".visual_manifest.json")
    atomic_json(
        manifest_path,
        {
            "schema_version": "1.0",
            "output_sha256": sha256_file(png_path),
            "canvas": {"width": int(width), "height": int(height)},
            "panels": ["main"],
            "labels": [item["label"] for item in elements],
            "elements": elements,
        },
    )
    return manifest_path


def render_diagram_candidate(
    run_dir: Path,
    *,
    template_id: str,
    content_json: str,
    output_prefix: str,
    figure_id: str,
) -> dict[str, Any]:
    """生成 .drawio、机器提取布局/清单、尝试导出 PNG/PDF，返回 work 候选信息与晋级命令。"""
    root = run_dir.resolve()
    content = resolve_inside(root, content_json, must_exist=True)
    stem = resolve_inside(root, output_prefix)
    relative = stem.relative_to(root).as_posix()
    if not relative.startswith("figures/work/") or stem.suffix:
        raise ContractError("output_prefix 必须是 figures/work/<id>/<version>/ 下的不含扩展名路径")
    drawio_path = stem.with_suffix(".drawio")
    generate_drawio(template_id, content, drawio_path)
    extracted = write_diagram_layout_report(drawio_path, figure_id)

    # 运行上游 check_layout.py 作独立版式体检（结果只作提示，晋级仍以
    # promote 的 diagram QA 为准）。
    check_script = (
        REPO_ROOT
        / "skills"
        / "sci-box"
        / "scibox-diagram"
        / "scripts"
        / "check_layout.py"
    )
    check_result: str = ""
    if check_script.is_file():
        check_proc = subprocess.run(
            [sys.executable, str(check_script), str(drawio_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        check_result = (check_proc.stdout or check_proc.stderr or "").strip()

    # 导出 PNG/PDF（依赖 draw.io 命令行）；缺省时留待人工导出。
    png_path = stem.with_suffix(".png")
    pdf_path = stem.with_suffix(".pdf")
    export_script = (
        REPO_ROOT / "skills" / "sci-box" / "scibox-diagram" / "scripts" / "export_figure.py"
    )
    exported = False
    if shutil.which("drawio") is not None:
        proc = subprocess.run(
            [sys.executable, str(export_script), str(drawio_path)],
            capture_output=True,
            text=True,
            timeout=600,
        )
        exported = proc.returncode == 0 and png_path.is_file() and pdf_path.is_file()
    artifacts: dict[str, str] = {}
    if exported:
        artifacts["visual_manifest"] = write_diagram_visual_manifest(
            drawio_path, png_path, extracted
        ).relative_to(root).as_posix()
        artifacts["outputs"] = [
            f"{relative}.drawio",
            f"{relative}.png",
            f"{relative}.pdf",
        ]
    else:
        artifacts["outputs"] = [f"{relative}.drawio"]
        artifacts["export"] = "pending_requires_drawio_cli"
    layout_report = drawio_path.with_suffix(".layout_report.json").relative_to(root).as_posix()
    promote = _diagram_promote_command(root.name, figure_id, relative, layout_report, exported)
    return {
        "success": True,
        "mode": "scibox-diagram",
        "template_id": template_id,
        "figure_id": figure_id,
        "drawio": drawio_path.relative_to(root).as_posix(),
        "layout_report": layout_report,
        "check_layout": check_result or None,
        "artifacts": artifacts,
        "promote": promote,
    }


def _diagram_promote_command(
    run_name: str, figure_id: str, relative: str, layout_report: str, exported: bool
) -> str:
    if not exported:
        return (
            f"# 尚未导出 PNG/PDF（缺 draw.io 命令行）：用 diagrams.net 打开 "
            f"{relative}.drawio → File → Export as PNG/PDF 到同目录后，再执行晋级。"
        )
    return (
        f"# 1) 打开 {relative}.png 逐块核对（文字溢出/箭头方向/数值）；"
        "写入同目录 *.human-review.json\n"
        f"python scripts/figures/promote_figure_candidate.py runs/{run_name} \\\n"
        f"  --figure-id {figure_id} \\\n"
        f"  --candidate {relative}.png --candidate {relative}.pdf \\\n"
        f"  --target-stem figures/current/{figure_id} \\\n"
        f"  --rendering-mode diagram \\\n"
        f"  --layout-report {layout_report} \\\n"
        f"  --visual-manifest {relative}.visual_manifest.json \\\n"
        f"  --figure-role <model_understanding|decisive_evidence|insight|stability> \\\n"
        f"  [--presentation-role <data_portrait|question_hero|supporting|appendix>] \\\n"
        f"  --human-review figures/work/{figure_id}/<version>/{figure_id}.human-review.json"
    )


def main() -> int:
    """生成 scibox-diagram work 候选并输出晋级命令。"""
    parser = argparse.ArgumentParser(description="scibox-diagram 生产桥：content JSON → work 候选")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--template", required=True, choices=sorted(_GENERATORS))
    parser.add_argument("--content-json", required=True, help="运行目录内的 content JSON 相对路径")
    parser.add_argument("--figure-id", required=True)
    parser.add_argument("--output-prefix", required=True)
    args = parser.parse_args()
    try:
        payload = render_diagram_candidate(
            args.run_dir,
            template_id=args.template,
            content_json=args.content_json,
            output_prefix=args.output_prefix,
            figure_id=args.figure_id,
        )
    except (ContractError, OSError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
