"""验证论文和图表生产回执的状态门禁。"""

import json
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, sha256_file
from shumozizi.paper.receipts import verify_figure_receipts
from shumozizi.workflow.state_service import Actor, StateService, WorkflowEvent
from tests.runtime_helpers import RuntimeFixture


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


@pytest.fixture
def accepted_figure_run() -> RuntimeFixture:
    """通过公开运行时入口生成图表可引用的 accepted result。"""
    fixture = RuntimeFixture()
    script = fixture.write_script(
        "emit.py",
        "import json, sys\nfrom pathlib import Path\n"
        "Path(sys.argv[1]).write_text(json.dumps({'value': 1}), encoding='utf-8')\n",
    )
    manifest = fixture.manifest("exec-q1", script.name, "q1.json")
    assert fixture.run_executor(manifest).returncode == 0
    fixture.set_results([fixture.candidate("r1", "exec-q1")])
    assert fixture.run_acceptor("r1").returncode == 0
    yield fixture
    fixture.close()


def _write_figure_receipt(fixture: RuntimeFixture) -> None:
    """写入一份完整且哈希有效的图表计划与回执。"""
    run_dir = fixture.run_dir
    data = run_dir / "figures/data.csv"
    script = run_dir / "figures/plot.py"
    output = run_dir / "figures/q1.png"
    for path, content in (
        (data, "x,y\n1,2\n"),
        (script, "print('ok')\n"),
        (output, "PNG"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "schema_name": "figure_plan",
            "schema_version": "2.0",
            "run_id": run_dir.name,
            "figures": [
                {
                    "figure_id": "q1",
                    "preferred": "Nature Figure",
                    "fallback": "skills/3coding-visual",
                }
            ],
        },
    )
    atomic_json(
        run_dir / "figures/q1.receipt.json",
        {
            "schema_name": "figure_receipt",
            "schema_version": "2.0",
            "run_id": run_dir.name,
            "figure_id": "q1",
            "question_id": "q1",
            "accepted_result_ids": ["r1"],
            "data_files": [{"path": "figures/data.csv", "sha256": sha256_file(data)}],
            "script": {"path": "figures/plot.py", "sha256": sha256_file(script)},
            "outputs": [{"path": "figures/q1.png", "sha256": sha256_file(output)}],
            "units": "kg",
            "legend": "观测值",
            "axes": {"x": "样本", "y": "质量 (kg)"},
            "generated_at": "2026-07-19T00:00:00Z",
        },
    )


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
        {
            "schema_name": "result_registry",
            "schema_version": "2.0",
            "run_id": run_dir.name,
            "results": [
                {
                    "result_id": "candidate-1",
                    "question_id": "q1",
                    "cycle": "baseline",
                    "status": "candidate",
                    "paper_allowed": False,
                    "execution_record_id": "",
                    "metric_spec_ids": [],
                    "sealed_result_path": None,
                    "result_seal_path": None,
                    "supersedes_result_id": None,
                }
            ],
        },
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
            "question_id": "q1",
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
    assert any("不是 accepted" in error for error in report["errors"])


def test_figure_receipt_rejects_invalid_seal(
    accepted_figure_run: RuntimeFixture,
) -> None:
    """图表回执必须复验每个引用结果的封条。"""
    _write_figure_receipt(accepted_figure_run)
    sealed_path = accepted_figure_run.run_dir / "results/sealed/r1.result.json"
    sealed = json.loads(sealed_path.read_text(encoding="utf-8"))
    sealed["conclusion"] = "被篡改的图表来源"
    atomic_json(sealed_path, sealed)

    report = verify_figure_receipts(accepted_figure_run.run_dir)

    assert not report["valid"]
    assert any("sealed result" in error for error in report["errors"])


def test_figure_receipt_rejects_cross_question_result(
    accepted_figure_run: RuntimeFixture,
) -> None:
    """图表回执必须与引用结果属于同一问题。"""
    _write_figure_receipt(accepted_figure_run)
    receipt_path = accepted_figure_run.run_dir / "figures/q1.receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["question_id"] = "q2"
    atomic_json(receipt_path, receipt)

    report = verify_figure_receipts(accepted_figure_run.run_dir)

    assert not report["valid"]
    assert any("question_id 不匹配" in error for error in report["errors"])


@pytest.mark.parametrize("status", ["revoked", "superseded"])
def test_figure_receipt_rejects_inactive_result(
    accepted_figure_run: RuntimeFixture,
    status: str,
) -> None:
    """图表不能继续引用已撤销或已替代的结果。"""
    _write_figure_receipt(accepted_figure_run)
    registry_path = accepted_figure_run.run_dir / "results/result_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["results"][0]["status"] = status
    registry["results"][0]["paper_allowed"] = False
    atomic_json(registry_path, registry)

    report = verify_figure_receipts(accepted_figure_run.run_dir)

    assert not report["valid"]
    assert any("不是 accepted" in error for error in report["errors"])
