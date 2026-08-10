"""验证 ANSWER_CONSISTENCY_GATE：冻结答案到生产工件链必须闭合才能渲染。

覆盖四类断裂与一条通过路径：

- 冻结答案引用的 result 未登记 -> blocked
- 已登记结果工件在磁盘缺失 -> blocked
- 论文 answer-map 未对齐冻结答案 -> blocked
- current 图源不是已登记生产工件 -> blocked
- 链完整闭合 -> pass
"""

from __future__ import annotations

from pathlib import Path

from shumozizi.core.io import atomic_json
from shumozizi.simple.answer_consistency import answer_consistency_gate, require_answer_consistency
from shumozizi.simple.initialization import initialize_simple_run


def _consistent_run(tmp_path: Path) -> Path:
    """构造生产事实链完整闭合的最小运行。"""
    run_dir = initialize_simple_run(
        tmp_path, "answer-gate", required_questions=["Q1"], workflow_version="3.2"
    )
    atomic_json(
        run_dir / "analysis/answer_map.json",
        {
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "answers": {
                "Q1": {
                    "objective_answer": {"result_id": "q1-final", "answer": "组2 导通。"}
                }
            },
        },
    )
    atomic_json(
        run_dir / "paper/answer-map.json",
        {
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "answers": {
                "Q1": {"primary_result_id": "q1-final", "result_ids": ["q1-final"]}
            },
        },
    )
    (run_dir / "results/raw").mkdir(parents=True, exist_ok=True)
    atomic_json(run_dir / "results/raw/q1-final.json", {"answer": "组2 导通。"})
    atomic_json(
        run_dir / "results/index.json",
        {
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "results": [
                {
                    "result_id": "q1-final",
                    "question_id": "Q1",
                    "status": "current",
                    "execution_valid": True,
                    "output_files": ["results/raw/q1-final.json"],
                }
            ],
        },
    )
    return run_dir


def test_gate_passes_when_chain_closes(tmp_path: Path) -> None:
    """冻结答案、登记结果、论文 answer-map 全部对齐且工件存在时 pass。"""
    run_dir = _consistent_run(tmp_path)
    verdict = answer_consistency_gate(run_dir)
    assert verdict["status"] == "pass"
    assert verdict["violations"] == []
    require_answer_consistency(run_dir)  # 不抛错


def test_gate_blocks_unregistered_frozen_answer(tmp_path: Path) -> None:
    """冻结答案引用的 result 未登记必须 RENDER_FORBIDDEN。"""
    run_dir = _consistent_run(tmp_path)
    # 论文和 index 指向 q1-other，而冻结答案指向 q1-final（未登记）。
    atomic_json(
        run_dir / "analysis/answer_map.json",
        {
            "answers": {
                "Q1": {"objective_answer": {"result_id": "q1-ghost", "answer": "x"}}
            }
        },
    )
    verdict = answer_consistency_gate(run_dir)
    assert verdict["status"] == "blocked"
    codes = {item["code"] for item in verdict["violations"]}
    assert "analysis_answer_result_not_registered" in codes
    try:
        require_answer_consistency(run_dir)
        raise AssertionError("应抛 ContractError")
    except Exception as exc:  # noqa: BLE001
        assert "RENDER_FORBIDDEN" in str(exc)


def test_gate_blocks_missing_registered_artifact(tmp_path: Path) -> None:
    """已登记结果声明的工作在磁盘缺失必须 RENDER_FORBIDDEN（_v2 丢工件场景）。"""
    run_dir = _consistent_run(tmp_path)
    (run_dir / "results/raw/q1-final.json").unlink(missing_ok=True)
    verdict = answer_consistency_gate(run_dir)
    assert verdict["status"] == "blocked"
    codes = {item["code"] for item in verdict["violations"]}
    assert "registered_artifact_missing" in codes


def test_gate_blocks_paper_not_aligned(tmp_path: Path) -> None:
    """论文 answer-map 未引用冻结答案 primary 必须 RENDER_FORBIDDEN。"""
    run_dir = _consistent_run(tmp_path)
    atomic_json(
        run_dir / "paper/answer-map.json",
        {
            "answers": {"Q1": {"primary_result_id": "q1-old", "result_ids": ["q1-old"]}}
        },
    )
    verdict = answer_consistency_gate(run_dir)
    assert verdict["status"] == "blocked"
    codes = {item["code"] for item in verdict["violations"]}
    assert "paper_answer_map_not_aligned" in codes


def test_gate_blocks_figure_source_not_production(tmp_path: Path) -> None:
    """current 图源不是已登记生产工件必须 RENDER_FORBIDDEN。"""
    run_dir = _consistent_run(tmp_path)
    atomic_json(
        run_dir / "figures/index.json",
        {
            "schema_name": "simple_figure_index",
            "schema_version": "1.3",
            "run_id": run_dir.name,
            "figures": [
                {
                    "figure_id": "fig1",
                    "question_id": "Q1",
                    "status": "current",
                    "paper_allowed": True,
                    "source_files": ["figures/work/opp-q1/v1/handmade.png"],
                }
            ],
        },
    )
    verdict = answer_consistency_gate(run_dir)
    assert verdict["status"] == "blocked"
    codes = {item["code"] for item in verdict["violations"]}
    assert "figure_source_not_production" in codes
