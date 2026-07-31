"""论证覆盖、独立冷读边界与 PAPER_REVIEW 闭环回归。"""

from __future__ import annotations

from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.paper.blueprint import (
    build_argument_coverage,
    paper_blueprint_review_prompt,
    parse_paper_blueprint,
    validate_argument_coverage,
)
from shumozizi.paper.checkpoints import (
    paper_checkpoint_errors,
    record_first_draft_cold_read_checkpoint,
    record_paper_blueprint_review_checkpoint,
    validate_first_draft_cold_read_checkpoint,
)
from shumozizi.paper.paper_review import (
    close_paper_review_finding,
    first_draft_cold_read_prompt,
    merge_paper_review_findings,
    paper_review_status,
    parse_paper_review,
    unclosed_high_priority_findings,
)
from shumozizi.paper.readiness import (
    derive_required_visual_obligations,
    presentation_figure_warnings,
    validate_figure_argument_obligations,
    validate_presentation_decisions,
)
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.state import read_simple_state


def _question_card(question_id: str, *, core: bool) -> str:
    """生成字段齐全的逐问完整性卡。"""
    common = {
        "题面要求": "给出题面目标下可直接核验的方案与数值。",
        "继承": "继承前问的共享状态、评价口径与约束集合。",
        "新增困难": "新增共享资源，使原有独立决策转为联合判定。",
        "数学对象": "共享状态上的可行域与目标函数。",
        "建模依据": "题面量词和资源关系直接支持这一对象。",
        "关键推导": "先消去冗余变量，再导出联合约束的等价形式。",
        "求解过程": "用精确评分器比较基线与结构不同的候选路线。",
        "主结果": "当前方案在统一指标下达到可行且更优的结果。",
        "结果解释": "改善来自共享资源被活跃约束重新分配。",
        "机制或规律": "边际收益随资源增加递减，瓶颈转移到第二约束。",
        "验证": "用独立复算和扰动实验排除偶然数值误差。",
        "适用边界": "结论仅适用于题面参数范围与当前聚合口径。",
        "直接答案": "采用所列联合方案，并报告题面目标的最终数值。",
    }
    lines = [f"## {question_id} 完整性卡", ""]
    lines.extend(f"- **{label}**：{value}" for label, value in common.items())
    if core:
        lines.extend(
            [
                "",
                "### 要支持的判断",
                "联合求解优于分别求解后直接组合。",
                "",
                "### 计算证据",
                "同预算 exact scorer 对照显示联合路线改善 8%。",
                "",
                "### 竞争解释",
                "用同一初值对照排除了改善仅由初值造成的解释。",
            ]
        )
    return "\n".join(lines)


def _complete_blueprint() -> str:
    """返回一份包含普通问和核心问的完整蓝图。"""
    return (
        "# PAPER_BLUEPRINT\n\n"
        "## 全篇中心判断\n\n共享数学对象贯穿全部问题。\n\n"
        "## 跨问题论证链\n\nQ2 继承 Q1 并增加联合资源约束。\n\n"
        + _question_card("Q1", core=False)
        + "\n\n"
        + _question_card("Q2", core=True)
        + "\n"
    )


def _new_run(tmp_path: Path, name: str = "paper-blueprint") -> Path:
    """初始化两问 v3.2 运行，并把 Q2 标记为核心问题。"""
    run_dir = initialize_simple_run(
        tmp_path,
        name,
        required_questions=["Q1", "Q2"],
        workflow_version="3.2",
    )
    modeling = load_json(run_dir / "analysis/MODELING_UNITS.json")
    modeling["units"] = [{"question_id": "Q1"}, {"question_id": "Q2", "core_question": True}]
    atomic_json(run_dir / "analysis/MODELING_UNITS.json", modeling)
    return run_dir


def _finding(*, finding_id: str = "FD-001", severity: str = "P1") -> dict[str, object]:
    """生成可导入的批量返修 finding。"""
    return {
        "finding_id": finding_id,
        "severity": severity,
        "finding": "Q2 共享模型只能依赖密集公式理解。",
        "impact": "冷读者无法快速复述共享参数与独立参数。",
        "affected_argument_units": ["Q2-shared-model"],
        "repair_type": "argument+figure",
        "target_files": ["paper/PAPER_BLUEPRINT.md", "paper/main.tex"],
        "expected_benefit": "建立共享模型的清晰阅读路径。",
        "estimated_cost": "约一小时",
        "acceptance_test": "冷读者能复述共享与独立参数。",
        "stop_condition": "图和正文闭环后不继续扩图。",
    }


def test_blueprint_parser_requires_core_specific_obligations() -> None:
    """旧蓝图无需新增全局写作区也继续兼容逐问论证合同。"""
    complete = parse_paper_blueprint(
        _complete_blueprint(),
        run_id="run-1",
        required_questions=["Q1", "Q2"],
        core_questions=["Q2"],
    )
    assert complete["complete"] is True
    assert validate_argument_coverage(complete) == []

    missing = parse_paper_blueprint(
        _complete_blueprint().replace("### 竞争解释", "### 未命名讨论"),
        run_id="run-1",
        required_questions=["Q1", "Q2"],
        core_questions=["Q2"],
    )
    assert missing["complete"] is False
    assert "Q2 缺少论证义务 alternative_explanation" in validate_argument_coverage(missing)


def test_new_run_templates_add_author_layer_without_breaking_machine_contract(
    tmp_path: Path,
) -> None:
    """新模板增加证据蒸馏和冷读说明，同时保留逐问及返修机器接口。"""
    run_dir = _new_run(tmp_path, "argument-driven-templates")
    blueprint_text = (run_dir / "paper/PAPER_BLUEPRINT.md").read_text(encoding="utf-8")

    assert "## 全局证据蒸馏" in blueprint_text
    assert "## 跨问题论证链与连续成文" in blueprint_text
    assert "## 正文与附录边界" in blueprint_text
    assert "## Q1 完整性卡" in blueprint_text
    assert "## Q2 完整性卡" in blueprint_text
    parsed = parse_paper_blueprint(
        blueprint_text,
        run_id=run_dir.name,
        required_questions=["Q1", "Q2"],
        core_questions=["Q2"],
    )
    assert [item["question_id"] for item in parsed["questions"]] == ["Q1", "Q2"]
    assert parsed["questions"][1]["core_question"] is True
    assert "key_judgment" in parsed["questions"][1]["obligations"]

    review_text = (run_dir / "paper/PAPER_REVIEW.md").read_text(encoding="utf-8")
    assert "## 评委冷读" in review_text
    assert "## 返修原则" in review_text
    assert "<!-- PAPER_REVIEW_FINDINGS:START -->" in review_text
    review = parse_paper_review(review_text)
    assert review["schema_name"] == "paper_review"
    assert review["run_id"] == run_dir.name
    assert review["findings"] == []


def test_argument_coverage_is_atomic_run_bound_derivative(tmp_path: Path) -> None:
    """覆盖矩阵从运行内蓝图生成，且拒绝输出到运行目录之外。"""
    run_dir = _new_run(tmp_path)
    (run_dir / "paper/PAPER_BLUEPRINT.md").write_text(_complete_blueprint(), encoding="utf-8")

    document = build_argument_coverage(run_dir)

    output = run_dir / "paper/generated/argument_coverage.json"
    assert output.is_file()
    assert load_json(output) == document
    assert document["source"]["path"] == "paper/PAPER_BLUEPRINT.md"
    assert document["complete"] is True
    with pytest.raises(ContractError, match="越过运行目录边界"):
        build_argument_coverage(run_dir, output_path="../../argument_coverage.json")


def test_blueprint_review_prompt_has_fixed_input_boundary(tmp_path: Path) -> None:
    """蓝图审核只能读取题目摘要和三个允许的论文规划输入。"""
    run_dir = _new_run(tmp_path, "blueprint-prompt")
    (run_dir / "problem/PROBLEM_SUMMARY.md").write_text("两问共享同一资源约束。", encoding="utf-8")
    (run_dir / "paper/PAPER_BLUEPRINT.md").write_text(_complete_blueprint(), encoding="utf-8")
    atomic_json(run_dir / "paper/answer-map.json", {"answers": {"Q1": {}, "Q2": {}}})
    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "figures": [
                {
                    "figure_id": "shared-model",
                    "caption": "共享参数结构",
                    "visual_question": "两问如何共享资源？",
                    "decision_consequence": "联合求解不能分解。",
                }
            ]
        },
    )
    prompt = paper_blueprint_review_prompt(
        run_dir, problem_summary_path="problem/PROBLEM_SUMMARY.md"
    )

    assert "<INPUT_BOUNDARY>" in prompt
    assert "continue_writing 或 return_blueprint" in prompt
    assert "两问共享同一资源约束" in prompt
    assert "最终 PDF" in prompt
    with pytest.raises(ContractError, match="problem/"):
        paper_blueprint_review_prompt(
            run_dir, problem_summary_path="paper/PAPER_BLUEPRINT.md"
        )


def test_first_draft_cold_read_accepts_only_paper_pdf(tmp_path: Path) -> None:
    """首稿冷读提示固定三分钟、逐问、逐图检查，且不允许附件越界。"""
    run_dir = _new_run(tmp_path, "cold-read")
    (run_dir / "paper/draft-1.pdf").write_bytes(b"%PDF-1.4\n")
    prompt = first_draft_cold_read_prompt(run_dir)

    assert "唯一允许的输入" in prompt
    assert "三分钟冷读" in prompt
    assert "question_checks" in prompt
    assert "figure_checks" in prompt
    assert "continue_revision 或 ready_for_candidate" in prompt
    assert "最多 5 项" in prompt
    with pytest.raises(ContractError, match="paper/ 下的 PDF"):
        first_draft_cold_read_prompt(run_dir, pdf_path="analysis/MODELING_UNITS.json")


def test_paper_review_p0_p1_needs_strong_closure(tmp_path: Path) -> None:
    """接受风险或延期不能关闭 P0/P1，只有修复或误报证据可以放行。"""
    run_dir = _new_run(tmp_path, "paper-review")
    input_path = run_dir / "review/first-draft-cold-read.json"
    atomic_json(input_path, {"findings": [_finding()]})

    imported = merge_paper_review_findings(
        run_dir,
        input_path="review/first-draft-cold-read.json",
        source="first_draft_cold_read",
    )
    assert unclosed_high_priority_findings(imported) == ["FD-001"]
    assert paper_review_status(run_dir)["candidate_allowed"] is False

    accepted = close_paper_review_finding(
        run_dir,
        finding_id="FD-001",
        status="accepted",
        evidence_of_closure=["作者已知悉该风险，但尚未完成返修。"],
    )
    assert unclosed_high_priority_findings(accepted) == ["FD-001"]

    repaired = close_paper_review_finding(
        run_dir,
        finding_id="FD-001",
        status="repaired",
        evidence_of_closure=["paper/main.tex 第 4 章已增加结构图与解释段。"],
    )
    assert unclosed_high_priority_findings(repaired) == []
    assert paper_review_status(run_dir)["candidate_allowed"] is True


def test_paper_review_rejects_invalid_combination_and_target(tmp_path: Path) -> None:
    """组合返修类型不能重复，目标文件也不能越过运行目录。"""
    run_dir = _new_run(tmp_path, "paper-review-invalid")
    invalid = _finding(severity="P2")
    invalid["repair_type"] = "argument+argument"
    invalid["target_files"] = ["../../outside.tex"]
    atomic_json(run_dir / "review/invalid.json", {"findings": [invalid]})

    with pytest.raises(ContractError, match="repair_type 不得重复组合"):
        merge_paper_review_findings(
            run_dir,
            input_path="review/invalid.json",
            source="first_draft_cold_read",
        )


def test_three_result_figures_do_not_cover_model_and_mechanism(tmp_path: Path) -> None:
    """每问一张结果图不能冒充共享模型、数学对象和决策机制覆盖。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "result-only-figures",
        required_questions=["Q1", "Q2", "Q3"],
        workflow_version="3.2",
    )
    atomic_json(
        run_dir / "analysis/MODELING_UNITS.json",
        {
            "schema_version": "1.4",
            "run_id": run_dir.name,
            "units": [
                {"question_id": "Q1", "core_question": False},
                {
                    "question_id": "Q2",
                    "core_question": True,
                    "mathematical_structure": "共享模型与共享参数形成联合可行域",
                },
                {
                    "question_id": "Q3",
                    "core_question": True,
                    "mathematical_structure": "模型选择与不确定性下的稳健决策",
                },
            ],
        },
    )
    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "schema_name": "figure_plan",
            "schema_version": "2.4",
            "run_id": run_dir.name,
            "visual_decisions": [
                {
                    "scope": scope,
                    "evidence_need": "required",
                    "presentation_need": "required",
                    "reason": "该问题需要正文主图呈现主要结果和判断依据。",
                }
                for scope in ("Q1", "Q2", "Q3", "whole_paper")
            ],
            "figures": [
                {
                    "figure_id": f"{question_id.lower()}-fit",
                    "question_id": question_id,
                    "required": True,
                    "role": "decisive_evidence",
                    "obligation_types": ["result"],
                }
                for question_id in ("Q1", "Q2", "Q3")
            ],
        },
    )

    errors = validate_figure_argument_obligations(run_dir)

    assert "Q2 缺少 mathematical_object/model_structure 图表义务覆盖" in errors
    assert "Q3 缺少 mechanism/comparison/decision 图表义务覆盖" in errors
    assert "whole_paper 缺少共享数学对象或跨问模型结构表达" in errors


def test_visual_obligations_derive_uncertainty_from_structured_output() -> None:
    """bootstrap 场景分布不能被只有均值结果的图掩盖。"""
    obligations = derive_required_visual_obligations(
        {
            "question_id": "Q1",
            "core_question": False,
            "visual_outputs": [
                {
                    "argument_unit_id": "Q1-uncertainty",
                    "visual_question": "置信带是否跨过决策阈值",
                    "required_data": [
                        "bootstrap_quantiles",
                        "scenario_distribution",
                        "decision_threshold",
                    ],
                    "output_path": "results/raw/q1-uncertainty.json",
                }
            ],
        }
    )

    assert {"uncertainty", "boundary"} <= obligations


def test_uncertainty_requires_matching_figure_obligation(tmp_path: Path) -> None:
    """声明 bootstrap 数据后，仅覆盖 result 必须报告 uncertainty 缺口。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "uncertainty-result-only",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    atomic_json(
        run_dir / "analysis/MODELING_UNITS.json",
        {
            "schema_version": "1.4",
            "run_id": run_dir.name,
            "units": [
                {
                    "question_id": "Q1",
                    "core_question": False,
                    "visual_outputs": [
                        {
                            "required_data": ["bootstrap_quantiles", "scenario_distribution"],
                            "visual_question": "不同场景下排序是否翻转",
                        }
                    ],
                }
            ],
        },
    )
    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "schema_version": "2.4",
            "visual_decisions": [],
            "figures": [
                {
                    "figure_id": "q1-mean",
                    "question_id": "Q1",
                    "required": True,
                    "role": "decisive_evidence",
                    "obligation_types": ["result"],
                }
            ],
        },
    )

    assert "Q1 缺少 uncertainty 图表义务覆盖" in validate_figure_argument_obligations(
        run_dir
    )


def test_active_constraints_require_boundary_obligation(tmp_path: Path) -> None:
    """可行域与活跃约束不能由最终得分图替代。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "active-constraint-score-only",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    atomic_json(
        run_dir / "analysis/MODELING_UNITS.json",
        {
            "schema_version": "1.4",
            "run_id": run_dir.name,
            "units": [
                {
                    "question_id": "Q1",
                    "core_question": False,
                    "visual_outputs": [
                        {
                            "required_data": [
                                "candidate_points",
                                "feasible_mask",
                                "active_constraints",
                            ],
                            "visual_question": "哪个活跃约束限制最终方案",
                        }
                    ],
                }
            ],
        },
    )
    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "schema_version": "2.4",
            "visual_decisions": [],
            "figures": [
                {
                    "figure_id": "q1-score",
                    "question_id": "Q1",
                    "required": True,
                    "role": "decisive_evidence",
                    "obligation_types": ["result"],
                }
            ],
        },
    )

    errors = validate_figure_argument_obligations(run_dir)
    assert "Q1 缺少 boundary 图表义务覆盖" in errors


def test_three_dense_figures_can_cover_all_derived_obligations(tmp_path: Path) -> None:
    """完整义务可由三张高密度图覆盖，门禁不退化为图数指标。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "dense-three-figures",
        required_questions=["Q1", "Q2", "Q3"],
        workflow_version="3.2",
    )
    units = []
    for question_id in ("Q1", "Q2", "Q3"):
        units.append(
            {
                "question_id": question_id,
                "core_question": True,
                "mathematical_structure": "三问共享模型、可行域与稳健决策",
                "visual_outputs": [
                    {
                        "required_data": [
                            "candidate_points",
                            "feasible_mask",
                            "active_constraints",
                            "bootstrap_quantiles",
                        ],
                        "visual_question": "结构、边界与不确定性如何共同决定方案",
                    }
                ],
            }
        )
    atomic_json(
        run_dir / "analysis/MODELING_UNITS.json",
        {"schema_version": "1.4", "run_id": run_dir.name, "units": units},
    )
    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "schema_version": "2.4",
            "visual_decisions": [],
            "figures": [
                {
                    "figure_id": f"{question_id.lower()}-evidence-chain",
                    "question_id": question_id,
                    "required": True,
                    "role": "decisive_evidence",
                    "obligation_types": [
                        "model_structure",
                        "mechanism",
                        "result",
                        "boundary",
                        "uncertainty",
                    ],
                }
                for question_id in ("Q1", "Q2", "Q3")
            ],
        },
    )

    assert validate_figure_argument_obligations(run_dir) == []


def test_structural_visual_waiver_requires_independent_review(tmp_path: Path) -> None:
    """共享模型存在时，全部 waived 不能再沿最短路径绕过展示任务。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "structural-waiver",
        required_questions=["Q1", "Q2"],
        workflow_version="3.2",
    )
    atomic_json(
        run_dir / "analysis/MODELING_UNITS.json",
        {
            "schema_version": "1.4",
            "run_id": run_dir.name,
            "units": [
                {
                    "question_id": "Q1",
                    "core_question": False,
                    "mathematical_structure": "两问共享模型和共享参数",
                },
                {"question_id": "Q2", "core_question": True},
            ],
        },
    )
    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "schema_name": "figure_plan",
            "schema_version": "2.4",
            "run_id": run_dir.name,
            "visual_decisions": [
                {
                    "scope": scope,
                    "evidence_need": "waived",
                    "presentation_need": "waived",
                    "reason": "作者认为公式已经足够，但尚未经过独立冷读复核。",
                }
                for scope in ("Q1", "Q2", "whole_paper")
            ],
            "figures": [],
        },
    )

    errors = validate_presentation_decisions(run_dir)

    assert "结构性展示需求 Q1=waived，但缺少独立 waiver_review" in errors
    assert "结构性展示需求 Q2=waived，但缺少独立 waiver_review" in errors
    assert "结构性展示需求 whole_paper=waived，但缺少独立 waiver_review" in errors


@pytest.mark.parametrize("schema_version", ["2.3", "2.4"])
def test_presentation_warning_supports_current_and_legacy_plans(
    tmp_path: Path, schema_version: str
) -> None:
    """2.3/2.4 的 required 呈现需求缺少 hero 时都应产生 advisory。"""
    run_dir = initialize_simple_run(
        tmp_path,
        f"presentation-warning-{schema_version.replace('.', '-')}",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "schema_name": "figure_plan",
            "schema_version": schema_version,
            "run_id": run_dir.name,
            "visual_decisions": [
                {
                    "scope": "Q1",
                    "evidence_need": "waived",
                    "presentation_need": "required",
                    "reason": "Q1 需要主图帮助评委快速识别结论和决策后果。",
                }
            ],
            "figures": [],
        },
    )

    assert presentation_figure_warnings(run_dir) == [
        "呈现需求 Q1 声明为 required，但缺少 question_hero 图；"
        "当前仅提示，不自动要求增加低价值图。"
    ]


def test_presentation_warning_accepts_v24_question_hero(tmp_path: Path) -> None:
    """2.4 已规划对应 hero 时不应产生展示缺口 warning。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "presentation-warning-satisfied",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "schema_name": "figure_plan",
            "schema_version": "2.4",
            "run_id": run_dir.name,
            "visual_decisions": [
                {
                    "scope": "Q1",
                    "evidence_need": "required",
                    "presentation_need": "required",
                    "reason": "Q1 需要正文主图呈现主要结果和决策依据。",
                }
            ],
            "figures": [
                {
                    "figure_id": "q1-hero",
                    "question_id": "Q1",
                    "presentation_role": "question_hero",
                }
            ],
        },
    )

    assert presentation_figure_warnings(run_dir) == []


def test_candidate_keeps_historical_checkpoints_after_batch_revision(tmp_path: Path) -> None:
    """批量返修可以改蓝图和正文，但审核报告与 finding 导入仍须可追溯。"""
    run_dir = _new_run(tmp_path, "checkpoint-history")
    (run_dir / "paper/PAPER_BLUEPRINT.md").write_text(
        _complete_blueprint(), encoding="utf-8"
    )
    atomic_json(run_dir / "paper/answer-map.json", {"answers": {"Q1": {}, "Q2": {}}})
    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "schema_name": "figure_plan",
            "schema_version": "2.4",
            "run_id": run_dir.name,
            "visual_decisions": [],
            "figures": [],
        },
    )
    atomic_json(
        run_dir / "review/paper-blueprint-review.json",
        {
            "schema_name": "paper_blueprint_review",
            "schema_version": "1.0",
            "decision": "continue_writing",
            "findings": [],
        },
    )
    record_paper_blueprint_review_checkpoint(
        run_dir,
        report_path="review/paper-blueprint-review.json",
        reviewer_context_id="independent-blueprint-context",
    )
    (run_dir / "paper/draft-1.pdf").write_bytes(b"%PDF-1.4\nfirst draft")
    atomic_json(
        run_dir / "review/first-draft-cold-read.json",
        {
            "schema_name": "first_draft_cold_read",
            "schema_version": "1.0",
            "decision": "continue_revision",
            "pdf_path": "paper/draft-1.pdf",
            "findings": [],
        },
    )
    record_first_draft_cold_read_checkpoint(
        run_dir,
        report_path="review/first-draft-cold-read.json",
        reviewer_context_id="independent-cold-read-context",
    )
    assert paper_checkpoint_errors(run_dir, candidate=True) == []

    # 返修按冷读 finding 改变论证修订；历史 checkpoint 证明审核动作发生过，
    # 最终 PDF 盲评另行绑定新的 argument_revision。
    (run_dir / "paper/PAPER_BLUEPRINT.md").write_text(
        _complete_blueprint() + "\n批量返修已改善阅读路径。\n", encoding="utf-8"
    )
    state = read_simple_state(run_dir)
    state["argument_revision"] = int(state["argument_revision"]) + 1
    atomic_json(run_dir / "state/run.json", state)

    assert any(
        "argument_revision 已变化" in item
        for item in validate_first_draft_cold_read_checkpoint(run_dir)
    )
    assert paper_checkpoint_errors(run_dir, candidate=True) == []
