"""验证 Competition-First v3.2 的轻量建模单元和 LaTeX 主链。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, sha256_file
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
from shumozizi.simple.results import register_result
from shumozizi.simple.review_focus import record_scientific_challenge_evidence
from shumozizi.simple.review_tasks import (
    create_review_task_receipt,
    persist_review_task_creation_event,
)
from shumozizi.simple.state import read_simple_state, update_simple_state, utc_now


def _register_result(run_dir: Path, result_id: str, *, objective: float = 1.0) -> None:
    """登记可用于 v3.2 比较、攻击和深化的真实生产结果。"""
    source = run_dir / "code" / f"{result_id}.py"
    output = run_dir / "results" / "raw" / f"{result_id}.json"
    source.write_text("print('ok')\n", encoding="utf-8")
    output.write_text(
        json.dumps({"metrics": {"objective": objective, "feasible": True}}),
        encoding="utf-8",
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
        metrics={"objective": objective, "feasible": True},
        metric_sources={
            "objective": {"file": f"results/raw/{result_id}.json", "json_path": "metrics.objective"},
            "feasible": {"file": f"results/raw/{result_id}.json", "json_path": "metrics.feasible"},
        },
        exit_code=0,
        stdout_path=f"results/{result_id}.stdout.log",
        stderr_path=f"results/{result_id}.stderr.log",
        started_at=now,
        finished_at=now,
        duration_seconds=10.0,
        objective_semantics_sha256="a" * 64,
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
        "schema_version": "1.0",
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
                "mode": "compare",
                "objective": {"exact_metric": "objective", "direction": "minimize"},
                "budget": {"kind": "wall_seconds", "tolerance_ratio": 0.1},
                "baseline": {"route_id": "R0", "mathematical_structure": "可解释规则模型"},
                "competitive_routes": [
                    {"route_id": "R1", "mathematical_structure": "约束规划"},
                    {"route_id": "R2", "mathematical_structure": "连续全局优化"},
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


def _actual(plan: dict[str, object]) -> None:
    """为计划回填真实实验的最小证据映射。"""
    unit = plan["units"][0]
    assert isinstance(unit, dict)
    unit["actual"] = {
        "expectation_status": "confirmed",
        "summary": "R2 在统一 exact 和共同预算下最佳，独立攻击没有改变排序。",
        "comparison": {"route_result_ids": {"R0": "baseline", "R1": "structural", "R2": "global"}},
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
    _actual(plan)
    write_modeling_units(run_dir, plan)

    require_v32_experiment_evidence(run_dir)


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


def test_v32_uses_competition_answer_map_for_paper_readiness(tmp_path: Path) -> None:
    """v3.2 继续使用逐问答案映射，而不是误落入旧 argument_map 协议。"""
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

    assert status["ready"], status


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
    _actual(plan)
    write_modeling_units(run_dir, plan)

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
    )

    status = simple_review.scientific_review_status(run_dir)

    assert status["allowed"], status
    assert not status["submission_ready"]
    assert status["unresolved_high_severities"] == ["P1"]
    assert not (run_dir / "review" / "summary.json").exists()
    simple_review.require_paper_generation_allowed(run_dir)


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
    _actual(plan)
    write_modeling_units(run_dir, plan)
    monkeypatch.setattr(
        simple_review,
        "_v32_scientific_challenge_status",
        lambda _run: {"allowed": True, "submission_ready": False, "reason": "fixture"},
    )

    simple_review.require_paper_generation_allowed(run_dir)
