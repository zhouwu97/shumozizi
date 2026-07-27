"""登记并复验 v3 的真实结果图表，不评价其科学结论。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

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
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.core.schema import require_valid
from shumozizi.simple.quality import quality_allows_paper
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import (
    is_competition_first_state,
    is_competition_first_v32_state,
    read_simple_state,
    utc_now,
)

INDEX_PATH = Path("figures/index.json")
FIGURE_PLAN_PATH = Path("figures/FIGURE_PLAN.json")
# 图的三种正当角色。stability 单列，因为舍入、采样层级和数值稳定性图是内部
# 审计产物：它们对评委的边际价值远低于机制、阈值和权衡，不该占据正文版面。
FIGURE_ROLES = frozenset({"model_understanding", "decisive_evidence", "insight", "stability"})
FIGURE_PLACEMENTS = frozenset({"body", "appendix"})
_APPENDIX_ONLY_ROLES = frozenset({"stability"})


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


def write_figure_plan(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """受控保存 v3.2 正文图表计划与逐问视觉决策。

    Args:
        run_dir: 当前运行目录。
        payload: ``FIGURE_PLAN`` 2.1 文档。

    Returns:
        已原子写入的图表计划。

    Raises:
        ContractError: Schema 不合法，或首版截止后扩张图表集合。
    """
    require_valid(payload, "figure_plan")
    if payload.get("run_id") != run_dir.name:
        raise ContractError("FIGURE_PLAN 的 run_id 与当前运行不一致")
    path = run_dir / FIGURE_PLAN_PATH
    old_ids: set[str] = set()
    if path.is_file():
        existing = load_json(path)
        old_ids = {
            item.get("figure_id")
            for item in existing.get("figures", [])
            if isinstance(item, dict) and isinstance(item.get("figure_id"), str)
        }
    new_ids = {
        item.get("figure_id")
        for item in payload.get("figures", [])
        if isinstance(item, dict) and isinstance(item.get("figure_id"), str)
    }
    if new_ids - old_ids:
        from shumozizi.simple.delivery import require_delivery_action_allowed

        require_delivery_action_allowed(run_dir, "expand_figure_plan")
    atomic_json(path, payload)
    return payload


def _file_record(run_dir: Path, relative: str) -> dict[str, str]:
    """生成一个已存在运行内文件的路径和哈希记录。"""
    path = resolve_inside(run_dir, relative, must_exist=True)
    return {"path": relative_inside(run_dir, path).as_posix(), "sha256": sha256_file(path)}


def _competition_first_run(run_dir: Path) -> bool:
    """判断当前运行是否使用 v3.1 简化图表协议。"""
    return is_competition_first_state(read_simple_state(run_dir))


def _register_competition_figure(
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
    figure_stage: str,
    scientific_question: str | None,
    expected_takeaway: str | None,
    cannot_prove: str | None,
    role: str | None = None,
    placement: str | None = None,
) -> dict[str, Any]:
    """登记由问题和 takeaway 驱动的 v3.1 图表。"""
    if figure_stage not in {"current", "evidence", "publication"}:
        raise ContractError("v3.1 figure_stage 必须为 current、evidence 或 publication")
    if role is None and is_competition_first_v32_state(read_simple_state(run_dir)):
        # role 可选时，把稳定性图放进正文只需不声明 role，附录约束等于可规避。
        raise ContractError(
            "v3.2 图表必须声明 role（model_understanding / decisive_evidence / "
            "insight / stability）：不声明角色时附录约束形同虚设"
        )
    if role is not None and role not in FIGURE_ROLES:
        raise ContractError("figure role 必须是 " + ", ".join(sorted(FIGURE_ROLES)))
    if placement is not None and placement not in FIGURE_PLACEMENTS:
        raise ContractError("figure placement 必须为 body 或 appendix")
    if role in _APPENDIX_ONLY_ROLES:
        if placement == "body":
            raise ContractError(
                "稳定性、舍入与采样层级图默认进入附录，不得抢占正文版面；"
                "正文位置应留给机制、阈值与权衡"
            )
        placement = "appendix"
    index = read_figure_index(run_dir)
    source_result = next(
        (item for item in read_result_index(run_dir)["results"] if item["result_id"] == result_id), None
    )
    if source_result is None or source_result.get("status") != "current" or not source_result.get("execution_valid"):
        raise ContractError("图表只能绑定 current 且 execution_valid=true 的真实结果")
    input_record = _file_record(run_dir, input_result)
    if input_record["path"] not in source_result["output_hashes"]:
        raise ContractError("图表输入必须是所绑定结果的已登记输出")
    if input_record["sha256"] != source_result["output_hashes"][input_record["path"]]:
        raise ContractError("图表输入哈希与所绑定结果不一致")
    output_records = [_file_record(run_dir, item) for item in outputs]
    suffixes = {Path(item["path"]).suffix.lower() for item in output_records}
    if not output_records or not suffixes <= {".png", ".pdf", ".svg"} or not suffixes & {".png", ".pdf"}:
        raise ContractError("v3.1 图表至少需要可读 PNG 或 PDF 输出")
    expected_prefix = "figures/current/"
    if any(not item["path"].startswith(expected_prefix) for item in output_records):
        raise ContractError("v3.1 图输出必须位于 figures/current/")
    entry = {
        "figure_id": figure_id,
        "template_id": template_id,
        "result_id": result_id,
        "input_result": input_record,
        "renderer_script": _file_record(run_dir, renderer_script),
        "outputs": output_records,
        "status": "current",
        "question_id": source_result["question_id"],
        "figure_stage": "current",
        "source": [input_record["path"]],
        "question": scientific_question or f"{source_result['question_id']} 的当前结果回答什么问题？",
        "takeaway": expected_takeaway or "该图呈现当前结果中可直接核对的结构差异。",
        "limitations": cannot_prove or "图表不能单独证明模型正确性或因果关系。",
        "source_result_ids": [result_id],
        "source_result_sha256s": {result_id: sha256_bytes(json_bytes(source_result))},
        "objective_semantics_sha256": source_result["objective_semantics_sha256"],
        "paper_allowed": True,
        "demo": False,
        "created_at": utc_now(),
    }
    if role is not None:
        entry["role"] = role
    if placement is not None:
        entry["placement"] = placement
    for existing in index["figures"]:
        if existing["figure_id"] == figure_id and existing["status"] == "current":
            existing["status"] = "superseded"
    index["figures"].append(entry)
    require_figure_index(index)
    atomic_json(run_dir / INDEX_PATH, index)
    return entry


def register_insight_figure(
    run_dir: Path,
    *,
    figure_id: str,
    result_id: str,
    input_result: str,
    renderer_script: str,
    outputs: list[str],
    question: str,
    takeaway: str,
    limitations: str | None = None,
    template_id: str = "custom",
    role: str | None = None,
    placement: str | None = None,
) -> dict[str, Any]:
    """登记仅包含来源、问题和 takeaway 的 v3.1 图表。

    Args:
        run_dir: 当前运行目录。
        figure_id: 图表标识。
        result_id: 真实来源结果。
        input_result: 图表读取的结果文件。
        renderer_script: 实际执行的绘图脚本。
        outputs: 已生成的 PNG/PDF/SVG 输出。
        question: 图表回答的问题。
        takeaway: 读者应一眼看到的结论。
        limitations: 可选的论证边界。
        template_id: 绘图实现类型，仅用于追溯。
        role: 图的角色（model_understanding / decisive_evidence / insight /
            stability）；stability 会被强制归入附录。
        placement: 计划版面位置（body 或 appendix）。

    Returns:
        当前图表索引条目。
    """
    if not _competition_first_run(run_dir):
        raise ContractError("register_insight_figure 仅适用于 Competition-First v3.1")
    return _register_competition_figure(
        run_dir,
        figure_id=figure_id,
        template_id=template_id,
        result_id=result_id,
        input_result=input_result,
        reference_template=renderer_script,
        renderer_script=renderer_script,
        outputs=outputs,
        text_boxes=renderer_script,
        figure_stage="current",
        scientific_question=question,
        expected_takeaway=takeaway,
        cannot_prove=limitations,
        role=role,
        placement=placement,
    )


def _verify_competition_figures(run_dir: Path) -> dict[str, Any]:
    """复验 v3.1 当前图的来源、哈希和基本可读性。"""
    index = read_figure_index(run_dir)
    results = {item["result_id"]: item for item in read_result_index(run_dir)["results"]}
    errors: list[dict[str, str]] = []
    checked: list[str] = []
    for figure in index["figures"]:
        if figure.get("status") != "current":
            continue
        figure_id = str(figure.get("figure_id", "<unknown>"))
        checked.append(figure_id)
        if figure.get("demo") or not figure.get("paper_allowed"):
            errors.append({"figure_id": figure_id, "message": "演示图或未允许图不能进入论文"})
        result = results.get(figure.get("result_id"))
        if result is None or result.get("status") != "current" or not result.get("execution_valid"):
            errors.append({"figure_id": figure_id, "message": "源结果已被替代或不再有效"})
            continue
        expected = sha256_bytes(json_bytes(result))
        if figure.get("source_result_sha256s", {}).get(result["result_id"]) != expected:
            errors.append({"figure_id": figure_id, "message": "源结果变化后图表需要重新生成"})
        input_record = figure.get("input_result", {})
        if input_record.get("path") not in result.get("output_hashes", {}):
            errors.append({"figure_id": figure_id, "message": "图表输入不属于源结果输出"})
        elif input_record.get("sha256") != result["output_hashes"][input_record["path"]]:
            errors.append({"figure_id": figure_id, "message": "图表输入哈希已漂移"})
        for record in [input_record, figure.get("renderer_script", {})]:
            issue = _verify_recorded_file(run_dir, record, "图表来源")
            if issue:
                errors.append({"figure_id": figure_id, "message": issue})
        for output in figure.get("outputs", []):
            issue = _verify_recorded_file(run_dir, output, "图表输出")
            if issue:
                errors.append({"figure_id": figure_id, "message": issue})
                continue
            path = resolve_inside(run_dir, output["path"], must_exist=True)
            if path.stat().st_size == 0:
                errors.append({"figure_id": figure_id, "message": "图表输出为空"})
            elif path.suffix.lower() == ".png":
                try:
                    from PIL import Image

                    with Image.open(path) as image:
                        image.verify()
                except (OSError, ValueError) as exc:
                    errors.append({"figure_id": figure_id, "message": f"PNG 不可读: {exc}"})
            elif path.suffix.lower() == ".pdf" and not path.read_bytes().startswith(b"%PDF"):
                errors.append({"figure_id": figure_id, "message": "PDF 图表不是有效 PDF 文件头"})
    return {"success": not errors, "checked_figure_ids": checked, "errors": errors}


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
    figure_stage: str = "publication",
    claim_ids: list[str] | None = None,
    scientific_question: str | None = None,
    expected_takeaway: str | None = None,
    cannot_prove: str | None = None,
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
    if _competition_first_run(run_dir):
        return _register_competition_figure(
            run_dir,
            figure_id=figure_id,
            template_id=template_id,
            result_id=result_id,
            input_result=input_result,
            reference_template=reference_template,
            renderer_script=renderer_script,
            outputs=outputs,
            text_boxes=text_boxes,
            figure_stage=figure_stage,
            scientific_question=scientific_question,
            expected_takeaway=expected_takeaway,
            cannot_prove=cannot_prove,
        )
    if not figure_id.replace("-", "").replace("_", "").replace(".", "").isalnum():
        raise ContractError(f"figure_id 不合法: {figure_id}")
    index = read_figure_index(run_dir)
    results = read_result_index(run_dir)
    source_result = next((item for item in results["results"] if item["result_id"] == result_id), None)
    if figure_stage not in {"evidence", "publication"}:
        raise ContractError("figure_stage 必须为 evidence 或 publication")
    if source_result is None or source_result["status"] != "current" or not source_result["execution_valid"]:
        raise ContractError("图表只能绑定 current 且 execution_valid=true 的真实结果")
    if figure_stage == "publication" and not quality_allows_paper(run_dir, result_id):
        raise ContractError("publication 图只能绑定已通过科学审核和质量层的结果")
    input_record = _file_record(run_dir, input_result)
    if input_record["path"] not in source_result["output_hashes"]:
        raise ContractError("图表输入必须是所绑定结果的已登记输出")
    if input_record["sha256"] != source_result["output_hashes"][input_record["path"]]:
        raise ContractError("图表输入哈希与所绑定结果不一致")
    output_records = [_file_record(run_dir, item) for item in outputs]
    expected_prefix = f"figures/{figure_stage}/"
    if any(not item["path"].startswith(expected_prefix) for item in output_records):
        raise ContractError(f"{figure_stage} 图输出必须位于 {expected_prefix}")
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
        "question_id": source_result["question_id"],
        "claim_ids": list(claim_ids or []),
        "figure_stage": figure_stage,
        "scientific_question": scientific_question
        or f"{source_result['question_id']} 的当前结果呈现什么可复验结构？",
        "expected_takeaway": expected_takeaway
        or "展示当前结果中可由图形直接核对的主要结构与差异。",
        "cannot_prove": cannot_prove
        or "该图不能单独证明模型正确性、因果关系或结论的普遍有效性。",
        "source_result_ids": [result_id],
        "source_result_sha256s": {result_id: sha256_bytes(json_bytes(source_result))},
        "objective_semantics_sha256": source_result["objective_semantics_sha256"],
        "paper_allowed": figure_stage == "publication",
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


def verify_current_figure_files(
    run_dir: Path, *, figure_stage: str = "publication"
) -> dict[str, Any]:
    """复验当前图表仍由 current 真实结果生成且输出未漂移。

    Args:
        run_dir: v3 运行目录。

    Returns:
        检查过的图表、错误明细和总体成功状态。
    """
    if _competition_first_run(run_dir):
        return _verify_competition_figures(run_dir)
    index = read_figure_index(run_dir)
    results = read_result_index(run_dir)
    result_map = {item["result_id"]: item for item in results["results"]}
    errors: list[dict[str, str]] = []
    checked: list[str] = []
    for figure in index["figures"]:
        if figure["status"] != "current":
            continue
        recorded_stage = figure.get("figure_stage", "publication")
        if recorded_stage != figure_stage:
            continue
        figure_id = figure["figure_id"]
        checked.append(figure_id)
        if figure["demo"] or (figure_stage == "publication" and not figure["paper_allowed"]):
            errors.append({"figure_id": figure_id, "message": "demo 图或未允许图不能进入论文"})
        result = result_map.get(figure["result_id"])
        if (
            result is None
            or result["status"] != "current"
            or not result["execution_valid"]
            or (
                figure_stage == "publication"
                and not quality_allows_paper(run_dir, figure["result_id"])
            )
        ):
            errors.append({"figure_id": figure_id, "message": "源结果已被替代或不再可用于论文"})
        else:
            expected_result_sha = sha256_bytes(json_bytes(result))
            recorded_sha = figure.get("source_result_sha256s", {}).get(
                figure["result_id"]
            )
            if recorded_sha is not None and recorded_sha != expected_result_sha:
                errors.append({"figure_id": figure_id, "message": "源结果条目变化后图表需要重新生成"})
            if figure.get("objective_semantics_sha256") not in {
                None,
                result.get("objective_semantics_sha256"),
            }:
                errors.append({"figure_id": figure_id, "message": "图表绑定的目标语义已变化"})
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
