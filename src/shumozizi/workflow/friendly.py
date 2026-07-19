"""为两个固定人工检查点生成可恢复的低认知负担提示。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, load_json, sha256_file


def _route_options(run_dir: Path) -> list[dict[str, Any]]:
    """按候选文件顺序生成编号选项。"""
    candidates = load_json(run_dir / "brief" / "route_candidates.json")
    recommended = candidates.get("recommended_route_id")
    options = []
    for number, candidate in enumerate(candidates.get("candidates", []), start=1):
        options.append(
            {
                "number": number,
                "route_id": candidate["route_id"],
                "name": candidate["name"],
                "recommended": candidate["route_id"] == recommended,
                "primary_model": candidate["primary_model"],
                "fallback": candidate["fallback"],
                "validation": candidate["validation"],
                "risks": candidate["risks"],
            }
        )
    if not options:
        raise ContractError("路线批准提示缺少候选路线")
    return options


def present_route_checkpoint(run_dir: Path) -> dict[str, Any]:
    """生成路线人工确认提示，不创建 receipt 或 ROUTE_LOCK。"""
    request = load_json(run_dir / "brief" / "route_approval_request.json")
    options = _route_options(run_dir)
    lines = [
        f"路线确认（请求 {request['request_id']}，状态版本 {request['state_revision']}）",
        "请回复选项编号；带 [推荐] 的选项只是建议，不代表系统已批准。",
    ]
    for item in options:
        marker = " [推荐]" if item["recommended"] else ""
        lines.append(
            f"{item['number']}. {item['name']}{marker}：主路线 {item['primary_model']}；"
            f"退路 {item['fallback']}；验证 {item['validation']}；风险 {', '.join(item['risks'])}"
        )
    lines.append("回复示例：选择 1，并委托系统执行输入清洗。")
    return {
        "checkpoint_kind": "route",
        "request_sha256": sha256_file(run_dir / "brief" / "route_approval_request.json"),
        "options": options,
        "message": "\n".join(lines),
        "receipt_created": (run_dir / "brief" / "route_approval_receipt.json").is_file(),
    }


def present_final_checkpoint(run_dir: Path) -> dict[str, Any]:
    """生成最终提交人工确认提示，展示所有绑定哈希和待确认警告。"""
    request_path = run_dir / "review" / "final_approval_request.json"
    request = load_json(request_path)
    qa = load_json(run_dir / "review" / "QA_AGGREGATE.json")
    evidence = load_json(run_dir / "review" / "EVIDENCE_VALIDATION.json")
    bindings = request["bindings"]
    warnings = [*request.get("warnings", []), *qa.get("warnings", [])]
    lines = [
        f"最终提交确认（请求 {request['request_id']}，状态版本 {request['state_revision']}）",
        f"PDF：{request['final_pdf_path']}，SHA-256：{bindings['final_pdf_sha256']}",
        f"QA：{qa['status']}，报告 SHA-256：{bindings['qa_report_sha256']}",
        f"证据：{evidence['status']}，报告 SHA-256：{bindings['evidence_report_sha256']}",
    ]
    if warnings:
        lines.append("待人工确认的警告：")
        lines.extend(f"- {warning}" for warning in sorted(set(warnings)))
    lines.append("回复“批准提交”或明确说明不批准；系统不会把查看提示视为批准。")
    return {
        "checkpoint_kind": "final",
        "request_sha256": sha256_file(request_path),
        "bindings": bindings,
        "warnings": sorted(set(warnings)),
        "message": "\n".join(lines),
        "receipt_created": (run_dir / "review" / "final_approval_receipt.json").is_file(),
    }


def present_resume_checkpoint(run_dir: Path) -> dict[str, Any]:
    """根据 state.json 恢复到唯一待人工点或给出系统状态。"""
    state = load_json(run_dir / "state.json")
    status = state["status"]
    if status == "WAITING_HUMAN_ROUTE":
        return present_route_checkpoint(run_dir)
    if status == "WAITING_HUMAN_FINAL":
        return present_final_checkpoint(run_dir)
    return {
        "checkpoint_kind": "none",
        "status": status,
        "revision": state["revision"],
        "message": f"当前状态为 {status}，没有新的人工确认请求。",
    }


def checkpoint_json(run_dir: Path) -> str:
    """输出稳定 JSON，供 Codex 桌面恢复或其他只读界面展示。"""
    return json.dumps(present_resume_checkpoint(run_dir), ensure_ascii=False, indent=2)
