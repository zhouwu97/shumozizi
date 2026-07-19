"""逐问验收的最小契约测试。"""

from pathlib import Path

from shumozizi.core.io import atomic_json
from shumozizi.questions.acceptance import verify_question_acceptance


def _base_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "runs" / "question-gate"
    (run_dir / "results").mkdir(parents=True)
    atomic_json(
        run_dir / "state.json",
        {"question_progress": {"Q1": {"experiment": "accepted"}}},
    )
    atomic_json(
        run_dir / "results/result_registry.json",
        {"results": [{"result_id": "r1", "status": "accepted", "paper_allowed": True}]},
    )
    return run_dir


def test_completed_question_requires_acceptance_receipt(tmp_path: Path) -> None:
    report = verify_question_acceptance(_base_run(tmp_path))

    assert not report["valid"]
    assert any("Q1" in error for error in report["errors"])


def test_rejected_question_cannot_supply_paper_chapter(tmp_path: Path) -> None:
    run_dir = _base_run(tmp_path)
    chapter = run_dir / "paper/sections/q1.typ"
    chapter.parent.mkdir(parents=True)
    chapter.write_text("回答\n", encoding="utf-8")
    checks = {name: {"passed": True, "evidence": "已核验"} for name in (
        "question_requirements", "model_output", "output_mapping", "hard_constraints",
        "baseline", "accepted_result", "uncertainty", "direct_answer",
        "upstream_dependencies", "claim_status",
    )}
    atomic_json(
        run_dir / "questions/Q1/QUESTION_ACCEPTANCE.json",
        {
            "schema_name": "question_acceptance",
            "schema_version": "2.0",
            "run_id": run_dir.name,
            "question_id": "Q1",
            "status": "rejected",
            "checks": checks,
            "accepted_result_ids": ["r1"],
            "chapter_paths": ["paper/sections/q1.typ"],
            "direct_answer": "未通过。",
            "claim_status": "inconclusive",
            "generated_at": "2026-07-19T00:00:00Z",
        },
    )

    report = verify_question_acceptance(run_dir)

    assert not report["valid"]
    assert any("不是 accepted" in error for error in report["errors"])
