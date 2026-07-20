"""验证独立审核 Skill 的可发现性与竞赛模式收敛规则。"""

from __future__ import annotations

import json
from pathlib import Path

from shumozizi.workflow.reviews import evaluate_r5_convergence

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_review_skills_are_top_level_and_executable() -> None:
    """R1-R5 顶层目录必须同时包含规范和 OpenAI 发现配置。"""
    for skill in (
        "mathmodel-review-r1-modeling",
        "mathmodel-review-r2-experiment",
        "mathmodel-review-r3-paper-logic",
        "mathmodel-review-r4-format-visual",
        "mathmodel-review-r5-comprehensive",
    ):
        directory = REPO_ROOT / ".agents" / "skills" / skill
        assert (directory / "SKILL.md").is_file()
        assert (directory / "agents/openai.yaml").is_file()
        content = (directory / "SKILL.md").read_text(encoding="utf-8")
        for required in ("输入文件", "禁止读取", "执行步骤", "Finding 证据格式", "通过条件", "结束前自检"):
            assert required in content, (skill, required)


def test_competition_r5_passes_after_one_clean_b_round(tmp_path: Path) -> None:
    """竞赛模式不再要求连续两轮 B/A，且预算上限为三轮。"""
    report_dir = tmp_path / "review/r5_comprehensive/round-1"
    report_dir.mkdir(parents=True)
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
        "quality_axis": {
            "verdict": "B_PASS",
            "total_score": 80,
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
