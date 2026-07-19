"""论文证据增强审计 Adapter；只读审计事实，不改变结果或状态。"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, load_json, sha256_file
from shumozizi.core.schema import require_valid
from shumozizi.evidence.validator import _active_result, _claim_value

UNIT_CONVERSIONS: dict[tuple[str, str], float] = {
    ("m", "km"): 0.001,
    ("km", "m"): 1000.0,
    ("g", "kg"): 0.001,
    ("kg", "g"): 1000.0,
    ("mg/L", "kg/m^3"): 1.0,
    ("kg/m^3", "mg/L"): 1.0,
}


def _check_unit_conversion(claim: dict[str, Any], units: set[str]) -> str | None:
    """要求单位变化由白名单比例或明确百分比表达式解释。"""
    display = claim["display"]
    display_unit = display.get("unit", "")
    scale = display.get("scale", 1)
    expression = claim.get("expression") or {}
    if len(units) == 1:
        source_unit = next(iter(units))
        if display_unit in {"", source_unit}:
            return None
        if display_unit == "%" and expression.get("op") == "divide" and scale == 100:
            return None
        expected = UNIT_CONVERSIONS.get((source_unit, display_unit))
        if expected is not None and scale == expected:
            return None
        return f"未声明合法单位转换: {source_unit} -> {display_unit}"
    if len(units) > 1 and expression.get("op") != "divide":
        return "不同单位输入只允许通过明确的 divide 表达式形成比值"
    if len(units) > 1 and display_unit == "%" and scale == 100:
        return None
    return "多单位输入必须声明可解释的比值展示单位"


def audit_paper_evidence(run_dir: Path, final_pdf: Path) -> dict[str, Any]:
    """检查多输入主张、单位、舍入和生成文件哈希。"""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        evidence_map = load_json(run_dir / "paper" / "evidence_map.json")
        require_valid(evidence_map, "evidence_map")
        generated = run_dir / "paper" / "generated" / "evidence_values.typ"
        if not generated.is_file():
            errors.append("缺少生成的 evidence_values.typ")
        else:
            text = generated.read_text(encoding="utf-8")
            if "#let evidence(id)" not in text:
                errors.append("generated evidence 文件缺少 evidence macro")
        source_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((run_dir / "paper").rglob("*.typ"))
            if "generated" not in path.parts
        )
        for claim in evidence_map["claims"]:
            claim_id = claim["claim_id"]
            if claim["display"]["decimals"] < 0:
                errors.append(f"舍入位数不能为负: {claim_id}")
            scale = claim["display"].get("scale", 1)
            if (
                not isinstance(scale, (int, float))
                or isinstance(scale, bool)
                or not math.isfinite(scale)
            ):
                errors.append(f"展示比例必须是有限数值: {claim_id}")
            if len(claim["inputs"]) > 1 and not claim.get("expression"):
                errors.append(f"多输入主张必须显式提供 expression: {claim_id}")
            units: set[str] = set()
            for item in claim["inputs"]:
                try:
                    _, sealed = _active_result(run_dir, item["result_id"])
                    metric = next(
                        row
                        for row in sealed["metrics"]
                        if row["metric_spec_id"] == item["metric_spec_id"]
                    )
                    units.add(metric["unit"])
                except (ContractError, StopIteration) as exc:
                    errors.append(f"主张 {claim_id} 的输入无效: {exc}")
            display_unit = claim["display"].get("unit", "")
            if len(units) > 1 and not display_unit:
                errors.append(f"多单位输入必须声明转换后的 display.unit: {claim_id}")
            conversion_error = _check_unit_conversion(claim, units)
            if conversion_error:
                errors.append(f"主张 {claim_id}: {conversion_error}")
            if f'#evidence("{claim_id}")' not in source_text:
                errors.append(f"论文源缺少 claim macro: {claim_id}")
            try:
                _claim_value(run_dir, claim)
            except Exception as exc:
                errors.append(f"主张表达式无法计算 {claim_id}: {exc}")
        report_path = run_dir / "review" / "EVIDENCE_VALIDATION.json"
        if report_path.is_file():
            report = load_json(report_path)
            if report.get("generated_evidence_sha256") and generated.is_file():
                if report["generated_evidence_sha256"] != sha256_file(generated):
                    errors.append("EVIDENCE_VALIDATION 与当前 generated evidence 哈希不一致")
    except Exception as exc:
        errors.append(str(exc))
    return {
        "adapter_id": "paper-evidence-audit",
        "adapter_version": "1.0.0",
        "status": "pass" if not errors else "blocked",
        "errors": errors,
        "warnings": warnings,
    }
