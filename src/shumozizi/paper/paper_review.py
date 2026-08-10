"""维护 ``PAPER_REVIEW.md`` 中可机器复核的批量返修 finding。"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, relative_inside, resolve_inside
from shumozizi.core.schema import require_valid

PAPER_REVIEW_PATH = Path("paper/PAPER_REVIEW.md")
_BLOCK_START = "<!-- PAPER_REVIEW_FINDINGS:START -->"
_BLOCK_END = "<!-- PAPER_REVIEW_FINDINGS:END -->"
_REPAIR_TYPES = ("science", "argument", "style", "figure", "render")
_HIGH_PRIORITY_CLOSED = {"repaired", "false_positive"}
_DISPOSITIONED = {"accepted", "repaired", "false_positive", "deferred_with_reason"}
_REPORT_STYLE_REPAIR_ONLY_CODES = frozenset(
    {
        "REPORT_STYLE_PATTERN",
        "PAPER_SECTION_UNDERDEVELOPED",
        "core_question_without_derivation",
        "core_question_without_mechanism",
        "generic_question_heading_repetition",
        "NARRATIVE_SCARCITY_REVIEW",
    }
)


def _report_style_gate_code(item: Mapping[str, Any]) -> str | None:
    """识别高置信度报告体 finding；其余编辑信号继续保持 advisory。"""
    serialized = json.dumps(dict(item), ensure_ascii=False).casefold()
    return next(
        (code for code in _REPORT_STYLE_REPAIR_ONLY_CODES if code.casefold() in serialized),
        None,
    )


def _atomic_text(path: Path, text: str) -> None:
    """在同目录完成文本原子替换，避免返修包只写入一半。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _structured_block(document: Mapping[str, Any]) -> str:
    """渲染 PAPER_REVIEW 内唯一受机器维护的 JSON 区块。"""
    return (
        f"{_BLOCK_START}\n"
        "```json\n"
        + json.dumps(document, ensure_ascii=False, indent=2)
        + "\n```\n"
        f"{_BLOCK_END}"
    )


def parse_paper_review(markdown: str) -> dict[str, Any]:
    """从 Markdown 中读取受控 finding JSON 区块。"""
    pattern = re.compile(
        re.escape(_BLOCK_START)
        + r"\s*```json\s*(?P<payload>\{.*?\})\s*```\s*"
        + re.escape(_BLOCK_END),
        re.DOTALL,
    )
    match = pattern.search(markdown)
    if match is None:
        raise ContractError("PAPER_REVIEW.md 缺少结构化 finding 闭环区块")
    try:
        value = json.loads(match.group("payload"))
    except json.JSONDecodeError as exc:
        raise ContractError(f"PAPER_REVIEW.md finding JSON 格式错误: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError("PAPER_REVIEW.md finding JSON 根节点必须是对象")
    require_valid(value, "paper_review")
    return value


def _repair_type_errors(value: object, finding_id: str) -> list[str]:
    """检查组合返修类型合法且不重复。"""
    if not isinstance(value, str):
        return [f"{finding_id}.repair_type 必须是字符串"]
    parts = value.split("+")
    errors: list[str] = []
    invalid = [part for part in parts if part not in _REPAIR_TYPES]
    if invalid:
        errors.append(f"{finding_id}.repair_type 含未知类型: {', '.join(invalid)}")
    if len(parts) != len(set(parts)):
        errors.append(f"{finding_id}.repair_type 不得重复组合")
    return errors


def paper_review_errors(document: Mapping[str, Any], *, run_dir: Path | None = None) -> list[str]:
    """返回 finding 闭环的语义错误，供候选门禁纯调用。

    Args:
        document: 由 ``parse_paper_review`` 解析的结构化文档。
        run_dir: 可选运行目录；提供时额外校验目标文件不越界。

    Returns:
        全部可操作错误；空数组表示结构与闭环状态自洽。
    """
    errors: list[str] = []
    findings = document.get("findings")
    if not isinstance(findings, list):
        return ["paper_review.findings 必须是数组"]
    seen: set[str] = set()
    root = run_dir.resolve() if run_dir is not None else None
    for index, item in enumerate(findings):
        if not isinstance(item, Mapping):
            errors.append(f"findings[{index}] 必须是对象")
            continue
        finding_id = item.get("finding_id")
        label = finding_id if isinstance(finding_id, str) else f"findings[{index}]"
        if isinstance(finding_id, str):
            if finding_id in seen:
                errors.append(f"finding_id 重复: {finding_id}")
            seen.add(finding_id)
        errors.extend(_repair_type_errors(item.get("repair_type"), label))
        status = item.get("status")
        evidence = item.get("evidence_of_closure")
        if status in _DISPOSITIONED and (not isinstance(evidence, list) or not evidence):
            errors.append(f"{label} 已处置但缺少 evidence_of_closure")
        if item.get("severity") in {"P0", "P1"} and status not in _HIGH_PRIORITY_CLOSED:
            errors.append(f"{label} 是未闭合的 {item.get('severity')} finding")
        report_style_code = _report_style_gate_code(item)
        if (
            report_style_code is not None
            and status in _DISPOSITIONED
            and status not in _HIGH_PRIORITY_CLOSED
        ):
            errors.append(
                f"{label} 命中高置信度报告体 {report_style_code}，候选稿只能 repaired 或 false_positive"
            )
        if root is not None:
            for target in item.get("target_files", []):
                try:
                    resolve_inside(root, target)
                except (ContractError, TypeError) as exc:
                    errors.append(f"{label}.target_files 越界或非法: {exc}")
    return errors


def unclosed_high_priority_findings(document: Mapping[str, Any]) -> list[str]:
    """返回未以修复证据或误报证据闭合的 P0/P1 finding ID。"""
    findings = document.get("findings")
    if not isinstance(findings, list):
        return []
    return [
        str(item.get("finding_id"))
        for item in findings
        if isinstance(item, Mapping)
        and item.get("severity") in {"P0", "P1"}
        and item.get("status") not in _HIGH_PRIORITY_CLOSED
    ]


def require_no_unclosed_high_priority(document: Mapping[str, Any]) -> None:
    """阻断仍有 P0/P1 返修项的调用流程。"""
    finding_ids = unclosed_high_priority_findings(document)
    if finding_ids:
        raise ContractError(f"PAPER_REVIEW 仍有未闭合 P0/P1: {', '.join(finding_ids)}")


def load_paper_review(run_dir: Path) -> dict[str, Any]:
    """读取运行内 PAPER_REVIEW，并校验 run_id 与路径边界。"""
    root = run_dir.resolve()
    path = resolve_inside(root, PAPER_REVIEW_PATH.as_posix(), must_exist=True)
    document = parse_paper_review(path.read_text(encoding="utf-8"))
    if document.get("run_id") != root.name:
        raise ContractError("PAPER_REVIEW.run_id 与运行目录不一致")
    return document


def _read_findings_input(path: Path) -> list[dict[str, Any]]:
    """从冷读或蓝图审核 JSON 中提取最多五项批量 finding。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractError(f"返修输入 JSON 格式错误: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("findings"), list):
        raise ContractError("返修输入必须是包含 findings 数组的 JSON 对象")
    if len(payload["findings"]) > 5:
        raise ContractError("一次批量返修最多导入 5 项最高价值 finding")
    if not all(isinstance(item, dict) for item in payload["findings"]):
        raise ContractError("返修输入 findings[] 必须全部是对象")
    return payload["findings"]


def merge_paper_review_findings(
    run_dir: Path,
    *,
    input_path: str,
    source: str,
) -> dict[str, Any]:
    """把一次独立审核的批量 finding 原子合入 PAPER_REVIEW。

    Args:
        run_dir: 当前运行目录。
        input_path: 运行目录内的独立审核 JSON 相对路径。
        source: finding 来源，例如 ``first_draft_cold_read``。

    Returns:
        合并后的完整 ``paper_review`` 文档。
    """
    root = run_dir.resolve()
    review_path = resolve_inside(root, PAPER_REVIEW_PATH.as_posix(), must_exist=True)
    input_file = resolve_inside(root, input_path, must_exist=True)
    incoming = _read_findings_input(input_file)
    original = review_path.read_text(encoding="utf-8")
    try:
        document = parse_paper_review(original)
    except ContractError as exc:
        if "缺少结构化 finding" not in str(exc):
            raise
        document = {
            "schema_name": "paper_review",
            "schema_version": "2.0",
            "run_id": root.name,
            "findings": [],
        }
    by_id = {item["finding_id"]: item for item in document["findings"]}
    for raw in incoming:
        finding = dict(raw)
        finding["source"] = source
        finding.setdefault("status", "open")
        finding.setdefault("evidence_of_closure", [])
        finding_id = finding.get("finding_id")
        if not isinstance(finding_id, str) or not finding_id.strip():
            raise ContractError("导入 finding 缺少非空 finding_id")
        if finding_id in by_id and by_id[finding_id] != finding:
            raise ContractError(f"finding_id 已存在且内容冲突: {finding_id}")
        by_id[finding_id] = finding
    document["findings"] = list(by_id.values())
    require_valid(document, "paper_review")
    semantic_errors = [
        error
        for error in paper_review_errors(document, run_dir=root)
        if "未闭合的 P" not in error
    ]
    if semantic_errors:
        raise ContractError("PAPER_REVIEW finding 非法: " + "；".join(semantic_errors))
    block = _structured_block(document)
    pattern = re.compile(
        re.escape(_BLOCK_START) + r".*?" + re.escape(_BLOCK_END), re.DOTALL
    )
    updated = pattern.sub(block, original) if pattern.search(original) else original.rstrip() + "\n\n" + block + "\n"
    _atomic_text(review_path, updated)
    return document


def close_paper_review_finding(
    run_dir: Path,
    *,
    finding_id: str,
    status: str,
    evidence_of_closure: list[str],
) -> dict[str, Any]:
    """登记 finding 处置结果并原子更新 PAPER_REVIEW。"""
    if status not in _DISPOSITIONED:
        raise ContractError(f"关闭 finding 时状态不合法: {status}")
    if not evidence_of_closure or not all(item.strip() for item in evidence_of_closure):
        raise ContractError("关闭 finding 必须提供非空 evidence_of_closure")
    root = run_dir.resolve()
    path = resolve_inside(root, PAPER_REVIEW_PATH.as_posix(), must_exist=True)
    original = path.read_text(encoding="utf-8")
    document = parse_paper_review(original)
    matched = False
    for item in document["findings"]:
        if item["finding_id"] == finding_id:
            item["status"] = status
            item["evidence_of_closure"] = evidence_of_closure
            matched = True
            break
    if not matched:
        raise ContractError(f"PAPER_REVIEW 不存在 finding: {finding_id}")
    require_valid(document, "paper_review")
    semantic_errors = [
        error
        for error in paper_review_errors(document, run_dir=root)
        if "未闭合的 P" not in error
    ]
    if semantic_errors:
        raise ContractError("PAPER_REVIEW finding 非法: " + "；".join(semantic_errors))
    pattern = re.compile(
        re.escape(_BLOCK_START) + r".*?" + re.escape(_BLOCK_END), re.DOTALL
    )
    _atomic_text(path, pattern.sub(_structured_block(document), original))
    return document


def paper_review_status(run_dir: Path) -> dict[str, Any]:
    """汇总 PAPER_REVIEW 的闭环状态，供 CLI 与候选门禁复用。"""
    document = load_paper_review(run_dir)
    unclosed = unclosed_high_priority_findings(document)
    unclosed_report_style = [
        str(item.get("finding_id"))
        for item in document.get("findings", [])
        if isinstance(item, Mapping)
        and _report_style_gate_code(item) is not None
        and item.get("status") not in _HIGH_PRIORITY_CLOSED
    ]
    errors = paper_review_errors(document, run_dir=run_dir)
    return {
        "valid": not errors,
        "finding_count": len(document["findings"]),
        "unclosed_p0_p1": unclosed,
        "unclosed_report_style": unclosed_report_style,
        "candidate_allowed": not unclosed and not unclosed_report_style and not errors,
    }


def first_draft_cold_read_prompt(run_dir: Path, *, pdf_path: str = "paper/draft-1.pdf") -> str:
    """生成仅接收第一版 PDF 的固定三分钟冷读提示。"""
    root = run_dir.resolve()
    pdf = resolve_inside(root, pdf_path, must_exist=True)
    relative_pdf = relative_inside(root, pdf).as_posix()
    if not relative_pdf.startswith("paper/") or pdf.suffix.lower() != ".pdf":
        raise ContractError("首稿冷读输入必须是运行目录 paper/ 下的 PDF")
    return (
        "你是第一版数学建模论文的独立冷读者。唯一允许的输入是随本提示附上的 PDF："
        f"{relative_pdf}。不得接收题面、源码、运行记录、作者解释、蓝图或前序审核结论；"
        "不得联网检索题目答案。先按真实三分钟冷读顺序阅读，再继续逐问和逐图检查。\n\n"
        "三分钟冷读必须回答：题目在解决什么；全文中心数学对象；多问怎样递进；每问最终"
        "回答；最关键两张图分别证明什么；哪一页最像工作报告；哪个问题最缺推导或机制；"
        "前五页是否建立数据或模型直觉。\n\n"
        "逐问检查：本问解决什么、相对前文新增或改变什么、关键数学处理、主结果和直接"
        "答案。共享模型、通用求解过程和实现验证可以由前文或全文统一章节明确覆盖，不要"
        "仅因本问没有重复 MATLAB/Python 重放、批量通过率或环境一致性而判为缺失；但上下"
        "界、构造、关键不等式和约束可行性等核心逻辑证明必须留在对应问题附近。\n\n"
        "逐图检查每张正文图：读者问题、关键观察、为何支持结论、是否重复表格、字号、"
        "是否承担过多任务、图后是否有机制解释。\n\n"
        "只输出一个 JSON 对象，不要 Markdown 代码围栏。字段必须为："
        "schema_name='first_draft_cold_read'、schema_version='1.0'、pdf_path、"
        "decision（只能是 continue_revision 或 ready_for_candidate）、three_minute_read、"
        "question_checks、figure_checks、findings。findings 必须按影响排序且"
        "最多 5 项，每项必须包含 finding_id、severity(P0-P3)、finding、impact、"
        "affected_argument_units、repair_type、target_files、expected_benefit、estimated_cost、"
        "acceptance_test、stop_condition。repair_type 只能由 science、argument、style、figure、"
        "render 以 + 组合。不要只给 pass/fail；没有高价值 finding 时输出空数组。"
    )
