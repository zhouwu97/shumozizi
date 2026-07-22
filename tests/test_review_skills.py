"""验证冻结审核 Skill 的归档完整性与历史收敛规则。"""

from __future__ import annotations

import json
from pathlib import Path

from shumozizi.workflow.reviews import evaluate_r5_convergence

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_review_skills_are_archived_and_not_auto_discoverable() -> None:
    """冻结的 R1-R5 Skill 应保留，但不能再位于主动发现目录。"""
    for skill in (
        "mathmodel-review-r1-modeling",
        "mathmodel-review-r2-experiment",
        "mathmodel-review-r3-paper-logic",
        "mathmodel-review-r4-format-visual",
        "mathmodel-review-r5-comprehensive",
    ):
        directory = REPO_ROOT / "legacy" / "review-v2" / "skills" / skill
        assert (directory / "SKILL.md").is_file()
        assert (directory / "agents/openai.yaml").is_file()
        content = (directory / "SKILL.md").read_text(encoding="utf-8")
        for required in ("输入文件", "禁止读取", "执行步骤", "Finding 证据格式", "通过条件", "结束前自检"):
            assert required in content, (skill, required)
        assert not (REPO_ROOT / ".agents" / "skills" / skill).exists()


def test_competition_r5_passes_after_one_clean_b_round(tmp_path: Path) -> None:
    """竞赛模式不再要求连续两轮 B/A，且预算上限为三轮。"""
    report_dir = tmp_path / "review/r5_comprehensive/round-1"
    report_dir.mkdir(parents=True)
    (tmp_path / "state.json").write_text(
        json.dumps({"mode": "competition"}), encoding="utf-8"
    )
    report = {
        "schema_name": "review_report",
        "schema_version": "2.0",
        "request_id": "request-1",
        "run_id": "run-1",
        "stage": "R5_COMPREHENSIVE",
        "review_round_id": "round-1",
        "request_sha256": "b" * 64,
        "input_manifest_sha256": "c" * 64,
        "session_sha256": "a" * 64,
        "verdict": "B",
        "findings": [],
        "rating": {
            "grade": "B",
            "confidence": "high",
            "basis": ["冻结提交包"],
            "downgrade_reasons": [],
            "expert_estimate": True,
        },
        "integrity_axis": {
            "verdict": "A_PASS",
            "checks": ["完整性通过"],
            "blockers": [],
        },
        "score_type": "competition_quality",
        "assessment_scope": "full_competition_submission",
        "raw_score": 80,
        "calibrated_score": 80,
        "score_caps_applied": [],
        "competition_claim_allowed": True,
        "quality_axis": {
            "verdict": "B_PASS",
            "raw_dimensions": {
                "problem_coverage": 80,
                "model_depth": 80,
                "experiment_validation": 80,
            },
            "dimensions": {
                "problem_coverage": 80,
                "model_depth": 80,
                "experiment_validation": 80,
            },
            "evidence": ["质量达到 B 轴阈值"],
        },
        "joint_verdict": "FINAL_CANDIDATE",
        "repair_scope": [],
        "required_retests": [],
        "read_only_confirmed": True,
        "generated_at": "2026-07-19T00:00:00Z",
    }
    (report_dir / "review_report.json").write_text(
        json.dumps(report, ensure_ascii=False), encoding="utf-8"
    )

    result = evaluate_r5_convergence(tmp_path)

    assert result["status"] == "pass"
    assert result["max_rounds"] == 3
    assert result["consecutive_passing_rounds"] == 1
