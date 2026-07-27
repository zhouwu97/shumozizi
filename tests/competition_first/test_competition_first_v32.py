"""验证 Competition-First v3.2 的轻量建模单元和 LaTeX 主链。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.paper.readiness import check_paper_readiness
from shumozizi.paper.templates import select_paper_template
from shumozizi.simple import review as simple_review
from shumozizi.simple.competition import write_answer_map
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.modeling_units import (
    require_v32_experiment_evidence,
    semantic_reconstruction_input_bindings,
    write_modeling_units,
)
from shumozizi.simple.objective_consequences import (
    require_objective_consequences,
    write_objective_candidates,
)
from shumozizi.simple.results import register_result
from shumozizi.simple.review_focus import (
    record_scientific_challenge_evidence,
    record_stronger_alternative,
)
from shumozizi.simple.review_tasks import (
    create_review_task_receipt,
    persist_review_task_creation_event,
)
from shumozizi.simple.state import read_simple_state, update_simple_state, utc_now


def _register_result(
    run_dir: Path,
    result_id: str,
    *,
    objective: float = 1.0,
    duration_seconds: float = 10.0,
    extra_metrics: dict[str, float] | None = None,
) -> None:
    """登记可用于 v3.2 比较、攻击、深化和目标后果比较的真实生产结果。"""
    source = run_dir / "code" / f"{result_id}.py"
    output = run_dir / "results" / "raw" / f"{result_id}.json"
    source.write_text("print('ok')\n", encoding="utf-8")
    metrics: dict[str, float | bool] = {
        "objective": objective,
        "feasible": True,
        "endpoint_action_shift": 0.5,
        "max_action_shift": 0.5,
        "guard_pass_rate": 0.9,
    }
    metrics.update(extra_metrics or {})
    output.write_text(json.dumps({"metrics": metrics}), encoding="utf-8")
    now = utc_now()
    register_result(
        run_dir,
        result_id=result_id,
        question_id="Q1",
        kind=result_id,
        command=f"python code/{result_id}.py",
        source_script=f"code/{result_id}.py",
        input_files=[f"code/{result_id}.py"],
        output_files=[f"results/raw/{result_id}.json"],
        metrics=metrics,
        metric_sources={
            name: {"file": f"results/raw/{result_id}.json", "json_path": f"metrics.{name}"}
            for name in metrics
        },
        exit_code=0,
        stdout_path=f"results/{result_id}.stdout.log",
        stderr_path=f"results/{result_id}.stderr.log",
        started_at=now,
        finished_at=now,
        duration_seconds=duration_seconds,
        objective_semantics_sha256="a" * 64,
    )


def _register_objective_probes(run_dir: Path) -> None:
    """登记两个候选目标的低成本后果 probe。"""
    _register_result(
        run_dir,
        "probe-sum",
        objective=6.0,
        duration_seconds=2.0,
        extra_metrics={"weakest_entity_gain": 0.2},
    )
    _register_result(
        run_dir,
        "probe-min",
        objective=7.0,
        duration_seconds=2.0,
        extra_metrics={"weakest_entity_gain": 3.4},
    )


def _semantic_reconstruction(run_dir: Path, suffix: str) -> dict[str, str]:
    """构造带真实 create_thread 事件的独立题意重建回执夹具。"""
    report_file = f"review/SEMANTIC_RECONSTRUCTION_{suffix}.md"
    report = run_dir / report_file
    report.write_text(f"# 题意重建 {suffix}\n\n只根据题面重建目标、变量和约束。\n", encoding="utf-8")
    event = persist_review_task_creation_event(
        run_dir,
        event_file=f"review/tasks/creation-events/semantic-{suffix}.json",
        raw_event={
            "schema_name": "review_task_creation_event",
            "schema_version": "1.0",
            "provider": "codex",
            "raw_task_id": f"semantic-task-{suffix}",
            "raw_thread_id": f"semantic-thread-{suffix}",
            "creation_mode": "create_thread",
            "parent_context_inherited": False,
            "created_at": "2026-07-25T00:00:00Z",
        },
    )
    receipt = create_review_task_receipt(
        run_dir,
        task_id=f"semantic-{suffix}",
        task_type="semantic_reconstruction",
        model_id="fixture-model",
        prompt_sha256="a" * 64,
        input_bindings=semantic_reconstruction_input_bindings(run_dir),
        report_file=report_file,
        creation_event_file=event.relative_to(run_dir).as_posix(),
    )
    return {"task_receipt": receipt.relative_to(run_dir).as_posix(), "report_file": report_file}


def _plan(run_dir: Path) -> dict[str, object]:
    """构造一个最小 compare 单元，覆盖 v3.2 的关键决策事实。"""
    return {
        "schema_version": "1.2",
        "run_id": run_dir.name,
        "semantic_reconstructions": [
            _semantic_reconstruction(run_dir, "A"),
            _semantic_reconstruction(run_dir, "B"),
        ],
        "research_story": {
            "central_tension": "在可行性约束下提高精确目标，同时保留可解释回退。",
            "question_progression": [
                {
                    "question_id": "Q1",
                    "role": "建立可复验的基线与统一评价口径。",
                    "upgrade": "用结构不同的路线比较并在首解后继续深化。",
                }
            ],
        },
        "units": [
            {
                "unit_id": "Q1-search",
                "question_id": "Q1",
                "core_question": True,
                "mode": "compare",
                "answer_contract": {
                    "required_output": "给出总成本最小的可执行方案及其成本。",
                    "decision_scope": "当前数据覆盖的全部任务与规划时段。",
                    "natural_baseline": "按题面优先级逐项构造的规则方案。",
                    "fallback_rule": "晋级失败时使用已通过稳定性检查的 R1。",
                    "primary_endpoint": {
                        "endpoint_id": "objective",
                        "name": "objective",
                        "definition": "所有任务完成后的精确总成本。",
                        "exact_metric_alignment": "与 exact scorer 的 objective 字段完全一致。",
                    },
                    "primary_criterion": "方案可行且相对自然 baseline 至少改善 10%。",
                    "endpoint_resolution": {
                        "status": "comparison_planned",
                        "basis": "聚合目标先通过候选后果 probe 冻结，主 endpoint 不变。",
                        "candidate_endpoints": [
                            {
                                "endpoint_id": "objective",
                                "definition": "所有任务完成后的精确总成本。",
                                "problem_text_basis": "题面要求总成本最小。",
                            },
                            {
                                "endpoint_id": "worst_case",
                                "definition": "最坏任务的最大成本。",
                                "problem_text_basis": "题面同时要求任务全部可行。",
                            },
                        ],
                        "decision_rule": "若合理口径导致路线翻转或行动漂移超过 1，则返回分析。",
                    },
                },
                "objective": {
                    "exact_metric": "objective",
                    "direction": "minimize",
                    "significant_improvement_ratio": 0.1,
                },
                "budget": {"kind": "wall_seconds", "tolerance_ratio": 0.1},
                "baseline": {
                    "route_id": "R0",
                    "mathematical_structure": "可解释规则模型",
                    "natural_rationale": "直接按题面优先级构造，是无需复杂优化的自然参照。",
                },
                "competitive_routes": [
                    {
                        "route_id": "R1",
                        "mathematical_structure": "约束规划",
                        "structure_exploited": "利用可行域的分段线性结构做精确剪枝。",
                        "expected_upside": "在同预算下把精确目标压到基线以下 15%。",
                        "expected_improvement_ratio": 0.15,
                    },
                    {
                        "route_id": "R2",
                        "mathematical_structure": "连续全局优化",
                        "structure_exploited": "利用目标在连续域上的可微性做多起点下降。",
                        "expected_upside": "有机会跳出基线所在的局部盆地。",
                        "expected_improvement_ratio": 0.25,
                    },
                ],
                "fallback": {"route_id": "R1", "switch_condition": "精确目标未改善时切换。"},
                "expected_outcome": "结构模型将在同预算下改善精确目标。",
                "first_batch_attack": {
                    "attack": "用独立小实例检查路线排序是否翻转。",
                    "decision": "若翻转则退回分析并修正建模假设。",
                },
                "refinement": {
                    "strategy_families": ["结构精化", "独立全局搜索"],
                    "stop_reason_whitelist": ["budget_exhausted", "exact_certificate"],
                },
                "validation": {
                    "oracle": {"required": False},
                    "sensitivity": {
                        "required": True,
                        "trigger": "参数影响目标排序。",
                        "pass_criterion": "主要结论在预登记扰动内不翻转。",
                    },
                    "robustness": {
                        "required": True,
                        "trigger": "输入噪声可能影响可行性。",
                        "pass_criterion": "极端场景仍满足可行性阈值。",
                    },
                },
            }
        ],
    }


def _objective_candidates(run_dir: Path, *, with_actual: bool = True) -> dict[str, object]:
    """构造开放目标的候选集合与后果度量声明。"""
    document: dict[str, object] = {
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "questions": [
            {
                "question_id": "Q1",
                "objective_openness": "open",
                "candidates": [
                    {
                        "objective_id": "sum",
                        "formula": "最大化累计收益 sum(gain_i)",
                        "expected_strategy_bias": "偏好把资源集中到最容易得分的实体。",
                        "problem_text_basis": "题面要求总体效果尽可能好。",
                    },
                    {
                        "objective_id": "min",
                        "formula": "最大化最弱实体收益 min(gain_i)",
                        "expected_strategy_bias": "偏好把资源摊向最难保障的实体。",
                        "problem_text_basis": "题面同时要求每个实体都被覆盖。",
                    },
                ],
                "consequence_metrics": [
                    {"metric": "objective", "kind": "efficiency", "direction": "minimize"},
                    {
                        "metric": "weakest_entity_gain",
                        "kind": "bottleneck",
                        "direction": "maximize",
                        "acceptable_floor": 1.0,
                    },
                ],
            }
        ],
    }
    if with_actual:
        questions = document["questions"]
        assert isinstance(questions, list)
        question = questions[0]
        assert isinstance(question, dict)
        question["actual"] = {
            "candidate_probes": {"sum": "probe-sum", "min": "probe-min"},
            "frozen_objective_id": "min",
            "freeze_rationale": "累计收益候选让最弱实体跌破可接受下限。",
        }
    return document


def _actual(plan: dict[str, object]) -> None:
    """为计划回填真实实验的最小证据映射。"""
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    unit["actual"] = {
        "expectation_status": "confirmed",
        "summary": "R2 在统一 exact 和共同预算下最佳，独立攻击没有改变排序。",
        "comparison": {
            "route_result_ids": {"R0": "baseline", "R1": "structural", "R2": "global"},
            "winner_route_id": "R2",
        },
        "actual_endpoint_resolution": {
            "status": "determined",
            "selected_endpoint_id": "objective",
            "problem_text_basis": "总成本最小是题面直接目标。",
            "evidence_result_ids": ["sensitivity"],
            "winner_route_ids": {"objective": "R2", "worst_case": "R2"},
        },
        "qualification_evidence": {
            "endpoint_checks": [
                {
                    "result_id": "sensitivity",
                    "metric": "endpoint_action_shift",
                    "operator": "<=",
                    "threshold": 1.0,
                }
            ],
            "guards": [
                {
                    "result_id": "robustness",
                    "metric": "guard_pass_rate",
                    "operator": ">=",
                    "threshold": 0.8,
                }
            ],
            "decision_stability": [
                {
                    "result_id": "sensitivity",
                    "metric": "max_action_shift",
                    "operator": "<=",
                    "threshold": 1.0,
                }
            ],
        },
        "first_batch_attack": {"result_ids": ["attack"], "conclusion": "未发现排序翻转。"},
        "refinement": {
            "first_feasible_result_id": "first-feasible",
            "final_result_id": "final",
            "family_result_ids": {
                "结构精化": ["structural"],
                "独立全局搜索": ["global"],
            },
            "stop_reason": "budget_exhausted",
        },
        "validation": {
            "sensitivity_result_ids": ["sensitivity"],
            "robustness_result_ids": ["robustness"],
        },
        "insights": [
            {
                "insight_id": "Q1-marginal",
                "kind": "marginal_gain",
                "observation": "第三次深化只带来 0.3 的目标改善。",
                "mechanism": "两条路线在同一活跃约束上受限，额外预算无法放松它。",
                "boundary": "该结论只覆盖已测试的预算区间。",
                "evidence_result_ids": ["structural", "global", "final"],
            }
        ],
    }


def test_v32_requires_two_fresh_reconstructions_then_real_comparison_evidence(tmp_path: Path) -> None:
    """v3.2 不能绕过题意重建、异构路线、首解后深化或事后结果对照。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v32-modeling-units",
        competition="cumcm",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    (run_dir / "problem" / "statement.md").write_text("最小化总成本。", encoding="utf-8")
    plan = _plan(run_dir)

    write_modeling_units(run_dir, plan)
    write_objective_candidates(run_dir, _objective_candidates(run_dir, with_actual=False))
    state = update_simple_state(run_dir, phase="experiment")

    assert state["schema_version"] == "3.2"
    for result_id, objective in (
        ("baseline", 10.0),
        ("structural", 8.0),
        ("global", 7.0),
        ("attack", 7.0),
        ("first-feasible", 9.0),
        ("final", 7.0),
        ("sensitivity", 7.2),
        ("robustness", 7.3),
    ):
        _register_result(run_dir, result_id, objective=objective)
    _register_objective_probes(run_dir)
    _actual(plan)
    write_modeling_units(run_dir, plan)
    write_objective_candidates(run_dir, _objective_candidates(run_dir))

    require_v32_experiment_evidence(run_dir)
    require_objective_consequences(run_dir)


def test_modeling_units_cannot_add_route_after_delivery_cutoff(tmp_path: Path) -> None:
    """首版 PDF 截止后不得借更新建模单元继续扩张候选路线。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v32-late-route",
        competition="cumcm",
        required_questions=["Q1"],
        workflow_version="3.2",
        total_hours=12,
    )
    plan = _plan(run_dir)
    write_modeling_units(run_dir, plan)
    control_path = run_dir / "state/delivery-control.json"
    control = load_json(control_path)
    start = datetime.fromisoformat(control["started_at"].replace("Z", "+00:00"))
    control["started_at"] = (start - timedelta(minutes=481)).isoformat().replace("+00:00", "Z")
    atomic_json(control_path, control)
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    routes = unit["competitive_routes"]
    assert isinstance(routes, list)
    routes.append(
        {
            "route_id": "R3",
            "mathematical_structure": "混合整数规划",
            "structure_exploited": "显式利用离散决策结构。",
            "expected_upside": "检查新的精确路线是否改善结果。",
            "expected_improvement_ratio": 0.2,
        }
    )

    with pytest.raises(ContractError, match="add_new_route"):
        write_modeling_units(run_dir, plan)


def test_v32_rejects_first_feasible_as_final_result(tmp_path: Path) -> None:
    """首个可行解即终止时，即使其它说明齐全也不得进入论文。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v32-first-solution",
        competition="cumcm",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    plan = _plan(run_dir)
    write_modeling_units(run_dir, plan)
    for result_id in (
        "baseline",
        "structural",
        "global",
        "attack",
        "first-feasible",
        "sensitivity",
        "robustness",
    ):
        _register_result(run_dir, result_id)
    _actual(plan)
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    actual = unit["actual"]
    assert isinstance(actual, dict)
    refinement = actual["refinement"]
    assert isinstance(refinement, dict)
    refinement["final_result_id"] = "first-feasible"
    write_modeling_units(run_dir, plan)

    with pytest.raises(ContractError, match="首个可行解"):
        require_v32_experiment_evidence(run_dir)


def test_v32_requires_direct_answer_contract_before_experiment(tmp_path: Path) -> None:
    """路线比较前必须先冻结本问要回答什么，不能实验后倒推 endpoint。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v32-answer-contract",
        competition="cumcm",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    plan = _plan(run_dir)
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    unit.pop("answer_contract")

    with pytest.raises(ContractError, match="answer_contract"):
        write_modeling_units(run_dir, plan)


def test_v32_failed_stability_cannot_promote_exact_winner(tmp_path: Path) -> None:
    """exact 最优但决策不稳定时必须回退或重设计，不能直接成为主答案。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v32-promotion-stability",
        competition="cumcm",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    plan = _plan(run_dir)
    for result_id, objective in (
        ("baseline", 10.0),
        ("structural", 8.0),
        ("global", 7.0),
        ("attack", 7.0),
        ("first-feasible", 9.0),
        ("final", 7.0),
        ("sensitivity", 7.2),
        ("robustness", 7.3),
    ):
        extra = {"max_action_shift": 2.0} if result_id == "sensitivity" else None
        _register_result(run_dir, result_id, objective=objective, extra_metrics=extra)
    _actual(plan)
    write_modeling_units(run_dir, plan)

    with pytest.raises(ContractError, match="validation_insufficient.*experiment"):
        require_v32_experiment_evidence(run_dir)


def test_v32_promotion_checks_ignore_manual_override(tmp_path: Path) -> None:
    """人工填写的通过结论不能覆盖由真实指标计算出的答案资格。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v32-derived-promotion",
        competition="cumcm",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    plan = _plan(run_dir)
    for result_id, objective in (
        ("baseline", 10.0),
        ("structural", 8.0),
        ("global", 7.0),
        ("attack", 7.0),
        ("first-feasible", 9.0),
        ("final", 7.0),
        ("sensitivity", 7.2),
        ("robustness", 7.3),
    ):
        _register_result(run_dir, result_id, objective=objective)
    _actual(plan)
    unit = plan["units"][0]
    unit["actual"]["promotion_decision"] = {
        "status": "fallback_selected",
        "selected_route_id": "R1",
        "selected_result_id": "structural",
        "rollback_target": None,
        "failure_kind": None,
        "route_upgrade_passed": False,
        "endpoint_consistent": True,
        "guard_constraints_passed": True,
        "decision_stable": True,
    }
    write_modeling_units(run_dir, plan)

    with pytest.raises(ContractError, match="系统派生答案资格不一致"):
        require_v32_experiment_evidence(run_dir)


def test_v32_endpoint_ranking_reversal_returns_to_analysis(tmp_path: Path) -> None:
    """合理 endpoint 导致赢家翻转时必须回到 analysis，不能降级为敏感性说明。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v32-endpoint-reversal",
        competition="cumcm",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    plan = _plan(run_dir)
    for result_id, objective in (
        ("baseline", 10.0),
        ("structural", 8.0),
        ("global", 7.0),
        ("attack", 7.0),
        ("first-feasible", 9.0),
        ("final", 7.0),
        ("sensitivity", 7.2),
        ("robustness", 7.3),
    ):
        _register_result(run_dir, result_id, objective=objective)
    _actual(plan)
    unit = plan["units"][0]
    unit["actual"]["actual_endpoint_resolution"]["winner_route_ids"]["worst_case"] = "R1"
    write_modeling_units(run_dir, plan)

    with pytest.raises(ContractError, match="endpoint_unresolved.*analysis"):
        require_v32_experiment_evidence(run_dir)


def test_v32_endpoint_resolution_must_cover_all_planned_candidates(tmp_path: Path) -> None:
    """endpoint 裁决不能用空赢家映射伪造已完成候选后果比较。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v32-endpoint-evidence-empty",
        competition="cumcm",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    plan = _plan(run_dir)
    for result_id, objective in (
        ("baseline", 10.0),
        ("structural", 8.0),
        ("global", 7.0),
        ("attack", 7.0),
        ("first-feasible", 9.0),
        ("final", 7.0),
        ("sensitivity", 7.2),
        ("robustness", 7.3),
    ):
        _register_result(run_dir, result_id, objective=objective)
    _actual(plan)
    unit = plan["units"][0]
    unit["actual"]["actual_endpoint_resolution"]["winner_route_ids"] = {}
    write_modeling_units(run_dir, plan)

    with pytest.raises(ContractError, match="完整覆盖预登记候选 endpoint"):
        require_v32_experiment_evidence(run_dir)


def test_answer_map_must_follow_selected_fallback(tmp_path: Path) -> None:
    """赢家未晋级而启用 fallback 后，论文不能继续把失败赢家列为主答案。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v32-fallback-answer",
        competition="cumcm",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    plan = _plan(run_dir)
    for result_id, objective in (
        ("baseline", 10.0),
        ("structural", 8.0),
        ("global", 7.0),
        ("attack", 7.0),
        ("first-feasible", 9.0),
        ("final", 7.0),
        ("sensitivity", 7.2),
        ("robustness", 7.3),
    ):
        _register_result(run_dir, result_id, objective=objective)
    _actual(plan)
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    unit["objective"]["significant_improvement_ratio"] = 0.5
    unit["actual"]["qualification_evidence"]["fallback"] = {
        "guards": [
            {
                "result_id": "structural",
                "metric": "guard_pass_rate",
                "operator": ">=",
                "threshold": 0.8,
            }
        ],
        "decision_stability": [
            {
                "result_id": "structural",
                "metric": "max_action_shift",
                "operator": "<=",
                "threshold": 1.0,
            }
        ],
    }
    write_modeling_units(run_dir, plan)
    require_v32_experiment_evidence(run_dir)

    with pytest.raises(ContractError, match="必须等于路线晋级/回退决定"):
        write_answer_map(
            run_dir,
            {
                "Q1": {
                    "result_ids": ["global", "final"],
                    "primary_result_id": "final",
                    "direct_answer_location": "paper/sections/q1.tex",
                }
            },
        )

    answer_map = write_answer_map(
        run_dir,
        {
            "Q1": {
                "result_ids": ["structural"],
                "primary_result_id": "structural",
                "direct_answer_location": "paper/sections/q1.tex",
            }
        },
    )
    assert answer_map["answers"]["Q1"]["primary_result_id"] == "structural"


def test_v32_rejects_typst_even_when_a_template_engine_is_available(tmp_path: Path) -> None:
    """v3.2 必须显式锁定 LaTeX，不能把 auto 或 Typst 当作可接受回退。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v32-latex-only",
        competition="cumcm",
        required_questions=["Q1"],
        workflow_version="3.2",
    )

    with pytest.raises(ContractError, match="强制使用 LaTeX"):
        select_paper_template(
            run_dir,
            language="zh",
            engine="typst",
            selection_reason="v3.2 不允许回退 Typst。",
        )
    assert read_simple_state(run_dir)["workflow"] == "competition-first-v3.2"


def test_v32_answer_map_alone_cannot_bypass_derived_qualification(tmp_path: Path) -> None:
    """v3.2 即使已有 answer map，也必须先形成系统派生答案资格。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v32-paper-readiness",
        competition="cumcm",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    _register_result(run_dir, "q1-primary")
    write_answer_map(
        run_dir,
        {"Q1": {"result_ids": ["q1-primary"], "direct_answer_location": "paper/sections/q1.tex"}},
    )

    status = check_paper_readiness(run_dir)

    assert not status["ready"]
    assert any("系统派生的答案资格" in error for error in status["errors"])


def test_v32_scientific_challenge_uses_current_evidence_without_legacy_summary(
    tmp_path: Path,
) -> None:
    """v3.2 用报告、fresh-thread 回执和当前结果放行论文，不要求 v3.1 摘要。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v32-scientific-challenge",
        competition="cumcm",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    (run_dir / "problem" / "statement.md").write_text("最小化总成本。", encoding="utf-8")
    plan = _plan(run_dir)
    write_modeling_units(run_dir, plan)
    write_objective_candidates(run_dir, _objective_candidates(run_dir, with_actual=False))
    update_simple_state(run_dir, phase="experiment")
    for result_id, objective in (
        ("baseline", 10.0),
        ("structural", 8.0),
        ("global", 7.0),
        ("attack", 7.0),
        ("first-feasible", 9.0),
        ("final", 7.0),
        ("sensitivity", 7.2),
        ("robustness", 7.3),
    ):
        _register_result(run_dir, result_id, objective=objective)
    _register_objective_probes(run_dir)
    _actual(plan)
    write_modeling_units(run_dir, plan)
    write_objective_candidates(run_dir, _objective_candidates(run_dir))

    packet = simple_review.build_review_packet(run_dir, kind="scientific")
    manifest_file = f"review/packet/scientific/{packet['packet_id']}/manifest.json"
    report = run_dir / "review" / "SCIENTIFIC_CHALLENGE.md"
    report.write_text(
        "# 科学挑战\n\n## 风险清单\n\n- **P0：** 无。\n- **P1-01：** 有限采样不能证明连续模型。\n",
        encoding="utf-8",
    )
    bindings = {
        "packet": {
            "manifest_file": manifest_file,
            "manifest_sha256": sha256_file(run_dir / manifest_file),
        }
    }
    task_dir = run_dir / "review" / "tasks" / "scientific-v32"
    task_dir.mkdir(parents=True)
    (task_dir / "input-bindings.json").write_text(
        json.dumps(bindings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    event = persist_review_task_creation_event(
        run_dir,
        event_file="review/tasks/scientific-v32/creation-event.json",
        raw_event={
            "schema_name": "review_task_creation_event",
            "schema_version": "1.0",
            "provider": "codex",
            "raw_task_id": "v32-scientific-task",
            "raw_thread_id": "v32-scientific-thread",
            "creation_mode": "create_thread",
            "parent_context_inherited": False,
            "created_at": "2026-07-25T00:00:00Z",
        },
    )
    create_review_task_receipt(
        run_dir,
        task_id="scientific-v32",
        task_type="scientific_open",
        model_id="fixture-model",
        prompt_sha256="1" * 64,
        input_bindings=bindings,
        report_file="review/SCIENTIFIC_CHALLENGE.md",
        creation_event_file=event.relative_to(run_dir).as_posix(),
    )
    record_scientific_challenge_evidence(
        run_dir,
        result_ids=[
            "baseline",
            "structural",
            "global",
            "attack",
            "first-feasible",
            "final",
            "sensitivity",
            "robustness",
        ],
        attack_description="独立攻击当前生产结果。",
        findings=[
            {
                "finding_id": "P1-01",
                "question_id": "Q1",
                "severity": "P1",
                "finding": "有限样本不能证明全部连续边界。",
                "action_type": "DATA_LIMITATION",
                "rollback_target": "paper",
                "invalidates": ["全域外推"],
                "required_action": "正文明确有限样本的适用边界。",
                "status": "open",
                "closure_evidence_result_ids": [],
                "why_not_repairable": "当前题目附件没有总体分布，赛程内无法取得新数据。",
            }
        ],
    )
    record_stronger_alternative(run_dir, found=False)

    status = simple_review.scientific_review_status(run_dir)

    assert status["allowed"], status
    assert not status["submission_ready"]
    assert status["unresolved_high_severities"] == ["P1"]
    assert not (run_dir / "review" / "summary.json").exists()
    simple_review.require_paper_generation_allowed(run_dir)

    record_scientific_challenge_evidence(
        run_dir,
        result_ids=[
            "baseline", "structural", "global", "attack",
            "first-feasible", "final", "sensitivity", "robustness",
        ],
        attack_description="发现可通过补算修复的模型缺陷。",
        findings=[
            {
                "finding_id": "P1-02",
                "question_id": "Q1",
                "severity": "P1",
                "finding": "缺少可直接补算的参数置信带。",
                "action_type": "MODEL_REPAIR",
                "rollback_target": "experiment",
                "invalidates": ["primary_result", "answer_map", "paper_section"],
                "required_action": "重新拟合并登记置信带结果。",
                "status": "open",
                "closure_evidence_result_ids": [],
            }
        ],
    )
    blocked = simple_review.scientific_review_status(run_dir)
    assert not blocked["allowed"]
    assert "P1-02→experiment" in blocked["reason"]


def test_v32_paper_generation_uses_modeling_evidence_not_legacy_tournament(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v3.2 以实际 compare 单元为准，不要求 v3.1 路线锦标赛文件。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v32-paper-generation",
        competition="cumcm",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    plan = _plan(run_dir)
    for result_id, objective in (
        ("baseline", 10.0),
        ("structural", 8.0),
        ("global", 7.0),
        ("attack", 7.0),
        ("first-feasible", 9.0),
        ("final", 7.0),
        ("sensitivity", 7.2),
        ("robustness", 7.3),
    ):
        _register_result(run_dir, result_id, objective=objective)
    _register_objective_probes(run_dir)
    _actual(plan)
    write_modeling_units(run_dir, plan)
    write_objective_candidates(run_dir, _objective_candidates(run_dir))
    record_stronger_alternative(run_dir, found=False)
    monkeypatch.setattr(
        simple_review,
        "_v32_scientific_challenge_status",
        lambda _run: {"allowed": True, "submission_ready": False, "reason": "fixture"},
    )

    simple_review.require_paper_generation_allowed(run_dir)


def test_v32_verify_reachable_without_web_audit(tmp_path: Path) -> None:
    """v3.2 在没有任何网页审核文件时，科学挑战 + PDF 盲评 → 能进入 verify 阶段。

    回归测试：P1-A 修复前，进入 verify 会无条件调用
    require_web_paper_audit_release()，导致纯 PDF 盲评路径被网页审核缺失阻断。
    """
    run_dir = initialize_simple_run(
        tmp_path,
        "v32-no-web-audit",
        competition="cumcm",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    (run_dir / "problem" / "statement.md").write_text("最小化总成本。", encoding="utf-8")

    plan = _plan(run_dir)
    write_modeling_units(run_dir, plan)
    write_objective_candidates(run_dir, _objective_candidates(run_dir, with_actual=False))
    update_simple_state(run_dir, phase="experiment")
    for result_id, objective in (
        ("baseline", 10.0),
        ("structural", 8.0),
        ("global", 7.0),
        ("attack", 7.0),
        ("first-feasible", 9.0),
        ("final", 7.0),
        ("sensitivity", 7.2),
        ("robustness", 7.3),
    ):
        _register_result(run_dir, result_id, objective=objective)
    _register_objective_probes(run_dir)
    _actual(plan)
    write_modeling_units(run_dir, plan)
    write_objective_candidates(run_dir, _objective_candidates(run_dir))

    # 科学挑战：v3.2 用报告 + fresh-thread 回执 + 当前结果放行。
    science_packet = simple_review.build_review_packet(run_dir, kind="scientific")
    science_manifest = f"review/packet/scientific/{science_packet['packet_id']}/manifest.json"
    (run_dir / "review" / "SCIENTIFIC_CHALLENGE.md").write_text(
        "# 科学挑战\n\n## 风险清单\n\n- **P0：** 无。\n- **P1：** 无。\n",
        encoding="utf-8",
    )
    science_bindings = {
        "packet": {
            "manifest_file": science_manifest,
            "manifest_sha256": sha256_file(run_dir / science_manifest),
        }
    }
    science_task_dir = run_dir / "review" / "tasks" / "scientific-no-web-audit"
    science_task_dir.mkdir(parents=True)
    (science_task_dir / "input-bindings.json").write_text(
        json.dumps(science_bindings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    science_event = persist_review_task_creation_event(
        run_dir,
        event_file="review/tasks/scientific-no-web-audit/creation-event.json",
        raw_event={
            "schema_name": "review_task_creation_event",
            "schema_version": "1.0",
            "provider": "codex",
            "raw_task_id": "no-web-audit-scientific-task",
            "raw_thread_id": "no-web-audit-scientific-thread",
            "creation_mode": "create_thread",
            "parent_context_inherited": False,
            "created_at": "2026-07-25T00:00:00Z",
        },
    )
    create_review_task_receipt(
        run_dir,
        task_id="scientific-no-web-audit",
        task_type="scientific_open",
        model_id="fixture-model",
        prompt_sha256="1" * 64,
        input_bindings=science_bindings,
        report_file="review/SCIENTIFIC_CHALLENGE.md",
        creation_event_file=science_event.relative_to(run_dir).as_posix(),
    )
    record_scientific_challenge_evidence(
        run_dir,
        result_ids=[
            "baseline",
            "structural",
            "global",
            "attack",
            "first-feasible",
            "final",
            "sensitivity",
            "robustness",
        ],
        attack_description="独立攻击当前生产结果。",
    )
    record_stronger_alternative(run_dir, found=False)
    assert simple_review.scientific_review_status(run_dir)["allowed"]

    # paper_review 阶段与最小 PDF：本测试只验证 verify 门禁，不重跑编译链。
    state_path = run_dir / "state" / "run.json"
    state_raw = load_json(state_path)
    state_raw["phase"] = "paper_review"
    atomic_json(state_path, state_raw)
    (run_dir / "paper" / "final.pdf").write_bytes(b"%PDF-1.4\nv32-no-web-audit")

    packet = simple_review.build_review_packet(run_dir, kind="paper-blind")
    manifest_file = f"review/packet/paper-blind/{packet['packet_id']}/manifest.json"
    report = run_dir / "review" / "PAPER_BLIND_REVIEW.md"
    report.write_text("# PDF 全面盲审\n\n本轮未确认 P0/P1。\n", encoding="utf-8")
    bindings = {
        "packet": {
            "manifest_file": manifest_file,
            "manifest_sha256": sha256_file(run_dir / manifest_file),
        }
    }
    event = persist_review_task_creation_event(
        run_dir,
        event_file="review/tasks/creation-events/paper-blind-no-web-audit.json",
        raw_event={
            "schema_name": "review_task_creation_event",
            "schema_version": "1.0",
            "provider": "codex",
            "raw_task_id": "paper-blind-no-web-audit-task",
            "raw_thread_id": "paper-blind-no-web-audit-thread",
            "creation_mode": "create_thread",
            "parent_context_inherited": False,
            "created_at": "2026-07-25T00:00:00Z",
        },
    )
    receipt = create_review_task_receipt(
        run_dir,
        task_id="paper-blind-no-web-audit",
        task_type="paper_blind_open",
        model_id="fixture-model",
        prompt_sha256=simple_review.paper_blind_review_prompt_sha256(run_dir, manifest_file),
        input_bindings=bindings,
        report_file=report.relative_to(run_dir).as_posix(),
        creation_event_file=event.relative_to(run_dir).as_posix(),
    )
    simple_review.import_paper_blind_review(
        run_dir,
        manifest_file=manifest_file,
        verdict="pass",
        highest_severity="none",
        reviewer_thread_id="paper-blind-no-web-audit-thread",
        task_receipt_file=receipt.relative_to(run_dir).as_posix(),
    )

    assert not any(
        (run_dir / "review" / name).is_file()
        for name in (
            "WEB_PAPER_AUDIT_PROMPT.json",
            "WEB_PAPER_AUDIT.json",
            "WEB_PAPER_AUDIT_REPAIR_PLAN.json",
        )
    ), "夹具不应预先创建任何网页审核文件"

    state = update_simple_state(run_dir, phase="verify")

    assert state["phase"] == "verify"
