"""逐问验收的结果完整性契约测试。"""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from shumozizi.core.io import atomic_json, relative_inside
from shumozizi.questions.acceptance import verify_question_acceptance
from tests.runtime_helpers import RuntimeFixture


def _base_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "runs" / "question-gate"
    (run_dir / "results").mkdir(parents=True)
    atomic_json(
        run_dir / "state.json",
        {"question_progress": {"Q1": {"experiment": "accepted"}}},
    )
    atomic_json(
        run_dir / "results/result_registry.json",
        {
            "schema_name": "result_registry",
            "schema_version": "2.0",
            "run_id": run_dir.name,
            "results": [],
        },
    )
    return run_dir


@pytest.fixture
def accepted_run() -> RuntimeFixture:
    """通过公开运行时入口生成真实 accepted/sealed result。"""
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


def _write_accepted_question(fixture: RuntimeFixture, question_id: str = "q1") -> None:
    """写入一份引用 r1 的已通过逐问验收回执。"""
    run_dir = fixture.run_dir
    atomic_json(
        run_dir / "state.json",
        {"question_progress": {question_id: {"experiment": "accepted"}}},
    )
    chapter = run_dir / f"paper/sections/{question_id}.typ"
    chapter.parent.mkdir(parents=True, exist_ok=True)
    chapter.write_text("回答\n", encoding="utf-8")
    checks = {
        name: {"passed": True, "evidence": "已核验"}
        for name in (
            "question_requirements",
            "model_output",
            "output_mapping",
            "hard_constraints",
            "baseline",
            "accepted_result",
            "uncertainty",
            "direct_answer",
            "upstream_dependencies",
            "claim_status",
        )
    }
    atomic_json(
        run_dir / f"questions/{question_id}/QUESTION_ACCEPTANCE.json",
        {
            "schema_name": "question_acceptance",
            "schema_version": "2.0",
            "run_id": run_dir.name,
            "question_id": question_id,
            "status": "accepted",
            "checks": checks,
            "accepted_result_ids": ["r1"],
            "chapter_paths": [f"paper/sections/{question_id}.typ"],
            "direct_answer": "问题已直接回答。",
            "claim_status": "inconclusive",
            "generated_at": "2026-07-19T00:00:00Z",
        },
    )


def test_completed_question_requires_acceptance_receipt(tmp_path: Path) -> None:
    report = verify_question_acceptance(_base_run(tmp_path))

    assert not report["valid"]
    assert any("Q1" in error for error in report["errors"])


def test_relative_inside_uses_canonical_root_for_windows_aliases() -> None:
    """Windows 短路径别名不应把同一目录误判为越界。"""
    root = Mock(spec=Path)
    root.resolve.return_value = Path("C:/Users/runneradmin/AppData/Local/Temp/run")
    child = Path("C:/Users/runneradmin/AppData/Local/Temp/run/paper/sections/q1.typ")

    assert relative_inside(root, child).as_posix() == "paper/sections/q1.typ"


def test_rejected_question_cannot_supply_paper_chapter(
    accepted_run: RuntimeFixture,
) -> None:
    _write_accepted_question(accepted_run)
    run_dir = accepted_run.run_dir
    receipt_path = run_dir / "questions/q1/QUESTION_ACCEPTANCE.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["status"] = "rejected"
    atomic_json(receipt_path, receipt)

    report = verify_question_acceptance(run_dir)

    assert not report["valid"]
    assert any("不是 accepted" in error for error in report["errors"])


def test_question_acceptance_rejects_tampered_sealed_result(
    accepted_run: RuntimeFixture,
) -> None:
    """逐问验收必须复验引用结果的 RFC 8785 封条。"""
    _write_accepted_question(accepted_run)
    sealed_path = accepted_run.run_dir / "results/sealed/r1.result.json"
    sealed = json.loads(sealed_path.read_text(encoding="utf-8"))
    sealed["conclusion"] = "被篡改的结论"
    atomic_json(sealed_path, sealed)

    report = verify_question_acceptance(accepted_run.run_dir)

    assert not report["valid"]
    assert any("sealed result" in error for error in report["errors"])


def test_question_acceptance_rejects_cross_question_result(
    accepted_run: RuntimeFixture,
) -> None:
    """逐问验收不能引用属于其他问题的 accepted result。"""
    _write_accepted_question(accepted_run, "q2")

    report = verify_question_acceptance(accepted_run.run_dir)

    assert not report["valid"]
    assert any("question_id 不匹配" in error for error in report["errors"])


def test_question_acceptance_rejects_missing_sealed_result(
    accepted_run: RuntimeFixture,
) -> None:
    """注册表的 accepted 状态不能替代实际 sealed result。"""
    _write_accepted_question(accepted_run)
    (accepted_run.run_dir / "results/sealed/r1.result.json").unlink()

    report = verify_question_acceptance(accepted_run.run_dir)

    assert not report["valid"]
    assert any("缺少文件" in error for error in report["errors"])
