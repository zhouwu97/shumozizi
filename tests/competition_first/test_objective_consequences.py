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
    require_v32_experiment_evidence,
    semantic_reconstruction_input_bindings,
    write_modeling_units,
)
from shumozizi.simple.objective_consequences import (
    frozen_objectives,
    require_objective_candidate_plan,
    validate_objective_candidates,
    write_objective_candidates,
)
from shumozizi.simple.results import register_result
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
        json.dumps({"metrics": metrics}), encoding="utf-8"
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


def test_core_question_rejects_verification_budget_exceeding_search_budget(
    tmp_path: Path,
) -> None:
    """核心问题的验证耗时超过搜索耗时时阻断，逼迫先继续搜索。"""
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

    with pytest.raises(ContractError, match="已超过搜索与深化耗时"):
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


def test_core_search_must_hold_a_minimum_share_of_production_compute(
    tmp_path: Path,
) -> None:
    """核心搜索占全局生产算力过低时阻断，即使单元内部比例合格。"""
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

    with pytest.raises(ContractError, match="低于要求的"):
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


def test_result_worse_than_baseline_cannot_reach_the_paper(tmp_path: Path) -> None:
    """赢家没有真正超过 baseline 时阻断——这是搜索强度的下限。"""
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

    with pytest.raises(ContractError, match="search_insufficient.*experiment"):
        require_v32_experiment_evidence(run_dir)


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


def test_exploration_audits_cannot_dilute_the_core_budget_share(tmp_path: Path) -> None:
    """把复算跑成 exploration 不能稀释核心搜索份额检查。"""
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

    with pytest.raises(ContractError, match="低于要求的"):
        require_v32_experiment_evidence(run_dir)
