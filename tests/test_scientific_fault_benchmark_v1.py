"""A2 确定性科学预检开发集的完整性、冻结和指标复算。"""

from __future__ import annotations

import json
from pathlib import Path

from shumozizi.core.io import sha256_file
from shumozizi.workflow.scientific_review import (
    audit_deterministic_prechecks,
    evaluate_deterministic_prechecks,
)

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "benchmarks/scientific_fault_benchmark_v1/cases.json"
BASELINE_PATH = ROOT / "benchmarks/scientific_fault_benchmark_v1/baseline.json"
REQUIRED_FIELDS = {
    "problem_fragment",
    "data_or_fixture",
    "model_spec",
    "experiment_plan",
    "code_or_pseudocode",
    "expected_fault",
    "expected_stage",
    "expected_severity_range",
    "oracle",
    "allowed_alternative_judgments",
}


def _load() -> tuple[dict, dict]:
    return (
        json.loads(CASES_PATH.read_text(encoding="utf-8")),
        json.loads(BASELINE_PATH.read_text(encoding="utf-8")),
    )


def test_benchmark_contains_twelve_frozen_cases_and_three_controls() -> None:
    cases_doc, _ = _load()
    cases = cases_doc["cases"]
    assert len(cases) == 12
    assert len({case["case_id"] for case in cases}) == 12
    assert sum(case["is_fault"] for case in cases) == 9
    assert sum(not case["is_fault"] for case in cases) == 3
    assert all(REQUIRED_FIELDS <= case.keys() for case in cases)


def test_baseline_is_bound_to_case_set_and_has_one_observation_per_case() -> None:
    cases_doc, baseline = _load()
    assert baseline["case_set_sha256"] == sha256_file(CASES_PATH)
    case_ids = {case["case_id"] for case in cases_doc["cases"]}
    observations = baseline["observations"]
    assert {item["case_id"] for item in observations} == case_ids
    assert len(observations) == len(case_ids)


def test_baseline_metrics_recompute_from_frozen_observations() -> None:
    cases_doc, baseline = _load()
    cases = {case["case_id"]: case for case in cases_doc["cases"]}
    observations = {item["case_id"]: item for item in baseline["observations"]}
    fault_ids = {case_id for case_id, case in cases.items() if case["is_fault"]}
    clean_ids = set(cases) - fault_ids
    detected = {
        case_id for case_id, item in observations.items() if item["outcome"] == "detected"
    }
    false_positive = {
        case_id
        for case_id, item in observations.items()
        if case_id in clean_ids and item["outcome"] == "false_positive"
    }
    stage_correct = {
        case_id
        for case_id in fault_ids
        if observations[case_id]["predicted_stage"] == cases[case_id]["expected_stage"]
    }
    metrics = baseline["metrics"]
    assert metrics["deterministic_fault_recall"] == len(detected & fault_ids) / len(
        fault_ids
    )
    assert metrics["deterministic_false_positive_rate"] == len(false_positive) / len(
        clean_ids
    )
    assert metrics["deterministic_correct_stage_assignment"] == len(stage_correct) / len(
        fault_ids
    )
    assert metrics["deterministic_unknown_rate"] == 0.0


def test_a4_deterministic_prechecks_detect_development_cases() -> None:
    cases_doc, _ = _load()
    result = evaluate_deterministic_prechecks(cases_doc["cases"])
    metrics = result["metrics"]

    assert metrics == {
        "deterministic_fault_recall": 1.0,
        "deterministic_false_positive_rate": 0.0,
        "deterministic_correct_stage_assignment": 1.0,
        "deterministic_severity_calibration": 1.0,
    }
    assert "reviewer_scientific_fault_recall" not in metrics
    assert "scientific_fault_recall" not in metrics
    assert all("suspicions" in item for item in result["observations"])
    assert all("findings" not in item for item in result["observations"])


def test_precheck_output_is_suspicion_not_formal_finding() -> None:
    case = {
        "problem_fragment": "使用未来预测做滚动评估",
        "data_or_fixture": "按 subject 分组的数据",
        "model_spec": "使用 Bootstrap 估计区间",
        "experiment_plan": "随机抽样但不使用随机切分，按 group 保持边界",
        "code_or_pseudocode": "train_test_split(..., shuffle=False)",
    }
    output = audit_deterministic_prechecks(case)
    assert output
    assert all(item["requires_independent_review"] is True for item in output)
    assert all("finding_id" not in item for item in output)
    assert all("gate_effect" not in item for item in output)
    assert all("accepted" not in item for item in output)


def test_sensitive_words_in_normal_text_do_not_decide_scientific_error() -> None:
    case = {
        "problem_fragment": "未来预测任务，使用 Bootstrap 置信区间",
        "data_or_fixture": "按 group 保存同一对象的全部观测",
        "model_spec": "目标仅在训练折内计算，随机种子固定",
        "experiment_plan": "按 group 划分并使用时间顺序验证",
        "code_or_pseudocode": "train_test_split(..., shuffle=False)",
    }
    output = audit_deterministic_prechecks(case)
    assert output == []
