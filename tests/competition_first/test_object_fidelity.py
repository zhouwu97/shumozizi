"""验证"题面几何对象保真"：判据收窄（圆柱→中心点）必须被显式声明。

CUMCM 2025 A 暴露的盲区：遮蔽判据把"圆柱形真目标"收窄成"参考点 T_ref"、
把"遮住整个轮廓"收窄成"遮挡一条视线"，还标 equivalent 蒙混过关。本文件验证
两层防线：FORMALIZATION_DIFF 的 object_fidelity 校验 + 科学挑战阶段 A 的
object_fidelity_checked 声明。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.modeling_units import (
    semantic_reconstruction_input_bindings,
    write_modeling_units,
)
from shumozizi.simple.results import register_result
from shumozizi.simple.review_focus import record_scientific_challenge_evidence
from shumozizi.simple.review_tasks import (
    create_review_task_receipt,
    persist_review_task_creation_event,
)
from shumozizi.simple.state import utc_now

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _run(tmp_path: Path, name: str) -> Path:
    """创建单问运行。"""
    return initialize_simple_run(
        tmp_path,
        name,
        required_questions=["Q1"],
        workflow_version="3.2",
    )


def _semantic_reconstruction(run_dir: Path) -> dict[str, str]:
    """构造带真实独立重建回执的题意重建条目。"""
    report_file = "review/SEMANTIC_RECONSTRUCTION_fixture.md"
    report = run_dir / report_file
    report.write_text(
        "# 题意重建\n\n题面要求烟幕云团遮蔽圆柱形真目标，避免导弹发现真目标。\n",
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


def _unit(fd: dict, run_dir: Path) -> dict:
    """构造一个含指定 formalization_diff 的 v1.4 单元。"""
    from shumozizi.core.io import sha256_file

    tooling_hash = sha256_file(run_dir / "state/tooling.json")
    return {
        "unit_id": "Q1-opt",
        "question_id": "Q1",
        "core_question": True,
        "unit_kind": "optimization",
        "capability_decision": {
            "python_considered": True,
            "matlab_considered": True,
            "matlab_availability": "unavailable",
            "tooling_sha256": tooling_hash,
            "selected_engine": "python",
            "matlab_role": None,
            "probe_waiver": None,
            "reason": "测试夹具：真实探测未发现 MATLAB，使用 Python 实现几何遮蔽模型。",
            "expected_gain": "若后续环境可用，异构数值实现可用于攻击同源误差并复核遮蔽判据。",
        },
        "question_delta": {
            "inherits_from": None,
            "added_entities": [],
            "added_resources": [],
            "shared_resources": [],
            "changed_constraints": [],
            "semantic_risk_signals": [],
            "possible_objective_change": "题面目标是遮蔽真目标。",
            "must_recheck_aggregation": False,
        },
        "answer_contract": {
            "required_output": "给出烟幕干扰弹对来袭导弹的有效遮蔽时长以及投放点和起爆点坐标，作为最终可提交答案。",
            "decision_scope": "覆盖 M1 来袭导弹、半径7m高10m圆柱形真目标、烟幕云团与无人机投放决策。",
            "natural_baseline": "采用无人机初始位置固定投放作为不优化的自然参照策略。",
            "fallback_rule": "若最优策略不可行，则报告遮蔽时长的可行上界与边界条件。",
            "primary_endpoint": {
                "endpoint_id": "shield_time",
                "name": "有效遮蔽时长",
                "definition": "云团球体遮挡来袭导弹指向真目标视线的累计时长测度。",
                "formula": "|{t: dist(segment(M1(t),T),C(t)) <= 10}|",
                "aggregation": {
                    "atomic_success": "单一时刻云团中心到导弹-真目标视线线段距离不超过云团半径。",
                    "within_entity": "同一枚烟幕弹有效生命周期内满足遮蔽判据的时间窗口。",
                    "across_resources": "多枚烟幕弹各自遮蔽区间取并集，重叠时段只计一次。",
                    "across_entities": "不同来袭导弹各自被遮蔽的时长独立求和。",
                    "temporal": "时间覆盖从起爆到云团生命周期结束的完整区间。",
                    "quantifier_order": "先逐枚烟幕弹计算遮蔽区间，再跨弹取并集、跨导弹求和。",
                },
                "exact_metric_alignment": "遮蔽时长与题面要求的有效遮蔽时间定义一致。",
            },
            "primary_criterion": "遮蔽时长最大、endpoint 已确定且 exact 指标可复验。",
            "endpoint_resolution": {"status": "determined", "basis": "题面明确要求有效遮蔽时间尽可能长。"},
            "infeasible_policy": {
                "strict_result": "严格报告在给定云团参数下是否存在非零遮蔽区间。",
                "fallback_decision": "不可行时在可行集合内求使遮蔽时长最大的时点。",
                "fallback_attained_reliability": "备用时点实际达到的遮蔽时长数值。",
                "retest_strategy": "调整投放点与起爆时刻后重新计算遮蔽区间。",
                "reliability_sensitivity": "不同云团位置与起爆时刻对遮蔽时长的敏感性分析。",
            },
        },
        "formalization_diff": fd,
        "objective": {
            "exact_metric": "shield_time",
            "direction": "maximize",
            "significant_improvement_ratio": 0.1,
            "threshold_provenance": "engineering_heuristic",
            "threshold_provenance_rationale": "测试夹具",
        },
        "expected_outcome": "给出最大遮蔽时长。",
        "budget": {"kind": "wall_seconds", "tolerance_ratio": 0.1},
        "baseline": {
            "route_id": "R0",
            "mathematical_structure": "不优化投放点的固定投放方案。",
            "natural_rationale": "固定投放作为不利用几何优化的自然参照。",
            "composition": {"mode": "joint", "joint_rationale": "在同一遮蔽测度 scorer 上评价联合方案。"},
        },
        "competitive_routes": [
            {
                "route_id": "R1",
                "mathematical_structure": "对投放点和起爆时刻做几何优化的方案。",
                "structure_exploited": "利用几何关系优化云团相对导弹视线位置以延长遮蔽。",
                "expected_upside": "相比固定投放基线显著延长有效遮蔽时长。",
                "expected_improvement_ratio": 0.2,
                "composition": {"mode": "joint", "joint_rationale": "在同一遮蔽测度 scorer 上评价联合方案。"},
            }
        ],
        "first_batch_attack": {
            "attack": "先攻击遮蔽判据口径与对象保真，再检查优化空间。",
            "decision": "按题面真目标几何对象与遮蔽判据裁决攻击结论。",
        },
        "refinement": {
            "strategy_families": ["geometric"],
            "stop_reason_whitelist": ["exact_certificate"],
        },
        "search_repetition": {
            "planned_repeats": 2,
            "instability_action": "若结果明显不稳定则返回 analysis 重新审视判据。",
        },
        "validation": {
            "oracle": {"required": False},
            "sensitivity": {"required": False},
            "robustness": {"required": False},
        },
    }


def _write(run_dir: Path, fd: dict) -> None:
    """写入 MODELING_UNITS 触发校验。"""
    import json as _json

    (run_dir / "review").mkdir(exist_ok=True)
    (run_dir / "review/SCIENTIFIC_CHALLENGE.md").write_text(
        "# 科学挑战\n\n独立攻击当前结果。\n", encoding="utf-8"
    )
    # 写真实 tooling 探测记录，满足 optimization 单元的 capability_decision。
    (run_dir / "state").mkdir(exist_ok=True)
    (run_dir / "state/tooling.json").write_text(
        _json.dumps(
            {
                "schema_version": "1.1",
                "checked_at": utc_now(),
                "engines": [
                    {"engine": "python", "available": True, "command": "python", "probe": None},
                    {"engine": "matlab", "available": False, "command": None, "probe": None},
                    {"engine": "octave", "available": False, "command": None, "probe": None},
                ],
            }
        ),
        encoding="utf-8",
    )
    plan = {
        "schema_version": "1.4",
        "run_id": run_dir.name,
        "semantic_reconstructions": [_semantic_reconstruction(run_dir)],
        "research_story": {
            "central_tension": "烟幕遮蔽真目标。",
            "central_mathematical_object": "云团与视线相交测度。",
            "question_progression": [
                {
                    "question_id": "Q1",
                    "role": "建立遮蔽测度与投放策略。",
                    "upgrade": "用独立实现检查几何判定。",
                    "inherits_from": [],
                    "inherited_object": "本问首次建立遮蔽测度。",
                    "new_difficulty": "云团与视线的相交判定。",
                    "new_mechanism": "几何相交测度直接对应题面遮蔽。",
                    "why_previous_insufficient": "当前是首问，尚未建立遮蔽测度与投放策略的统一计算框架，需要先定义共享的几何相交判定。",
                    "answer_increment": "给出遮蔽时长与投放策略。",
                }
            ],
        },
        "units": [_unit(fd, run_dir)],
    }
    write_modeling_units(run_dir, plan)


def _cylinder_to_point_fd() -> dict:
    """复现 CUMCM 2025 A 的判据收窄：圆柱→参考点。"""
    return {
        "source": "受领任务 1.5 s 后即投放 1 枚烟幕干扰弹，间隔 3.6 s 后起爆。",
        "formalized_as": "T_ref=中心点(0,200,5)；遮蔽=|{t:dist(segment(M1(t),T_ref),C(t))<=10}|",
        "transformation": "equivalent",
        "added_semantics": "把云团中心 10m 内有效遮蔽形式化为与视线线段相交。",
        "removed_semantics": "未引入浓度衰减或视场角。",
        "equivalence_evidence": "题面物理量全部进入模型，未改变原题目标。",
    }


def test_cylinder_to_point_without_fidelity_blocked(tmp_path: Path) -> None:
    """把圆柱形真目标收窄成参考点且未声明 object_fidelity → 阻断。"""
    run_dir = _run(tmp_path, "cyl-no-fidelity")
    with pytest.raises(ContractError, match="object_fidelity"):
        _write(run_dir, _cylinder_to_point_fd())


def test_cylinder_to_point_with_fidelity_passes(tmp_path: Path) -> None:
    """显式声明几何收窄的等价理由 → 通过。"""
    run_dir = _run(tmp_path, "cyl-with-fidelity")
    fd = _cylinder_to_point_fd()
    fd["object_fidelity"] = {
        "subject": "真目标圆柱 → 中心参考点",
        "statement": (
            "圆柱半径7m小于云团半径10m，导引头锁定目标中心；以中心点作参考的"
            "遮蔽时长与实际轮廓遮挡差异已作敏感性分析，不作为唯一正式判据。"
        ),
    }
    _write(run_dir, fd)


def test_point_target_no_fidelity_required(tmp_path: Path) -> None:
    """题面本身是点目标时不需要 object_fidelity。"""
    run_dir = _run(tmp_path, "point-target")
    fd = {
        "source": "给出设备位置使覆盖某点目标。",
        "formalized_as": "T_ref=点目标(0,200,5)；dist(segment, T_ref)<=10",
        "transformation": "equivalent",
        "added_semantics": "目标按点处理。",
        "removed_semantics": "无",
        "equivalence_evidence": "题面目标即单点，按点处理。",
    }
    _write(run_dir, fd)


def _stage_a(fidelity: dict | None) -> dict:
    """构造阶段 A 语义评估（含可选 object_fidelity_checked）。"""
    assessment: dict = {
        "priority": "semantics_or_decomposition",
        "reason": "先攻击遮蔽判据的聚合口径与对象保真。",
        "counterexample": {
            "question_id": "Q1",
            "case_a": "两弹区间重叠时并集 vs 求和",
            "case_b": "并集=5s 求和=7s",
            "expected_preference": "并集符合题面'遮蔽可不连续'",
        },
    }
    if fidelity is not None:
        assessment["object_fidelity_checked"] = fidelity
    return assessment


def _register_result(run_dir: Path) -> None:
    """登记一个 current production 结果供科学挑战引用。"""
    import json

    source = run_dir / "code" / "baseline.py"
    output = run_dir / "results" / "raw" / "baseline.json"
    source.parent.mkdir(exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("print('ok')\n", encoding="utf-8")
    output.write_text(
        json.dumps(
            {
                "metrics": {
                    "objective": 1.0,
                    "feasible": True,
                    "hard_constraints_passed": True,
                }
            }
        ),
        encoding="utf-8",
    )
    register_result(
        run_dir,
        result_id="baseline",
        question_id="Q1",
        kind="baseline",
        command="python code/baseline.py",
        source_script="code/baseline.py",
        input_files=["code/baseline.py"],
        output_files=["results/raw/baseline.json"],
        metrics={"objective": 1.0, "feasible": True},
        metric_sources={
            "objective": {"file": "results/raw/baseline.json", "json_path": "metrics.objective"},
            "feasible": {"file": "results/raw/baseline.json", "json_path": "metrics.feasible"},
        },
        exit_code=0,
        stdout_path="results/baseline.stdout.log",
        stderr_path="results/baseline.stderr.log",
        started_at=utc_now(),
        finished_at=utc_now(),
        duration_seconds=1.0,
        execution_mode="production",
        provisional=False,
        objective_semantics_sha256="a" * 64,
    )


def _record_challenge(run_dir: Path, fidelity: dict | None) -> None:
    """记录一次带阶段 A 的科学挑战。"""
    from shumozizi.simple.modeling_units import (
        semantic_reconstruction_input_bindings as _b,
    )
    from shumozizi.simple.review_tasks import (
        create_review_task_receipt as _c,
    )
    from shumozizi.simple.review_tasks import (
        persist_review_task_creation_event as _p,
    )

    (run_dir / "review").mkdir(exist_ok=True)
    (run_dir / "review/SCIENTIFIC_CHALLENGE.md").write_text(
        "# 科学挑战\n\n独立攻击当前生产结果。\n", encoding="utf-8"
    )
    _register_result(run_dir)
    event = _p(
        run_dir,
        event_file="review/tasks/creation-events/challenge.json",
        raw_event={
            "schema_name": "review_task_creation_event",
            "schema_version": "1.0",
            "provider": "codex",
            "raw_task_id": "challenge",
            "raw_thread_id": "challenge-thread",
            "creation_mode": "create_thread",
            "parent_context_inherited": False,
            "created_at": "2026-07-25T00:00:00Z",
        },
    )
    bindings = _b(run_dir, role="faithful_reconstruction")
    _c(
        run_dir,
        task_id="challenge",
        task_type="scientific_open",
        model_id="fixture-model",
        prompt_sha256="1" * 64,
        input_bindings=bindings,
        report_file="review/SCIENTIFIC_CHALLENGE.md",
        creation_event_file=event.relative_to(run_dir).as_posix(),
    )
    record_scientific_challenge_evidence(
        run_dir,
        result_ids=["baseline"],
        attack_description="独立攻击当前生产结果。",
        findings=[],
        stage_a_semantic_assessment=_stage_a(fidelity),
    )


def test_stage_a_object_fidelity_must_be_boolean(tmp_path: Path) -> None:
    """object_fidelity_checked 声明时必须是布尔 + 依据。"""
    run_dir = _run(tmp_path, "stagea-bad-fidelity")
    with pytest.raises(ContractError, match="object_fidelity_checked"):
        _record_challenge(run_dir, {"object_is_faithful": "yes"})


def test_stage_a_object_fidelity_with_basis_passes(tmp_path: Path) -> None:
    """阶段 A 声明核对过对象保真并通过 → 可记录。"""
    run_dir = _run(tmp_path, "stagea-good-fidelity")
    _record_challenge(
        run_dir,
        {
            "object_is_faithful": False,
            "basis": "正式目标用 T_ref 单点替代圆柱，判据收窄已识别并作敏感性。",
        },
    )


def test_stage_a_object_fidelity_absent_still_allowed(tmp_path: Path) -> None:
    """未声明 object_fidelity_checked 时科学挑战仍可记录（兼容旧流程）。"""
    run_dir = _run(tmp_path, "stagea-no-fidelity")
    _record_challenge(run_dir, None)
