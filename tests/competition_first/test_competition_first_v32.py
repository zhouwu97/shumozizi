"""验证 Competition-First v3.2 的轻量建模单元和 LaTeX 主链。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from openpyxl import Workbook

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.knowledge.retrieval import write_analysis_knowledge_retrieval
from shumozizi.paper.readiness import check_paper_readiness
from shumozizi.paper.templates import select_paper_template
from shumozizi.simple import review as simple_review
from shumozizi.simple.competition import verify_submission_exports, write_answer_map
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.modeling_units import (
    first_feasible_checkpoint_prompt,
    question_outcome_selections,
    require_v32_experiment_evidence,
    require_v32_modeling_plan,
    semantic_reconstruction_input_bindings,
    validate_visual_output_sources,
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


def _record_fixture_knowledge_retrieval(run_dir: Path) -> None:
    """让不评估知识匹配质量的主链夹具显式完成检索尝试。"""
    write_analysis_knowledge_retrieval(
        run_dir,
        None,
        {
            "problem_type": "测试用优化问题",
            "data_structure": "测试构造数据",
            "task_types": ["路线比较"],
        },
        unavailable_reason="该主链测试夹具不装载真实论文卡索引，仅验证阶段合同。",
    )


def _fixture_capability_decision(run_dir: Path) -> dict[str, object]:
    """写入真实探测记录形状，并返回与其哈希绑定的 Python 选择。"""
    tooling = {
        "schema_version": "1.1",
        "checked_at": utc_now(),
        "engines": [
            {
                "engine": "python",
                "available": True,
                "command": "python",
                "probe": {
                    "command": ["python", "--version"],
                    "exit_code": 0,
                    "timed_out": False,
                    "stdout_sha256": "a" * 64,
                    "stderr_sha256": "b" * 64,
                    "summary": "Python available",
                },
            },
            {
                "engine": "matlab",
                "available": False,
                "command": None,
                "probe": None,
            },
            {
                "engine": "octave",
                "available": False,
                "command": None,
                "probe": None,
            },
        ],
    }
    tooling_path = run_dir / "state/tooling.json"
    atomic_json(tooling_path, tooling)
    return {
        "python_considered": True,
        "matlab_considered": True,
        "matlab_availability": "unavailable",
        "tooling_sha256": sha256_file(tooling_path),
        "selected_engine": "python",
        "matlab_role": None,
        "probe_waiver": None,
        "reason": "真实探测未发现 MATLAB 或 Octave，因此当前使用 Python 实现。",
        "expected_gain": "若后续环境可用，异构数值实现可用于攻击同源误差。",
    }


def _paper_blind_report(required_questions: list[str]) -> str:
    """构造自由报告与同源结构化结果并存的盲评夹具。"""
    structured = {
        "cold_read": {
            "input_scope": "frozen_pdf_only",
            "direct_answers_found_within_3_minutes": {
                question_id: True for question_id in required_questions
            },
            "one_sentence_contribution": "论文用统一数学对象给出逐问可定位的直接答案。",
            "cross_question_inheritance_understood": True,
            "first_five_pages_establish_data_intuition": True,
            "hero_figures_identified": {
                question_id: True for question_id in required_questions
            },
            "report_like_pages": [],
        },
        "structure": {
            field: "pass"
            for field in (
                "problem_restatement",
                "problem_analysis",
                "assumptions",
                "symbols_and_data",
                "four_questions",
                "model_evaluation",
            )
        },
        "argument_findings": {
            question_id: {
                "missing_roles": [],
                "pages": [1],
                "finding": f"{question_id} 的数学对象、推导、结果、机制与验证均可在第一页定位。",
            }
            for question_id in required_questions
        },
        "question_progression": {
            "status": "pass",
            "interchangeable_questions": False,
            "links": [
                {
                    "from": previous,
                    "to": current,
                    "inheritance": "后问继承前问的数学对象并增加新的决策约束。",
                }
                for previous, current in zip(
                    required_questions, required_questions[1:], strict=False
                )
            ],
            "summary": "各问按照共享数学对象和新增约束形成不可任意交换的递进链。",
        },
        "narrative_risks": [],
        "review_summary": "独立盲评未发现阻断问题，逐问论证、直接答案与递进关系均可定位。",
    }
    return (
        "# PDF 全面盲审\n\n本轮未确认 P0/P1。\n\n"
        "## 结构化盲评结果\n```json\n"
        + json.dumps(structured, ensure_ascii=False, indent=2)
        + "\n```\n"
    )


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
        "hard_constraints_passed": True,
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


def _semantic_reconstruction(
    run_dir: Path, suffix: str, role: str | None = None
) -> dict[str, str]:
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
    bindings = semantic_reconstruction_input_bindings(run_dir, role=role)
    receipt = create_review_task_receipt(
        run_dir,
        task_id=f"semantic-{suffix}",
        task_type="semantic_reconstruction",
        model_id="fixture-model",
        prompt_sha256="a" * 64,
        input_bindings=bindings,
        report_file=report_file,
        creation_event_file=event.relative_to(run_dir).as_posix(),
    )
    result = {
        "task_receipt": receipt.relative_to(run_dir).as_posix(),
        "report_file": report_file,
    }
    if role is not None:
        result["role"] = role
    return result


def _v14_non_search_plan(run_dir: Path, unit_kind: str) -> dict[str, object]:
    """构造评价或 exact-oracle 单元，证明非搜索题型不被路线门绑架。"""
    unit: dict[str, object] = {
        "unit_id": f"Q1-{unit_kind}",
        "question_id": "Q1",
        "core_question": True,
        "unit_kind": unit_kind,
        "question_delta": {
            "inherits_from": None,
            "added_entities": [],
            "added_resources": [],
            "shared_resources": [],
            "changed_constraints": [],
            "semantic_risk_signals": [],
            "possible_objective_change": "本问直接按题面给定指标计算，不改变目标聚合。",
            "must_recheck_aggregation": False,
        },
        "answer_contract": {
            "required_output": "给出题面指标的精确计算值与可行结论。",
            "decision_scope": "当前题面规定的全部对象和时间范围。",
            "natural_baseline": "按定义直接计算的手工核对值。",
            "fallback_rule": "只有独立复算冲突时返回模型检查。",
            "primary_endpoint": {
                "endpoint_id": "objective",
                "name": "题面精确指标",
                "definition": "对全部题面对象按给定口径计算的总指标。",
                "formula": "J=sum_i value_i",
                "aggregation": {
                    "atomic_success": "单个对象的指标按题面定义计算。",
                    "within_entity": "对象内部先完成全部组成项求和。",
                    "across_resources": "资源维度按题面指定权重聚合。",
                    "across_entities": "全部对象的指标再执行总体求和。",
                    "temporal": "时间维度覆盖题面给定完整区间。",
                    "quantifier_order": "先对每个对象计算，再对全部对象求和。",
                },
                "exact_metric_alignment": "与生产结果 objective 字段完全一致。",
            },
            "primary_criterion": "结果可行、endpoint 已确定且 exact 指标可复验。",
            "endpoint_resolution": {
                "status": "determined",
                "basis": "题面直接给出评价定义，不存在合理的替代聚合。",
            },
        },
        "objective": {"exact_metric": "objective", "direction": "minimize"},
        "expected_outcome": "主方法给出可行且可由独立计算复验的直接答案。",
        "validation": {
            "oracle": {"required": False},
            "sensitivity": {"required": False},
            "robustness": {"required": False},
        },
    }
    if unit_kind == "exact_oracle":
        unit["capability_decision"] = _fixture_capability_decision(run_dir)
        unit["oracle"] = {
            "oracle_kind": "独立枚举积分算法",
            "independence": "独立实现且不复用主计算的区间构造代码。",
            "agreement": {
                "metric": "objective",
                "absolute_tolerance": 1e-6,
                "relative_tolerance": 1e-6,
                "interval_structure_must_match": True,
                "structure_metric": "interval_count",
            },
        }
    else:
        unit["primary_method"] = {
            "method_id": "direct-evaluation",
            "mathematical_structure": "固定方案上的确定性评价计算。",
        }
        unit["natural_comparison"] = "与按定义直接计算的手工核对值比较。"
        if unit_kind == "evaluation":
            unit["fixed_inputs"] = ["题面给定方案", "题面给定参数"]
            unit["endpoint_refinement"] = "连续端点细化直到指标变化低于预设容差。"
        elif unit_kind == "data_modeling":
            unit["data_contract"] = {
                "observational_unit": "以题面定义的独立实体作为统计单位。",
                "split_or_validation": "按实体分组完成训练验证隔离。",
                "diagnostic_plan": "检查残差、异常值与关键假设偏离。",
            }
        elif unit_kind == "simulation":
            unit["capability_decision"] = _fixture_capability_decision(run_dir)
            unit["simulation_contract"] = {
                "calibration": "使用题面基准情形校准仿真参数。",
                "convergence": "逐级细化时间步长并检查输出收敛。",
                "sensitivity": "按预登记范围扰动关键参数并记录结论边界。",
            }
    return {
        "schema_version": "1.4",
        "run_id": run_dir.name,
        "semantic_reconstructions": [
            _semantic_reconstruction(run_dir, "faithful", "faithful_reconstruction"),
        ],
        "research_story": {
            "central_tension": "在保持题面评价口径的前提下给出可复验直接答案。",
            "central_mathematical_object": "统一评价指标及其跨对象聚合算子。",
            "question_progression": [
                {
                    "question_id": "Q1",
                    "role": "建立固定方案的统一评价口径。",
                    "upgrade": "用独立实现检查数值和区间结构。",
                    "inherits_from": [],
                    "inherited_object": "本问首次建立统一评价指标。",
                    "new_difficulty": "需要区分数值一致与结构一致。",
                    "new_mechanism": "独立计算直接核对题面指标。",
                    "why_previous_insufficient": "当前是首问，没有可继承计算。",
                    "answer_increment": "给出可定位的题面直接答案。",
                }
            ],
        },
        "units": [unit],
    }


def _v14_optimization_plan(run_dir: Path) -> dict[str, object]:
    """构造只含一条结构 challenger 的 v1.4 优化合同。"""
    plan = _v14_non_search_plan(run_dir, "evaluation")
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    unit["unit_kind"] = "optimization"
    unit["capability_decision"] = _fixture_capability_decision(run_dir)
    unit.pop("primary_method")
    unit["objective"] = {
        "exact_metric": "objective",
        "direction": "minimize",
        "significant_improvement_ratio": 0.1,
    }
    unit["budget"] = {"kind": "wall_seconds", "tolerance_ratio": 0.1}
    unit["baseline"] = {
        "route_id": "R0",
        "mathematical_structure": "题面规则构造",
        "natural_rationale": "不使用复杂搜索即可得到的自然可行参照。",
        "composition": {
            "mode": "joint",
            "joint_rationale": "直接在统一 scorer 上评价完整联合方案。",
        },
    }
    unit["competitive_routes"] = [
        {
            "route_id": "R1",
            "mathematical_structure": "约束规划与精确剪枝",
            "structure_exploited": "利用约束传播缩小联合可行域。",
            "expected_upside": "预计相对自然基线改善至少百分之十五。",
            "expected_improvement_ratio": 0.15,
            "composition": {
                "mode": "joint",
                "joint_rationale": "候选路线始终由统一联合 scorer 评价。",
            },
        }
    ]
    unit["first_batch_attack"] = {
        "attack": "用独立小实例攻击可行性和路线排序。",
        "decision": "发现冲突时返回分析修正目标或约束。",
    }
    unit["refinement"] = {
        "strategy_families": ["约束结构深化"],
        "stop_reason_whitelist": ["budget_exhausted", "verified_stagnation"],
    }
    unit["search_repetition"] = {
        "planned_repeats": 1,
        "instability_action": "若单次结果明显不稳定则增加独立随机种子并继续搜索。",
    }
    return plan


def test_visual_outputs_reject_paths_outside_results_raw(tmp_path: Path) -> None:
    """绘图中间数据必须留在运行目录的可追溯 raw 区域。"""
    run_dir = initialize_simple_run(
        tmp_path, "visual-output-path", workflow_version="3.2", required_questions=["Q1"]
    )
    plan = _v14_non_search_plan(run_dir, "evaluation")
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    unit["visual_outputs"] = [
        {
            "visual_question": "统一评价指标如何由各对象的组成项逐层聚合形成？",
            "argument_unit_id": "Q1-aggregation",
            "required_data": ["entities", "aggregate"],
            "output_path": "../outside.json",
        }
    ]

    with pytest.raises(ContractError, match="运行目录内的相对路径"):
        write_modeling_units(run_dir, plan)


def test_data_rich_unit_requires_visual_output_contract_before_experiment(
    tmp_path: Path,
) -> None:
    """数据建模不能等到论文阶段才决定保存哪些结构化绘图数据。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "visual-output-before-experiment",
        workflow_version="3.2",
        required_questions=["Q1"],
    )
    plan = _v14_non_search_plan(run_dir, "data_modeling")
    _record_fixture_knowledge_retrieval(run_dir)
    write_modeling_units(run_dir, plan)

    with pytest.raises(ContractError, match="进入实验前.*visual_outputs"):
        require_v32_modeling_plan(run_dir)


def test_figure_plan_24_requires_declared_structured_visual_data(tmp_path: Path) -> None:
    """数据型论证图不能等到论文阶段再从最终标量猜造结构。"""
    run_dir = initialize_simple_run(
        tmp_path, "visual-output-binding", workflow_version="3.2", required_questions=["Q1"]
    )
    plan = _v14_non_search_plan(run_dir, "evaluation")
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    unit["visual_outputs"] = [
        {
            "visual_question": "统一评价指标如何由各对象的组成项逐层聚合形成？",
            "argument_unit_id": "Q1-aggregation",
            "required_data": ["entities", "aggregate"],
            "output_path": "results/raw/q1_aggregation.json",
        }
    ]
    write_modeling_units(run_dir, plan)
    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "schema_name": "figure_plan",
            "schema_version": "2.4",
            "run_id": run_dir.name,
            "figures": [
                {
                    "figure_id": "q1-aggregation",
                    "required": True,
                    "argument_unit_ids": ["Q1-aggregation"],
                    "obligation_types": ["mechanism", "decision"],
                    "source_files": ["results/raw/q1_aggregation.json"],
                }
            ],
        },
    )

    errors = validate_visual_output_sources(run_dir)
    assert any("结构化绘图数据无效" in item for item in errors)

    atomic_json(
        run_dir / "results/raw/q1_aggregation.json",
        {"entities": [{"id": 1}], "aggregate": 1.0},
    )
    assert validate_visual_output_sources(run_dir) == []


def test_visual_output_source_checks_required_fields(tmp_path: Path) -> None:
    """已存在的 JSON 仍必须包含事前声明的绘图字段。"""
    run_dir = initialize_simple_run(
        tmp_path, "visual-output-fields", workflow_version="3.2", required_questions=["Q1"]
    )
    plan = _v14_non_search_plan(run_dir, "evaluation")
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    unit["visual_outputs"] = [
        {
            "visual_question": "统一评价指标如何由各对象的组成项逐层聚合形成？",
            "argument_unit_id": "Q1-aggregation",
            "required_data": ["entities", "aggregate"],
            "output_path": "results/raw/q1_aggregation.json",
        }
    ]
    write_modeling_units(run_dir, plan)
    atomic_json(run_dir / "results/raw/q1_aggregation.json", {"entities": []})
    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "schema_name": "figure_plan",
            "schema_version": "2.4",
            "run_id": run_dir.name,
            "figures": [
                {
                    "figure_id": "q1-aggregation",
                    "required": True,
                    "argument_unit_ids": ["Q1-aggregation"],
                    "obligation_types": ["mechanism"],
                    "source_files": ["results/raw/q1_aggregation.json"],
                }
            ],
        },
    )

    assert validate_visual_output_sources(run_dir) == [
        "必需图 q1-aggregation 的 results/raw/q1_aggregation.json 缺少绘图字段: aggregate"
    ]


def _attach_v14_optimization_actual(
    plan: dict[str, object], *, search_health: dict[str, object] | None = None
) -> None:
    """给 v1.4 优化合同附上单 challenger 的真实结果映射。"""
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    actual: dict[str, object] = {
        "expectation_status": "confirmed",
        "summary": "结构 challenger 在统一 exact scorer 下优于自然基线。",
        "comparison": {
            "route_result_ids": {"R0": "baseline", "R1": "challenger"},
            "winner_route_id": "R1",
        },
        "actual_endpoint_resolution": {
            "status": "determined",
            "selected_endpoint_id": "objective",
            "problem_text_basis": "题面直接要求总指标最小。",
            "evidence_result_ids": ["check"],
            "winner_route_ids": {"objective": "R1"},
        },
        "qualification_evidence": {
            "endpoint_checks": [
                {
                    "result_id": "check",
                    "metric": "endpoint_action_shift",
                    "operator": "<=",
                    "threshold": 1.0,
                }
            ],
            "guards": [
                {
                    "result_id": "check",
                    "metric": "guard_pass_rate",
                    "operator": ">=",
                    "threshold": 0.8,
                }
            ],
            "decision_stability": [
                {
                    "result_id": "check",
                    "metric": "max_action_shift",
                    "operator": "<=",
                    "threshold": 1.0,
                }
            ],
        },
        "first_batch_attack": {
            "result_ids": ["attack"],
            "conclusion": "独立小实例未发现可行性或排序冲突。",
        },
        "refinement": {
            "first_feasible_result_id": "first-feasible",
            "first_feasible_checkpoint": {
                "reviewed_result_id": "first-feasible",
                "review_mode": "independent_ai",
                "independent_context": True,
                "reviewer_context_id": "fixture-first-feasible-review",
                "highest_risks": [
                    "共享约束的边界处理可能让首解在临界点失去可行性。"
                ],
                "reversal_assumption": "若资源不能在相邻时间段复用，当前路线排序可能反转。",
                "stronger_route_worth_testing": True,
                "stronger_route": "测试显式传播共享约束的联合搜索路线。",
                "next_discriminating_experiment": "构造资源恰好饱和的小实例并比较两条路线的 exact 排序。",
                "followup_result_ids": ["checkpoint-probe"],
                "followup_conclusion": "边界小实例仍支持结构 challenger，未发现排序反转。",
                "decision": "continue_experiment",
            },
            "final_result_id": "final",
            "family_result_ids": {"约束结构深化": ["challenger", "final"]},
            "stop_reason": "budget_exhausted",
        },
        "validation": {},
        "insights": [
            {
                "insight_id": "Q1-constraint",
                "kind": "active_constraint",
                "observation": "最终方案由两类共享约束共同限制。",
                "mechanism": "约束传播提前删除了不可能改善的分支。",
                "boundary": "仅覆盖当前题面规模和预算。",
                "evidence_result_ids": ["challenger", "final"],
            }
        ],
    }
    if search_health is not None:
        actual["search_health"] = search_health
    unit["actual"] = actual


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
            "central_mathematical_object": "统一可行域、精确评分器与候选方案状态。",
            "question_progression": [
                {
                    "question_id": "Q1",
                    "role": "建立可复验的基线与统一评价口径。",
                    "upgrade": "用结构不同的路线比较并在首解后继续深化。",
                    "inherits_from": [],
                    "inherited_object": "本问首次建立统一可行域和精确评分器。",
                    "new_difficulty": "需要同时处理硬约束、路线异构性和有限搜索预算。",
                    "new_mechanism": "以统一精确评分器比较异构路线并约束晋级。",
                    "why_previous_insufficient": "这是基础问题，不存在可直接复用的前问模型。",
                    "answer_increment": "形成可执行主答案、量化改进和已验证回退方案。",
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
    _record_fixture_knowledge_retrieval(run_dir)
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


def test_modeling_units_can_add_route_after_delivery_cutoff(tmp_path: Path) -> None:
    """时间截止只调度优先级，不再替代科学判断冻结候选路线。"""
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

    assert write_modeling_units(run_dir, plan)["units"][0]["competitive_routes"][-1][
        "route_id"
    ] == "R3"


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


def test_v32_failed_stability_warns_without_replacing_objective_answer(tmp_path: Path) -> None:
    """扰动不稳定降低证据等级，但不能替换题面原目标答案。"""
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

    require_v32_experiment_evidence(run_dir)
    outcome = question_outcome_selections(run_dir)["Q1"]
    assert outcome["objective_answer"]["result_id"] == "final"
    assert outcome["evidence_grade"]["perturbation_stability"] == "weak"
    assert any("扰动敏感" in warning for warning in outcome["warnings"])


@pytest.mark.parametrize("unit_kind", ["evaluation", "data_modeling", "simulation"])
def test_v14_non_search_unit_needs_no_competitive_routes(
    tmp_path: Path, unit_kind: str
) -> None:
    """评价、数据建模和仿真按主方法合同验收，不伪造优化路线赛马。"""
    run_dir = initialize_simple_run(
        tmp_path,
        f"v14-{unit_kind}",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    _register_result(run_dir, "primary", objective=4.0)
    plan = _v14_non_search_plan(run_dir, unit_kind)
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    unit["actual"] = {
        "expectation_status": "confirmed",
        "summary": "主方法完成题面评价并得到可复验的可行结果。",
        "primary_result_id": "primary",
        "validation": {},
        "insights": [
            {
                "insight_id": "Q1-mechanism",
                "kind": "mechanism",
                "observation": "全部组成项均按统一口径进入总指标。",
                "mechanism": "先实体内后实体间聚合避免重复计数。",
                "boundary": "结论仅覆盖当前题面给定数据范围。",
                "evidence_result_ids": ["primary"],
            }
        ],
    }
    write_modeling_units(run_dir, plan)

    require_v32_experiment_evidence(run_dir)
    outcome = question_outcome_selections(run_dir)["Q1"]
    assert outcome["objective_answer"]["result_id"] == "primary"
    assert outcome["evidence_grade"]["search_confidence"] == "not_applicable"


def test_v14_low_semantic_risk_needs_only_local_faithful_reconstruction(
    tmp_path: Path,
) -> None:
    """低风险题只需一份忠实语义结论，线程回执仅作独立性记录。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v14-low-semantic-risk",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    plan = _v14_non_search_plan(run_dir, "evaluation")
    faithful = plan["semantic_reconstructions"][0]
    assert isinstance(faithful, dict)
    faithful.pop("task_receipt")
    plan["semantic_reconstructions"] = [faithful]

    write_modeling_units(run_dir, plan)


def test_v14_high_semantic_risk_requires_adversary_and_counterexample(
    tmp_path: Path,
) -> None:
    """高风险题必须增加语义攻击，并用最小反例闭合聚合歧义。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v14-high-semantic-risk",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    plan = _v14_non_search_plan(run_dir, "evaluation")
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    delta = unit["question_delta"]
    assert isinstance(delta, dict)
    delta["must_recheck_aggregation"] = True
    plan["semantic_reconstructions"] = [plan["semantic_reconstructions"][0]]

    with pytest.raises(ContractError, match="semantic_adversary"):
        write_modeling_units(run_dir, plan)

    plan["semantic_reconstructions"].append(
        _semantic_reconstruction(run_dir, "risk-adversary", "semantic_adversary")
    )
    with pytest.raises(ContractError, match="semantic_counterexample"):
        write_modeling_units(run_dir, plan)


def test_v14_exact_oracle_checks_metric_and_interval_structure(tmp_path: Path) -> None:
    """exact oracle 同时核对指标容差和区间结构，而非仅比较成功布尔值。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v14-exact-oracle",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    _register_result(
        run_dir,
        "primary",
        objective=4.0,
        extra_metrics={"interval_count": 3.0},
    )
    _register_result(
        run_dir,
        "oracle",
        objective=4.0,
        extra_metrics={"interval_count": 3.0},
    )
    plan = _v14_non_search_plan(run_dir, "exact_oracle")
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    unit["actual"] = {
        "expectation_status": "confirmed",
        "summary": "独立 oracle 与主计算在数值和区间结构上完全一致。",
        "primary_result_id": "primary",
        "oracle_result_id": "oracle",
        "validation": {},
        "insights": [
            {
                "insight_id": "Q1-active",
                "kind": "active_constraint",
                "observation": "三个有效区间共同构成最终评价集合。",
                "mechanism": "区间端点由同一组活跃约束决定。",
                "boundary": "只覆盖当前参数与时间区间。",
                "evidence_result_ids": ["primary", "oracle"],
            }
        ],
    }
    write_modeling_units(run_dir, plan)
    require_v32_experiment_evidence(run_dir)

    # 数值一致但区间数量不一致仍是正式冲突。
    index = load_json(run_dir / "results/index.json")
    oracle = next(item for item in index["results"] if item["result_id"] == "oracle")
    oracle["metrics"]["interval_count"] = 4.0
    atomic_json(run_dir / "results/index.json", index)
    with pytest.raises(ContractError, match="区间结构冲突"):
        require_v32_experiment_evidence(run_dir)

    oracle["metrics"]["interval_count"] = 3.0
    oracle["metrics"]["objective"] = 5.0
    atomic_json(run_dir / "results/index.json", index)
    with pytest.raises(ContractError, match="正式指标冲突"):
        require_v32_experiment_evidence(run_dir)


def test_legacy_oracle_only_is_viewable_but_cannot_become_formal_answer(
    tmp_path: Path,
) -> None:
    """旧 oracle-only 缺少 agreement 时只能读取，不能伪装 verified 进入论文。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "legacy-oracle-only",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    _register_result(run_dir, "final", objective=9.184696)
    plan = _plan(run_dir)
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    unit["mode"] = "oracle_only"
    unit["oracle"] = {
        "oracle_kind": "独立解析复算",
        "independence": "不复用主求解器实现。",
    }
    _actual(plan)
    atomic_json(run_dir / "analysis/MODELING_UNITS.json", plan)

    outcome = question_outcome_selections(run_dir)["Q1"]

    assert outcome["objective_answer"]["claim_level"] == "legacy_unverified"
    assert outcome["evidence_grade"]["verification_status"] == "legacy_unverified"
    with pytest.raises(ContractError, match="迁移.*1.4"):
        write_answer_map(
            run_dir,
            {
                "Q1": {
                    "result_ids": ["final"],
                    "primary_result_id": "final",
                    "direct_answer_location": "paper/sections/q1.tex",
                }
            },
        )


def test_v14_suitable_unit_must_consider_matlab_before_selecting_python(
    tmp_path: Path,
) -> None:
    """优化等适配题型不能因为 Python 可运行就静默跳过 MATLAB。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v14-matlab-capability-decision",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    plan = _v14_optimization_plan(run_dir)
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    del unit["capability_decision"]

    with pytest.raises(ContractError, match="capability_decision"):
        write_modeling_units(run_dir, plan)

    unit["capability_decision"] = {
        "python_considered": True,
        "matlab_considered": False,
        "matlab_availability": "available",
        "selected_engine": "python",
        "matlab_role": None,
        "reason": "Python 当前已有可运行实现，但尚未做 MATLAB 比较。",
        "expected_gain": "MATLAB 可能提供不同的非线性约束搜索族。",
    }
    with pytest.raises(ContractError, match="matlab_considered.*true"):
        write_modeling_units(run_dir, plan)


def test_v14_suitable_unit_rejects_unprobed_matlab_claim(tmp_path: Path) -> None:
    """写 considered=true 不能替代真实工具探测或明确豁免。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v14-matlab-not-probed",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    plan = _v14_optimization_plan(run_dir)
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    decision = unit["capability_decision"]
    assert isinstance(decision, dict)
    decision["matlab_availability"] = "not_probed"

    with pytest.raises(ContractError, match="not_probed"):
        write_modeling_units(run_dir, plan)


def test_v14_suitable_unit_binds_matlab_decision_to_real_probe(tmp_path: Path) -> None:
    """可用性声明必须绑定当前 tooling 探测，不能自由填写 available/unavailable。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v14-matlab-probe-binding",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    plan = _v14_optimization_plan(run_dir)
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    decision = unit["capability_decision"]
    assert isinstance(decision, dict)
    decision["tooling_sha256"] = "0" * 64

    with pytest.raises(ContractError, match="tooling_sha256"):
        write_modeling_units(run_dir, plan)


def test_v14_allows_only_explicit_matlab_probe_waivers(tmp_path: Path) -> None:
    """解析、精确枚举、环境禁用或无异构增益可跳过探测，但必须具体说明。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v14-matlab-probe-waiver",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    plan = _v14_optimization_plan(run_dir)
    (run_dir / "state/tooling.json").unlink()
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    unit["capability_decision"] = {
        "python_considered": True,
        "matlab_considered": True,
        "matlab_availability": "waived",
        "tooling_sha256": None,
        "selected_engine": "python",
        "matlab_role": None,
        "probe_waiver": {
            "reason_code": "small_exact_enumeration",
            "justification": "候选集合可由 Python 有限枚举穷尽，并直接给出全局最优证书。",
        },
        "reason": "有限枚举比启动外部数值引擎更直接，且不损失可验证性。",
        "expected_gain": "MATLAB 不会形成不同算法族，也不会增加新的科学证据。",
    }

    write_modeling_units(run_dir, plan)

    waiver = unit["capability_decision"]["probe_waiver"]
    assert isinstance(waiver, dict)
    waiver["reason_code"] = "convenience"
    with pytest.raises(ContractError, match="probe_waiver.reason_code"):
        write_modeling_units(run_dir, plan)


def test_v14_optimization_accepts_one_challenger_and_one_refinement_family(
    tmp_path: Path,
) -> None:
    """核心优化默认只要求 baseline + 一条结构 challenger，第二条按需触发。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v14-one-challenger",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    for result_id, objective in (
        ("baseline", 10.0),
        ("challenger", 8.0),
        ("attack", 8.0),
        ("check", 8.0),
        ("first-feasible", 9.0),
        ("checkpoint-probe", 8.8),
        ("final", 7.5),
    ):
        _register_result(run_dir, result_id, objective=objective)
    plan = _v14_optimization_plan(run_dir)
    _attach_v14_optimization_actual(plan)
    write_modeling_units(run_dir, plan)

    require_v32_experiment_evidence(run_dir)
    assert question_outcome_selections(run_dir)["Q1"]["objective_answer"]["result_id"] == "final"

    unit = plan["units"][0]
    assert isinstance(unit, dict)
    unit["second_challenger_required"] = True
    with pytest.raises(ContractError, match="第二条 challenger"):
        write_modeling_units(run_dir, plan)


def test_v14_core_search_requires_first_feasible_ai_checkpoint(
    tmp_path: Path,
) -> None:
    """核心题首解必须先经轻量独立复核，才能把后续深化认作已闭环。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v14-first-feasible-checkpoint",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    for result_id, objective in (
        ("baseline", 10.0),
        ("challenger", 8.0),
        ("attack", 8.0),
        ("check", 8.0),
        ("first-feasible", 9.0),
        ("checkpoint-probe", 8.8),
        ("final", 7.5),
    ):
        _register_result(run_dir, result_id, objective=objective)
    plan = _v14_optimization_plan(run_dir)
    _attach_v14_optimization_actual(plan)
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    refinement = unit["actual"]["refinement"]
    assert isinstance(refinement, dict)
    checkpoint = refinement.pop("first_feasible_checkpoint")
    write_modeling_units(run_dir, plan)

    with pytest.raises(ContractError, match="first_feasible_checkpoint"):
        require_v32_experiment_evidence(run_dir)

    refinement["first_feasible_checkpoint"] = checkpoint
    assert isinstance(checkpoint, dict)
    checkpoint["decision"] = "return_analysis"
    write_modeling_units(run_dir, plan)
    with pytest.raises(ContractError, match="返回 analysis"):
        require_v32_experiment_evidence(run_dir)


def test_first_feasible_prompt_focuses_independent_ai_on_next_decision(
    tmp_path: Path,
) -> None:
    """首解提示只要求最高价值纠错和下一项区分实验，不生成第二份综合审核。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v14-first-feasible-prompt",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    _register_result(run_dir, "first-feasible", objective=9.0)
    plan = _v14_optimization_plan(run_dir)
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    unit["actual"] = {
        "refinement": {"first_feasible_result_id": "first-feasible"}
    }
    write_modeling_units(run_dir, plan)

    prompt = first_feasible_checkpoint_prompt(run_dir, "Q1")

    assert "独立上下文" in prompt
    assert "最可能错在哪里" in prompt
    assert "最低成本区分实验" in prompt
    assert "continue_experiment" in prompt
    assert "return_analysis" in prompt
    assert "最多 3 项" in prompt


@pytest.mark.parametrize(
    ("health", "message"),
    [
        ({"seed_count": 1, "materially_unstable": True}, "一个随机种子"),
        ({"challenger_still_improving": True}, "持续快速改善"),
        ({"stop_reason_matches_log": False}, "搜索日志冲突"),
    ],
)
def test_v14_search_health_keeps_only_real_insufficiency_as_hard_block(
    tmp_path: Path, health: dict[str, object], message: str
) -> None:
    """只阻断真实未搜索、单种子不稳定、仍在改善或停止记录冲突。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v14-search-health-" + message[:4],
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    for result_id, objective in (
        ("baseline", 10.0),
        ("challenger", 8.0),
        ("attack", 8.0),
        ("check", 8.0),
        ("first-feasible", 9.0),
        ("checkpoint-probe", 8.8),
        ("final", 7.5),
    ):
        _register_result(run_dir, result_id, objective=objective)
    plan = _v14_optimization_plan(run_dir)
    _attach_v14_optimization_actual(plan, search_health=health)
    write_modeling_units(run_dir, plan)

    with pytest.raises(ContractError, match=message):
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


def test_v32_research_story_requires_substantive_question_progression(tmp_path: Path) -> None:
    """新运行不能只用角色和升级标签冒充逐问继承蓝图。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v32-research-story",
        competition="cumcm",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    plan = _plan(run_dir)
    del plan["research_story"]["question_progression"][0]["new_mechanism"]

    with pytest.raises(ContractError, match="new_mechanism"):
        write_modeling_units(run_dir, plan)


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


def test_answer_map_keeps_objective_answer_and_records_robust_recommendation(
    tmp_path: Path,
) -> None:
    """名义解不稳定时，题面答案不被稳健 fallback 替换。"""
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
        _register_result(
            run_dir,
            result_id,
            objective=objective,
            extra_metrics={"max_action_shift": 2.0}
            if result_id == "sensitivity"
            else None,
        )
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

    with pytest.raises(ContractError, match="objective_answer"):
        write_answer_map(
            run_dir,
            {
                "Q1": {
                    "result_ids": ["structural"],
                    "primary_result_id": "structural",
                    "direct_answer_location": "paper/sections/q1.tex",
                }
            },
        )

    answer_map = write_answer_map(
        run_dir,
        {
            "Q1": {
                "result_ids": ["global", "final"],
                "primary_result_id": "final",
                "direct_answer_location": "paper/sections/q1.tex",
            }
        },
    )
    answer = answer_map["answers"]["Q1"]
    assert answer["primary_result_id"] == "final"
    assert answer["objective_answer"]["result_id"] == "final"
    assert answer["recommended_plan"]["result_id"] == "structural"
    assert question_outcome_selections(run_dir)["Q1"]["objective_answer"]["result_id"] == "final"


def test_stable_objective_answer_is_not_replaced_by_fallback_recommendation(
    tmp_path: Path,
) -> None:
    """名义答案稳定时，即使 fallback 通过也继续推荐题面赢家。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v32-stable-objective-recommendation",
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

    outcome = question_outcome_selections(run_dir)["Q1"]

    assert outcome["objective_answer"]["result_id"] == "final"
    assert outcome["recommended_plan"]["route_id"] == "R2"
    assert outcome["recommended_plan"]["result_id"] == "final"


def test_workbook_export_must_use_objective_answer_metrics(tmp_path: Path) -> None:
    """Excel 即使存在 fallback 建议，也必须写入题面 objective answer 的核心数值。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "v32-q4-workbook-export",
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
        extra_metrics: dict[str, float] = {}
        if result_id == "final":
            extra_metrics["duration"] = 9.184696
        elif result_id == "structural":
            extra_metrics["duration"] = 4.536088
        if result_id == "sensitivity":
            extra_metrics["max_action_shift"] = 2.0
        _register_result(
            run_dir,
            result_id,
            objective=objective,
            extra_metrics=extra_metrics or None,
        )
    _actual(plan)
    unit = plan["units"][0]
    assert isinstance(unit, dict)
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
    workbook_path = run_dir / "artifacts/result2.xlsx"
    workbook_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    workbook.active.title = "Sheet1"
    workbook["Sheet1"]["H2"] = 4.536088
    workbook.save(workbook_path)
    answer_payload = {
        "Q1": {
            "result_ids": ["final", "structural"],
            "primary_result_id": "final",
            "direct_answer_location": "paper/sections/q1.tex",
            "excel_output_location": "artifacts/result2.xlsx",
            "submission_export": {
                "path": "artifacts/result2.xlsx",
                "source_result_id": "final",
                "metric_cells": {"duration": "Sheet1!H2"},
            },
        }
    }

    with pytest.raises(ContractError, match="duration.*不一致"):
        write_answer_map(run_dir, answer_payload)

    workbook["Sheet1"]["H2"] = 9.184696
    workbook.save(workbook_path)
    answer_map = write_answer_map(run_dir, answer_payload)

    assert answer_map["answers"]["Q1"]["submission_export"]["source_result_id"] == "final"
    assert verify_submission_exports(run_dir)["success"] is True


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
    _record_fixture_knowledge_retrieval(run_dir)
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


def test_v32_verify_reachable_without_web_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    _record_fixture_knowledge_retrieval(run_dir)
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
    report.write_text(_paper_blind_report(["Q1"]), encoding="utf-8")
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
    imported = simple_review.import_paper_blind_review(
        run_dir,
        manifest_file=manifest_file,
        verdict="pass",
        highest_severity="none",
        reviewer_thread_id="paper-blind-no-web-audit-thread",
        task_receipt_file=receipt.relative_to(run_dir).as_posix(),
    )
    blind_record = imported["paper_blind_review"]
    assert blind_record["schema_version"] == "1.2"
    assert blind_record["cold_read"]["direct_answers_found_within_3_minutes"] == {
        "Q1": True
    }
    assert blind_record["argument_findings"]["Q1"]["pages"] == [1]
    assert blind_record["reviewer"]["thread_id"] == "paper-blind-no-web-audit-thread"
    assert blind_record["manual_intervention"]["source"] == "user_fixed_prompt"
    assert blind_record["manual_intervention"]["input_scope"] == "frozen_pdf_only"
    assert "figure_gaps" in blind_record["manual_intervention"]["dimensions"]

    assert not any(
        (run_dir / "review" / name).is_file()
        for name in (
            "WEB_PAPER_AUDIT_PROMPT.json",
            "WEB_PAPER_AUDIT.json",
            "WEB_PAPER_AUDIT_REPAIR_PLAN.json",
        )
    ), "夹具不应预先创建任何网页审核文件"

    # 本测试只隔离验证“网页审核可选”；CUMCM 论证审计由专用测试覆盖。
    monkeypatch.setattr(
        "shumozizi.paper.cumcm_adapter.require_cumcm_paper_review_audit",
        lambda _run: None,
    )
    state = update_simple_state(run_dir, phase="verify")

    assert state["phase"] == "verify"
