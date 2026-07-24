"""执行五问独立三段式质量协议并写入质量层。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 运行目录位于仓库的 isolated-runs 下；该层级固定，避免依赖当前工作目录。
REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.simple.adapters import run_verification_protocol
from shumozizi.simple.quality import assess_result_quality

ROOT = Path(__file__).resolve().parents[1]

RESULT_IDS = {
    "Q1": "q1_quality_verified_revision3",
    "Q2": "q2_quality_verified_revision3",
    "Q3": "q3_quality_verified_revision3",
    "Q4": "q4_quality_verified_revision3",
    "Q5": "q5_quality_verified_revision3",
}


def _contract(question: str) -> dict[str, object]:
    """构造一问的选择合同和三段受控执行边界。"""
    lower, upper, bins, variable, group, metric = (0.0, 15.0, 16, "action_count", "all_action_counts", "objective_missile_s") if question == "Q5" else (0.0, 2.0, 3, "variant", "local_variants", "duration_s")
    raw = f"results/raw/{question.lower()}.json"
    prefix = f"results/raw/{question.lower()}.quality"
    candidates = f"{prefix}.candidates.json"
    exact = f"{prefix}.exact.json"
    audit = f"{prefix}.audit.json"
    if question == "Q5":
        coverage = {
            "candidate_variables": ["action_count", "seed"],
            "groups": [
                {
                    "id": "all_action_counts",
                    "variables": ["action_count"],
                    "metric": "occupied_bins",
                    "bins_per_variable": 16,
                    "bounds": {"action_count": [0.0, 15.0]},
                    "minimum_joint_coverage": 1.0,
                },
                {
                    "id": "both_seeds",
                    "variables": ["seed"],
                    "metric": "occupied_bins",
                    "bins_per_variable": 2,
                    "bounds": {"seed": [202505.0, 202506.0]},
                    "minimum_joint_coverage": 1.0,
                },
            ],
        }
    else:
        coverage = {
            "candidate_variables": [variable],
            "groups": [
                {
                    "id": group,
                    "variables": [variable],
                    "metric": "occupied_bins",
                    "bins_per_variable": bins,
                    "bounds": {variable: [lower, upper]},
                    "minimum_joint_coverage": 1.0,
                }
            ],
        }
    return {
        "schema_version": "1.2",
        "adapter_id": "cumcm2025a-independent-quality",
        "adapter_version": "1.1",
        "selection_contract": {"objective": {"metric": metric, "direction": "maximize", "objective_version": "finite-cylinder-union-v2", "scorer_version": "adaptive-lipschitz-time-v2", "constraint_version": "flight-kinematics-v1", "semantics": "union", "fine_tolerance": 5e-5}, "coverage": coverage, "required_evidence": ["finite-cylinder-exact-score", "continuous-geometry-certificate"], "required_prior_questions": [] if question == "Q1" else [f"Q{int(question[1]) - 1}"]},
        "stages": {
            "candidate_generator": {"implementation_file": "code/quality_candidate_generator.py", "arguments": [question, raw, candidates], "input_files": [raw], "output_file": candidates},
            "exact_scorer": {"implementation_file": "code/quality_exact_scorer.py", "arguments": [question, candidates, raw, exact], "input_files": [candidates, raw], "output_file": exact},
            "search_auditor": {"implementation_file": "code/quality_search_auditor.py", "arguments": [question, candidates, exact, raw, audit], "input_files": [candidates, exact, raw], "output_file": audit},
        },
    }


def main() -> int:
    """按 Q1 至 Q5 顺序实际运行协议并申请 accepted 质量记录。"""
    receipts = []
    for question in ("Q1", "Q2", "Q3", "Q4", "Q5"):
        protocol = run_verification_protocol(ROOT, result_id=RESULT_IDS[question], question_id=question, contract=_contract(question))
        record = assess_result_quality(ROOT, result_id=RESULT_IDS[question], assessment={"result_role": "accepted", "verification": protocol["verification"], "reasons": ["独立候选生成、有限圆柱精确评分与搜索审计均已实际执行"]})
        receipts.append({"question": question, "verification": protocol["verification"], "quality": record})
    output = ROOT / "reports" / "QUALITY_PROTOCOL_REPORT.json"
    output.write_text(json.dumps({"schema_version": "1.0", "receipts": receipts}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
