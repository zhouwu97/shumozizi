"""基于独立 R1/R2 审核产物计算 held-out reviewer 指标。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, load_json, sha256_file
from shumozizi.core.schema import require_valid

STAGE_SKILLS = {
    "R1_MODELING": "mathmodel-review-r1-modeling",
    "R2_EXPERIMENT": "mathmodel-review-r2-experiment",
}


def _normalized(value: str) -> str:
    """统一标签空白和大小写，避免仅因排版造成不匹配。"""
    return " ".join(value.casefold().split())


def _matching_findings(
    expected: dict[str, Any], findings: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """按 oracle 允许的语义标签匹配 reviewer finding。"""
    accepted = {_normalized(label) for label in expected["accepted_labels"]}
    return [item for item in findings if _normalized(item["fault"]) in accepted]


def _verify_review_provenance(
    observations_path: Path, case_id: str, run: dict[str, Any]
) -> None:
    """实际读取 request/session/report，拒绝只自填哈希的观察。"""
    for artifact in ("request", "session", "report"):
        raw_path = Path(run[f"review_{artifact}_path"])
        path = raw_path if raw_path.is_absolute() else observations_path.parent / raw_path
        if not path.is_file():
            raise ContractError(f"reviewer {artifact} 产物不存在: {case_id}")
        if sha256_file(path) != run[f"review_{artifact}_sha256"]:
            raise ContractError(f"reviewer {artifact} 产物哈希不一致: {case_id}")


def evaluate_reviewer_benchmark(
    cases_path: Path,
    oracle_path: Path,
    observations_path: Path,
) -> dict[str, Any]:
    """只从独立审核观察计算 reviewer 指标，禁止调用确定性规则。"""
    cases_doc = load_json(cases_path)
    oracle_doc = load_json(oracle_path)
    observations_doc = load_json(observations_path)
    require_valid(cases_doc, "scientific_reviewer_cases")
    require_valid(oracle_doc, "scientific_reviewer_oracle")
    require_valid(observations_doc, "scientific_reviewer_observations")

    benchmark_ids = {
        cases_doc["benchmark_id"],
        oracle_doc["benchmark_id"],
        observations_doc["benchmark_id"],
    }
    if len(benchmark_ids) != 1:
        raise ContractError("reviewer benchmark_id 不一致")
    if oracle_doc["case_set_sha256"] != sha256_file(cases_path):
        raise ContractError("reviewer oracle 未绑定当前 held-out 变体集")
    if observations_doc["case_set_sha256"] != sha256_file(cases_path):
        raise ContractError("reviewer observations 未绑定当前 held-out 变体集")
    if observations_doc["oracle_sha256"] != sha256_file(oracle_path):
        raise ContractError("reviewer observations 未绑定当前隐藏 oracle")

    cases = {item["case_id"]: item for item in cases_doc["cases"]}
    oracle = {item["case_id"]: item for item in oracle_doc["cases"]}
    observations = {
        item["case_id"]: item for item in observations_doc["observations"]
    }
    if len(cases) != len(cases_doc["cases"]):
        raise ContractError("held-out 变体集 case_id 必须唯一")
    if len(oracle) != len(oracle_doc["cases"]):
        raise ContractError("reviewer oracle case_id 必须唯一")
    if len(observations) != len(observations_doc["observations"]):
        raise ContractError("reviewer observations case_id 必须唯一")
    if set(cases) != set(oracle) or set(cases) != set(observations):
        raise ContractError("reviewer cases、oracle 与 observations 必须逐例完整对应")

    expected_finding_count = 0
    detected_finding_count = 0
    stage_correct_count = 0
    severity_correct_count = 0
    clean_case_count = 0
    false_positive_count = 0
    unknown_count = 0
    for case_id, case in cases.items():
        expected_case = oracle[case_id]
        observation = observations[case_id]
        run_stages = {run["stage"] for run in observation["review_runs"]}
        if len(run_stages) != len(observation["review_runs"]):
            raise ContractError(f"reviewer observation 重复审核阶段: {case_id}")
        if not set(case["required_review_stages"]).issubset(run_stages):
            raise ContractError(f"reviewer observation 缺少要求的 R1/R2 审核: {case_id}")
        for run in observation["review_runs"]:
            if run["skill"] != STAGE_SKILLS[run["stage"]]:
                raise ContractError(f"reviewer stage 与 Skill 不匹配: {case_id}")
            _verify_review_provenance(observations_path, case_id, run)
        if expected_case["is_fault"]:
            expected_finding_count += len(expected_case["expected_findings"])
        else:
            clean_case_count += 1
        if observation["outcome"] == "unknown":
            unknown_count += 1
            continue
        if expected_case["is_fault"]:
            for expected in expected_case["expected_findings"]:
                matches = _matching_findings(expected, observation["findings"])
                if not matches:
                    continue
                detected_finding_count += 1
                if any(item["stage"] == expected["expected_stage"] for item in matches):
                    stage_correct_count += 1
                if any(
                    item["severity"] in expected["expected_severity_range"]
                    for item in matches
                ):
                    severity_correct_count += 1
        elif observation["findings"]:
            false_positive_count += 1

    if expected_finding_count == 0 or clean_case_count == 0:
        raise ContractError("reviewer benchmark 必须同时包含错误与干净对照")
    metrics = {
        "reviewer_scientific_fault_recall": detected_finding_count
        / expected_finding_count,
        "reviewer_false_positive_rate": false_positive_count / clean_case_count,
        "reviewer_correct_stage_assignment": stage_correct_count
        / expected_finding_count,
        "reviewer_severity_calibration": severity_correct_count
        / expected_finding_count,
        "reviewer_unknown_rate": unknown_count / len(cases),
    }
    return {
        "benchmark_id": cases_doc["benchmark_id"],
        "case_set_sha256": sha256_file(cases_path),
        "oracle_sha256": sha256_file(oracle_path),
        "metrics": metrics,
    }
