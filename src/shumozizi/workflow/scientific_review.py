"""R1/R2/R3 的确定性科学预检，不替代独立审核。"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class PrecheckSuspicion:
    """由固定规则产生的可疑模式，不是正式 reviewer finding。"""

    suspicion: str
    suggested_review_stage: str
    suggested_severity: str
    suggested_probe: str
    evidence: list[str]
    requires_independent_review: bool = True


def _text(case: dict[str, Any], *fields: str) -> str:
    return " ".join(str(case.get(field, "")) for field in fields).casefold()


def _time_leakage(case: dict[str, Any]) -> PrecheckSuspicion | None:
    context = _text(case, "problem_fragment", "data_or_fixture", "model_spec")
    experiment = _text(case, "experiment_plan", "code_or_pseudocode")
    future_signal = any(term in context for term in ("t+1", "未来", "future"))
    shuffled_split = "shuffle=true" in experiment or "随机切分" in experiment
    if future_signal and shuffled_split:
        return PrecheckSuspicion("时间泄漏模式", "R2_EXPERIMENT", "P1", "independent_reimplementation", ["未来信息与随机切分同时出现"])
    return None


def _target_leakage(case: dict[str, Any]) -> PrecheckSuspicion | None:
    context = _text(case, "data_or_fixture", "model_spec", "experiment_plan", "code_or_pseudocode")
    target_stat = any(term in context for term in ("target_mean", "groupby(y)", "['y'].transform", "目标编码"))
    global_fit = any(term in context for term in ("全数据", "交叉验证前", "共用"))
    if target_stat and global_fit:
        return PrecheckSuspicion("目标派生特征泄漏模式", "R2_EXPERIMENT", "P1", "permutation_test", ["目标统计量在验证切分前构造"])
    return None


def _unit_error(case: dict[str, Any]) -> PrecheckSuspicion | None:
    data = _text(case, "data_or_fixture")
    formula = _text(case, "model_spec", "code_or_pseudocode")
    mixed_units = "unit=kw" in data and "unit=s" in data and "元/kwh" in data
    missing_conversion = (
        "power_kw * duration_s * price" in formula
        and not any(term in formula for term in ("/ 3600", "/3600", "to_hour"))
    )
    if mixed_units and missing_conversion:
        return PrecheckSuspicion("公式量纲错误模式", "R1_MODELING", "P1", "unit_consistency_probe", ["kW、s 与元/kWh 未换算即相乘"])
    return None


def _nonidentifiable(case: dict[str, Any]) -> PrecheckSuspicion | None:
    model = _text(case, "problem_fragment", "data_or_fixture", "model_spec", "code_or_pseudocode")
    product_only = bool(re.search(r"a\s*\*\s*b", model)) and "curve_fit" in model
    reports_separate = "同时报告 a、b" in model or "两个参数" in model
    if product_only and reports_separate:
        return PrecheckSuspicion("参数不可辨识模式", "R1_MODELING", "P1", "synthetic_recovery", ["参数仅以乘积 a*b 进入模型"])
    return None


def _wrong_formula(case: dict[str, Any]) -> PrecheckSuspicion | None:
    mechanism = _text(case, "data_or_fixture", "problem_fragment")
    formula = _text(case, "code_or_pseudocode")
    shared = _text(case, "model_spec", "experiment_plan")
    if "线性衰减" in mechanism and "distance ** 2" in formula and "两份代码" in shared:
        return PrecheckSuspicion("共享错误公式模式", "R1_MODELING", "P1", "independent_reimplementation", ["线性机制与平方衰减公式矛盾"])
    return None


def _group_split(case: dict[str, Any]) -> PrecheckSuspicion | None:
    data = _text(case, "data_or_fixture", "problem_fragment")
    split = _text(case, "experiment_plan", "code_or_pseudocode")
    repeated = "subject_id" in data and any(term in data for term in ("重复", "每个 subject"))
    random_rows = "train_test_split" in split and not any(term in split for term in ("group", "subject_id"))
    if repeated and random_rows:
        return PrecheckSuspicion("重复测量切分风险", "R2_EXPERIMENT", "P1", "independent_reimplementation", ["重复测量按行随机拆分"])
    return None


def _hidden_constraint(case: dict[str, Any]) -> PrecheckSuspicion | None:
    source = _text(case, "problem_fragment", "data_or_fixture")
    model = _text(case, "model_spec", "code_or_pseudocode")
    required_floor = any(term in source for term in ("库存下限", ">= 0", ">=0"))
    omitted = "未声明库存下限" in model or ("capacity" in model and "inventory" not in model)
    if required_floor and omitted:
        return PrecheckSuspicion("隐藏硬约束遗漏模式", "R1_MODELING", "P0", "constraint_counterexample", ["题面库存下限未进入优化约束"])
    return None


def _weak_robustness(case: dict[str, Any]) -> PrecheckSuspicion | None:
    context = _text(case, "data_or_fixture", "experiment_plan", "code_or_pseudocode")
    tiny = "1e-12" in context
    material_gap = bool(re.search(r"\b40%", context)) or "不确定性量级" in context
    if tiny and material_gap:
        return PrecheckSuspicion("稳健性辨识力不足模式", "R2_EXPERIMENT", "P2", "sensitivity_probe", ["扰动量级远小于结论差距"])
    return None


def _direction_reversal(case: dict[str, Any]) -> PrecheckSuspicion | None:
    data = _text(case, "data_or_fixture", "problem_fragment")
    model = _text(case, "model_spec", "code_or_pseudocode")
    values = re.search(r"a\s*=\s*(\d+(?:\.\d+)?).*b\s*=\s*(\d+(?:\.\d+)?)", data)
    minimizes = "成本最小" in model or "cost" in model
    chooses_max = "max(cost" in model or "b 更优" in data
    if values and minimizes and chooses_max and float(values.group(2)) > float(values.group(1)):
        return PrecheckSuspicion("结论方向与目标不一致模式", "R3_PAPER_LOGIC", "P1", "exact_oracle", ["最小化目标却选择更大成本"])
    return None


DETERMINISTIC_PRECHECK_RULES: tuple[
    Callable[[dict[str, Any]], PrecheckSuspicion | None], ...
] = (
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


def audit_deterministic_prechecks(case: dict[str, Any]) -> list[dict[str, Any]]:
    """运行固定规则；结果只能作为机器预检证据。"""
    return [
        asdict(suspicion)
        for rule in DETERMINISTIC_PRECHECK_RULES
        if (suspicion := rule(case))
    ]


def evaluate_deterministic_prechecks(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """计算冻结开发集上的机器预检指标，不生成 reviewer 指标。"""
    rows = []
    for case in cases:
        suspicions = audit_deterministic_prechecks(case)
        rows.append({"case_id": case["case_id"], "suspicions": suspicions})
    fault_cases = [case for case in cases if case["is_fault"]]
    clean_cases = [case for case in cases if not case["is_fault"]]
    by_id = {row["case_id"]: row["suspicions"] for row in rows}
    detected = [case for case in fault_cases if by_id[case["case_id"]]]
    false_positives = [case for case in clean_cases if by_id[case["case_id"]]]
    stage_correct = [
        case
        for case in detected
        if any(
            item["suggested_review_stage"] == case["expected_stage"]
            for item in by_id[case["case_id"]]
        )
    ]
    severity_correct = [
        case
        for case in detected
        if any(
            item["suggested_severity"] in case["expected_severity_range"]
            for item in by_id[case["case_id"]]
        )
    ]
    metrics = {
        "deterministic_fault_recall": len(detected) / len(fault_cases),
        "deterministic_false_positive_rate": len(false_positives) / len(clean_cases),
        "deterministic_correct_stage_assignment": len(stage_correct) / len(fault_cases),
        "deterministic_severity_calibration": len(severity_correct) / len(fault_cases),
    }
    return {"observations": rows, "metrics": metrics}
