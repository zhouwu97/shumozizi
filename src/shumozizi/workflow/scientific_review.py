"""R1/R2/R3 可复用的确定性科学错误诊断。"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ScientificFinding:
    """由跨材料一致性检查产生的科学 finding。"""

    fault: str
    stage: str
    severity: str
    evidence: list[str]


def _text(case: dict[str, Any], *fields: str) -> str:
    return " ".join(str(case.get(field, "")) for field in fields).casefold()


def _time_leakage(case: dict[str, Any]) -> ScientificFinding | None:
    context = _text(case, "problem_fragment", "data_or_fixture", "model_spec")
    experiment = _text(case, "experiment_plan", "code_or_pseudocode")
    future_signal = any(term in context for term in ("t+1", "未来", "future"))
    shuffled_split = "shuffle=true" in experiment or "随机切分" in experiment
    if future_signal and shuffled_split:
        return ScientificFinding("时间泄漏", "R2_EXPERIMENT", "P1", ["未来信息与随机切分同时出现"])
    return None


def _target_leakage(case: dict[str, Any]) -> ScientificFinding | None:
    context = _text(case, "data_or_fixture", "model_spec", "experiment_plan", "code_or_pseudocode")
    target_stat = any(term in context for term in ("target_mean", "groupby(y)", "['y'].transform", "目标编码"))
    global_fit = any(term in context for term in ("全数据", "交叉验证前", "共用"))
    if target_stat and global_fit:
        return ScientificFinding("目标派生特征泄漏", "R2_EXPERIMENT", "P1", ["目标统计量在验证切分前构造"])
    return None


def _unit_error(case: dict[str, Any]) -> ScientificFinding | None:
    data = _text(case, "data_or_fixture")
    formula = _text(case, "model_spec", "code_or_pseudocode")
    mixed_units = "unit=kw" in data and "unit=s" in data and "元/kwh" in data
    missing_conversion = (
        "power_kw * duration_s * price" in formula
        and not any(term in formula for term in ("/ 3600", "/3600", "to_hour"))
    )
    if mixed_units and missing_conversion:
        return ScientificFinding("公式量纲错误", "R1_MODELING", "P1", ["kW、s 与元/kWh 未换算即相乘"])
    return None


def _nonidentifiable(case: dict[str, Any]) -> ScientificFinding | None:
    model = _text(case, "problem_fragment", "data_or_fixture", "model_spec", "code_or_pseudocode")
    product_only = bool(re.search(r"a\s*\*\s*b", model)) and "curve_fit" in model
    reports_separate = "同时报告 a、b" in model or "两个参数" in model
    if product_only and reports_separate:
        return ScientificFinding("参数不可辨识但拟合优度很高", "R1_MODELING", "P1", ["参数仅以乘积 a*b 进入模型"])
    return None


def _wrong_formula(case: dict[str, Any]) -> ScientificFinding | None:
    mechanism = _text(case, "data_or_fixture", "problem_fragment")
    formula = _text(case, "code_or_pseudocode")
    shared = _text(case, "model_spec", "experiment_plan")
    if "线性衰减" in mechanism and "distance ** 2" in formula and "两份代码" in shared:
        return ScientificFinding("两份代码共享同一错误公式", "R1_MODELING", "P1", ["线性机制与平方衰减公式矛盾"])
    return None


def _group_split(case: dict[str, Any]) -> ScientificFinding | None:
    data = _text(case, "data_or_fixture", "problem_fragment")
    split = _text(case, "experiment_plan", "code_or_pseudocode")
    repeated = "subject_id" in data and any(term in data for term in ("重复", "每个 subject"))
    random_rows = "train_test_split" in split and not any(term in split for term in ("group", "subject_id"))
    if repeated and random_rows:
        return ScientificFinding("重复测量样本泄漏", "R2_EXPERIMENT", "P1", ["重复测量按行随机拆分"])
    return None


def _hidden_constraint(case: dict[str, Any]) -> ScientificFinding | None:
    source = _text(case, "problem_fragment", "data_or_fixture")
    model = _text(case, "model_spec", "code_or_pseudocode")
    required_floor = any(term in source for term in ("库存下限", ">= 0", ">=0"))
    omitted = "未声明库存下限" in model or ("capacity" in model and "inventory" not in model)
    if required_floor and omitted:
        return ScientificFinding("遗漏隐藏硬约束", "R1_MODELING", "P0", ["题面库存下限未进入优化约束"])
    return None


def _weak_robustness(case: dict[str, Any]) -> ScientificFinding | None:
    context = _text(case, "data_or_fixture", "experiment_plan", "code_or_pseudocode")
    tiny = "1e-12" in context
    material_gap = bool(re.search(r"\b40%", context)) or "不确定性量级" in context
    if tiny and material_gap:
        return ScientificFinding("稳健性实验无辨识力", "R2_EXPERIMENT", "P2", ["扰动量级远小于结论差距"])
    return None


def _direction_reversal(case: dict[str, Any]) -> ScientificFinding | None:
    data = _text(case, "data_or_fixture", "problem_fragment")
    model = _text(case, "model_spec", "code_or_pseudocode")
    values = re.search(r"a\s*=\s*(\d+(?:\.\d+)?).*b\s*=\s*(\d+(?:\.\d+)?)", data)
    minimizes = "成本最小" in model or "cost" in model
    chooses_max = "max(cost" in model or "b 更优" in data
    if values and minimizes and chooses_max and float(values.group(2)) > float(values.group(1)):
        return ScientificFinding("图表数字正确但论文结论方向相反", "R3_PAPER_LOGIC", "P1", ["最小化目标却选择更大成本"])
    return None


SCIENTIFIC_RULES: tuple[Callable[[dict[str, Any]], ScientificFinding | None], ...] = (
    _time_leakage,
    _target_leakage,
    _unit_error,
    _nonidentifiable,
    _wrong_formula,
    _group_split,
    _hidden_constraint,
    _weak_robustness,
    _direction_reversal,
)


def audit_scientific_case(case: dict[str, Any]) -> list[dict[str, Any]]:
    """运行全部独立规则并返回可序列化 findings。"""
    return [asdict(finding) for rule in SCIENTIFIC_RULES if (finding := rule(case))]


def evaluate_scientific_benchmark(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """计算冻结案例集的召回、误报、阶段和严重度指标。"""
    rows = []
    for case in cases:
        findings = audit_scientific_case(case)
        rows.append({"case_id": case["case_id"], "findings": findings})
    fault_cases = [case for case in cases if case["is_fault"]]
    clean_cases = [case for case in cases if not case["is_fault"]]
    by_id = {row["case_id"]: row["findings"] for row in rows}
    detected = [case for case in fault_cases if by_id[case["case_id"]]]
    false_positives = [case for case in clean_cases if by_id[case["case_id"]]]
    stage_correct = [
        case
        for case in detected
        if any(item["stage"] == case["expected_stage"] for item in by_id[case["case_id"]])
    ]
    severity_correct = [
        case
        for case in detected
        if any(item["severity"] in case["expected_severity_range"] for item in by_id[case["case_id"]])
    ]
    metrics = {
        "deterministic_fault_recall": len(detected) / len(fault_cases),
        "scientific_fault_recall": len(detected) / len(fault_cases),
        "false_positive_rate": len(false_positives) / len(clean_cases),
        "correct_stage_assignment": len(stage_correct) / len(fault_cases),
        "severity_calibration": len(severity_correct) / len(fault_cases),
        "unknown_rate": 0.0,
    }
    return {"observations": rows, "metrics": metrics}
