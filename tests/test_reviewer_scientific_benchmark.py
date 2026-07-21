"""held-out 变体集与独立 R1/R2 reviewer 指标的来源隔离测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, sha256_file
from shumozizi.core.schema import require_valid
from shumozizi.workflow.reviewer_benchmark import evaluate_reviewer_benchmark

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = ROOT / "benchmarks/scientific_fault_benchmark_v1"
CASES_PATH = BENCHMARK_DIR / "reviewer_variants.json"
ORACLE_PATH = BENCHMARK_DIR / "reviewer_oracle.json"
STATUS_PATH = BENCHMARK_DIR / "reviewer_status.json"
STAGE_SKILLS = {
    "R1_MODELING": "mathmodel-review-r1-modeling",
    "R2_EXPERIMENT": "mathmodel-review-r2-experiment",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _complete_observations(provenance_dir: Path) -> dict:
    cases_doc = _load(CASES_PATH)
    oracle_by_id = {item["case_id"]: item for item in _load(ORACLE_PATH)["cases"]}
    observations = []
    for case in cases_doc["cases"]:
        oracle = oracle_by_id[case["case_id"]]
        review_runs = []
        for index, stage in enumerate(case["required_review_stages"]):
            artifacts = {}
            for artifact in ("request", "session", "report"):
                path = provenance_dir / f"{case['case_id']}-{index}-{artifact}.json"
                path.write_text(
                    json.dumps({"case_id": case["case_id"], "stage": stage}),
                    encoding="utf-8",
                )
                artifacts[f"review_{artifact}_path"] = path.name
                artifacts[f"review_{artifact}_sha256"] = sha256_file(path)
            review_runs.append(
                {
                    "stage": stage,
                    "skill": STAGE_SKILLS[stage],
                    **artifacts,
                }
            )
        observations.append(
            {
                "case_id": case["case_id"],
                "outcome": "reviewed",
                "review_runs": review_runs,
                "findings": [
                    {
                        "fault": expected["accepted_labels"][0],
                        "stage": expected["expected_stage"],
                        "severity": expected["expected_severity_range"][0],
                        "evidence": ["independent-review:test-fixture"],
                    }
                    for expected in oracle["expected_findings"]
                ],
            }
        )
    return {
        "schema_name": "scientific_reviewer_observations",
        "schema_version": "1.0",
        "benchmark_id": cases_doc["benchmark_id"],
        "case_set_sha256": sha256_file(CASES_PATH),
        "oracle_sha256": sha256_file(ORACLE_PATH),
        "observations": observations,
    }


def test_reviewer_variants_are_label_hidden_and_frozen() -> None:
    cases_doc = _load(CASES_PATH)
    oracle_doc = _load(ORACLE_PATH)
    status = _load(STATUS_PATH)
    require_valid(cases_doc, "scientific_reviewer_cases")
    require_valid(oracle_doc, "scientific_reviewer_oracle")
    require_valid(status, "scientific_reviewer_benchmark_status")

    assert oracle_doc["case_set_sha256"] == sha256_file(CASES_PATH)
    assert status["case_set_sha256"] == sha256_file(CASES_PATH)
    assert status["oracle_sha256"] == sha256_file(ORACLE_PATH)
    assert len(cases_doc["cases"]) == 10
    assert all(
        not ({"is_fault", "expected_fault", "expected_findings"} & set(case))
        for case in cases_doc["cases"]
    )
    assert sum(not item["is_fault"] for item in oracle_doc["cases"]) == 4
    assert len(next(item for item in oracle_doc["cases"] if item["case_id"] == "RV-06-two-faults")["expected_findings"]) == 2

    by_id = {item["case_id"]: item for item in cases_doc["cases"]}
    temporal_text = " ".join(by_id["RV-01-temporal-order"].values().__str__())
    target_text = " ".join(str(value) for value in by_id["RV-02-label-aggregate"].values())
    assert all(term not in temporal_text for term in ("未来", "泄漏", "随机切分"))
    assert all(term not in target_text for term in ("target_mean", "groupby(y)", "全数据"))


def test_reviewer_metric_is_unmeasured_until_independent_reviews_exist() -> None:
    status = _load(STATUS_PATH)
    assert status["status"] == "not_run"
    assert status["scientific_capability_claim_allowed"] is False
    assert set(status["metrics"].values()) == {None}


def test_reviewer_metrics_only_use_bound_independent_observations(tmp_path: Path) -> None:
    observations = _complete_observations(tmp_path)
    observations_path = tmp_path / "reviewer_observations.json"
    atomic_json(observations_path, observations)
    require_valid(observations, "scientific_reviewer_observations")

    result = evaluate_reviewer_benchmark(CASES_PATH, ORACLE_PATH, observations_path)
    assert result["metrics"] == {
        "reviewer_scientific_fault_recall": 1.0,
        "reviewer_false_positive_rate": 0.0,
        "reviewer_correct_stage_assignment": 1.0,
        "reviewer_severity_calibration": 1.0,
        "reviewer_unknown_rate": 0.0,
    }
    assert "deterministic_fault_recall" not in result["metrics"]

    observations["case_set_sha256"] = "0" * 64
    atomic_json(observations_path, observations)
    with pytest.raises(ContractError, match="held-out 变体集"):
        evaluate_reviewer_benchmark(CASES_PATH, ORACLE_PATH, observations_path)


def test_reviewer_metrics_reject_incomplete_case_coverage(tmp_path: Path) -> None:
    observations = _complete_observations(tmp_path)
    observations["observations"].pop()
    observations_path = tmp_path / "reviewer_observations.json"
    atomic_json(observations_path, observations)
    with pytest.raises(ContractError, match="逐例完整对应"):
        evaluate_reviewer_benchmark(CASES_PATH, ORACLE_PATH, observations_path)
