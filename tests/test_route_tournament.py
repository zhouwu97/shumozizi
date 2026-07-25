"""验证核心问题必须以真实统一 exact 结果参加路线锦标赛。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError
from shumozizi.simple.competition import (
    require_route_tournament_for_paper,
    write_route_tournament,
)
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.results import register_result
from shumozizi.simple.state import utc_now


def _result(run_dir: Path, result_id: str, *, objective: float, duration: float) -> None:
    """登记一条带统一 exact、可行与稳健性事实的路线执行结果。"""
    source = run_dir / "code" / f"{result_id}.py"
    output = run_dir / "results" / "raw" / f"{result_id}.json"
    source.write_text("print('route')\n", encoding="utf-8")
    output.write_text(
        json.dumps(
            {
                "metrics": {
                    "objective": objective,
                    "feasible": True,
                    "robustness_passed": True,
                }
            }
        ),
        encoding="utf-8",
    )
    now = utc_now()
    register_result(
        run_dir,
        result_id=result_id,
        question_id="Q1",
        kind=f"route-{result_id}",
        command=f"python code/{result_id}.py --budget 100",
        source_script=f"code/{result_id}.py",
        input_files=[f"code/{result_id}.py"],
        output_files=[f"results/raw/{result_id}.json"],
        metrics={"objective": objective, "feasible": True, "robustness_passed": True},
        metric_sources={
            name: {"file": f"results/raw/{result_id}.json", "json_path": f"metrics.{name}"}
            for name in ("objective", "feasible", "robustness_passed")
        },
        exit_code=0,
        stdout_path=f"results/{result_id}.stdout.log",
        stderr_path=f"results/{result_id}.stderr.log",
        started_at=now,
        finished_at=now,
        duration_seconds=duration,
        objective_semantics_sha256="a" * 64,
    )


def _route(route_id: str, result_id: str, structure: str, *, runtime: float) -> dict[str, object]:
    """构造已绑定真实执行结果的一条路线。"""
    return {
        "route_id": route_id,
        "mathematical_structure": structure,
        "assumptions": ["使用题目给定输入。"],
        "probe_result_ids": [result_id],
        "exact_score_result_id": result_id,
        "feasibility_result_id": result_id,
        "feasible": True,
        "runtime_seconds": runtime,
        "robustness_result_id": result_id,
        "mechanism_value": "给出题目特定的可解释机制。",
        "failure_mode": "极端参数下可能退化。",
        "switch_condition": "exact 目标未提升时切回基线。",
        "budget_result_ids": [result_id],
    }


def test_core_route_tournament_derives_strong_from_real_exact_results(tmp_path: Path) -> None:
    """strong 只能由同目标、同预算和不同数学结构的真实结果导出。"""
    run_dir = initialize_simple_run(tmp_path, "route-strong", required_questions=["Q1"])
    _result(run_dir, "baseline", objective=10.0, duration=10.0)
    _result(run_dir, "structural", objective=8.0, duration=11.0)
    _result(run_dir, "high-ceiling", objective=7.0, duration=10.5)
    payload = {
        "schema_version": "1.0",
        "question_id": "Q1",
        "core_question": True,
        "comparison": {
            "exact_metric": "objective",
            "objective_direction": "minimize",
            "budget_kind": "wall_seconds",
            "budget_tolerance_ratio": 0.2,
            "significant_improvement_ratio": 0.05,
        },
        "baseline": _route("R0", "baseline", "可解释规则模型", runtime=10.0),
        "candidates": [
            _route("R1", "structural", "约束规划", runtime=11.0),
            _route("R2", "high-ceiling", "连续全局优化", runtime=10.5),
        ],
        "selection": {
            "winner_route_id": "R2",
            "fallback_route_id": "R1",
            "selection_rationale": "R2 在统一 exact 目标下改善且保留 R1 作为回退。",
        },
    }

    tournament = write_route_tournament(run_dir, payload)

    assert tournament["derived_strength"] == "strong"
    assert require_route_tournament_for_paper(run_dir)["derived_strength"] == "strong"


def test_proxy_or_description_cannot_replace_exact_tournament_result(tmp_path: Path) -> None:
    """只有描述或 proxy 领先、没有 exact result ID 时不得登记路线赢家。"""
    run_dir = initialize_simple_run(tmp_path, "route-proxy", required_questions=["Q1"])
    _result(run_dir, "baseline", objective=10.0, duration=10.0)
    payload = {
        "schema_version": "1.0",
        "question_id": "Q1",
        "core_question": True,
        "comparison": {
            "exact_metric": "objective",
            "objective_direction": "minimize",
            "budget_kind": "wall_seconds",
            "budget_tolerance_ratio": 0.2,
            "significant_improvement_ratio": 0.05,
        },
        "baseline": _route("R0", "baseline", "规则", runtime=10.0),
        "candidates": [
            {
                **_route("R1", "baseline", "不同结构", runtime=10.0),
                "exact_score_result_id": "missing-exact",
            },
            _route("R2", "baseline", "另一不同结构", runtime=10.0),
        ],
        "selection": {
            "winner_route_id": "R1",
            "fallback_route_id": "R0",
            "selection_rationale": "只在 proxy 上领先。",
        },
    }

    with pytest.raises(ContractError, match="exact_score_result_id"):
        write_route_tournament(run_dir, payload)
