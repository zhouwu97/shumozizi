"""验证竞争质量合同不会退化为关键词、草稿或静态说明。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json
from shumozizi.paper import policy
from shumozizi.paper.evidence_contracts import (
    evidence_binding_template,
    publication_evidence_binding_errors,
    write_publication_evidence_bindings,
)
from shumozizi.paper.publication import (
    freeze_publication_snapshot,
    require_publication_snapshot,
)
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.modeling_units import validate_modeling_units, write_modeling_units
from shumozizi.simple.results import register_result
from shumozizi.simple.state import utc_now


def _methodology_audit() -> dict[str, object]:
    """构造能够处理重复观察、删失和非线性风险的最小审计。"""
    return {
        "data_generating_process": "每位对象在多个时间点被重复观测，真实状态随时间连续演化。",
        "observation_process": "采样只发生在离散随访时点，缺失与随访计划可能共同影响观测。",
        "time_or_censoring": "首次达到阈值只能定位到两次观测之间，须按区间删失处理。",
        "dependency_structure": "同一对象内测量相关，模型应保留对象层随机效应或等价相关结构。",
        "functional_form_risk": "时间效应可能非线性，线性项只是待检验近似而非默认真相。",
        "unused_fields_review": "协变量逐一审查其缺失、混杂和泄漏风险，未入模字段说明原因。",
        "statistically_valid_alternatives": [
            {
                "method": "区间删失 AFT 生存模型",
                "addresses_risk": "直接表达首次达标只位于相邻随访区间内的观测机制。",
                "decision": "adopt",
                "decision_reason": "目标是首次达标时点，因此主模型必须保留区间删失结构。",
                "discriminating_check": "与离散阈值反解比较推荐时点及其重抽样区间是否发生实质偏移。",
            },
            {
                "method": "带平滑时间项的广义加性混合模型",
                "addresses_risk": "检查重复测量相关和时间函数非线性会否改变条件概率曲线。",
                "decision": "sensitivity",
                "decision_reason": "作为对主结论函数形式假设的独立敏感性检验。",
                "discriminating_check": "比较平滑项有效自由度、校准误差和阈值交点的置信范围。",
            },
        ],
        "recommendation_uncertainty": {
            "required": True,
            "rationale": "推荐时点由样本估计和阈值反解得到，必须报告抽样不确定性。",
            "method": "按对象重抽样的 Bootstrap 区间与删失口径重估。",
        },
    }


def _data_modeling_plan(
    run_dir: Path,
    *,
    include_audit: bool,
    outcome_kind: str = "recommendation",
) -> dict[str, object]:
    """构造低语义风险的数据建模单元，以测试质量合同而非路线赛马。"""
    report = run_dir / "review" / "FAITHFUL_RECONSTRUCTION.md"
    report.write_text("# 忠实重建\n\n按题面定义统计对象、达标事件和推荐输出。\n", encoding="utf-8")
    data_contract: dict[str, object] = {
        "outcome_kind": outcome_kind,
        "observational_unit": "以受试对象为统计单位，并保留其重复随访记录。",
        "split_or_validation": "按对象分组切分，防止同一对象的观测同时出现在训练和验证。",
        "diagnostic_plan": "检查校准、残差、删失处理和关键协变量缺失对结论的影响。",
    }
    if include_audit:
        data_contract["methodology_audit"] = _methodology_audit()
    unit: dict[str, object] = {
        "unit_id": "Q1-data-modeling",
        "question_id": "Q1",
        "core_question": True,
        "unit_kind": "data_modeling",
        "question_delta": {
            "inherits_from": None,
            "added_entities": [],
            "added_resources": [],
            "shared_resources": [],
            "changed_constraints": [],
            "semantic_risk_signals": [],
            "possible_objective_change": "本问直接按题面达标定义输出推荐时点，不改变总体聚合。",
            "must_recheck_aggregation": False,
        },
        "answer_contract": {
            "required_output": "给出满足题面达标目标的推荐时点及其适用边界。",
            "decision_scope": "题面给定总体、随访窗口和协变量范围内的对象。",
            "natural_baseline": "按离散观测时点直接汇总的经验达标比例。",
            "fallback_rule": "若统计模型与独立重估冲突，则回到观测机制和数据清洗检查。",
            "primary_endpoint": {
                "endpoint_id": "threshold_time",
                "name": "总体首次达标时点",
                "definition": "在题面总体内达到目标达标比例的最早推荐时点。",
                "formula": "t^*=inf{t:P(T<=t)>=p0}",
                "aggregation": {
                    "atomic_success": "单个对象首次达到题面阈值即视为成功。",
                    "within_entity": "对象内重复测量先确定首次成功对应的时间区间。",
                    "across_resources": "协变量只用于条件建模，不改变成功事件定义。",
                    "across_entities": "对象层事件按题面总体比例聚合。",
                    "temporal": "时间覆盖题面给定的完整随访窗口。",
                    "quantifier_order": "先判定对象事件，再对总体比例反解推荐时点。",
                },
                "exact_metric_alignment": "生产结果中的 objective 字段记录同一推荐时点指标。",
            },
            "primary_criterion": "endpoint 已解决、推荐方案可行且生产指标可复验。",
            "endpoint_resolution": {
                "status": "determined",
                "basis": "题面已直接给出总体达标比例的判定方向。",
            },
        },
        "objective": {"exact_metric": "objective", "direction": "minimize"},
        "expected_outcome": "获得可复验的推荐时点，并说明观测机制下的区间边界。",
        "validation": {
            "oracle": {"required": False},
            "sensitivity": {"required": False},
            "robustness": {"required": False},
        },
        "primary_method": {
            "method_id": "interval-censored-aft",
            "mathematical_structure": "保留区间删失和对象层重复测量的生存时间模型。",
        },
        "natural_comparison": "与按离散随访点计算的经验达标比例进行口径核对。",
        "data_contract": data_contract,
    }
    return {
        "schema_version": "1.4",
        "run_id": run_dir.name,
        "semantic_reconstructions": [
            {
                "role": "faithful_reconstruction",
                "report_file": "review/FAITHFUL_RECONSTRUCTION.md",
            }
        ],
        "research_story": {
            "central_tension": "离散随访下的首次达标时点不能被错误当作精确观测值。",
            "central_mathematical_object": "对象层首次达标时间及其总体分布函数。",
            "question_progression": [
                {
                    "question_id": "Q1",
                    "role": "建立保留观测机制的推荐时点估计。",
                    "upgrade": "用统计正确替代路线攻击删失和非线性假设。",
                    "inherits_from": [],
                    "inherited_object": "首问建立总体首次达标时间这一共享对象。",
                    "new_difficulty": "离散观测和对象内相关同时影响估计。",
                    "new_mechanism": "通过区间删失模型把观测窗口转化为时间分布信息。",
                    "why_previous_insufficient": "当前是首问，经验比例无法表达观察区间。",
                    "answer_increment": "给出带边界说明的推荐时点。",
                }
            ],
        },
        "units": [unit],
    }


def _register_result(
    run_dir: Path,
    result_id: str,
    *,
    metrics: dict[str, object] | None = None,
) -> None:
    """登记可被数据模型实际验证与正文绑定的最小 production 结果。"""
    source = run_dir / "code" / f"{result_id}.py"
    output = run_dir / "results" / "raw" / f"{result_id}.json"
    source.write_text("print('ok')\n", encoding="utf-8")
    metrics = metrics or {
        "objective": 12.0,
        "feasible": True,
        "hard_constraints_passed": True,
    }
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
        duration_seconds=1.0,
        execution_mode="production",
        provisional=False,
        objective_semantics_sha256="a" * 64,
    )


def _quality_run(tmp_path: Path, run_id: str) -> Path:
    """创建启用竞争质量合同的 v3.2 运行。"""
    return initialize_simple_run(
        tmp_path,
        run_id,
        required_questions=["Q1"],
        workflow_version="3.2",
        quality_policy="competition-quality-v1",
    )


def test_data_modeling_requires_statistics_first_audit(tmp_path: Path) -> None:
    """新质量合同拒绝没有数据机制审计的“主模型 + 简单基线”。"""
    run_dir = _quality_run(tmp_path, "quality-methodology")

    with pytest.raises(ContractError, match="methodology_audit"):
        write_modeling_units(run_dir, _data_modeling_plan(run_dir, include_audit=False))

    document = write_modeling_units(run_dir, _data_modeling_plan(run_dir, include_audit=True))
    unit = document["units"][0]
    assert isinstance(unit, dict)
    audit = unit["data_contract"]["methodology_audit"]
    assert audit["recommendation_uncertainty"]["required"] is True


def test_recommendation_outcome_cannot_disable_uncertainty_binding(tmp_path: Path) -> None:
    """推荐型数据建模不能靠 required=false 跳过不确定性结果和正式稿绑定。"""
    run_dir = _quality_run(tmp_path, "quality-recommendation-uncertainty")
    plan = _data_modeling_plan(run_dir, include_audit=True)
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    contract = unit["data_contract"]
    assert isinstance(contract, dict)
    audit = contract["methodology_audit"]
    assert isinstance(audit, dict)
    uncertainty = audit["recommendation_uncertainty"]
    assert isinstance(uncertainty, dict)
    uncertainty.update({"required": False, "method": None})

    with pytest.raises(ContractError, match="outcome_kind=recommendation"):
        write_modeling_units(run_dir, plan)


def test_data_modeling_must_declare_outcome_kind_in_quality_runs(tmp_path: Path) -> None:
    """新合同不能从题目文本猜测推荐语义，必须显式声明输出类型。"""
    run_dir = _quality_run(tmp_path, "quality-outcome-kind")
    plan = _data_modeling_plan(run_dir, include_audit=True)
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    contract = unit["data_contract"]
    assert isinstance(contract, dict)
    contract.pop("outcome_kind")

    with pytest.raises(ContractError, match="outcome_kind"):
        write_modeling_units(run_dir, plan)


def test_descriptive_outcome_may_document_no_recommendation_uncertainty(
    tmp_path: Path,
) -> None:
    """纯关系刻画可声明不产出推荐值，但仍须解释为什么没有不确定性对象。"""
    run_dir = _quality_run(tmp_path, "quality-descriptive-uncertainty")
    plan = _data_modeling_plan(
        run_dir,
        include_audit=True,
        outcome_kind="descriptive",
    )
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    contract = unit["data_contract"]
    assert isinstance(contract, dict)
    audit = contract["methodology_audit"]
    assert isinstance(audit, dict)
    uncertainty = audit["recommendation_uncertainty"]
    assert isinstance(uncertainty, dict)
    uncertainty.update({"required": False, "method": None})

    document = write_modeling_units(run_dir, plan)
    stored_unit = document["units"][0]
    assert isinstance(stored_unit, dict)
    assert stored_unit["data_contract"]["outcome_kind"] == "descriptive"


def test_data_modeling_requires_real_methodology_and_uncertainty_results(tmp_path: Path) -> None:
    """审计字段必须落实到 production 结果，不能只写一段稳健性措辞。"""
    run_dir = _quality_run(tmp_path, "quality-results")
    plan = _data_modeling_plan(run_dir, include_audit=True)
    for result_id in ("primary", "methodology", "uncertainty"):
        _register_result(run_dir, result_id)
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    unit["actual"] = {
        "expectation_status": "confirmed",
        "summary": "主模型、统计正确替代与不确定性重估均完成生产验证。",
        "primary_result_id": "primary",
        "validation": {"methodology_result_ids": ["methodology"]},
        "insights": [
            {
                "insight_id": "Q1-observation-window",
                "kind": "mechanism",
                "observation": "首次达标只落在相邻随访时点构成的区间内。",
                "mechanism": "区间删失模型保留了离散采样造成的时间不确定性。",
                "boundary": "结论仅覆盖当前对象总体和预登记随访窗口。",
                "evidence_result_ids": ["primary", "methodology"],
            }
        ],
    }

    with pytest.raises(ContractError, match="uncertainty_result_ids"):
        validate_modeling_units(run_dir, plan, require_actual=True)

    validation = unit["actual"]["validation"]
    assert isinstance(validation, dict)
    validation["uncertainty_result_ids"] = ["uncertainty"]
    assert validate_modeling_units(run_dir, plan, require_actual=True) == []


def test_evidence_bindings_require_current_publication_statement(tmp_path: Path) -> None:
    """方法和区间结果须有正式稿行号与断言，长稿或散文不能替代。"""
    run_dir = _quality_run(tmp_path, "quality-bindings")
    plan = _data_modeling_plan(run_dir, include_audit=True)
    _register_result(run_dir, "primary")
    _register_result(run_dir, "methodology")
    _register_result(
        run_dir,
        "uncertainty",
        metrics={"ci_lower_week": 10.0, "ci_upper_week": 14.0},
    )
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    unit["actual"] = {
        "validation": {
            "methodology_result_ids": ["methodology"],
            "uncertainty_result_ids": ["uncertainty"],
        }
    }
    atomic_json(run_dir / "analysis/MODELING_UNITS.json", plan)
    (run_dir / "paper/main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "方法学复算保留区间删失和对象层相关结构。\n"
        "推荐时点的 Bootstrap 95% 区间为 10--14 周。\n"
        "\\end{document}\n",
        encoding="utf-8",
    )

    with pytest.raises(ContractError, match="发布快照"):
        require_publication_snapshot(run_dir)
    freeze_publication_snapshot(run_dir)
    assert require_publication_snapshot(run_dir) is not None

    template = evidence_binding_template(run_dir)
    assert any("待填写" in item["statement"] for item in template["bindings"])
    assert any(
        item["role"] == "uncertainty" and "metric_assertions" in item
        for item in template["bindings"]
    )
    assert publication_evidence_binding_errors(run_dir, payload=template)
    bindings = template["bindings"]
    assert isinstance(bindings, list)
    for item in bindings:
        assert isinstance(item, dict)
        if item["role"] == "methodology":
            item.update(
                {
                    "source_path": "paper/main.tex",
                    "source_span": "paper/main.tex:3-3",
                    "statement": "方法学复算保留区间删失和对象层相关结构。",
                }
            )
        else:
            item.update(
                {
                    "source_path": "paper/main.tex",
                    "source_span": "paper/main.tex:4-4",
                    "statement": "推荐时点的 Bootstrap 95% 区间为 10--14 周。",
                    "metric_assertions": [
                        {
                            "result_id": "uncertainty",
                            "metric": "ci_lower_week",
                            "value_text": "10",
                        },
                        {
                            "result_id": "uncertainty",
                            "metric": "ci_upper_week",
                            "value_text": "14",
                        },
                    ],
                }
            )
    write_publication_evidence_bindings(run_dir, template)
    assert publication_evidence_binding_errors(run_dir) == []

    missing_value_assertions = json.loads(json.dumps(template))
    uncertainty_binding = next(
        item
        for item in missing_value_assertions["bindings"]
        if item["role"] == "uncertainty"
    )
    uncertainty_binding.pop("metric_assertions")
    assert any(
        "metric_assertions" in error
        for error in publication_evidence_binding_errors(
            run_dir,
            payload=missing_value_assertions,
        )
    )

    wrong_value_assertion = json.loads(json.dumps(template))
    uncertainty_binding = next(
        item
        for item in wrong_value_assertion["bindings"]
        if item["role"] == "uncertainty"
    )
    uncertainty_binding["metric_assertions"][0]["value_text"] = "11"
    assert any(
        "与生产结果指标不一致" in error
        for error in publication_evidence_binding_errors(
            run_dir,
            payload=wrong_value_assertion,
        )
    )

    (run_dir / "paper/main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n改写后的正文。\\end{document}\n",
        encoding="utf-8",
    )
    assert any("依赖摘要" in error for error in publication_evidence_binding_errors(run_dir))


def test_workflow_snapshot_keeps_quality_policy_frozen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """中途改工作流只报告漂移，不让本运行静默切换评估规则。"""
    run_dir = _quality_run(tmp_path, "quality-snapshot")
    snapshot = policy.workflow_snapshot(run_dir)
    assert snapshot is not None
    frozen = policy.frozen_policy_fingerprints(run_dir)
    assert snapshot["quality_policy"] == "competition-quality-v1"
    assert frozen == snapshot["policy_fingerprints"]

    monkeypatch.setattr(
        policy,
        "current_policy_fingerprints",
        lambda _root: {"paper": "b" * 64, "visual": "c" * 64},
    )
    status = policy.workflow_snapshot_status(run_dir)
    assert status["status"] == "workflow_drift"
    assert policy.frozen_policy_fingerprints(run_dir) == frozen
