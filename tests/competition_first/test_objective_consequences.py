"""验证 v3.2 的目标后果比较、核心问题预算倾斜与规律挖掘门禁。

这些测试锁定的是建模上限，而不是协议完整度：目标必须先看后果再冻结，核心
问题的搜索预算不能被验证压过，核心问题必须真的提炼出规律。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from shumozizi.core.io import ContractError
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.modeling_units import (
    question_outcome_selections,
    require_v32_experiment_evidence,
    semantic_reconstruction_input_bindings,
    validate_modeling_units,
    write_modeling_units,
)
from shumozizi.simple.objective_consequences import (
    frozen_objectives,
    require_objective_candidate_plan,
    validate_objective_candidates,
    write_objective_candidates,
)
from shumozizi.simple.results import register_result
from shumozizi.simple.review_focus import record_scientific_challenge_evidence
from shumozizi.simple.review_tasks import (
    create_review_task_receipt,
    persist_review_task_creation_event,
)
from shumozizi.simple.state import utc_now


def _run(tmp_path: Path, name: str) -> Path:
    """创建一个最小 v3.2 运行目录。"""
    run_dir = initialize_simple_run(
        tmp_path,
        name,
        competition="cumcm",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    (run_dir / "problem" / "statement.md").write_text("最大化总收益。", encoding="utf-8")
    return run_dir


def _register(
    run_dir: Path,
    result_id: str,
    *,
    objective: float = 1.0,
    duration_seconds: float = 10.0,
    extra: dict[str, float] | None = None,
    output_extra: dict[str, Any] | None = None,
    execution_mode: str = "production",
) -> None:
    """登记一个真实执行结果，默认 production。"""
    (run_dir / "code" / f"{result_id}.py").write_text("print('ok')\n", encoding="utf-8")
    metrics: dict[str, float | bool] = {
        "objective": objective,
        "feasible": True,
        "endpoint_action_shift": 0.0,
        "max_action_shift": 0.0,
        "guard_pass_rate": 1.0,
    }
    metrics.update(extra or {})
    (run_dir / "results" / "raw" / f"{result_id}.json").write_text(
        json.dumps({"metrics": metrics, **(output_extra or {})}), encoding="utf-8"
    )
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
        execution_mode=execution_mode,
        objective_semantics_sha256="a" * 64,
    )


def _candidates(run_dir: Path) -> dict[str, Any]:
    """构造两个候选目标：累计收益与最弱实体收益。"""
    return {
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "questions": [
            {
                "question_id": "Q1",
                "objective_openness": "open",
                "candidates": [
                    {
                        "objective_id": "sum",
                        "formula": "max sum(gain_i)",
                        "expected_strategy_bias": "资源集中到最易得分实体。",
                        "problem_text_basis": "题面要求总体效果尽可能好。",
                    },
                    {
                        "objective_id": "min",
                        "formula": "max min(gain_i)",
                        "expected_strategy_bias": "资源摊向最难保障实体。",
                        "problem_text_basis": "题面要求每个实体都被覆盖。",
                    },
                ],
                "consequence_metrics": [
                    {"metric": "objective", "kind": "efficiency", "direction": "maximize"},
                    {
                        "metric": "weakest",
                        "kind": "bottleneck",
                        "direction": "maximize",
                        "acceptable_floor": 1.0,
                    },
                ],
            }
        ],
    }


def test_open_objective_cannot_freeze_a_single_formula_before_experiments(tmp_path: Path) -> None:
    """开放目标只留一个公式时，进入实验前即被拒绝。"""
    run_dir = _run(tmp_path, "single-objective")
    payload = _candidates(run_dir)
    payload["questions"][0]["candidates"] = payload["questions"][0]["candidates"][:1]

    with pytest.raises(ContractError, match="至少需要两个候选目标"):
        write_objective_candidates(run_dir, payload)


def test_consequence_metrics_must_include_a_non_efficiency_guard(tmp_path: Path) -> None:
    """只度量效率无法暴露"总量最优但个体失守"，必须被拒绝。"""
    run_dir = _run(tmp_path, "efficiency-only")
    payload = _candidates(run_dir)
    payload["questions"][0]["consequence_metrics"] = [
        {"metric": "objective", "kind": "efficiency", "direction": "maximize"}
    ]

    with pytest.raises(ContractError, match="fairness/bottleneck/safety"):
        write_objective_candidates(run_dir, payload)


def test_missing_candidate_file_blocks_entering_experiment(tmp_path: Path) -> None:
    """没有候选目标文件时不允许进入实验阶段。"""
    run_dir = _run(tmp_path, "missing-candidates")

    with pytest.raises(ContractError, match="OBJECTIVE_CANDIDATES"):
        require_objective_candidate_plan(run_dir)


def test_freezing_a_guard_breaking_objective_requires_explicit_pareto_tradeoff(
    tmp_path: Path,
) -> None:
    """冻结让瓶颈指标崩溃的目标时，必须给出显式权衡和真实 Pareto 证据。"""
    run_dir = _run(tmp_path, "guard-break")
    write_objective_candidates(run_dir, _candidates(run_dir))
    _register(run_dir, "probe-sum", objective=20.3, extra={"weakest": 0.22})
    _register(run_dir, "probe-min", objective=19.2, extra={"weakest": 4.55})
    payload = _candidates(run_dir)
    payload["questions"][0]["actual"] = {
        "candidate_probes": {"sum": "probe-sum", "min": "probe-min"},
        "frozen_objective_id": "sum",
        "freeze_rationale": "累计收益更高。",
    }

    with pytest.raises(ContractError, match="tradeoff_decision"):
        validate_objective_candidates(run_dir, payload, require_actual=True)

    payload["questions"][0]["actual"]["tradeoff_decision"] = {
        "accepted_loss": "接受最弱实体收益降到 0.22。",
        "justification": "题面明确以累计收益裁决。",
        "pareto_result_ids": ["probe-sum"],
    }
    with pytest.raises(ContractError, match="至少两点真实 Pareto 证据"):
        validate_objective_candidates(run_dir, payload, require_actual=True)

    _register(run_dir, "pareto-95", objective=19.8, extra={"weakest": 3.1})
    payload["questions"][0]["actual"]["tradeoff_decision"]["pareto_result_ids"] = [
        "probe-sum",
        "pareto-95",
    ]
    validate_objective_candidates(run_dir, payload, require_actual=True)


def test_choosing_the_guard_safe_objective_needs_no_tradeoff_paperwork(tmp_path: Path) -> None:
    """选择不牺牲瓶颈指标的目标时不额外增加合同负担。"""
    run_dir = _run(tmp_path, "guard-safe")
    _register(run_dir, "probe-sum", objective=20.3, extra={"weakest": 0.22})
    _register(run_dir, "probe-min", objective=19.2, extra={"weakest": 4.55})
    payload = _candidates(run_dir)
    payload["questions"][0]["actual"] = {
        "candidate_probes": {"sum": "probe-sum", "min": "probe-min"},
        "frozen_objective_id": "min",
        "freeze_rationale": "累计收益候选让最弱实体失守。",
    }

    validate_objective_candidates(run_dir, payload, require_actual=True)
    write_objective_candidates(run_dir, payload)

    assert frozen_objectives(run_dir) == {"Q1": "min"}


def _reconstruction(run_dir: Path, suffix: str) -> dict[str, str]:
    """构造独立题意重建回执。"""
    report_file = f"review/SEMANTIC_{suffix}.md"
    (run_dir / report_file).write_text(f"# 重建 {suffix}\n\n只读题面。\n", encoding="utf-8")
    event = persist_review_task_creation_event(
        run_dir,
        event_file=f"review/tasks/creation-events/semantic-{suffix}.json",
        raw_event={
            "schema_name": "review_task_creation_event",
            "schema_version": "1.0",
            "provider": "codex",
            "raw_task_id": f"task-{suffix}",
            "raw_thread_id": f"thread-{suffix}",
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
        prompt_sha256="b" * 64,
        input_bindings=semantic_reconstruction_input_bindings(run_dir),
        report_file=report_file,
        creation_event_file=event.relative_to(run_dir).as_posix(),
    )
    return {"task_receipt": receipt.relative_to(run_dir).as_posix(), "report_file": report_file}


def _units(run_dir: Path, *, core: bool = True) -> dict[str, Any]:
    """构造一个核心 compare 单元及其实际证据。"""
    return {
        "schema_version": "1.2",
        "run_id": run_dir.name,
        "semantic_reconstructions": [
            _reconstruction(run_dir, "A"),
            _reconstruction(run_dir, "B"),
        ],
        "research_story": {
            "central_tension": "在瓶颈约束下提高总体收益。",
            "central_mathematical_object": "统一收益向量、瓶颈指标与精确可行性判定器。",
            "question_progression": [
                {
                    "question_id": "Q1",
                    "role": "建立总体收益与瓶颈保障的统一评价口径。",
                    "upgrade": "比较异构结构路线并深化可行候选。",
                    "inherits_from": [],
                    "inherited_object": "本问首次建立收益向量和精确可行性判定器。",
                    "new_difficulty": "总体收益、瓶颈保障和硬可行性可能产生冲突。",
                    "new_mechanism": "用共同后果指标比较事件区间覆盖与逆向指派。",
                    "why_previous_insufficient": "这是基础问题，不存在可直接继承的前问模型。",
                    "answer_increment": "得到兼顾总体收益、瓶颈保障和回退条件的方案。",
                }
            ],
        },
        "units": [
            {
                "unit_id": "Q1-core",
                "question_id": "Q1",
                "core_question": core,
                "mode": "compare",
                "answer_contract": {
                    "required_output": "给出总体收益与瓶颈保障兼顾的方案。",
                    "decision_scope": "当前任务集合内的全部被保障实体。",
                    "natural_baseline": "逐步选择当前增益最大项的贪心规则。",
                    "fallback_rule": "逆向指派失败时切换到已比较的事件区间覆盖路线。",
                    "primary_endpoint": {
                        "endpoint_id": "objective",
                        "name": "objective",
                        "definition": "按冻结目标计算的精确总体收益。",
                        "exact_metric_alignment": "直接读取 production 结果的 objective。",
                    },
                    "primary_criterion": "可行且相对自然 baseline 改善达到预设阈值。",
                    "endpoint_resolution": {
                        "status": "comparison_planned",
                        "basis": "先比较总量与瓶颈目标的真实策略后果。",
                        "candidate_endpoints": [
                            {
                                "endpoint_id": "objective",
                                "definition": "按冻结目标计算的精确总体收益。",
                                "problem_text_basis": "题面要求提高总体收益。",
                            },
                            {
                                "endpoint_id": "bottleneck",
                                "definition": "最弱实体的最低收益。",
                                "problem_text_basis": "题面要求每个实体均受保障。",
                            },
                        ],
                        "decision_rule": "若合理 endpoint 导致路线翻转则返回 analysis。",
                    },
                },
                "objective": {
                    "exact_metric": "objective",
                    "direction": "maximize",
                    "significant_improvement_ratio": 0.1,
                },
                "budget": {"kind": "wall_seconds", "tolerance_ratio": 0.1},
                "baseline": {
                    "route_id": "R0",
                    "mathematical_structure": "贪心规则",
                    "natural_rationale": "逐步选择当前增益最大项，是题目最直接的可解释规则。",
                },
                "competitive_routes": [
                    {
                        "route_id": "R1",
                        "mathematical_structure": "事件区间覆盖",
                        "structure_exploited": "利用事件边界离散化连续覆盖。",
                        "expected_upside": "把总收益推高到基线之上。",
                        "expected_improvement_ratio": 0.2,
                    },
                    {
                        "route_id": "R2",
                        "mathematical_structure": "逆向指派",
                        "structure_exploited": "从瓶颈实体反推指派。",
                        "expected_upside": "改善最弱实体保障。",
                        "expected_improvement_ratio": 0.15,
                    },
                ],
                "fallback": {"route_id": "R1", "switch_condition": "逆向指派不可行时。"},
                "expected_outcome": "结构路线优于贪心。",
                "first_batch_attack": {
                    "attack": "独立小实例检查排序。",
                    "decision": "翻转则回到分析。",
                },
                "refinement": {
                    "strategy_families": ["结构精化", "独立全局搜索"],
                    "stop_reason_whitelist": ["budget_exhausted"],
                },
                "validation": {
                    "oracle": {"required": False},
                    "sensitivity": {"required": False},
                    "robustness": {"required": False},
                },
            }
        ],
    }


def _fill_actual(units: dict[str, Any], *, insights: list[dict[str, Any]] | None = None) -> None:
    """回填最小实际证据。"""
    unit = units["units"][0]
    unit["actual"] = {
        "expectation_status": "confirmed",
        "summary": "R1 在统一 exact 下最佳。",
        "comparison": {
            "route_result_ids": {"R0": "baseline", "R1": "interval", "R2": "reverse"},
            "winner_route_id": "R1",
        },
        "actual_endpoint_resolution": {
            "status": "determined",
            "selected_endpoint_id": "objective",
            "problem_text_basis": "总体收益是题面直接目标，瓶颈收益作为 guard。",
            "evidence_result_ids": ["interval"],
            "winner_route_ids": {"objective": "R1", "bottleneck": "R1"},
        },
        "qualification_evidence": {
            "endpoint_checks": [
                {
                    "result_id": "interval",
                    "metric": "endpoint_action_shift",
                    "operator": "<=",
                    "threshold": 1.0,
                }
            ],
            "guards": [
                {
                    "result_id": "interval",
                    "metric": "guard_pass_rate",
                    "operator": ">=",
                    "threshold": 0.8,
                }
            ],
            "decision_stability": [
                {
                    "result_id": "interval",
                    "metric": "max_action_shift",
                    "operator": "<=",
                    "threshold": 1.0,
                }
            ],
        },
        "first_batch_attack": {"result_ids": ["attack"], "conclusion": "排序未翻转。"},
        "refinement": {
            "first_feasible_result_id": "first",
            "final_result_id": "final",
            "family_result_ids": {"结构精化": ["interval"], "独立全局搜索": ["reverse"]},
            "stop_reason": "budget_exhausted",
        },
        "validation": {},
    }
    if insights is not None:
        unit["actual"]["insights"] = insights


def _search_results(run_dir: Path, *, search_seconds: float) -> None:
    """登记比较与深化结果，赢家路线真实超过 baseline。"""
    scores = {
        "baseline": 10.0,
        "interval": 13.0,
        "reverse": 11.6,
        "first": 10.5,
        "final": 13.0,
    }
    for result_id, objective in scores.items():
        _register(
            run_dir, result_id, objective=objective, duration_seconds=search_seconds / len(scores)
        )


def test_core_question_warns_when_verification_exceeds_search_budget(
    tmp_path: Path,
) -> None:
    """验证耗时偏高只提示资源配置，不能否决已经有效的答案。"""
    run_dir = _run(tmp_path, "budget-skew")
    units = _units(run_dir)
    write_modeling_units(run_dir, units)
    _search_results(run_dir, search_seconds=50.0)
    _register(run_dir, "attack", duration_seconds=200.0)
    _fill_actual(
        units,
        insights=[
            {
                "insight_id": "Q1-marginal",
                "kind": "marginal_gain",
                "observation": "第三个动作边际收益接近零。",
                "mechanism": "三个动作的有效窗口高度重叠。",
                "boundary": "只覆盖已测试航向区间。",
                "evidence_result_ids": ["interval", "final"],
            }
        ],
    )
    write_modeling_units(run_dir, units)

    warnings = validate_modeling_units(run_dir, units, require_actual=True)
    assert any("超过搜索与深化耗时" in warning for warning in warnings)
    require_v32_experiment_evidence(run_dir)


def test_core_question_requires_a_real_regularity_not_only_recomputation(
    tmp_path: Path,
) -> None:
    """核心问题缺少规律提炼时阻断；补上机制类规律后通过。"""
    run_dir = _run(tmp_path, "insight-missing")
    units = _units(run_dir)
    write_modeling_units(run_dir, units)
    _search_results(run_dir, search_seconds=250.0)
    _register(run_dir, "attack", duration_seconds=10.0)
    _fill_actual(units)
    write_modeling_units(run_dir, units)

    with pytest.raises(ContractError, match="必须提炼规律"):
        require_v32_experiment_evidence(run_dir)

    _fill_actual(
        units,
        insights=[
            {
                "insight_id": "Q1-active",
                "kind": "active_constraint",
                "observation": "最优解始终贴住投放间隔下界。",
                "mechanism": "间隔约束限制了窗口衔接，成为唯一活跃约束。",
                "boundary": "该结论不外推到更长时域。",
                "evidence_result_ids": ["interval", "reverse"],
            }
        ],
    )
    write_modeling_units(run_dir, units)

    require_v32_experiment_evidence(run_dir)


def test_descriptive_only_insight_does_not_satisfy_a_core_question(tmp_path: Path) -> None:
    """只有反直觉描述、没有机制或边际收益时，核心问题仍不算理解。"""
    run_dir = _run(tmp_path, "insight-shallow")
    units = _units(run_dir)
    write_modeling_units(run_dir, units)
    _search_results(run_dir, search_seconds=250.0)
    _register(run_dir, "attack", duration_seconds=10.0)
    _fill_actual(
        units,
        insights=[
            {
                "insight_id": "Q1-odd",
                "kind": "counterintuitive",
                "observation": "结果比预期低。",
                "mechanism": "尚不清楚。",
                "boundary": "未验证。",
                "evidence_result_ids": ["final"],
            }
        ],
    )
    write_modeling_units(run_dir, units)

    with pytest.raises(ContractError, match="只有描述性规律"):
        require_v32_experiment_evidence(run_dir)


def test_run_without_any_core_question_is_rejected(tmp_path: Path) -> None:
    """全部问题都不标核心时阻断，避免预算被平均分配。"""
    run_dir = _run(tmp_path, "no-core")
    units = _units(run_dir, core=False)

    with pytest.raises(ContractError, match="至少标记一个核心问题"):
        write_modeling_units(run_dir, units)


def test_core_search_low_compute_share_is_advisory(
    tmp_path: Path,
) -> None:
    """核心搜索占比低于 35% 时告警，但不能取消题面答案。"""
    run_dir = _run(tmp_path, "global-share")
    units = _units(run_dir)
    write_modeling_units(run_dir, units)
    _search_results(run_dir, search_seconds=50.0)
    _register(run_dir, "attack", duration_seconds=5.0)
    # 与核心单元无关的复算与格式稳定性实验占据绝大部分算力。
    for index in range(4):
        _register(run_dir, f"audit-{index}", duration_seconds=100.0)
    _fill_actual(
        units,
        insights=[
            {
                "insight_id": "Q1-mechanism",
                "kind": "mechanism",
                "observation": "瓶颈实体决定整体上限。",
                "mechanism": "覆盖窗口在瓶颈实体上无法叠加。",
                "boundary": "只覆盖当前参数区间。",
                "evidence_result_ids": ["reverse"],
            }
        ],
    )
    write_modeling_units(run_dir, units)

    warnings = validate_modeling_units(run_dir, units, require_actual=True)
    assert any("低于建议值 35%" in warning for warning in warnings)
    require_v32_experiment_evidence(run_dir)


def _good_insight() -> list[dict[str, Any]]:
    """返回一条满足核心问题要求的实质规律。"""
    return [
        {
            "insight_id": "Q1-mechanism",
            "kind": "mechanism",
            "observation": "瓶颈实体决定整体上限。",
            "mechanism": "覆盖窗口在瓶颈实体上无法叠加。",
            "boundary": "只覆盖当前参数区间。",
            "evidence_result_ids": ["interval"],
        }
    ]


def _ready_core_unit(run_dir: Path, *, scores: dict[str, float] | None = None) -> dict[str, Any]:
    """构造一个已完成、可通过全部检查的核心单元。"""
    units = _units(run_dir)
    write_modeling_units(run_dir, units)
    default = {
        "baseline": 10.0,
        "interval": 13.0,
        "reverse": 11.6,
        "first": 10.5,
        "final": 13.0,
    }
    for result_id, objective in (scores or default).items():
        _register(run_dir, result_id, objective=objective, duration_seconds=50.0)
    _register(run_dir, "attack", duration_seconds=5.0)
    _fill_actual(units, insights=_good_insight())
    return units


def test_weak_improvement_lowers_claim_but_keeps_feasible_answer(tmp_path: Path) -> None:
    """改善不足只能降低证据等级，不能删除题面可行答案。"""
    run_dir = _run(tmp_path, "no-improvement")
    units = _ready_core_unit(
        run_dir,
        scores={
            "baseline": 13.0,
            "interval": 13.05,
            "reverse": 11.0,
            "first": 10.5,
            "final": 13.05,
        },
    )
    write_modeling_units(run_dir, units)

    require_v32_experiment_evidence(run_dir)
    outcome = question_outcome_selections(run_dir)["Q1"]
    assert outcome["objective_answer"]["result_id"] == "final"
    assert outcome["objective_answer"]["claim_level"] == "feasible"
    assert outcome["evidence_grade"]["search_confidence"] == "weak"
    assert any("baseline" in warning for warning in outcome["warnings"])


def test_near_bound_baseline_needs_actual_bound_evidence(tmp_path: Path) -> None:
    """改善很小时可声明 baseline 已近界，但必须给出界的证据。"""
    run_dir = _run(tmp_path, "near-bound")
    units = _ready_core_unit(
        run_dir,
        scores={
            "baseline": 13.0,
            "interval": 13.05,
            "reverse": 11.0,
            "first": 10.5,
            "final": 13.05,
        },
    )
    comparison = units["units"][0]["actual"]["comparison"]
    comparison["baseline_near_bound"] = True
    write_modeling_units(run_dir, units)

    with pytest.raises(ContractError, match="near_bound_evidence"):
        require_v32_experiment_evidence(run_dir)

    comparison["near_bound_evidence"] = "线性松弛上界给出 13.1，baseline 已达 99.2%。"
    write_modeling_units(run_dir, units)

    require_v32_experiment_evidence(run_dir)


def test_declared_winner_must_match_the_measured_best_route(tmp_path: Path) -> None:
    """赢家必须由实测 exact 决定，不能由声明指定。"""
    run_dir = _run(tmp_path, "wrong-winner")
    units = _ready_core_unit(run_dir)
    units["units"][0]["actual"]["comparison"]["winner_route_id"] = "R2"
    write_modeling_units(run_dir, units)

    with pytest.raises(ContractError, match="不是实测 exact 最优路线"):
        require_v32_experiment_evidence(run_dir)


def test_final_result_may_not_regress_below_the_comparison_winner(tmp_path: Path) -> None:
    """深化后的最终结果不得比比较阶段的赢家更差。"""
    run_dir = _run(tmp_path, "final-regress")
    units = _ready_core_unit(
        run_dir,
        scores={
            "baseline": 10.0,
            "interval": 13.0,
            "reverse": 11.6,
            "first": 10.5,
            "final": 12.0,
        },
    )
    write_modeling_units(run_dir, units)

    with pytest.raises(ContractError, match="深化不能让结果退步"):
        require_v32_experiment_evidence(run_dir)


def test_core_route_requires_a_quantified_expected_upside(tmp_path: Path) -> None:
    """核心问题的预期上限必须可量化，纯文字声明事后无法对照。"""
    run_dir = _run(tmp_path, "prose-upside")
    units = _units(run_dir)
    del units["units"][0]["competitive_routes"][0]["expected_improvement_ratio"]

    with pytest.raises(ContractError, match="expected_improvement_ratio"):
        write_modeling_units(run_dir, units)


def test_upside_shortfall_must_be_registered_not_narrated_away(tmp_path: Path) -> None:
    """路线预期上限明显落空时必须显式登记原因与决定。"""
    run_dir = _run(tmp_path, "upside-shortfall")
    units = _ready_core_unit(
        run_dir,
        scores={
            "baseline": 10.0,
            "interval": 11.5,
            "reverse": 10.2,
            "first": 10.1,
            "final": 11.5,
        },
    )
    write_modeling_units(run_dir, units)

    with pytest.raises(ContractError, match="预期上限明显落空"):
        require_v32_experiment_evidence(run_dir)

    units["units"][0]["actual"]["comparison"]["upside_shortfall"] = {
        "cause": "逆向指派受瓶颈实体的可达性限制，理论增益无法实现。",
        "decision": "放弃逆向指派，把余下预算投入事件区间路线的深化。",
    }
    write_modeling_units(run_dir, units)

    require_v32_experiment_evidence(run_dir)


def test_determined_cannot_bypass_candidate_comparison_when_ambiguity_is_open(
    tmp_path: Path,
) -> None:
    """题意歧义未决时不能用 determined 跳过候选后果比较。"""
    run_dir = _run(tmp_path, "determined-bypass")
    (run_dir / "analysis").mkdir(parents=True, exist_ok=True)
    (run_dir / "analysis" / "objective-ambiguities.json").write_text(
        json.dumps(
            {
                "ambiguities": [
                    {
                        "question_id": "Q1",
                        "candidate_interpretations": ["累计收益", "最弱实体收益"],
                        "can_change_primary_result": True,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    payload = _candidates(run_dir)
    payload["questions"][0] = {
        "question_id": "Q1",
        "objective_openness": "determined",
        "determined_basis": "题面已经说清楚了。",
    }

    with pytest.raises(ContractError, match="不能声明 determined"):
        write_objective_candidates(run_dir, payload)


def test_determined_is_allowed_when_no_open_ambiguity_exists(tmp_path: Path) -> None:
    """没有未决歧义时，determined 仍是正常且低负担的路径。"""
    run_dir = _run(tmp_path, "determined-ok")
    payload = _candidates(run_dir)
    payload["questions"][0] = {
        "question_id": "Q1",
        "objective_openness": "determined",
        "determined_basis": "题面只给出唯一的总成本最小化目标。",
    }

    write_objective_candidates(run_dir, payload)

    assert frozen_objectives(run_dir) == {}


def test_exploration_audits_are_included_in_budget_advisory(tmp_path: Path) -> None:
    """预算建议的分母仍统计 exploration，但结果只告警不阻断。"""
    run_dir = _run(tmp_path, "exploration-dilution")
    units = _units(run_dir)
    write_modeling_units(run_dir, units)
    _search_results(run_dir, search_seconds=50.0)
    _register(run_dir, "attack", duration_seconds=5.0)
    for index in range(4):
        _register(
            run_dir,
            f"audit-{index}",
            duration_seconds=100.0,
            execution_mode="exploration",
        )
    _fill_actual(units, insights=_good_insight())
    write_modeling_units(run_dir, units)

    warnings = validate_modeling_units(run_dir, units, require_actual=True)
    assert any("低于建议值 35%" in warning for warning in warnings)
    require_v32_experiment_evidence(run_dir)


def _upgrade_units_to_semantic_13(
    run_dir: Path, units: dict[str, Any]
) -> dict[str, Any]:
    """把旧夹具升级为带问题差分、聚合合同和评分预检的 1.3 计划。"""
    units["schema_version"] = "1.3"
    for suffix, role in (
        ("A", "faithful_reconstruction"),
        ("B", "semantic_adversary"),
    ):
        create_review_task_receipt(
            run_dir,
            task_id=f"semantic-{suffix}",
            task_type="semantic_reconstruction",
            model_id="fixture-model",
            prompt_sha256="b" * 64,
            input_bindings=semantic_reconstruction_input_bindings(run_dir, role=role),
            report_file=f"review/SEMANTIC_{suffix}.md",
            creation_event_file=f"review/tasks/creation-events/semantic-{suffix}.json",
        )
    units["semantic_reconstructions"][0]["role"] = "faithful_reconstruction"
    units["semantic_reconstructions"][1]["role"] = "semantic_adversary"
    unit = units["units"][0]
    unit["question_delta"] = {
        "inherits_from": None,
        "added_entities": ["多个被保障实体"],
        "added_resources": [],
        "shared_resources": ["统一资源预算"],
        "changed_constraints": [],
        "semantic_risk_signals": [
            "multiple_entities",
            "objective_form_ambiguity",
        ],
        "possible_objective_change": "总体收益可能是求和，也可能要求最弱实体同时达标。",
        "must_recheck_aggregation": True,
    }
    endpoint = unit["answer_contract"]["primary_endpoint"]
    endpoint["formula"] = "max F(S_1, ..., S_n)"
    endpoint["aggregation"] = {
        "atomic_success": "单个评价点满足事先声明的成功判据。",
        "within_entity": "同一实体内部按全部评价点共同达标聚合。",
        "across_resources": "多个资源按至少一个资源成功的并集聚合。",
        "across_entities": "多个被保障实体按正式目标指定的算子聚合。",
        "temporal": "对满足整体成功事件的时间集合计算测度。",
        "quantifier_order": "先固定时刻和实体，再检查评价点与可用资源。",
    }
    unit["answer_contract"]["semantic_counterexample"] = {
        "case_a": "方案 A 的各实体成功时间完全错开但累计时间较高。",
        "case_b": "方案 B 的各实体在同一时间段共同成功但累计较低。",
        "expected_preference": "若题意要求共同保障，应优先选择方案 B。",
        "candidate_rankings": {"sum": "A>B", "min": "B>A"},
    }
    unit["answer_contract"]["semantic_scorer_preflight"] = {
        "cases": [
            {
                "case_id": "simultaneous",
                "construction": "所有主体在同一窗口共同满足成功事件。",
                "expected_ranking": "应高于累计相近但完全错开的方案。",
                "rationale": "该案例检查主体间共同满足的聚合语义。",
            },
            {
                "case_id": "staggered",
                "construction": "每个主体分别满足但成功时间窗口完全错开。",
                "expected_ranking": "共同保障分数应为零或低于同步方案。",
                "rationale": "该案例区分时间求和与共同时间集合。",
            },
            {
                "case_id": "zero_bottleneck",
                "construction": "一个主体长期成功而另一个主体始终失败。",
                "expected_ranking": "共同保障或瓶颈目标不得给出高分。",
                "rationale": "该案例检查总量是否掩盖最弱主体失守。",
            },
        ],
        "pass_criterion": "三个案例的实际 scorer 排序必须与人工预期完全一致。",
    }
    for route in [unit["baseline"], *unit["competitive_routes"]]:
        route["composition"] = {
            "mode": "joint",
            "joint_rationale": "路线直接在统一目标与共享约束下评价完整方案。",
        }
    return units


def test_semantic_13_requires_asymmetric_reconstruction_roles(tmp_path: Path) -> None:
    """两个同质 fresh thread 不能冒充相关性较低的题意复核。"""
    run_dir = _run(tmp_path, "semantic-roles")
    units = _upgrade_units_to_semantic_13(run_dir, _units(run_dir))
    units["semantic_reconstructions"][1]["role"] = "faithful_reconstruction"
    create_review_task_receipt(
        run_dir,
        task_id="semantic-B",
        task_type="semantic_reconstruction",
        model_id="fixture-model",
        prompt_sha256="b" * 64,
        input_bindings=semantic_reconstruction_input_bindings(
            run_dir, role="faithful_reconstruction"
        ),
        report_file="review/SEMANTIC_B.md",
        creation_event_file="review/tasks/creation-events/semantic-B.json",
    )

    with pytest.raises(ContractError, match="忠实重建与语义攻击"):
        write_modeling_units(run_dir, units)


def test_semantic_13_decomposition_requires_declared_risk_and_joint_followup(
    tmp_path: Path,
) -> None:
    """分解后组合必须被识别为语义风险，并继续接受联合 scorer。"""
    run_dir = _run(tmp_path, "decomposition-contract")
    units = _upgrade_units_to_semantic_13(run_dir, _units(run_dir))
    route = units["units"][0]["competitive_routes"][0]
    route["composition"] = {
        "mode": "heuristic_decomposition",
        "joint_scorer_followup": "分解结果只作初值，继续在联合目标下改进。",
    }

    with pytest.raises(ContractError, match="decompose_then_combine"):
        write_modeling_units(run_dir, units)

    units["units"][0]["question_delta"]["semantic_risk_signals"].append(
        "decompose_then_combine"
    )
    write_modeling_units(run_dir, units)


def test_objective_11_filters_illegal_candidate_before_consequence_experiments(
    tmp_path: Path,
) -> None:
    """题意不符的目标先淘汰，不因数值漂亮进入真实后果实验。"""
    run_dir = _run(tmp_path, "legality-first")
    write_modeling_units(run_dir, _upgrade_units_to_semantic_13(run_dir, _units(run_dir)))
    payload = _candidates(run_dir)
    payload["schema_version"] = "1.1"
    for candidate in payload["questions"][0]["candidates"]:
        candidate.update(
            {
                "source_language": "题面要求总体效果并明确所有实体均受保障。",
                "preserved_quantifiers": "保留时间、实体与成功事件的量词次序。",
                "altered_quantifiers": "没有改变题面原有的量词次序。",
                "introduced_preferences": "没有引入题面之外的价值偏好。",
                "convenience_only": False,
            }
        )
    payload["questions"][0]["candidates"][0]["support_level"] = "direct"
    payload["questions"][0]["candidates"][1]["support_level"] = "incompatible"
    payload["questions"][0]["actual"] = {
        "candidate_probes": {},
        "frozen_objective_id": "sum",
        "freeze_rationale": "另一个目标改变题面量词，正式目标由题面直接支持。",
    }

    validate_objective_candidates(run_dir, payload, require_actual=True)


def test_semantic_scorer_preflight_must_precede_route_search(tmp_path: Path) -> None:
    """高风险核心问题必须先证明 scorer 排序正确，再比较优化路线。"""
    run_dir = _run(tmp_path, "scorer-first")
    units = _upgrade_units_to_semantic_13(run_dir, _units(run_dir))
    write_modeling_units(run_dir, units)
    _register(
        run_dir,
        "semantic-preflight",
        duration_seconds=1.0,
        extra={"semantic_case_count": 3.0, "semantic_case_pass_rate": 1.0},
        output_extra={
            "semantic_cases": [
                {
                    "case_id": "simultaneous",
                    "expected_ranking": "应高于累计相近但完全错开的方案。",
                    "actual_ranking": "应高于累计相近但完全错开的方案。",
                    "passed": True,
                },
                {
                    "case_id": "staggered",
                    "expected_ranking": "共同保障分数应为零或低于同步方案。",
                    "actual_ranking": "共同保障分数应为零或低于同步方案。",
                    "passed": True,
                },
                {
                    "case_id": "zero_bottleneck",
                    "expected_ranking": "共同保障或瓶颈目标不得给出高分。",
                    "actual_ranking": "共同保障或瓶颈目标不得给出高分。",
                    "passed": True,
                },
            ]
        },
    )
    _search_results(run_dir, search_seconds=250.0)
    _register(run_dir, "attack", duration_seconds=5.0)
    _fill_actual(
        units,
        insights=[
            {
                "insight_id": "Q1-joint",
                "kind": "mechanism",
                "observation": "联合评价避免累计高但最弱主体为零的方案晋级。",
                "mechanism": "主体间聚合在每个时刻先于时间测度执行。",
                "boundary": "只适用于当前题面声明的共同保障口径。",
                "evidence_result_ids": ["interval", "final"],
            }
        ],
    )
    units["units"][0]["actual"]["semantic_scorer_preflight_result_id"] = (
        "semantic-preflight"
    )
    write_modeling_units(run_dir, units)

    require_v32_experiment_evidence(run_dir)


def test_high_risk_scientific_challenge_must_attack_semantics_first(
    tmp_path: Path,
) -> None:
    """高风险问题的科学挑战不能绕去优先攻击容易量化的搜索细节。"""
    run_dir = _run(tmp_path, "semantic-first-challenge")
    write_modeling_units(run_dir, _upgrade_units_to_semantic_13(run_dir, _units(run_dir)))
    _register(run_dir, "challenge-result", objective=12.0)

    with pytest.raises(ContractError, match="第一攻击必须针对语义"):
        record_scientific_challenge_evidence(
            run_dir,
            result_ids=["challenge-result"],
            attack_description="检查搜索器是否在固定预算下充分收敛。",
            stage_a_semantic_assessment={
                "priority": "model_or_search",
                "reason": "当前先检查搜索器的数值收敛与预算敏感性。",
            },
        )

    receipt = record_scientific_challenge_evidence(
        run_dir,
        result_ids=["challenge-result"],
        attack_description="先用错开满足与同步满足反例攻击当前主体间聚合。",
        stage_a_semantic_assessment={
            "priority": "semantics_or_decomposition",
            "reason": "本问包含多主体和共享资源，目标聚合错误会让全部搜索失去意义。",
            "counterexample": {
                "question_id": "Q1",
                "case_a": "各主体成功窗口完全错开，但累计成功时间更高。",
                "case_b": "各主体在同一窗口共同成功，但累计成功时间较低。",
                "expected_preference": "共同保障题意应选择同步成功的方案 B。",
            },
        },
    )

    assert receipt["schema_version"] == "1.4"
