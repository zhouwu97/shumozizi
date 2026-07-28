"""验证规律必须被论文真正使用，以及"更强路线"判断必须闭合。

这两条针对同一失分模式：结论被反复验证，但更强的解法和已发现的规律都没有
进入最终论文。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from shumozizi.core.io import ContractError
from shumozizi.knowledge.retrieval import (
    write_analysis_knowledge_retrieval,
    write_paper_knowledge_application,
)
from shumozizi.paper.cumcm_adapter import SECTION_TARGETS, write_cumcm_structure_map
from shumozizi.paper.readiness import check_paper_readiness
from shumozizi.simple.competition import write_answer_map
from shumozizi.simple.figures import write_figure_plan
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.modeling_units import core_question_insights
from shumozizi.simple.results import register_result
from shumozizi.simple.review_focus import (
    record_stronger_alternative,
    stronger_alternative_status,
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
    write_analysis_knowledge_retrieval(
        run_dir,
        None,
        {
            "problem_type": "测试夹具",
            "data_structure": "最小生产结果",
            "task_types": ["结果洞察"],
        },
        unavailable_reason="测试夹具不加载仓内论文卡索引，显式记录后继续。",
    )
    write_paper_knowledge_application(run_dir)
    return run_dir


def _register(
    run_dir: Path, result_id: str = "q1-primary", *, objective: float = 1.0
) -> None:
    """登记一个真实生产结果。"""
    (run_dir / "code" / f"{result_id}.py").write_text("print('ok')\n", encoding="utf-8")
    (run_dir / "results" / "raw" / f"{result_id}.json").write_text(
        json.dumps(
            {
                "metrics": {
                    "objective": objective,
                    "feasible": True,
                    "endpoint_action_shift": 0.0,
                    "max_action_shift": 0.0,
                    "guard_pass_rate": 1.0,
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
        kind=result_id,
        command=f"python code/{result_id}.py",
        source_script=f"code/{result_id}.py",
        input_files=[f"code/{result_id}.py"],
        output_files=[f"results/raw/{result_id}.json"],
        metrics={
            "objective": objective,
            "feasible": True,
            "endpoint_action_shift": 0.0,
            "max_action_shift": 0.0,
            "guard_pass_rate": 1.0,
        },
        metric_sources={
            name: {
                "file": f"results/raw/{result_id}.json",
                "json_path": f"metrics.{name}",
            }
            for name in (
                "objective",
                "feasible",
                "endpoint_action_shift",
                "max_action_shift",
                "guard_pass_rate",
            )
        },
        exit_code=0,
        stdout_path=f"results/{result_id}.stdout.log",
        stderr_path=f"results/{result_id}.stderr.log",
        started_at=now,
        finished_at=now,
        duration_seconds=1.0,
        objective_semantics_sha256="a" * 64,
    )


def _units_with_insight(run_dir: Path, insight_id: str = "Q1-mechanism") -> None:
    """写入带系统答案资格与核心规律的最小 1.2 建模单元。"""
    _register(run_dir, "q1-baseline", objective=2.0)
    _register(run_dir, "q1-challenger", objective=1.5)
    (run_dir / "analysis").mkdir(parents=True, exist_ok=True)
    (run_dir / "analysis" / "MODELING_UNITS.json").write_text(
        json.dumps(
            {
                "schema_version": "1.2",
                "run_id": run_dir.name,
                "units": [
                    {
                        "unit_id": "Q1-core",
                        "question_id": "Q1",
                        "core_question": True,
                        "mode": "compare",
                        "answer_contract": {
                            "required_output": "给出目标值最小的可执行方案。",
                            "decision_scope": "当前题面数据覆盖的全部对象。",
                            "natural_baseline": "按题面顺序逐项选择的直接规则。",
                            "fallback_rule": "主路线失效时使用已比较的 R1。",
                            "primary_endpoint": {
                                "endpoint_id": "objective",
                                "name": "objective",
                                "definition": "方案的精确目标值。",
                                "exact_metric_alignment": "对应结果中的 objective。",
                            },
                            "primary_criterion": "可行且相对自然 baseline 至少改善 10%。",
                            "endpoint_resolution": {
                                "status": "comparison_planned",
                                "basis": "比较主目标与瓶颈口径的行动后果。",
                                "candidate_endpoints": [
                                    {
                                        "endpoint_id": "objective",
                                        "definition": "方案的精确目标值。",
                                        "problem_text_basis": "题面要求目标最小。",
                                    },
                                    {
                                        "endpoint_id": "bottleneck",
                                        "definition": "最坏对象的目标值。",
                                        "problem_text_basis": "题面要求全部对象可行。",
                                    },
                                ],
                                "decision_rule": "路线翻转则返回 analysis。",
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
                            "mathematical_structure": "题面直接规则",
                            "natural_rationale": "无需复杂模型即可执行。",
                        },
                        "competitive_routes": [
                            {
                                "route_id": "R1",
                                "mathematical_structure": "局部结构优化",
                                "structure_exploited": "利用局部可分结构。",
                                "expected_upside": "相对基线降低目标。",
                                "expected_improvement_ratio": 0.2,
                            },
                            {
                                "route_id": "R2",
                                "mathematical_structure": "全局离散优化",
                                "structure_exploited": "联合搜索全部决策。",
                                "expected_upside": "找到更低的全局候选。",
                                "expected_improvement_ratio": 0.4,
                            },
                        ],
                        "fallback": {
                            "route_id": "R1",
                            "switch_condition": "主路线资格失败时。",
                        },
                        "expected_outcome": "R2 相对自然 baseline 有实质改善。",
                        "first_batch_attack": {
                            "attack": "检查小实例排序。",
                            "decision": "翻转则返回 analysis。",
                        },
                        "refinement": {
                            "strategy_families": ["局部精化", "全局搜索"],
                            "stop_reason_whitelist": ["budget_exhausted"],
                        },
                        "validation": {
                            "oracle": {"required": False},
                            "sensitivity": {"required": False},
                            "robustness": {"required": False},
                        },
                        "actual": {
                            "comparison": {
                                "route_result_ids": {
                                    "R0": "q1-baseline",
                                    "R1": "q1-challenger",
                                    "R2": "q1-primary",
                                },
                                "winner_route_id": "R2",
                            },
                            "actual_endpoint_resolution": {
                                "status": "determined",
                                "selected_endpoint_id": "objective",
                                "problem_text_basis": "题面直接要求精确目标最小。",
                                "evidence_result_ids": ["q1-primary"],
                                "winner_route_ids": {
                                    "objective": "R2",
                                    "bottleneck": "R2",
                                },
                            },
                            "qualification_evidence": {
                                "endpoint_checks": [
                                    {
                                        "result_id": "q1-primary",
                                        "metric": "endpoint_action_shift",
                                        "operator": "<=",
                                        "threshold": 1.0,
                                    }
                                ],
                                "guards": [
                                    {
                                        "result_id": "q1-primary",
                                        "metric": "guard_pass_rate",
                                        "operator": ">=",
                                        "threshold": 0.8,
                                    }
                                ],
                                "decision_stability": [
                                    {
                                        "result_id": "q1-primary",
                                        "metric": "max_action_shift",
                                        "operator": "<=",
                                        "threshold": 1.0,
                                    }
                                ],
                            },
                            "refinement": {"final_result_id": "q1-primary"},
                            "insights": [
                                {
                                    "insight_id": insight_id,
                                    "kind": "mechanism",
                                    "observation": "瓶颈实体决定整体上限。",
                                    "mechanism": "覆盖窗口无法在瓶颈实体上叠加。",
                                    "boundary": "只覆盖当前参数区间。",
                                    "evidence_result_ids": ["q1-primary"],
                                }
                            ]
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_structure_map(run_dir: Path) -> None:
    """为只测试论文洞察消费的夹具补齐 CUMCM 结构前提。"""
    source_of_truth = {
        "argument_plan": "paper/ARGUMENT_PLAN.md",
        "storyboard": "paper/STORYBOARD.md",
        "figure_plan": "figures/FIGURE_PLAN.json",
        "results": "results/RESULT_REGISTRY.json",
        "modeling_units": "analysis/MODELING_UNITS.json",
    }
    for relative in source_of_truth.values():
        path = run_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file():
            path.write_text("fixture source\n", encoding="utf-8")
    reference = run_dir / "paper/reference.docx"
    reference.write_bytes(b"reference")
    sections = []
    for target in SECTION_TARGETS:
        sources = ["argument_plan"]
        scope = "local"
        if target == "五、模型的建立与求解":
            sources = ["Q1"]
        elif target == "六、模型的综合分析与检验":
            sources = ["results"]
            scope = "cross_question_only"
        sections.append(
            {
                "target": target,
                "sources": sources,
                "purpose": "保留本节在完整论文中的论证功能。",
                "required_claims": [],
                "forbidden_content": (
                    ["模型名称", "最终数值", "大段题面复制"]
                    if target == "一、问题重述"
                    else []
                ),
                "preserve_argument_order": True,
                "compression": "deduplicate_only",
                "scope": scope,
            }
        )
    write_cumcm_structure_map(
        run_dir,
        {
            "template": {
                "reference_docx": "paper/reference.docx",
                "path_scope": "run",
                "usage": "styles_and_outer_structure_only",
                "placeholder_content_authoritative": False,
            },
            "source_of_truth": source_of_truth,
            "adaptation_rules": {
                "allowed": [
                    "map_sections",
                    "move_paragraphs",
                    "rewrite_headings",
                    "deduplicate_repetition",
                    "reorder_figures",
                    "repair_cross_references",
                ],
                "forbidden": [
                    "change_model",
                    "select_or_modify_numbers",
                    "create_new_conclusions",
                ],
            },
            "sections": sections,
            "page_planning": {
                "recommended_body_pages": [24, 30],
                "inspect_below_pages": 18,
                "hard_gate": False,
            },
        },
    )


def test_core_insights_are_exposed_for_paper_consumption(tmp_path: Path) -> None:
    """核心问题的实质规律可被论文阶段读取。"""
    run_dir = _run(tmp_path, "insight-exposed")
    _units_with_insight(run_dir)

    available = core_question_insights(run_dir)

    assert list(available) == ["Q1"]
    assert available["Q1"][0]["insight_id"] == "Q1-mechanism"


def test_paper_blocks_when_core_insight_is_produced_but_never_used(tmp_path: Path) -> None:
    """规律挖出来却不进论文时阻断，避免它退化成旁路产物。"""
    run_dir = _run(tmp_path, "insight-unused")
    _register(run_dir)
    _units_with_insight(run_dir)
    write_answer_map(
        run_dir,
        {
            "Q1": {
                "result_ids": ["q1-primary"],
                "primary_result_id": "q1-primary",
                "direct_answer_location": "paper/sections/q1.tex",
            }
        },
    )
    write_figure_plan(
        run_dir,
        {
            "schema_name": "figure_plan",
            "schema_version": "2.1",
            "run_id": run_dir.name,
            "visual_decisions": [
                {
                    "question_id": "Q1",
                    "status": "waived",
                    "reason": "本夹具的核心规律可由公式和直接答案完整表达，不需要额外主图。",
                }
            ],
            "figures": [],
        },
    )
    _write_structure_map(run_dir)

    status = check_paper_readiness(run_dir)

    assert not status["ready"]
    assert any("未引用任何 insight_id" in error for error in status["errors"]), status["errors"]


def test_paper_passes_when_the_answer_map_cites_the_insight(tmp_path: Path) -> None:
    """答案映射引用规律后正常放行。"""
    run_dir = _run(tmp_path, "insight-used")
    _register(run_dir)
    _units_with_insight(run_dir)
    write_answer_map(
        run_dir,
        {
            "Q1": {
                "result_ids": ["q1-primary"],
                "primary_result_id": "q1-primary",
                "direct_answer_location": "paper/sections/q1.tex",
                "insight_ids": ["Q1-mechanism"],
            }
        },
    )
    write_figure_plan(
        run_dir,
        {
            "schema_name": "figure_plan",
            "schema_version": "2.1",
            "run_id": run_dir.name,
            "visual_decisions": [
                {
                    "question_id": "Q1",
                    "status": "waived",
                    "reason": "本夹具的核心规律可由公式和直接答案完整表达，不需要额外主图。",
                }
            ],
            "figures": [],
        },
    )
    _write_structure_map(run_dir)

    status = check_paper_readiness(run_dir)

    assert status["ready"], status


def test_answer_map_cannot_cite_an_unknown_insight(tmp_path: Path) -> None:
    """引用不存在的 insight_id 时阻断，避免凭空声称讲了机制。"""
    run_dir = _run(tmp_path, "insight-phantom")
    _register(run_dir)
    _units_with_insight(run_dir)
    write_answer_map(
        run_dir,
        {
                "Q1": {
                    "result_ids": ["q1-primary"],
                    "primary_result_id": "q1-primary",
                    "direct_answer_location": "paper/sections/q1.tex",
                    "insight_ids": ["Q1-imagined"],
            }
        },
    )

    status = check_paper_readiness(run_dir)

    assert not status["ready"]
    assert any("不存在的 insight_id" in error for error in status["errors"]), status["errors"]


def test_unrecorded_stronger_alternative_is_not_allowed(tmp_path: Path) -> None:
    """未记录是否存在更强路线时不放行。"""
    run_dir = _run(tmp_path, "alternative-missing")

    assert not stronger_alternative_status(run_dir)["allowed"]


def test_found_stronger_route_must_be_attempted_or_declared_infeasible(
    tmp_path: Path,
) -> None:
    """发现更强路线时必须真的尝试，或写明赛程内不可行。"""
    run_dir = _run(tmp_path, "alternative-open")

    with pytest.raises(ContractError, match="attempted 或 infeasible_in_schedule"):
        record_stronger_alternative(
            run_dir, found=True, description="用逆向覆盖同时约束最弱实体。"
        )

    with pytest.raises(ContractError, match="必须绑定真实生产结果"):
        record_stronger_alternative(
            run_dir,
            found=True,
            description="用逆向覆盖同时约束最弱实体。",
            resolution="attempted",
        )


def test_attempted_stronger_route_must_bind_real_execution(tmp_path: Path) -> None:
    """声明已尝试更强路线时必须绑定真实执行结果。"""
    run_dir = _run(tmp_path, "alternative-attempted")

    with pytest.raises(ContractError, match="未真实执行"):
        record_stronger_alternative(
            run_dir,
            found=True,
            description="用逆向覆盖同时约束最弱实体。",
            resolution="attempted",
            result_ids=["never-ran"],
        )

    _register(run_dir, "pareto-probe")
    record = record_stronger_alternative(
        run_dir,
        found=True,
        description="用逆向覆盖同时约束最弱实体。",
        resolution="attempted",
        result_ids=["pareto-probe"],
    )

    assert record["resolution"] == "attempted"
    assert stronger_alternative_status(run_dir)["allowed"]


def test_infeasible_stronger_route_needs_a_concrete_reason(tmp_path: Path) -> None:
    """声明赛程内不可行时必须写明具体理由。"""
    run_dir = _run(tmp_path, "alternative-infeasible")

    with pytest.raises(ContractError, match="必须写明具体理由"):
        record_stronger_alternative(
            run_dir,
            found=True,
            description="完整 Pareto 前沿枚举。",
            resolution="infeasible_in_schedule",
        )

    record_stronger_alternative(
        run_dir,
        found=True,
        description="完整 Pareto 前沿枚举。",
        resolution="infeasible_in_schedule",
        reason="单点求解约 40 分钟，赛程剩余时间不足以枚举前沿。",
    )

    assert stronger_alternative_status(run_dir)["allowed"]


def test_no_stronger_alternative_is_a_valid_closed_answer(tmp_path: Path) -> None:
    """没有发现更强路线时不增加额外负担。"""
    run_dir = _run(tmp_path, "alternative-none")

    record_stronger_alternative(run_dir, found=False)

    assert stronger_alternative_status(run_dir)["allowed"]


def test_stale_stronger_route_evidence_reopens_the_gate(tmp_path: Path) -> None:
    """更强路线尝试引用的结果失效后重新阻断。"""
    run_dir = _run(tmp_path, "alternative-stale")
    _register(run_dir, "pareto-probe")
    record_stronger_alternative(
        run_dir,
        found=True,
        description="用逆向覆盖同时约束最弱实体。",
        resolution="attempted",
        result_ids=["pareto-probe"],
    )
    index_path = run_dir / "results" / "index.json"
    index: dict[str, Any] = json.loads(index_path.read_text(encoding="utf-8"))
    index["results"] = [
        item for item in index["results"] if item["result_id"] != "pareto-probe"
    ]
    index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    status = stronger_alternative_status(run_dir)

    assert not status["allowed"]
    assert "已失效" in status["reason"]
