"""验证论文和图表生产回执的状态门禁。"""

import json
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, sha256_file
from shumozizi.paper.receipts import verify_figure_receipts, verify_paper_build_receipt
from shumozizi.workflow.state_service import Actor, StateService, WorkflowEvent
from tests.review_contract_helpers import write_viable_scientific_viability_fixture
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
                    "preferred": "skills/mathmodel-figure-templates",
                    "fallback": "skills/3coding-visual",
                    "selected_skill": "skills/3coding-visual",
                    "template_id": "custom",
                    "selection_reason": "测试夹具使用最小自定义图表",
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
            "selected_skill": "skills/3coding-visual",
            "template_id": "custom",
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


def _write_paper_package(
    fixture: RuntimeFixture,
    referenced_result_ids: list[str],
) -> None:
    """写入最小哈希闭合论文包，保留已有图表计划。"""
    run_dir = fixture.run_dir
    root = run_dir.parents[1]
    state = {"revision": 1}
    atomic_json(run_dir / "state.json", state)
    final_pdf = run_dir / "paper/final.pdf"
    final_pdf.parent.mkdir(parents=True, exist_ok=True)
    final_pdf.write_bytes(b"PDF")
    files = {
        "mathmodel_paper": root / "skills/mathmodel-paper/SKILL.md",
        "writing_skill": root / "skills/5writing/SKILL.md",
        "typst_author": root / "skills/typst-author/SKILL.md",
        "figure_templates": root / "skills/mathmodel-figure-templates/SKILL.md",
        "coding_visual": root / "skills/3coding-visual/SKILL.md",
        "competition_template": root / "profiles/generic.json",
        "model_spec": run_dir / "reports/model_spec.md",
        "claim_gate": run_dir / "paper/claim_gate.json",
    }
    for path in files.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n" if path.name == "claim_gate.json" else "绑定文件\n", encoding="utf-8")
    section = run_dir / "paper/main.typ"
    section.write_text("= 测试论文\n", encoding="utf-8")
    registry = run_dir / "results/result_registry.json"
    figures_plan = json.loads(
        (run_dir / "figures/FIGURE_PLAN.json").read_text(encoding="utf-8")
    ) if (run_dir / "figures/FIGURE_PLAN.json").is_file() else {
        "schema_name": "figure_plan",
        "schema_version": "2.0",
        "run_id": run_dir.name,
        "figures": [],
    }
    atomic_json(run_dir / "figures/FIGURE_PLAN.json", figures_plan)
    bindings: dict[str, object] = {}
    for name, path in files.items():
        binding_root = root if root in path.parents else run_dir
        bindings[name] = {
            "path": path.relative_to(binding_root).as_posix(),
            "sha256": sha256_file(path),
        }
    bindings["result_registry"] = {
        "path": "results/result_registry.json",
        "sha256": sha256_file(registry),
    }
    bindings["section_files"] = [
        {"path": "paper/main.typ", "sha256": sha256_file(section)}
    ]
    bindings["figures_used"] = [
        {
            "path": f"figures/{figure['figure_id']}.png",
            "sha256": sha256_file(run_dir / f"figures/{figure['figure_id']}.png"),
        }
        for figure in figures_plan["figures"]
    ]
    plan = {
        "schema_name": "paper_plan",
        "schema_version": "2.0",
        "run_id": run_dir.name,
        "referenced_result_ids": referenced_result_ids,
        "bindings": bindings,
        "final_pdf_path": "paper/final.pdf",
    }
    plan_path = run_dir / "paper/paper_plan.json"
    atomic_json(plan_path, plan)
    atomic_json(
        run_dir / "paper/PAPER_BUILD_RECEIPT.json",
        {
            "schema_name": "paper_build_receipt",
            "schema_version": "2.0",
            "run_id": run_dir.name,
            "plan_path": "paper/paper_plan.json",
            "plan_sha256": sha256_file(plan_path),
            "state_revision": 1,
            "final_pdf_path": "paper/final.pdf",
            "final_pdf_sha256": sha256_file(final_pdf),
            "generated_at": "2026-07-19T00:00:00Z",
        },
    )


def _set_paper_allowed(fixture: RuntimeFixture, allowed: bool) -> None:
    """更新注册表权限并同步论文计划中的注册表哈希。"""
    registry_path = fixture.run_dir / "results/result_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["results"][0]["paper_allowed"] = allowed
    atomic_json(registry_path, registry)
    plan_path = fixture.run_dir / "paper/paper_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["bindings"]["result_registry"]["sha256"] = sha256_file(registry_path)
    atomic_json(plan_path, plan)
    receipt_path = fixture.run_dir / "paper/PAPER_BUILD_RECEIPT.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["plan_sha256"] = sha256_file(plan_path)
    atomic_json(receipt_path, receipt)


def test_paper_completed_requires_production_receipts(tmp_path: Path) -> None:
    """没有论文或图表回执时不得进入 PAPER_DRAFTED。"""
    run_dir = tmp_path / "runs" / "receipt-gate"
    (run_dir / "paper").mkdir(parents=True)
    (run_dir / "figures").mkdir()
    (run_dir / "state.json").write_text(json.dumps(_state(run_dir.name)), encoding="utf-8")
    write_viable_scientific_viability_fixture(run_dir)

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
            "figures": [
                {
                    "figure_id": "q1",
                    "preferred": "skills/mathmodel-figure-templates",
                    "fallback": "skills/3coding-visual",
                    "selected_skill": "skills/3coding-visual",
                    "template_id": "custom",
                    "selection_reason": "测试夹具使用最小自定义图表",
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
            "selected_skill": "skills/3coding-visual",
            "template_id": "custom",
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


def test_unreferenced_paper_forbidden_result_does_not_block(
    accepted_figure_run: RuntimeFixture,
) -> None:
    """论文未引用的 accepted 诊断结果不应阻断构建。"""
    registry_path = accepted_figure_run.run_dir / "results/result_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["results"][0]["paper_allowed"] = False
    atomic_json(registry_path, registry)
    _write_paper_package(accepted_figure_run, [])

    report = verify_paper_build_receipt(accepted_figure_run.run_dir)

    assert report["valid"]


def test_referenced_paper_forbidden_result_is_rejected(
    accepted_figure_run: RuntimeFixture,
) -> None:
    """论文实际引用的结果必须保留 paper_allowed 权限。"""
    registry_path = accepted_figure_run.run_dir / "results/result_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["results"][0]["paper_allowed"] = False
    atomic_json(registry_path, registry)
    _write_paper_package(accepted_figure_run, ["r1"])

    report = verify_paper_build_receipt(accepted_figure_run.run_dir)

    assert not report["valid"]
    assert any("未允许写入论文" in error for error in report["errors"])


def test_referenced_paper_invalid_seal_is_rejected(
    accepted_figure_run: RuntimeFixture,
) -> None:
    """论文引用的结果封条失效时不得通过构建回执。"""
    _write_paper_package(accepted_figure_run, ["r1"])
    sealed_path = accepted_figure_run.run_dir / "results/sealed/r1.result.json"
    sealed = json.loads(sealed_path.read_text(encoding="utf-8"))
    sealed["conclusion"] = "篡改"
    atomic_json(sealed_path, sealed)

    report = verify_paper_build_receipt(accepted_figure_run.run_dir)

    assert not report["valid"]
    assert any("sealed result" in error for error in report["errors"])


def test_evidence_map_result_must_be_declared_in_paper_plan(
    accepted_figure_run: RuntimeFixture,
) -> None:
    """evidence map 实际引用结果不能通过漏填论文引用集合绕过。"""
    _write_paper_package(accepted_figure_run, [])
    atomic_json(
        accepted_figure_run.run_dir / "paper/evidence_map.json",
        {
            "schema_name": "evidence_map",
            "schema_version": "2.0",
            "run_id": accepted_figure_run.run_dir.name,
            "claims": [
                {
                    "claim_id": "Q1-VALUE",
                    "inputs": [
                        {"name": "value", "result_id": "r1", "metric_spec_id": "r1-value"}
                    ],
                    "expression": None,
                    "display": {"decimals": 2, "unit": "dimensionless"},
                }
            ],
        },
    )

    report = verify_paper_build_receipt(accepted_figure_run.run_dir)

    assert not report["valid"]
    assert any("evidence_map 引用结果未列入" in error for error in report["errors"])


def test_figure_result_must_be_declared_in_paper_plan(
    accepted_figure_run: RuntimeFixture,
) -> None:
    """图表实际引用结果不能通过漏填论文引用集合绕过。"""
    _write_figure_receipt(accepted_figure_run)
    _write_paper_package(accepted_figure_run, [])

    report = verify_paper_build_receipt(accepted_figure_run.run_dir)

    assert not report["valid"]
    assert any("图表 q1 引用结果未列入" in error for error in report["errors"])
