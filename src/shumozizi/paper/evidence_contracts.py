"""把数据建模的方法学与不确定性结果绑定到正式论文源码。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.paper.policy import workflow_quality_policy
from shumozizi.paper.publication import publication_source_digest, publication_text_sources
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import read_simple_state, utc_now

PUBLICATION_EVIDENCE_BINDINGS_PATH = Path("paper/EVIDENCE_BINDINGS.json")


def _required_roles(run_dir: Path) -> dict[str, dict[str, list[str]]]:
    """从已执行的数据建模单元导出必须进入正文的结果证据角色。"""
    if workflow_quality_policy(run_dir) != "competition-quality-v1":
        return {}
    payload = load_json(run_dir / "analysis/MODELING_UNITS.json")
    required: dict[str, dict[str, list[str]]] = {}
    for unit in payload.get("units", []):
        if not isinstance(unit, dict) or unit.get("unit_kind") != "data_modeling":
            continue
        contract = unit.get("data_contract")
        actual = unit.get("actual")
        if not isinstance(contract, dict) or not isinstance(actual, dict):
            continue
        audit = contract.get("methodology_audit")
        validation = actual.get("validation")
        if not isinstance(audit, dict) or not isinstance(validation, dict):
            continue
        unit_id = str(unit.get("unit_id", "")).strip()
        question_id = str(unit.get("question_id", "")).strip()
        if not unit_id or not question_id:
            continue
        roles = {
            "methodology": [
                str(item)
                for item in validation.get("methodology_result_ids", [])
                if isinstance(item, str) and item.strip()
            ]
        }
        uncertainty = audit.get("recommendation_uncertainty")
        if isinstance(uncertainty, dict) and uncertainty.get("required") is True:
            roles["uncertainty"] = [
                str(item)
                for item in validation.get("uncertainty_result_ids", [])
                if isinstance(item, str) and item.strip()
            ]
        required[unit_id] = {"question_id": question_id, **roles}
    return required


def evidence_binding_template(run_dir: Path) -> dict[str, Any]:
    """生成不含正文断言的证据绑定骨架，供作者补写正式源码位置。"""
    root = run_dir.resolve()
    requirements = _required_roles(root)
    bindings = [
        {
            "unit_id": unit_id,
            "question_id": roles["question_id"],
            "role": role,
            "result_ids": result_ids,
            "source_path": "待填写：正式发布入口中的文件",
            "source_span": "待填写：paper/main.tex:行号-行号",
            "statement": "待填写：正文中可复述的方法或区间结论",
        }
        for unit_id, roles in requirements.items()
        for role, result_ids in roles.items()
        if role != "question_id"
    ]
    return {
        "schema_name": "publication_evidence_bindings",
        "schema_version": "1.0",
        "run_id": read_simple_state(root)["run_id"],
        "publication_source_sha256": publication_source_digest(root),
        "bindings": bindings,
        "generated_at": utc_now(),
    }


def write_publication_evidence_bindings(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """校验并原子写入正式论文的方法学/不确定性证据绑定。"""
    errors = publication_evidence_binding_errors(run_dir, payload=payload)
    if errors:
        raise ContractError("论文证据绑定不满足质量合同: " + "；".join(errors))
    atomic_json(run_dir.resolve() / PUBLICATION_EVIDENCE_BINDINGS_PATH, payload)
    return payload


def publication_evidence_binding_errors(
    run_dir: Path,
    *,
    payload: dict[str, Any] | None = None,
) -> list[str]:
    """验证正式稿没有把方法学、不确定性结果留在实验目录或散文里。"""
    root = run_dir.resolve()
    requirements = _required_roles(root)
    if not requirements:
        return []
    if payload is None:
        path = root / PUBLICATION_EVIDENCE_BINDINGS_PATH
        if not path.is_file():
            return ["缺少 paper/EVIDENCE_BINDINGS.json：方法学与不确定性证据尚未进入正式稿"]
        payload = load_json(path)
    if payload.get("schema_name") != "publication_evidence_bindings" or payload.get("schema_version") != "1.0":
        return ["EVIDENCE_BINDINGS 协议无效"]
    if payload.get("run_id") != read_simple_state(root)["run_id"]:
        return ["EVIDENCE_BINDINGS.run_id 与当前运行不一致"]
    try:
        digest = publication_source_digest(root)
        sources = {path.relative_to(root).as_posix(): path for path in publication_text_sources(root)}
    except ContractError as exc:
        return [f"无法验证 EVIDENCE_BINDINGS 的正式稿入口: {exc}"]
    errors: list[str] = []
    if payload.get("publication_source_sha256") != digest:
        errors.append("EVIDENCE_BINDINGS 未绑定当前正式稿依赖摘要")
    records = payload.get("bindings")
    if not isinstance(records, list):
        return [*errors, "EVIDENCE_BINDINGS.bindings 必须是数组"]
    results = {str(item.get("result_id")) for item in read_result_index(root).get("results", []) if item.get("execution_mode") == "production" and item.get("execution_valid") is True}
    seen: set[tuple[str, str]] = set()
    for raw in records:
        if not isinstance(raw, dict):
            errors.append("EVIDENCE_BINDINGS 含非对象条目")
            continue
        unit_id, role = raw.get("unit_id"), raw.get("role")
        if not isinstance(unit_id, str) or not isinstance(role, str):
            errors.append("EVIDENCE_BINDINGS 条目缺少 unit_id 或 role")
            continue
        expected = requirements.get(unit_id, {}).get(role)
        if expected is None:
            errors.append(f"{unit_id}/{role} 不是当前要求的证据角色")
            continue
        seen.add((unit_id, role))
        if raw.get("question_id") != requirements[unit_id]["question_id"]:
            errors.append(f"{unit_id}/{role} 绑定了错误问题")
        bound_ids = raw.get("result_ids")
        if not isinstance(bound_ids, list) or set(bound_ids) != set(expected):
            errors.append(f"{unit_id}/{role} 必须精确绑定当前验证结果")
        elif not set(bound_ids).issubset(results):
            errors.append(f"{unit_id}/{role} 绑定了非当前 production 结果")
        source_path = raw.get("source_path")
        source_span = raw.get("source_span")
        statement = raw.get("statement")
        if not all(isinstance(item, str) and item.strip() for item in (source_path, source_span, statement)):
            errors.append(f"{unit_id}/{role} 缺少正式源码位置或可复述结论")
            continue
        source = sources.get(source_path)
        match = re.fullmatch(r"(.+):(\d+)-(\d+)", source_span.strip())
        if source is None or match is None or match.group(1) != source_path:
            errors.append(f"{unit_id}/{role} 未绑定正式稿依赖闭包中的有效 source_span")
            continue
        start, end = int(match.group(2)), int(match.group(3))
        lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
        if start < 1 or end < start or end > len(lines):
            errors.append(f"{unit_id}/{role} source_span 超出正式稿行范围")
            continue
        excerpt = "\n".join(lines[start - 1 : end])
        if re.sub(r"\s+", "", statement) not in re.sub(r"\s+", "", excerpt):
            errors.append(f"{unit_id}/{role} 的可复述结论不在声明正式稿位置")
    for unit_id, roles in requirements.items():
        for role in roles:
            if role != "question_id" and (unit_id, role) not in seen:
                errors.append(f"{unit_id}/{role} 缺少正式论文证据绑定")
    return errors


def require_publication_evidence_bindings(run_dir: Path) -> None:
    """候选稿前要求新质量合同的统计证据已进入正式论文。"""
    errors = publication_evidence_binding_errors(run_dir)
    if errors:
        raise ContractError("；".join(errors))
