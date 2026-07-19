"""从已哈希执行输出生成不可变指标来源。"""

from __future__ import annotations

import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, resolve_inside, sha256_file
from shumozizi.core.schema import require_valid
from shumozizi.runtime.execution import execution_record_path, verify_execution_record

EXTRACTOR_VERSION = "1.0.0"
ALLOWED_EXTRACTORS = {
    "json-pointer",
    "csv-cell",
    "csv-column-aggregate",
    "text-regex-named-group",
    "numpy-npz-key",
    "derived-expression",
}
NUMERIC_OPS = {"add", "subtract", "multiply", "divide", "mean", "min", "max"}


def utc_now() -> str:
    """返回 RFC 3339 UTC 时间。"""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def implementation_sha256() -> str:
    """返回当前提取器实现的内容哈希。"""
    return sha256_file(Path(__file__))


def _json_pointer(document: Any, pointer: str) -> Any:
    """按照 RFC 6901 解析 JSON Pointer。"""
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ContractError("JSON Pointer 必须为空或以 / 开头")
    value = document
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        try:
            value = value[int(token)] if isinstance(value, list) else value[token]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ContractError(f"JSON Pointer 不存在: {pointer}") from exc
    return value


def _number(value: Any, purpose: str) -> float | int:
    """拒绝布尔值并要求数值类型。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{purpose} 必须是数值")
    return value


def evaluate_expression(expression: dict[str, Any], values: dict[str, Any]) -> Any:
    """解释受限 AST；不执行字符串代码。"""
    if set(expression) == {"ref"}:
        ref = expression["ref"]
        if ref not in values:
            raise ContractError(f"派生指标引用不存在: {ref}")
        return values[ref]
    op = expression.get("op")
    args = expression.get("args")
    if op not in NUMERIC_OPS or not isinstance(args, list) or not args:
        raise ContractError("派生指标表达式包含非法操作或参数")
    evaluated = [_number(evaluate_expression(item, values), f"表达式 {op}") for item in args]
    if op == "add":
        return sum(evaluated)
    if op == "subtract":
        if len(evaluated) != 2:
            raise ContractError("subtract 只接受两个参数")
        return evaluated[0] - evaluated[1]
    if op == "multiply":
        result: float | int = 1
        for value in evaluated:
            result *= value
        return result
    if op == "divide":
        if len(evaluated) != 2 or evaluated[1] == 0:
            raise ContractError("divide 要求两个参数且分母非零")
        return evaluated[0] / evaluated[1]
    if op == "mean":
        return mean(evaluated)
    return min(evaluated) if op == "min" else max(evaluated)


def _apply_transform(value: Any, transform: dict[str, Any] | None) -> Any:
    """执行单步、受限数值转换。"""
    if transform is None:
        return value
    numeric = _number(value, "待转换指标")
    operand = _number(transform.get("value"), "转换参数")
    op = transform.get("op")
    if op == "multiply":
        return numeric * operand
    if op == "divide" and operand != 0:
        return numeric / operand
    if op == "add":
        return numeric + operand
    if op == "subtract":
        return numeric - operand
    raise ContractError(f"非法或不可执行的指标转换: {op}")


def _source_value(path: Path, extractor: dict[str, Any]) -> Any:
    """运行一个白名单文件提取器。"""
    extractor_id = extractor["id"]
    selector = extractor.get("selector")
    options = extractor.get("options", {})
    if extractor_id == "json-pointer":
        return _json_pointer(json.loads(path.read_text(encoding="utf-8")), selector)
    if extractor_id in {"csv-cell", "csv-column-aggregate"}:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if extractor_id == "csv-cell":
            try:
                raw = rows[int(selector["row"])][selector["column"]]
            except (IndexError, KeyError, TypeError, ValueError) as exc:
                raise ContractError("CSV 单元格定位失败") from exc
            return float(raw) if re.fullmatch(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", raw) else raw
        column = selector["column"] if isinstance(selector, dict) else selector
        values = [float(row[column]) for row in rows]
        operation = options.get("aggregate", "mean")
        if not values or operation not in {"mean", "sum", "min", "max"}:
            raise ContractError("CSV 列聚合规则非法或列为空")
        return {"mean": mean, "sum": sum, "min": min, "max": max}[operation](values)
    if extractor_id == "text-regex-named-group":
        if (
            not isinstance(selector, dict)
            or not selector.get("pattern")
            or not selector.get("group")
        ):
            raise ContractError("文本正则必须声明 pattern 与 group")
        match = re.search(selector["pattern"], path.read_text(encoding="utf-8"), re.MULTILINE)
        if match is None:
            raise ContractError("文本正则未匹配")
        raw = match.group(selector["group"])
        return float(raw) if re.fullmatch(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", raw) else raw
    if extractor_id == "numpy-npz-key":
        try:
            import numpy as np
        except ImportError as exc:
            raise ContractError("numpy-npz-key 需要安装 numpy") from exc
        with np.load(path, allow_pickle=False) as archive:
            value = archive[str(selector)]
            if value.size != 1:
                raise ContractError("NPZ 指标必须是标量")
            return value.item()
    raise ContractError(f"不支持的文件提取器: {extractor_id}")


def materialize_metric(run_dir: Path, definition: dict[str, Any]) -> dict[str, Any]:
    """复验来源并把指标定义物化为不可变 provenance。"""
    extractor = dict(definition.get("extractor", {}))
    extractor_id = extractor.get("id")
    if extractor_id not in ALLOWED_EXTRACTORS:
        raise ContractError(f"提取器不在白名单: {extractor_id}")
    if extractor.get("version", EXTRACTOR_VERSION) != EXTRACTOR_VERSION:
        raise ContractError("提取器版本不受支持")
    current_impl = implementation_sha256()
    declared_impl = extractor.get("implementation_sha256")
    if declared_impl not in {None, current_impl}:
        raise ContractError("提取器实现哈希变化")
    extractor.update({"version": EXTRACTOR_VERSION, "implementation_sha256": current_impl})
    execution_id: str | None = None
    output_artifact: dict[str, str] | None = None
    inputs = definition.get("inputs", [])
    expression = definition.get("expression")
    if extractor_id == "derived-expression":
        values: dict[str, Any] = {}
        units: set[str] = set()
        for item in inputs:
            provenance = load_json(
                run_dir / "results" / "metric_specs" / f"{item['metric_spec_id']}.json"
            )
            require_valid(provenance, "metric_provenance")
            values[item["name"]] = provenance["final_value"]
            units.add(provenance["final_unit"])
        raw_value = evaluate_expression(expression, values)
        raw_unit = definition.get("raw_unit") or (
            next(iter(units)) if len(units) == 1 else "derived"
        )
    else:
        execution_id = definition.get("execution_record_id")
        if not isinstance(execution_id, str):
            raise ContractError("文件指标必须引用 execution_record_id")
        report = verify_execution_record(run_dir, execution_id)
        if not report["valid"]:
            raise ContractError("执行记录复验失败: " + "; ".join(report["errors"]))
        record = load_json(execution_record_path(run_dir, execution_id))
        declared = definition.get("output_artifact", {})
        output = next(
            (item for item in record["output_files"] if item["path"] == declared.get("path")), None
        )
        if output is None:
            raise ContractError("指标输出不属于执行记录的已哈希输出")
        path = resolve_inside(run_dir, output["path"], must_exist=True)
        actual_hash = sha256_file(path)
        if actual_hash != output["sha256"] or declared.get("sha256", actual_hash) != actual_hash:
            raise ContractError("指标输出哈希变化")
        output_artifact = {"path": output["path"], "sha256": actual_hash}
        raw_value = _source_value(path, extractor)
        raw_unit = definition.get("raw_unit")
        if not isinstance(raw_unit, str) or not raw_unit:
            raise ContractError("指标必须声明 raw_unit")
    final_value = _apply_transform(raw_value, definition.get("transform"))
    if "raw_value" in definition and definition["raw_value"] != raw_value:
        raise ContractError("指标值与输出字段不一致")
    if "final_value" in definition and definition["final_value"] != final_value:
        raise ContractError("转换后指标值不一致")
    provenance = {
        "schema_name": "metric_provenance",
        "schema_version": "2.0",
        "metric_spec_id": definition["metric_spec_id"],
        "execution_record_id": execution_id,
        "output_artifact": output_artifact,
        "extractor": extractor,
        "inputs": inputs,
        "expression": expression,
        "raw_value": raw_value,
        "raw_unit": raw_unit,
        "transform": definition.get("transform"),
        "final_value": final_value,
        "final_unit": definition.get("final_unit", raw_unit),
        "generated_at": utc_now(),
    }
    require_valid(provenance, "metric_provenance")
    path = run_dir / "results" / "metric_specs" / f"{provenance['metric_spec_id']}.json"
    if path.exists():
        raise ContractError(f"metric provenance 已存在，拒绝覆盖: {path.name}")
    atomic_json(path, provenance)
    return provenance


def verify_metric(run_dir: Path, metric_spec_id: str) -> dict[str, Any]:
    """重新提取并比较既有 provenance，但不覆盖原文件。"""
    path = run_dir / "results" / "metric_specs" / f"{metric_spec_id}.json"
    stored = load_json(path)
    require_valid(stored, "metric_provenance")
    temporary_definition = {
        key: value
        for key, value in stored.items()
        if key not in {"schema_name", "schema_version", "generated_at"}
    }
    temporary_path = path.with_suffix(".verify-tmp")
    path.rename(temporary_path)
    try:
        regenerated = materialize_metric(run_dir, temporary_definition)
        valid = all(
            regenerated.get(key) == stored.get(key)
            for key in (
                "raw_value",
                "raw_unit",
                "final_value",
                "final_unit",
                "extractor",
                "output_artifact",
            )
        )
        path.unlink()
        temporary_path.rename(path)
    except Exception:
        if path.exists():
            path.unlink()
        temporary_path.rename(path)
        raise
    return {"valid": valid, "metric_spec_id": metric_spec_id, "sha256": sha256_file(path)}
