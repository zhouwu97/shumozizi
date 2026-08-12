"""验证 FORMALIZATION_DIFF 拦截"题面目标被静默替换"的目标漂移。

本次故障（Q2 把"潜在风险最小"静默换成"可靠性达标后最早"）的根因是：形式化
阶段目标被替换，却没有任何机制在目标被创造时审查它。这些测试复现该场景，
确保 silent_replacement 被阻断、surrogate 必须声明支持等级、阈值必须有出处。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shumozizi.core.io import ContractError
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.modeling_units import (
    semantic_reconstruction_input_bindings,
    write_modeling_units,
)
from shumozizi.simple.review_tasks import (
    create_review_task_receipt,
    persist_review_task_creation_event,
)


def _run(tmp_path: Path, name: str) -> Path:
    """创建单问 Competition-First 运行。"""
    return initialize_simple_run(
        tmp_path,
        name,
        required_questions=["Q2"],
        workflow_version="3.2",
    )


def _fixture_capability_decision(run_dir: Path) -> dict[str, object]:
    """写入真实工具探测记录并返回绑定的 Python 引擎选择。"""
    from shumozizi.core.io import atomic_json, sha256_file
    from shumozizi.simple.state import utc_now

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
            {"engine": "matlab", "available": False, "command": None, "probe": None},
            {"engine": "octave", "available": False, "command": None, "probe": None},
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
        "reason": "真实探测未发现 MATLAB 或 Octave，使用 Python 实现。",
        "expected_gain": "若后续环境可用，异构实现可用于攻击同源误差。",
    }


def _semantic_reconstruction(run_dir: Path) -> dict[str, str]:
    """构造带真实独立重建回执的题意重建条目（role=faithful_reconstruction）。"""
    report_file = "review/SEMANTIC_RECONSTRUCTION_fixture.md"
    report = run_dir / report_file
    report.write_text(
        "# 题意重建\n\n只根据题面重建目标、变量和约束：题面要求给出使孕妇潜在"
        "风险最小的最佳检测时点。\n",
        encoding="utf-8",
    )
    event = persist_review_task_creation_event(
        run_dir,
        event_file="review/tasks/creation-events/semantic-fixture.json",
        raw_event={
            "schema_name": "review_task_creation_event",
            "schema_version": "1.0",
            "provider": "codex",
            "raw_task_id": "semantic-task-fixture",
            "raw_thread_id": "semantic-thread-fixture",
            "creation_mode": "create_thread",
            "parent_context_inherited": False,
            "created_at": "2026-07-25T00:00:00Z",
        },
    )
    bindings = semantic_reconstruction_input_bindings(
        run_dir, role="faithful_reconstruction"
    )
    receipt = create_review_task_receipt(
        run_dir,
        task_id="semantic-fixture",
        task_type="semantic_reconstruction",
        model_id="fixture-model",
        prompt_sha256="a" * 64,
        input_bindings=bindings,
        report_file=report_file,
        creation_event_file=event.relative_to(run_dir).as_posix(),
    )
    return {
        "task_receipt": receipt.relative_to(run_dir).as_posix(),
        "report_file": report_file,
        "role": "faithful_reconstruction",
    }


def _base_plan(run_dir: Path) -> dict:
    """构造一个可合法通过 v1.4 校验的优化单元（含合法 FORMALIZATION_DIFF）。"""
    return {
        "schema_version": "1.4",
        "run_id": run_dir.name,
        "semantic_reconstructions": [_semantic_reconstruction(run_dir)],
        "research_story": {
            "central_tension": "在保持题面潜在风险最小化口径的前提下给出可复验时点。",
            "central_mathematical_object": "统一风险函数及其跨孕妇聚合算子。",
            "question_progression": [
                {
                    "question_id": "Q2",
                    "role": "建立风险最小化的时点决策口径。",
                    "upgrade": "用独立实现检查风险值与时点结构。",
                    "inherits_from": [],
                    "inherited_object": "本问首次建立统一风险函数。",
                    "new_difficulty": "需要同时优化分组与时点。",
                    "new_mechanism": "风险函数直接对应题面潜在风险。",
                    "why_previous_insufficient": "当前是首问，没有可继承计算。",
                    "answer_increment": "给出使潜在风险最小的分组与推荐时点。",
                }
            ],
        },
        "units": [
            {
                "unit_id": "Q2-optimization",
                "question_id": "Q2",
                "core_question": True,
                "unit_kind": "optimization",
                "capability_decision": _fixture_capability_decision(run_dir),
                "question_delta": {
                    "inherits_from": None,
                    "added_entities": [],
                    "added_resources": [],
                    "shared_resources": [],
                    "changed_constraints": [],
                    "semantic_risk_signals": [],
                    "possible_objective_change": "题面目标是潜在风险最小化。",
                    "must_recheck_aggregation": False,
                },
                "answer_contract": {
                    "required_output": "给出各组最佳检测时点使潜在风险最小。",
                    "decision_scope": "各 BMI 分组在 10-25 周窗口内的时点决策。",
                    "natural_baseline": "统一检测时点作为自然参照。",
                    "fallback_rule": "若最优时点不可行则报告边界。",
                    "primary_endpoint": {
                        "endpoint_id": "t_opt",
                        "name": "潜在风险最小的最佳时点",
                        "definition": "使孕妇潜在风险函数最小的检测时点。",
                        "formula": "t* = argmin_t R_g(t)",
                        "aggregation": {
                            "atomic_success": "单个孕妇在时点 t 的检测成功。",
                            "within_entity": "同一孕妇的重复记录先聚合。",
                            "across_resources": "检测与复检资源统一计入风险。",
                            "across_entities": "组内孕妇风险等权聚合。",
                            "temporal": "覆盖 10-25 周完整决策窗口。",
                            "quantifier_order": "先逐孕妇计算风险，再组内聚合。",
                        },
                        "exact_metric_alignment": "与风险函数最小值对齐。",
                    },
                    "primary_criterion": "风险函数最小且 endpoint 确定。",
                    "endpoint_resolution": {
                        "status": "determined",
                        "basis": "题面明确要求潜在风险最小。",
                    },
                    "infeasible_policy": {
                        "strict_result": "严格报告窗口内是否存在可行时点。",
                        "fallback_decision": "不可行集合内求最小风险时点并报告可达可靠度。",
                        "fallback_attained_reliability": "备用时点实际达到的可靠性下界。",
                        "retest_strategy": "在备用时点检测并安排复检机制。",
                        "reliability_sensitivity": "q=0.85/0.90/0.95 的时点变化。",
                    },
                },
                "formalization_diff": {
                    "source": "题面要求给出使孕妇潜在风险最小的最佳时点。",
                    "formalized_as": "t* = argmin_t R_g(t)，R_g 为统一风险函数。",
                    "transformation": "equivalent",
                    "added_semantics": "无",
                    "removed_semantics": "无",
                    "equivalence_evidence": "风险函数直接对应题面潜在风险最小。",
                },
                "objective": {
                    "exact_metric": "risk",
                    "direction": "minimize",
                    "significant_improvement_ratio": 0.1,
                    "threshold_provenance": "engineering_heuristic",
                    "threshold_provenance_rationale": "测试夹具：阈值仅作启发式。",
                },
                "expected_outcome": "给出风险最小的时点与分组。",
                "budget": {"kind": "wall_seconds", "tolerance_ratio": 0.1},
                "baseline": {
                    "route_id": "R0",
                    "mathematical_structure": "统一检测时点",
                    "natural_rationale": "不优化分组的自然参照。",
                    "composition": {"mode": "joint", "joint_rationale": "统一 scorer。"},
                },
                "competitive_routes": [
                    {
                        "route_id": "R1",
                        "mathematical_structure": "风险函数最小化的联合优化",
                        "structure_exploited": "同时优化分组与时点。",
                        "expected_upside": "风险显著低于统一时点。",
                        "expected_improvement_ratio": 0.2,
                        "composition": {
                            "mode": "joint",
                            "joint_rationale": "统一 scorer 评价联合方案。",
                        },
                    }
                ],
                "first_batch_attack": {
                    "attack": "先攻击风险函数的定义口径。",
                    "decision": "按题面原目标裁决。",
                },
                "refinement": {
                    "strategy_families": ["risk-minimizing"],
                    "stop_reason_whitelist": ["exact_certificate"],
                },
                "search_repetition": {
                    "planned_repeats": 2,
                    "instability_action": "结果不稳定则返回 analysis。",
                },
                "validation": {
                    "oracle": {"required": False},
                    "sensitivity": {"required": False},
                    "robustness": {"required": False},
                },
            }
        ],
    }


def _write(run_dir: Path, plan: dict) -> None:
    """填充 run_id 并写入 MODELING_UNITS（触发校验）。"""
    plan["run_id"] = run_dir.name
    write_modeling_units(run_dir, plan)


def test_silent_replacement_is_blocked(tmp_path: Path) -> None:
    """把风险最小化静默换成"可靠性达标后最早"必须被阻断。"""
    run_dir = _run(tmp_path, "silent-replacement")
    plan = _base_plan(run_dir)
    unit = plan["units"][0]
    unit["formalization_diff"] = {
        "source": "题面要求给出使孕妇潜在风险最小的最佳时点。",
        "formalized_as": "t* = inf{t: L_g(t) >= q}，q=0.90",
        "transformation": "silent_replacement",
        "added_semantics": "新增题面未给出的可靠性阈值 q=0.90",
        "removed_semantics": "显式风险函数、过早/延迟检测的统一损失",
        "equivalence_evidence": "NONE",
    }

    with pytest.raises(ContractError, match="silent_replacement"):
        _write(run_dir, plan)


def test_surrogate_requires_support_level(tmp_path: Path) -> None:
    """surrogate 必须声明支持等级，不能既替代原目标又不给依据。"""
    run_dir = _run(tmp_path, "surrogate-no-support")
    plan = _base_plan(run_dir)
    unit = plan["units"][0]
    unit["formalization_diff"]["transformation"] = "surrogate"
    unit["formalization_diff"]["removed_semantics"] = "显式风险函数"

    with pytest.raises(ContractError, match="support_level"):
        _write(run_dir, plan)


def test_surrogate_with_sensitivity_only_support_is_rejected_as_conclusion(
    tmp_path: Path,
) -> None:
    """sensitivity_only 的 surrogate 不能作为正式目标结论。"""
    run_dir = _run(tmp_path, "surrogate-sensitivity-only")
    plan = _base_plan(run_dir)
    unit = plan["units"][0]
    unit["formalization_diff"]["transformation"] = "surrogate"
    unit["formalization_diff"]["removed_semantics"] = "显式风险函数"
    unit["formalization_diff"]["support_level"] = "sensitivity_only"

    with pytest.raises(ContractError, match="sensitivity_only"):
        _write(run_dir, plan)


def test_equivalent_transformation_is_accepted(tmp_path: Path) -> None:
    """等价形式化（题面目标原样数学化）应通过。"""
    run_dir = _run(tmp_path, "equivalent-ok")
    _write(run_dir, _base_plan(run_dir))


def test_threshold_requires_provenance(tmp_path: Path) -> None:
    """有显著改善阈值时必须声明出处。"""
    run_dir = _run(tmp_path, "threshold-no-provenance")
    plan = _base_plan(run_dir)
    unit = plan["units"][0]
    objective = unit["objective"]
    objective.pop("threshold_provenance")
    objective.pop("threshold_provenance_rationale")

    with pytest.raises(ContractError, match="threshold_provenance"):
        _write(run_dir, plan)


def test_engineering_heuristic_threshold_requires_rationale(tmp_path: Path) -> None:
    """engineering_heuristic 阈值必须给出理由并保证敏感性。"""
    run_dir = _run(tmp_path, "threshold-heuristic-no-rationale")
    plan = _base_plan(run_dir)
    unit = plan["units"][0]
    objective = unit["objective"]
    objective.pop("threshold_provenance_rationale")

    with pytest.raises(ContractError, match="threshold_provenance_rationale"):
        _write(run_dir, plan)


def test_equivalent_transformation_does_not_require_support_level(
    tmp_path: Path,
) -> None:
    """等价形式化不需要额外 support_level（它就是题面本身）。"""
    run_dir = _run(tmp_path, "equivalent-no-support-field")
    plan = _base_plan(run_dir)
    unit = plan["units"][0]
    unit["formalization_diff"].pop("support_level", None)
    _write(run_dir, plan)


def test_decision_unit_requires_infeasible_policy(tmp_path: Path) -> None:
    """优化/协同决策单元必须声明无可行解的决策闭环。"""
    run_dir = _run(tmp_path, "decision-no-infeasible")
    plan = _base_plan(run_dir)
    unit = plan["units"][0]
    unit["answer_contract"].pop("infeasible_policy")

    with pytest.raises(ContractError, match="infeasible_policy"):
        _write(run_dir, plan)


def test_evaluation_unit_does_not_require_infeasible_policy(tmp_path: Path) -> None:
    """评价类（非决策）单元不强制无可行解三件套。"""
    run_dir = _run(tmp_path, "evaluation-no-infeasible")
    plan = _base_plan(run_dir)
    unit = plan["units"][0]
    unit["unit_kind"] = "evaluation"
    unit["objective"] = {
        "exact_metric": "objective",
        "direction": "minimize",
    }
    unit.pop("capability_decision")
    unit.pop("budget")
    unit.pop("baseline")
    unit.pop("competitive_routes")
    unit.pop("first_batch_attack")
    unit.pop("refinement")
    unit.pop("search_repetition")
    unit["primary_method"] = {
        "method_id": "direct-evaluation",
        "mathematical_structure": "固定方案上的确定性评价计算。",
    }
    unit["fixed_inputs"] = ["题面给定方案", "题面给定参数"]
    unit["endpoint_refinement"] = "连续端点细化直到指标变化低于预设容差。"
    unit["natural_comparison"] = "与按定义直接计算的手工核对值比较。"
    unit["answer_contract"].pop("infeasible_policy", None)
    _write(run_dir, plan)


def test_infeasible_policy_requires_all_closure_fields(tmp_path: Path) -> None:
    """无可行解三件套缺任一项都应被阻断。"""
    run_dir = _run(tmp_path, "infeasible-incomplete")
    plan = _base_plan(run_dir)
    unit = plan["units"][0]
    unit["answer_contract"]["infeasible_policy"].pop("retest_strategy")

    with pytest.raises(ContractError, match="retest_strategy"):
        _write(run_dir, plan)


def _cold_start_prompt(run_dir: Path) -> str:
    """生成冷启动目标忠实度提示（复用夹具 run）。"""
    from shumozizi.paper.formalization_fidelity import formalization_fidelity_prompt

    return formalization_fidelity_prompt(run_dir)


def test_cold_start_prompt_exposes_formalization_diff(tmp_path: Path) -> None:
    """冷启动提示必须暴露 FORMALIZATION_DIFF 与直接答案合同。"""
    run_dir = _run(tmp_path, "cold-start-prompt")
    plan = _base_plan(run_dir)
    unit = plan["units"][0]
    unit["formalization_diff"] = {
        "source": "题面要求给出使孕妇潜在风险最小的最佳时点。",
        "formalized_as": "t* = inf{t: L_g(t) >= q}，q=0.90",
        "transformation": "surrogate",
        "added_semantics": "新增可靠性阈值 q=0.90",
        "removed_semantics": "显式风险函数",
        "support_level": "assumption_supported",
        "equivalence_evidence": "可靠度达标作为风险的可测代理。",
    }
    _write(run_dir, plan)

    prompt = _cold_start_prompt(run_dir)

    assert "FORMALIZATION_DIFF" in prompt
    assert "surrogate" in prompt
    assert "潜在风险最小" in prompt
    assert "q=0.90" in prompt
    assert "silent_replacement" in prompt
    assert "missing_decision_variables" in prompt


def test_cold_start_prompt_forbids_solver_context(tmp_path: Path) -> None:
    """冷启动提示必须禁止读取求解过程与作者解释。"""
    run_dir = _run(tmp_path, "cold-start-isolation")
    _write(run_dir, _base_plan(run_dir))

    prompt = _cold_start_prompt(run_dir)

    assert "禁止读取" in prompt
    assert "code/" in prompt or "results/" in prompt
    assert "作者解释" in prompt


def test_cold_start_prompt_for_equivalent_target_is_still_auditable(
    tmp_path: Path,
) -> None:
    """即使目标是等价形式化，也要暴露给独立 reviewer 核验。"""
    run_dir = _run(tmp_path, "cold-start-equivalent")
    _write(run_dir, _base_plan(run_dir))

    prompt = _cold_start_prompt(run_dir)

    assert "equivalent" in prompt
    assert "1. 题面要求的每个决策变量" in prompt
    assert "2. 题面要求优化的量" in prompt


def test_event_time_estimand_requires_time_dependent_metric(tmp_path: Path) -> None:
    """目标是首次达标时点时，判定指标必须与目标同构（时间依赖而非记录级）。"""
    run_dir = _run(tmp_path, "event-time-misaligned")
    plan = _base_plan(run_dir)
    unit = plan["units"][0]
    endpoint = unit["answer_contract"]["primary_endpoint"]
    endpoint["estimand_kind"] = "event_time"
    endpoint["exact_metric_alignment"] = "以单条记录分类概率的 Brier 判主模型。"
    unit["formalization_diff"]["formalized_as"] = "t* = argmin_t R_g(t)，首次达标时点"

    with pytest.raises(ContractError, match="时间依赖"):
        _write(run_dir, plan)


def test_event_time_estimand_with_time_dependent_metric_passes(tmp_path: Path) -> None:
    """事件时间目标使用时间依赖指标时应通过。"""
    run_dir = _run(tmp_path, "event-time-aligned")
    plan = _base_plan(run_dir)
    unit = plan["units"][0]
    endpoint = unit["answer_contract"]["primary_endpoint"]
    endpoint["estimand_kind"] = "event_time"
    endpoint["exact_metric_alignment"] = (
        "以时间依赖 Brier 与 landmark calibration 直接评价首次达标时点。"
    )
    unit["formalization_diff"]["formalized_as"] = "t* = argmin_t R_g(t)，首次达标时点"

    _write(run_dir, plan)


def test_low_bootstrap_replications_blocked(tmp_path: Path) -> None:
    """报 95% 区间时 Bootstrap 少于 500 次应被阻断（30 次会伪稳定）。"""
    run_dir = _run(tmp_path, "bootstrap-30")
    plan = _base_plan(run_dir)
    unit = plan["units"][0]
    unit["data_quality_contract"] = {
        "uncertainty": {"replications": 30},
    }

    with pytest.raises(ContractError, match="500"):
        _write(run_dir, plan)


def test_adequate_bootstrap_replications_accepted(tmp_path: Path) -> None:
    """Bootstrap 1000 次应通过。"""
    run_dir = _run(tmp_path, "bootstrap-1000")
    plan = _base_plan(run_dir)
    unit = plan["units"][0]
    unit["data_quality_contract"] = {
        "uncertainty": {"replications": 1000},
    }
    _write(run_dir, plan)


def test_decision_weight_requires_sensitivity(tmp_path: Path) -> None:
    """单一风险/损失权重无敏感性说明应被阻断。"""
    run_dir = _run(tmp_path, "weight-no-sensitivity")
    plan = _base_plan(run_dir)
    unit = plan["units"][0]
    unit["data_quality_contract"] = {
        "decision_weights": {"missed_detection": 4},
    }

    with pytest.raises(ContractError, match="weight_sensitivity"):
        _write(run_dir, plan)


def test_decision_weight_with_sensitivity_accepted(tmp_path: Path) -> None:
    """风险权重作为参数并给区间敏感性应通过。"""
    run_dir = _run(tmp_path, "weight-with-sensitivity")
    plan = _base_plan(run_dir)
    unit = plan["units"][0]
    unit["data_quality_contract"] = {
        "decision_weights": {"missed_detection": 4},
        "weight_sensitivity": "漏检损失 λ 在 1--10 区间扫描，结论对 λ 不敏感。",
    }
    _write(run_dir, plan)


def test_decision_unit_partition_requires_optimization(tmp_path: Path) -> None:
    """决策单元有分组但无优化依据应被阻断（禁止启发式分位数）。"""
    run_dir = _run(tmp_path, "partition-no-optimization")
    plan = _base_plan(run_dir)
    unit = plan["units"][0]
    unit["data_quality_contract"] = {
        "partitioning": {"bmi": "分位数切分"},
    }

    with pytest.raises(ContractError, match="partition_optimization"):
        _write(run_dir, plan)


def test_recommendation_requires_future_information_bound(tmp_path: Path) -> None:
    """前瞻推荐必须声明只用决策当时可得信息。"""
    run_dir = _run(tmp_path, "future-info")
    plan = _base_plan(run_dir)
    unit = plan["units"][0]
    unit["data_quality_contract"] = {
        "recommendation_contract": "给出各时点推荐",
    }

    with pytest.raises(ContractError, match="future_information_bound"):
        _write(run_dir, plan)


def test_data_quality_contract_optional_for_evaluation(tmp_path: Path) -> None:
    """评价类（非决策）单元不强制数据质量合同。"""
    run_dir = _run(tmp_path, "quality-evaluation")
    plan = _base_plan(run_dir)
    unit = plan["units"][0]
    unit["unit_kind"] = "evaluation"
    unit["objective"] = {
        "exact_metric": "objective",
        "direction": "minimize",
    }
    unit.pop("capability_decision")
    unit.pop("budget")
    unit.pop("baseline")
    unit.pop("competitive_routes")
    unit.pop("first_batch_attack")
    unit.pop("refinement")
    unit.pop("search_repetition")
    unit["primary_method"] = {
        "method_id": "direct-evaluation",
        "mathematical_structure": "固定方案上的确定性评价计算。",
    }
    unit["fixed_inputs"] = ["题面给定方案", "题面给定参数"]
    unit["endpoint_refinement"] = "连续端点细化直到指标变化低于预设容差。"
    unit["natural_comparison"] = "与按定义直接计算的手工核对值比较。"
    unit.pop("data_quality_contract", None)
    _write(run_dir, plan)
