"""登记并复验 v3 的真实结果图表，不评价其科学结论。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    load_json,
    relative_inside,
    resolve_inside,
    sha256_file,
)
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import utc_now

INDEX_PATH = Path("figures/index.json")


def _schema() -> dict[str, Any]:
    """读取 v3 图表索引 Schema。"""
    return load_json(resolve_repo_root(Path(__file__)) / "schemas/simple_figure_index.schema.json")


def require_figure_index(payload: dict[str, Any]) -> None:
    """确保图表索引符合轻量追溯协议。

    Args:
        payload: 图表索引对象。

    Raises:
        ContractError: 图表索引不符合 Schema。
    """
    validator = Draft202012Validator(_schema(), format_checker=FormatChecker())
    errors = [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    ]
    if errors:
        raise ContractError("; ".join(errors))


def read_figure_index(run_dir: Path) -> dict[str, Any]:
    """读取并验证图表索引。

    Args:
        run_dir: v3 运行目录。

    Returns:
        已验证的图表索引。
    """
    payload = load_json(run_dir / INDEX_PATH)
    require_figure_index(payload)
    return payload


def _file_record(run_dir: Path, relative: str) -> dict[str, str]:
    """生成一个已存在运行内文件的路径和哈希记录。"""
    path = resolve_inside(run_dir, relative, must_exist=True)
    return {"path": relative_inside(run_dir, path).as_posix(), "sha256": sha256_file(path)}


def register_figure(
    run_dir: Path,
    *,
    figure_id: str,
    template_id: str,
    result_id: str,
    input_result: str,
    reference_template: str,
    renderer_script: str,
    outputs: list[str],
    text_boxes: str,
) -> dict[str, Any]:
    """登记一次真实图表生成并替代同 ID 的旧 current 图。

    Args:
        run_dir: v3 运行目录。
        figure_id: 用户可识别的图表 ID。
        template_id: 已接入的模板 ID。
        result_id: 数据来源结果 ID。
        input_result: 本次读取的 JSON 输出。
        reference_template: 复制到运行目录的保留模板源文件。
        renderer_script: 本仓 v3 渲染器副本。
        outputs: PNG、PDF、SVG 三种输出。
        text_boxes: 绘图 artist 文字边界输出。

    Returns:
        新图表索引条目。

    Raises:
        ContractError: 任一文件、结果或 ID 不满足协议。
    """
    if not figure_id.replace("-", "").replace("_", "").replace(".", "").isalnum():
        raise ContractError(f"figure_id 不合法: {figure_id}")
    index = read_figure_index(run_dir)
    results = read_result_index(run_dir)
    source_result = next((item for item in results["results"] if item["result_id"] == result_id), None)
    if source_result is None or source_result["status"] != "current" or not source_result["execution_valid"]:
        raise ContractError("图表只能绑定 current 且 execution_valid=true 的真实结果")
    input_record = _file_record(run_dir, input_result)
    if input_record["path"] not in source_result["output_hashes"]:
        raise ContractError("图表输入必须是所绑定结果的已登记输出")
    if input_record["sha256"] != source_result["output_hashes"][input_record["path"]]:
        raise ContractError("图表输入哈希与所绑定结果不一致")
    output_records = [_file_record(run_dir, item) for item in outputs]
    suffixes = {Path(item["path"]).suffix.lower() for item in output_records}
    if suffixes != {".png", ".pdf", ".svg"} or any(
        resolve_inside(run_dir, item["path"], must_exist=True).stat().st_size == 0
        for item in output_records
    ):
        raise ContractError("图表必须生成非空 PNG、PDF、SVG 三种输出")
    entry = {
        "figure_id": figure_id,
        "template_id": template_id,
        "result_id": result_id,
        "input_result": input_record,
        "reference_template": _file_record(run_dir, reference_template),
        "renderer_script": _file_record(run_dir, renderer_script),
        "outputs": output_records,
        "text_boxes": _file_record(run_dir, text_boxes),
        "status": "current",
        "paper_allowed": True,
        "demo": False,
        "created_at": utc_now(),
    }
    for existing in index["figures"]:
        if existing["figure_id"] == figure_id and existing["status"] == "current":
            existing["status"] = "superseded"
    index["figures"].append(entry)
    require_figure_index(index)
    atomic_json(run_dir / INDEX_PATH, index)
    return entry


def _verify_recorded_file(run_dir: Path, record: dict[str, str], label: str) -> str | None:
    """复验一个路径/哈希记录并返回可读错误。"""
    try:
        current = sha256_file(resolve_inside(run_dir, record["path"], must_exist=True))
    except ContractError as exc:
        return f"{label} 无效: {exc}"
    if current != record["sha256"]:
        return f"{label} 哈希不一致: {record['path']}"
    return None


def verify_current_figure_files(run_dir: Path) -> dict[str, Any]:
    """复验当前图表仍由 current 真实结果生成且输出未漂移。

    Args:
        run_dir: v3 运行目录。

    Returns:
        检查过的图表、错误明细和总体成功状态。
    """
    index = read_figure_index(run_dir)
    results = read_result_index(run_dir)
    result_map = {item["result_id"]: item for item in results["results"]}
    errors: list[dict[str, str]] = []
    checked: list[str] = []
    for figure in index["figures"]:
        if figure["status"] != "current":
            continue
        figure_id = figure["figure_id"]
        checked.append(figure_id)
        if figure["demo"] or not figure["paper_allowed"]:
            errors.append({"figure_id": figure_id, "message": "demo 图或未允许图不能进入论文"})
        result = result_map.get(figure["result_id"])
        if result is None or result["status"] != "current" or not result["execution_valid"]:
            errors.append({"figure_id": figure_id, "message": "源结果已被替代或不再可用于论文"})
        else:
            input_path = figure["input_result"]["path"]
            if input_path not in result["output_hashes"]:
                errors.append({"figure_id": figure_id, "message": "图表输入不再属于源结果输出"})
            elif figure["input_result"]["sha256"] != result["output_hashes"][input_path]:
                errors.append({"figure_id": figure_id, "message": "源结果更新后图表需要重新生成"})
        for label, record in (
            ("图表输入", figure["input_result"]),
            ("参考模板", figure["reference_template"]),
            ("渲染脚本", figure["renderer_script"]),
            ("文字边界", figure["text_boxes"]),
        ):
            issue = _verify_recorded_file(run_dir, record, label)
            if issue:
                errors.append({"figure_id": figure_id, "message": issue})
        for output in figure["outputs"]:
            issue = _verify_recorded_file(run_dir, output, "图表输出")
            if issue:
                errors.append({"figure_id": figure_id, "message": issue})
                continue
            if resolve_inside(run_dir, output["path"], must_exist=True).stat().st_size == 0:
                errors.append({"figure_id": figure_id, "message": f"图表输出为空: {output['path']}"})
        try:
            boxes_path = resolve_inside(run_dir, figure["text_boxes"]["path"], must_exist=True)
            boxes_document = json.loads(boxes_path.read_text(encoding="utf-8"))
            boxes = boxes_document.get("boxes") if isinstance(boxes_document, dict) else None
            if not isinstance(boxes, list):
                raise ContractError("文字边界文件缺少 boxes 数组")
            png = next(
                item["path"] for item in figure["outputs"] if Path(item["path"]).suffix.lower() == ".png"
            )
            # 复用独立 QA 的图片可读性和文字边界相交检查，不在索引层做主观评分。
            from tools.qa.figqa import audit_figure

            audit = audit_figure(resolve_inside(run_dir, png, must_exist=True), boxes)
            if audit["errors"]:
                raise ContractError("；".join(audit["errors"]))
        except (ContractError, OSError, json.JSONDecodeError, StopIteration) as exc:
            errors.append({"figure_id": figure_id, "message": f"图表 QA 失败: {exc}"})
    return {"success": not errors, "checked_figure_ids": checked, "errors": errors}
