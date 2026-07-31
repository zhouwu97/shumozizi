"""验证类型化知识使用合同与视觉模式提取。"""

from __future__ import annotations

from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.knowledge.retrieval import _visual_patterns
from shumozizi.knowledge.usage import (
    build_knowledge_usage_report,
    build_paper_knowledge_context,
    build_visual_pattern_suggestions,
    knowledge_usage_errors,
    record_knowledge_usage_outcomes,
)
from shumozizi.simple.figures import _require_learned_visual_pattern_contract
from shumozizi.simple.initialization import initialize_simple_run


def _run(tmp_path: Path, run_id: str) -> Path:
    """创建最小运行目录并写入一个可绑定的建模单元。"""
    run_dir = initialize_simple_run(
        tmp_path, run_id, workflow_version="3.2", required_questions=["Q1"]
    )
    atomic_json(
        run_dir / "analysis/MODELING_UNITS.json",
        {"units": [{"unit_id": "Q1-main", "question_id": "Q1"}]},
    )
    return run_dir


def _retrieval(run_dir: Path, accepted: list[dict[str, object]], rejected: list[dict[str, object]] | None = None) -> None:
    """写入供 usage 报告读取的最小检索记录。"""
    rejected = rejected or []
    candidate_ids = [
        str(item["pattern_id"])
        for item in [*accepted, *rejected]
        if isinstance(item.get("pattern_id"), str)
    ]
    atomic_json(
        run_dir / "knowledge/analysis-retrieval.json",
        {
            "schema_name": "knowledge_retrieval",
            "schema_version": "1.0",
            "stage": "analysis",
            "run_id": run_dir.name,
            "status": "matched",
            "task_fingerprint": {
                "problem_type": "测试问题",
                "data_structure": "结构化数据",
                "task_types": ["优化"],
                "statistical_units": [],
                "mathematical_difficulties": [],
                "objective_structures": [],
                "constraint_types": [],
                "validation_risks": [],
                "question_chain": [],
                "structural_tags": [],
                "keywords": [],
            },
            "matched_cards": [
                {
                    "paper_id": "paper-1",
                    "title": "结构模式卡",
                    "score": 1.0,
                    "structural_similarity": 0.8,
                    "domain_similarity": 0.2,
                    "matched_on": ["结构匹配"],
                    "candidate_patterns": [
                        {"pattern_id": pattern_id, "pattern": "只迁移结构并由当前题重新验证"}
                        for pattern_id in candidate_ids
                    ],
                }
            ],
            "accepted_patterns": accepted,
            "rejected_patterns": rejected,
            "forbidden_transfer": ["原题参数", "公式和代码", "数值结论", "奖项评价"],
            "no_match_reason": None,
            "unavailable_reason": None,
        },
    )


def _typed(pattern_id: str = "paper-1:P1", **changes: object) -> dict[str, object]:
    """返回一个完整的路线知识采用记录。"""
    item: dict[str, object] = {
        "pattern_id": pattern_id,
        "reason": "当前题共享约束使该结构值得验证。",
        "route_application": "在当前题中改为联合建模并比较自然基线。",
        "application_layer": "analysis_route",
        "target_ids": ["Q1-main"],
        "current_problem_basis": ["Q1 与后续问题共享同一资源约束。"],
        "adaptation": "只迁移联合建模的结构思想，变量和约束由当前题重新定义。",
        "expected_effect": "减少分问独立求解造成的资源冲突。",
        "falsification_condition": "若联合模型与精确分解完全一致，则撤销该结构优势。",
        "status": "planned",
    }
    item.update(changes)
    return item


def test_typed_adoption_binds_existing_model_target(tmp_path: Path) -> None:
    """类型化路线知识绑定真实建模单元时可通过分析阶段。"""
    run_dir = _run(tmp_path, "typed-adoption")
    _retrieval(run_dir, [_typed()])

    report = build_knowledge_usage_report(run_dir, stage="analysis")

    assert knowledge_usage_errors(report) == []
    assert (run_dir / "paper/generated/knowledge_usage.json").is_file()


def test_typed_adoption_rejects_unknown_target_and_paper_planned_state(tmp_path: Path) -> None:
    """未知目标和未验证的 planned 模式不能进入论文。"""
    run_dir = _run(tmp_path, "typed-errors")
    _retrieval(
        run_dir,
        [_typed(target_ids=["Q9"], status="planned")],
    )
    (run_dir / "paper/KNOWLEDGE_APPLICATION.md").write_text(
        "## `paper-1:P1`\n\n- 写作决定：采用\n", encoding="utf-8"
    )

    analysis_errors = knowledge_usage_errors(build_knowledge_usage_report(run_dir, stage="analysis"))
    paper_errors = knowledge_usage_errors(build_knowledge_usage_report(run_dir, stage="paper"))

    assert any("target_ids 不存在" in item for item in analysis_errors)
    assert any("不能把知识模式" in item for item in paper_errors)


def test_rejected_pattern_leaking_into_model_contract_is_reported(tmp_path: Path) -> None:
    """分析阶段拒绝的模式不得通过文字出现在建模合同。"""
    run_dir = _run(tmp_path, "rejected-leak")
    _retrieval(
        run_dir,
        [],
        [{"pattern_id": "paper-1:P2", "reason": "当前题不具备该模式的适用条件。"}],
    )
    atomic_json(
        run_dir / "analysis/MODELING_UNITS.json",
        {"units": [{"unit_id": "Q1-main", "question_id": "Q1", "note": "paper-1:P2"}]},
    )

    report = build_knowledge_usage_report(run_dir)

    assert any("已拒绝知识模式" in item for item in knowledge_usage_errors(report))


def test_outcome_update_is_atomic_and_paper_context_is_filtered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """结果不足时不落盘；证据齐全后只输出安全的写作上下文。"""
    run_dir = _run(tmp_path, "usage-outcome")
    _retrieval(run_dir, [_typed()])
    retrieval_path = run_dir / "knowledge/analysis-retrieval.json"
    before = retrieval_path.read_bytes()
    outcome = {
        "pattern_id": "paper-1:P1",
        "status": "validated",
        "evidence_result_ids": ["q1-current"],
        "observed_effect": "联合建模消除了共享资源重复占用。",
        "conclusion": "保留联合建模结构，但不宣称知识卡证明当前结论。",
    }

    with pytest.raises(ContractError, match="非 current production"):
        record_knowledge_usage_outcomes(run_dir, [outcome])
    assert retrieval_path.read_bytes() == before

    monkeypatch.setattr(
        "shumozizi.knowledge.usage._current_result_ids", lambda _run_dir: {"q1-current"}
    )
    record_knowledge_usage_outcomes(run_dir, [outcome])
    context = build_paper_knowledge_context(run_dir)

    assert context["patterns"][0]["allowed_claim"] == outcome["conclusion"]
    assert context["patterns"][0]["evidence_result_ids"] == ["q1-current"]
    assert "route_application" not in context["patterns"][0]


def test_visual_pattern_card_is_structured_and_keeps_transfer_boundary() -> None:
    """论文卡视觉模式保留原型、面板和不可迁移边界。"""
    body = """
## 视觉模式

```yaml
visual_patterns:
  - pattern_id: feasible-boundary-zoom
    visual_archetype: feasible_region_active_constraints
    information_structure: tradeoff
    argument_roles: [model_structure, boundary, decision]
    panel_layout:
      rows: 1
      columns: 2
    reading_order: [overview, local_zoom]
    visible_elements: [feasible_region, active_constraint, selected_point]
    required_data_fields: [candidate_points, feasible_mask, active_constraints, selected_point]
    applicable_when:
      - 候选解具有可投影的决策空间
    not_applicable_when:
      - 结果只有一个标量且没有边界结构
    transferable_principle:
      - 先展示全局结构，再放大决定方案的局部边界
```
"""

    patterns = _visual_patterns(body, "paper-1")

    assert patterns[0]["visual_archetype"] == "feasible_region_active_constraints"
    assert patterns[0]["reading_order"] == ["overview", "local_zoom"]
    assert "selected_point" in patterns[0]["visible_elements"]
    assert "candidate_points" in patterns[0]["required_data_fields"]


def test_figure_plan_only_uses_adopted_matching_visual_pattern(tmp_path: Path) -> None:
    """学习视觉模式必须已采用并与当前图原型和义务一致。"""
    run_dir = _run(tmp_path, "visual-plan-binding")
    visual_pattern = {
        "pattern_id": "paper-1:V1",
        "visual_archetype": "feasible_region_active_constraints",
        "argument_roles": ["model_structure", "boundary"],
        "reading_order": ["overview", "local_zoom"],
        "visible_elements": ["feasible_region", "active_constraint"],
        "required_data_fields": ["candidate_points", "feasible_mask", "active_constraints"],
        "applicable_when": ["当前题存在可投影的二维可行域"],
        "not_applicable_when": ["当前题只有无结构的单一标量结果"],
        "transferable_principle": ["先展示全局结构，再放大活跃约束"],
    }
    atomic_json(
        run_dir / "knowledge/analysis-retrieval.json",
        {
            "matched_cards": [{"visual_patterns": [visual_pattern]}],
            "accepted_patterns": [
                {
                    "pattern_id": "paper-1:P1",
                    "application_layer": "visual_design",
                    "visual_pattern_ids": ["paper-1:V1"],
                    "figure_ids": ["q1-boundary"],
                }
            ],
        },
    )
    atomic_json(
        run_dir / "analysis/MODELING_UNITS.json",
        {
            "units": [
                {
                    "unit_id": "Q1-main",
                    "question_id": "Q1",
                    "core_question": True,
                    "visual_outputs": [
                        {
                            "argument_unit_id": "Q1-boundary",
                            "visual_question": "活跃约束如何决定当前方案",
                            "required_data": [
                                "candidate_points",
                                "feasible_mask",
                                "active_constraints",
                            ],
                            "output_path": "results/raw/q1-boundary.json",
                        }
                    ],
                }
            ]
        },
    )
    figure = {
        "figure_id": "q1-boundary",
        "question_id": "Q1",
        "visual_archetype": "feasible_region_active_constraints",
        "obligation_types": ["model_structure", "boundary"],
        "argument_unit_ids": ["Q1-boundary"],
        "learned_pattern_ids": ["paper-1:V1"],
        "learned_pattern_adaptation": "使用当前题候选点重绘可行域，并只保留当前活跃约束。",
    }

    _require_learned_visual_pattern_contract(run_dir, {"figures": [figure]})

    with pytest.raises(ContractError, match="原型"):
        _require_learned_visual_pattern_contract(
            run_dir,
            {"figures": [{**figure, "visual_archetype": "uncertainty_fan_with_threshold"}]},
        )


def test_visual_suggestion_rejects_pattern_without_current_structure_data(tmp_path: Path) -> None:
    """视觉模式不能在当前 visual_outputs 缺字段时伪装成可用 renderer。"""
    run_dir = _run(tmp_path, "visual-data-rejection")
    visual_pattern = {
        "pattern_id": "paper-1:V1",
        "visual_archetype": "feasible_region_active_constraints",
        "argument_roles": ["model_structure", "boundary"],
        "reading_order": ["overview", "local_zoom"],
        "visible_elements": ["feasible_region", "active_constraint"],
        "required_data_fields": ["candidate_points", "feasible_mask", "active_constraints"],
        "applicable_when": ["当前题存在可投影的二维可行域"],
        "not_applicable_when": ["当前题只有无结构的单一标量结果"],
        "transferable_principle": ["先展示全局结构，再放大活跃约束"],
    }
    atomic_json(
        run_dir / "knowledge/analysis-retrieval.json",
        {
            "matched_cards": [{"visual_patterns": [visual_pattern]}],
            "accepted_patterns": [
                {
                    "pattern_id": "paper-1:P1",
                    "application_layer": "visual_design",
                    "visual_pattern_ids": ["paper-1:V1"],
                    "figure_ids": ["q1-boundary"],
                }
            ],
        },
    )
    atomic_json(
        run_dir / "analysis/MODELING_UNITS.json",
        {
            "units": [
                {
                    "unit_id": "Q1-main",
                    "question_id": "Q1",
                    "core_question": True,
                    "visual_outputs": [
                        {
                            "argument_unit_id": "Q1-boundary",
                            "required_data": ["candidate_points"],
                            "output_path": "results/raw/q1-boundary.json",
                        }
                    ],
                }
            ]
        },
    )

    report = build_visual_pattern_suggestions(run_dir)

    assert report["recommendations"] == []
    assert report["rejections"][0]["missing_data_fields"] == [
        "active_constraints",
        "feasible_mask",
    ]
    retrieval = load_json(run_dir / "knowledge/analysis-retrieval.json")
    retrieval["accepted_patterns"] = []
    atomic_json(run_dir / "knowledge/analysis-retrieval.json", retrieval)
    candidate_report = build_visual_pattern_suggestions(run_dir)
    assert candidate_report["rejections"][0]["adoption_status"] == "candidate"


def test_validation_and_paper_bindings_must_exist_in_current_run(tmp_path: Path) -> None:
    """验证知识和论文结构知识必须落到当前合同与真实正文锚点。"""
    run_dir = _run(tmp_path, "typed-layer-bindings")
    atomic_json(
        run_dir / "analysis/MODELING_UNITS.json",
        {
            "units": [
                {
                    "unit_id": "Q1-main",
                    "question_id": "Q1",
                    "validation": {"robustness": {"required": True}},
                }
            ]
        },
    )
    validation = _typed(
        application_layer="validation_design",
        validation_bindings=[
            {
                "target_id": "Q1-main",
                "validation_kind": "robustness",
                "metric": "decision_flip_rate",
                "pass_criterion": "扰动后方案翻转率不超过事前阈值。",
            }
        ],
    )
    _retrieval(run_dir, [validation])
    assert knowledge_usage_errors(build_knowledge_usage_report(run_dir, stage="analysis")) == []

    paper = _typed(
        application_layer="paper_structure",
        target_ids=["共享模型"],
        paper_bindings=[
            {
                "blueprint_anchor": "共享模型",
                "source_path": "paper/sections/q1.tex",
                "realization_anchor": "先定义共享状态，再回答第一问",
            }
        ],
        status="validated",
        evidence_result_ids=["q1-current"],
        observed_effect="共享对象减少了跨问重复定义。",
        conclusion="保留共享模型入口并逐问说明增量。",
    )
    _retrieval(run_dir, [paper])
    (run_dir / "paper/PAPER_BLUEPRINT.md").write_text(
        "# 蓝图\n\n## 共享模型\n\n先建立统一状态。\n", encoding="utf-8"
    )
    (run_dir / "paper/sections").mkdir(parents=True, exist_ok=True)
    (run_dir / "paper/main.tex").write_text(
        "\\input{sections/q1}\n", encoding="utf-8"
    )
    (run_dir / "paper/sections/q1.tex").write_text(
        "先定义共享状态，再回答第一问。\n", encoding="utf-8"
    )
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "shumozizi.knowledge.usage._current_result_ids", lambda _run_dir: {"q1-current"}
        )
        assert knowledge_usage_errors(build_knowledge_usage_report(run_dir, stage="paper")) == []

    (run_dir / "paper/sections/q1.tex").write_text("正文没有计划锚点。\n", encoding="utf-8")
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "shumozizi.knowledge.usage._current_result_ids", lambda _run_dir: {"q1-current"}
        )
        errors = knowledge_usage_errors(build_knowledge_usage_report(run_dir, stage="paper"))
    assert any("正文兑现锚点不存在" in item for item in errors)
