"""验证证据链审计：论文图/方法名必须能回溯到 production 结果。"""

from __future__ import annotations

from pathlib import Path

from shumozizi.core.io import atomic_json
from shumozizi.paper.evidence_chain_audit import audit_evidence_chain
from shumozizi.simple.initialization import initialize_simple_run


def _run(tmp_path: Path, name: str) -> Path:
    """创建单问运行。"""
    return initialize_simple_run(
        tmp_path,
        name,
        required_questions=["Q1"],
        workflow_version="3.2",
    )


def _write_paper(run_dir: Path, body: str) -> None:
    """写一份正文 tex。"""
    paper = run_dir / "paper"
    paper.mkdir(exist_ok=True)
    (paper / "main.tex").write_text(body, encoding="utf-8")


def _codes(report: dict) -> set[str]:
    """返回审计发现 class 集合。"""
    return {item["class"] for item in report["findings"]}


def _write_index(run_dir: Path, figures: list[dict]) -> None:
    """写入 figures/index.json。"""
    figures_dir = run_dir / "figures"
    figures_dir.mkdir(exist_ok=True)
    atomic_json(
        figures_dir / "index.json",
        {"schema_version": "1.3", "run_id": run_dir.name, "figures": figures},
    )


def _bound_figure(figure_id: str, output_name: str) -> dict:
    """构造一个绑定 production 结果的合法图条目。"""
    return {
        "figure_id": figure_id,
        "status": "current",
        "paper_allowed": True,
        "question_id": "Q1",
        "outputs": [{"path": f"figures/current/{output_name}", "sha256": "0" * 64}],
        "source_result_ids": ["r-Q1"],
        "renderer_script": {"path": "code/figures/render.py"},
    }


def test_unregistered_figure_is_broken(tmp_path: Path) -> None:
    """论文引用的图不在 figures/index.json 里 → EVIDENCE_CHAIN_BROKEN。"""
    run_dir = _run(tmp_path, "ec-unregistered")
    _write_paper(
        run_dir,
        "\\section{Q1}\n\\includegraphics{figures/current/freehand.png}\n",
    )
    _write_index(run_dir, [])
    report = audit_evidence_chain(run_dir)
    assert "EVIDENCE_CHAIN_BROKEN" in _codes(report)


def test_unbound_figure_is_broken(tmp_path: Path) -> None:
    """图登记了但没绑 production 结果 → EVIDENCE_CHAIN_BROKEN。"""
    run_dir = _run(tmp_path, "ec-unbound")
    _write_paper(
        run_dir,
        "\\section{Q1}\n\\includegraphics{figures/current/q4-confusion.png}\n",
    )
    _write_index(
        run_dir,
        [
            {
                "figure_id": "q4-confusion",
                "status": "current",
                "paper_allowed": True,
                "question_id": "Q4",
                "outputs": [{"path": "figures/current/q4-confusion.png"}],
                "source_result_ids": [],
            }
        ],
    )
    report = audit_evidence_chain(run_dir)
    assert "EVIDENCE_CHAIN_BROKEN" in _codes(report)


def test_bound_figure_is_clean(tmp_path: Path) -> None:
    """绑定 production 结果的图 → 无 EVIDENCE_CHAIN_BROKEN。"""
    run_dir = _run(tmp_path, "ec-bound")
    _write_paper(
        run_dir,
        "\\section{Q1}\n\\includegraphics{figures/current/q1-reliability.png}\n",
    )
    _write_index(run_dir, [_bound_figure("q1-reliability", "q1-reliability.png")])
    report = audit_evidence_chain(run_dir)
    assert "EVIDENCE_CHAIN_BROKEN" not in _codes(report)


def test_method_name_drift_flagged(tmp_path: Path) -> None:
    """正文出现与 estimator_contract 冲突的方法名 → METHOD_NAME_DRIFT。"""
    run_dir = _run(tmp_path, "ec-method-drift")
    _write_paper(
        run_dir,
        "\\section{Q1}\n采用 GEE 样条刻画纵向响应。\n\\includegraphics{x.png}\n",
    )
    _write_index(run_dir, [_bound_figure("x", "x.png")])
    handoff = run_dir / "paper/writer-handoff"
    handoff.mkdir(parents=True, exist_ok=True)
    atomic_json(
        handoff / "answer-and-claims.json",
        {
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "questions": [
                {
                    "question_id": "Q1",
                    "must_answer": "某正式答案",
                    "estimator_contract": {
                        "formal_method": "cluster-robust-ols-spline",
                        "mathematical_structure": "Ridge 样条预测 + 聚类稳健 OLS 推断",
                        "formalization_transformation": "surrogate",
                    },
                }
            ],
        },
    )
    report = audit_evidence_chain(run_dir)
    assert "METHOD_NAME_DRIFT" in _codes(report)


def test_method_name_match_is_clean(tmp_path: Path) -> None:
    """正文方法名与 estimator_contract 一致 → 无 METHOD_NAME_DRIFT。"""
    run_dir = _run(tmp_path, "ec-method-match")
    _write_paper(
        run_dir,
        "\\section{Q1}\n采用聚类稳健 OLS 样条刻画纵向响应。\n"
        "\\includegraphics{x.png}\n",
    )
    _write_index(run_dir, [_bound_figure("x", "x.png")])
    handoff = run_dir / "paper/writer-handoff"
    handoff.mkdir(parents=True, exist_ok=True)
    atomic_json(
        handoff / "answer-and-claims.json",
        {
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "questions": [
                {
                    "question_id": "Q1",
                    "must_answer": "某正式答案",
                    "estimator_contract": {
                        "formal_method": "cluster-robust-ols-spline",
                        "mathematical_structure": "Ridge 样条预测 + 聚类稳健 OLS 推断",
                        "formalization_transformation": "surrogate",
                    },
                }
            ],
        },
    )
    report = audit_evidence_chain(run_dir)
    assert "METHOD_NAME_DRIFT" not in _codes(report)


def test_import_audit_merges_evidence_chain(tmp_path: Path) -> None:
    """import_audit 应并入证据链客观失败。"""
    from shumozizi.paper.import_audit import _evidence_chain_findings

    run_dir = _run(tmp_path, "ec-import-merge")
    _write_paper(
        run_dir,
        "\\section{Q1}\n\\includegraphics{figures/current/freehand.png}\n",
    )
    _write_index(run_dir, [])
    findings = _evidence_chain_findings(run_dir)
    assert any(
        item["class"] == "EVIDENCE_CHAIN_BROKEN" for item in findings
    )
