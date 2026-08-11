"""把数据建模的方法学与不确定性结果绑定到正式论文源码。"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
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
        # WHY: 即使有人绕过建模单元写入路径，推荐型输出也不能靠
        # ``required=false`` 使正文不确定性义务消失。
        requires_uncertainty = (
            contract.get("outcome_kind") == "recommendation"
            or (isinstance(uncertainty, dict) and uncertainty.get("required") is True)
        )
        if requires_uncertainty:
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
    bindings: list[dict[str, Any]] = []
    for unit_id, roles in requirements.items():
        for role, result_ids in roles.items():
            if role == "question_id":
                continue
            binding: dict[str, Any] = {
                "unit_id": unit_id,
                "question_id": roles["question_id"],
                "role": role,
                "result_ids": result_ids,
                "source_path": "待填写：正式发布入口中的文件",
                "source_span": "待填写：paper/main.tex:行号-行号",
                "statement": "待填写：正文中可复述的方法或区间结论",
            }
            if role == "uncertainty":
                binding["metric_assertions"] = [
                    {
                        "result_id": result_id,
                        "metric": "待填写：生产结果中的区间端点或不确定性指标",
                        "value_text": "待填写：正式稿中出现的数值",
                    }
                    for result_id in result_ids
                ]
            bindings.append(binding)
    return {
        "schema_name": "publication_evidence_bindings",
        "schema_version": "1.1",
        "run_id": read_simple_state(root)["run_id"],
        "publication_source_sha256": publication_source_digest(root),
        "bindings": bindings,
        "generated_at": utc_now(),
    }


def _normalise_text(value: str) -> str:
    """归一化正式稿断言，保留数值 token 的可辨识边界。"""
    return re.sub(r"\s+", "", value).replace("−", "-")


def _metric_value_matches_text(metric_value: Any, value_text: str) -> bool:
    """判断绑定文本是否准确复述生产结果的数值。

    Args:
        metric_value: 已由结果索引和输出文件双重校验过的指标值。
        value_text: 作者声称写入正式稿的数值文本。

    Returns:
        文本可无损表示该数值时为真。
    """
    if isinstance(metric_value, bool) or not isinstance(metric_value, (int, float)):
        return False
    try:
        return Decimal(value_text.replace(",", "")) == Decimal(str(metric_value))
    except (InvalidOperation, ValueError):
        return False


def _statement_contains_value(statement: str, value_text: str) -> bool:
    """验证数值以完整 token 出现在可复述正式稿断言中。"""
    normalized_statement = _normalise_text(statement)
    normalized_value = _normalise_text(value_text)
    if not normalized_value:
        return False
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", normalized_value):
        return re.search(
            rf"(?<![\d.]){re.escape(normalized_value)}(?![\d.])",
            normalized_statement,
        ) is not None
    return normalized_value in normalized_statement


def _metric_assertion_errors(
    raw: dict[str, Any],
    *,
    unit_id: str,
    role: str,
    expected_result_ids: list[str],
    result_records: dict[str, dict[str, Any]],
    statement: str,
) -> list[str]:
    """验证不确定性结论逐项复述了当前生产结果中的数值。

    Args:
        raw: 单条证据绑定。
        unit_id: 当前建模单元标识。
        role: 证据角色。
        expected_result_ids: 本角色必须绑定的生产结果。
        result_records: 当前可用生产结果索引。
        statement: 已验证出现在正式稿中的可复述断言。

    Returns:
        不满足数值绑定合同的错误列表。
    """
    if role != "uncertainty":
        return []
    assertions = raw.get("metric_assertions")
    if not isinstance(assertions, list) or not assertions:
        return [f"{unit_id}/{role} 必须声明非空 metric_assertions 以绑定区间或不确定性数值"]
    errors: list[str] = []
    asserted_result_ids: set[str] = set()
    for index, assertion in enumerate(assertions):
        label = f"{unit_id}/{role}.metric_assertions[{index}]"
        if not isinstance(assertion, dict):
            errors.append(f"{label} 必须是对象")
            continue
        result_id = assertion.get("result_id")
        metric = assertion.get("metric")
        value_text = assertion.get("value_text")
        if not all(isinstance(item, str) and item.strip() for item in (result_id, metric, value_text)):
            errors.append(f"{label} 必须包含 result_id、metric 与 value_text")
            continue
        if result_id not in expected_result_ids:
            errors.append(f"{label} 绑定了本角色之外的 result_id")
            continue
        record = result_records.get(result_id)
        metrics = record.get("metrics") if isinstance(record, dict) else None
        if not isinstance(metrics, dict) or metric not in metrics:
            errors.append(f"{label} 指向的生产结果不含指标 {metric}")
            continue
        if not _metric_value_matches_text(metrics[metric], value_text):
            errors.append(f"{label} 的 value_text 与生产结果指标不一致")
            continue
        if not _statement_contains_value(statement, value_text):
            errors.append(f"{label} 的数值未出现在可复述正式稿结论中")
            continue
        asserted_result_ids.add(result_id)
    missing = sorted(set(expected_result_ids) - asserted_result_ids)
    if missing:
        errors.append(f"{unit_id}/{role} 缺少生产结果数值断言: {', '.join(missing)}")
    return errors


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
    if payload.get("schema_name") != "publication_evidence_bindings" or payload.get("schema_version") != "1.1":
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
    result_records = {
        str(item.get("result_id")): item
        for item in read_result_index(root).get("results", [])
        if item.get("execution_mode") == "production" and item.get("execution_valid") is True
    }
    results = set(result_records)
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
        if role == "uncertainty" and not expected:
            errors.append(f"{unit_id}/{role} 缺少当前生产的不确定性结果")
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
        if _normalise_text(statement) not in _normalise_text(excerpt):
            errors.append(f"{unit_id}/{role} 的可复述结论不在声明正式稿位置")
            continue
        errors.extend(
            _metric_assertion_errors(
                raw,
                unit_id=unit_id,
                role=role,
                expected_result_ids=expected,
                result_records=result_records,
                statement=statement,
            )
        )
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
