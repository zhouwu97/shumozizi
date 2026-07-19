"""验证论文和图表生产回执的状态门禁。"""

import json
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, sha256_file
from shumozizi.paper.receipts import verify_figure_receipts
from shumozizi.workflow.state_service import Actor, StateService, WorkflowEvent


def _state(run_id: str) -> dict:
    """构造进入论文阶段所需的最小合法状态。"""
    return {
        "schema_name": "workflow_state",
        "schema_version": "2.0",
        "run_schema_version": "2.0",
        "run_id": run_id,
        "problem_source": "problem.md",
        "mode": "audit",
        "status": "RESULTS_ACCEPTED",
        "revision": 2,
        "completed_stages": ["EXPERIMENTING"],
        "active_stage": "paper",
        "route_locked": True,
        "paper_ready": False,
        "question_progress": {},
        "review_gates": {},
        "artifacts": {},
        "last_updated_by": "test",
        "updated_at": "2026-07-19T00:00:00Z",
        "history": [],
    }


def test_paper_completed_requires_production_receipts(tmp_path: Path) -> None:
    """没有论文或图表回执时不得进入 PAPER_DRAFTED。"""
    run_dir = tmp_path / "runs" / "receipt-gate"
    (run_dir / "paper").mkdir(parents=True)
    (run_dir / "figures").mkdir()
    (run_dir / "state.json").write_text(json.dumps(_state(run_dir.name)), encoding="utf-8")

    with pytest.raises(ContractError, match="生产回执"):
        StateService(tmp_path).transition(
            run_dir.name,
            WorkflowEvent.PAPER_COMPLETED,
            Actor("test"),
            [],
        )


def test_figure_receipt_rejects_non_accepted_result(tmp_path: Path) -> None:
    """图表不能把 candidate 或 revoked 结果冒充 accepted 数据。"""
    run_dir = tmp_path / "runs" / "figure-receipt"
    (run_dir / "figures").mkdir(parents=True)
    (run_dir / "results").mkdir()
    data = run_dir / "figures/data.csv"
    script = run_dir / "figures/plot.py"
    output = run_dir / "figures/q1.png"
    for path, content in ((data, "x,y\n1,2\n"), (script, "print('ok')\n"), (output, "PNG")):
        path.write_text(content, encoding="utf-8")
    atomic_json(
        run_dir / "results/result_registry.json",
        {"results": [{"result_id": "candidate-1", "status": "candidate", "paper_allowed": False}]},
    )
    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "schema_name": "figure_plan",
            "schema_version": "2.0",
            "run_id": run_dir.name,
            "figures": [{"figure_id": "q1", "preferred": "Nature Figure", "fallback": "skills/3coding-visual"}],
        },
    )
    atomic_json(
        run_dir / "figures/q1.receipt.json",
        {
            "schema_name": "figure_receipt",
            "schema_version": "2.0",
            "run_id": run_dir.name,
            "figure_id": "q1",
            "accepted_result_ids": ["candidate-1"],
            "data_files": [{"path": "figures/data.csv", "sha256": sha256_file(data)}],
            "script": {"path": "figures/plot.py", "sha256": sha256_file(script)},
            "outputs": [{"path": "figures/q1.png", "sha256": sha256_file(output)}],
            "units": "kg",
            "legend": "观测值",
            "axes": {"x": "样本", "y": "质量 (kg)"},
            "generated_at": "2026-07-19T00:00:00Z",
        },
    )

    report = verify_figure_receipts(run_dir)

    assert not report["valid"]
    assert any("非 accepted 结果" in error for error in report["errors"])
