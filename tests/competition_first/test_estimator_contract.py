"""验证交接包的 estimator 契约：正文方法与代码实现的一致性 ground truth。"""

from __future__ import annotations

from pathlib import Path

from shumozizi.core.io import atomic_json, load_json
from shumozizi.paper.handoff import _estimator_contracts
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.state import read_simple_state, write_simple_state


def _run(tmp_path: Path, name: str) -> Path:
    """创建三问运行并推进到 paper 阶段。"""
    run_dir = initialize_simple_run(
        tmp_path,
        name,
        required_questions=["Q1", "Q2"],
        workflow_version="3.2",
    )
    state = read_simple_state(run_dir)
    state["phase"] = "paper"
    write_simple_state(run_dir, state)
    return run_dir


def _write_modeling_units(run_dir: Path) -> None:
    """写入带 primary_method 与 formalization_diff 的 MODELING_UNITS。"""
    atomic_json(
        run_dir / "analysis/MODELING_UNITS.json",
        {
            "schema_version": "1.4",
            "run_id": run_dir.name,
            "units": [
                {
                    "unit_id": "Q1-unit",
                    "question_id": "Q1",
                    "core_question": True,
                    "unit_kind": "optimization",
                    "primary_method": {
                        "method_id": "cluster-robust-ols-spline",
                        "mathematical_structure": "Ridge 样条预测 + 聚类稳健 OLS 推断",
                    },
                    "formalization_diff": {
                        "source": "题面要求给出最优方案。",
                        "formalized_as": "min t s.t. L_g(t)>=0.90",
                        "transformation": "surrogate",
                        "added_semantics": "可靠性阈值 q=0.90",
                        "removed_semantics": "显式风险函数",
                        "support_level": "assumption_supported",
                        "equivalence_evidence": "可靠度达标作为风险代理。",
                    },
                }
            ],
        },
    )


def test_estimator_contracts_reads_modeling_units(tmp_path: Path) -> None:
    """从 MODELING_UNITS 提取每问正式方法名与转换类型。"""
    run_dir = _run(tmp_path, "contracts-read")
    _write_modeling_units(run_dir)
    contracts = _estimator_contracts(run_dir)
    assert "Q1" in contracts
    q1 = contracts["Q1"]
    assert q1["formal_method"] == "cluster-robust-ols-spline"
    assert "Ridge 样条" in q1["mathematical_structure"]
    assert q1["formalization_transformation"] == "surrogate"


def test_estimator_contracts_graceful_without_modeling_units(tmp_path: Path) -> None:
    """缺 MODELING_UNITS 时返回空契约，不抛错。"""
    run_dir = _run(tmp_path, "contracts-empty")
    assert _estimator_contracts(run_dir) == {}


def test_build_writer_handoff_includes_estimator_contract(tmp_path: Path) -> None:
    """交接包的 answer-and-claims JSON 应包含 estimator_contract。"""
    run_dir = _run(tmp_path, "handoff-contract")
    _write_modeling_units(run_dir)
    # 交接包需要材料，直接调用内部构建函数验证契约字段进入 JSON。
    from shumozizi.paper.handoff import _build_answer_and_claims

    document = _build_answer_and_claims(run_dir)
    questions = document["questions"]
    assert questions, "至少一个问题"
    q1 = next(q for q in questions if q["question_id"] == "Q1")
    assert q1["estimator_contract"]["formal_method"] == "cluster-robust-ols-spline"
    assert q1["estimator_contract"]["formalization_transformation"] == "surrogate"


def test_answer_and_claims_markdown_documents_method_contract(tmp_path: Path) -> None:
    """Author 可读的 ANSWER_AND_CLAIMS.md 应写出方法契约与禁用改名约束。"""
    run_dir = _run(tmp_path, "handoff-md")
    _write_modeling_units(run_dir)
    from shumozizi.paper.handoff import (
        _build_answer_and_claims,
        _render_answer_and_claims_markdown,
    )

    document = _build_answer_and_claims(run_dir)
    markdown = _render_answer_and_claims_markdown(document)
    assert "正式方法与实现契约" in markdown
    assert "cluster-robust-ols-spline" in markdown
    assert "不得" in markdown


def test_handoff_json_validates_with_estimator_contract(tmp_path: Path) -> None:
    """带 estimator_contract 的 answer-and-claims 应通过 schema 校验。"""
    run_dir = _run(tmp_path, "handoff-schema")
    _write_modeling_units(run_dir)
    # 写入 minimal current 结果，让 must_answer 非空以便 schema 校验通过。
    index = load_json(run_dir / "results/index.json")
    index["results"].append(
        {
            "result_id": "r-Q1",
            "question_id": "Q1",
            "kind": "test",
            "source_script": None,
            "command": "test",
            "input_files": [],
            "input_hashes": {},
            "output_files": [],
            "output_hashes": {},
            "metric_sources": {},
            "method_facts": {},
            "status": "current",
            "execution_mode": "production",
            "execution_valid": True,
            "exit_code": 0,
            "stdout_path": "results/Q1.stdout.log",
            "stderr_path": "results/Q1.stderr.log",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:01Z",
            "duration_seconds": 1.0,
            "error": None,
            "created_at": "2026-01-01T00:00:01Z",
            "objective_semantics_sha256": "0" * 64,
            "dependency_scope": "question",
            "affected_question_ids": ["Q1"],
            "metrics": {"objective": 12.0, "feasible": True},
        }
    )
    atomic_json(run_dir / "results/index.json", index)
    # 补 Q2 结果，保证两问 must_answer 均非空。
    index["results"].append(
        {
            "result_id": "r-Q2",
            "question_id": "Q2",
            "kind": "test",
            "source_script": None,
            "command": "test",
            "input_files": [],
            "input_hashes": {},
            "output_files": [],
            "output_hashes": {},
            "metric_sources": {},
            "method_facts": {},
            "status": "current",
            "execution_mode": "production",
            "execution_valid": True,
            "exit_code": 0,
            "stdout_path": "results/Q2.stdout.log",
            "stderr_path": "results/Q2.stderr.log",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:01Z",
            "duration_seconds": 1.0,
            "error": None,
            "created_at": "2026-01-01T00:00:01Z",
            "objective_semantics_sha256": "0" * 64,
            "dependency_scope": "question",
            "affected_question_ids": ["Q2"],
            "metrics": {"objective": 8.0, "feasible": True},
        }
    )
    atomic_json(run_dir / "results/index.json", index)
    from shumozizi.core.schema import require_valid
    from shumozizi.paper.handoff import _build_answer_and_claims

    document = _build_answer_and_claims(run_dir)
    require_valid(document, "answer_and_claims")
