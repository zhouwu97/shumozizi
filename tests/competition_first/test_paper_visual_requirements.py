"""验证论文论证能够自动产生视觉需求，而不恢复固定图数门。"""

from __future__ import annotations

from pathlib import Path

from shumozizi.core.io import atomic_json, load_json
from shumozizi.paper.editorial import record_paper_cold_reader_actions
from shumozizi.paper.external_author import decide_author_request
from shumozizi.paper.visual_requirements import (
    build_visual_requirements_from_paper,
    derive_visual_requirements_from_paper,
    validate_paper_visual_requirement_closure,
)
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.visual_opportunities import build_visual_opportunity_pool


def _visual_run(tmp_path: Path) -> Path:
    """构造具有五个独立视觉论证义务的最小运行。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "paper-visual-loop",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    atomic_json(
        run_dir / "analysis/MODELING_UNITS.json",
        {
            "schema_name": "modeling_units",
            "schema_version": "1.4",
            "run_id": run_dir.name,
            "units": [
                {
                    "unit_id": "u1",
                    "question_id": "Q1",
                    "unit_kind": "evaluation",
                    "core_question": False,
                    "visual_outputs": [
                        {
                            "argument_unit_id": f"argument-{index}",
                            "visual_question": f"论证关系 {index} 如何成立？",
                            "takeaway": f"关系 {index} 支撑不同的正文论证。",
                            "visual_archetype": "active-constraint plot",
                        }
                        for index in range(1, 6)
                    ],
                }
            ],
        },
    )
    atomic_json(
        run_dir / "paper/answer-map.json",
        {
            "answers": {
                "Q1": {
                    "primary_result_id": "result-q1",
                    "result_ids": ["result-q1"],
                    "objective_answer": {"result_id": "result-q1", "answer": "正式答案。"},
                }
            }
        },
    )
    return run_dir


def test_argument_driven_requirements_have_no_three_figure_cap(tmp_path: Path) -> None:
    """五个独立论证需求必须全部保留，不能隐式截断为三项。"""
    run_dir = _visual_run(tmp_path)

    payload = build_visual_requirements_from_paper(run_dir)

    assert payload["generation_policy"] == "argument_driven_no_figure_count_target"
    assert payload["summary"] == {"total": 5, "covered": 0, "open": 5}
    assert len(load_json(run_dir / "figures/visual-opportunities.json")["opportunities"]) == 5
    assert all(
        item["figure_tier"] == "supporting_figure"
        for item in payload["requirements"]
    )


def test_current_figure_covers_matching_argument_requirement(tmp_path: Path) -> None:
    """绑定同一论证单元的 current 图应关闭对应需求，而不是继续重复补图。"""
    run_dir = _visual_run(tmp_path)
    index = load_json(run_dir / "figures/index.json")
    index["figures"].append(
        {
            "figure_id": "current-argument-1",
            "question_id": "Q1",
            "role": "model_understanding",
            "argument_unit_ids": ["argument-1"],
            "status": "current",
            "paper_allowed": True,
        }
    )
    atomic_json(run_dir / "figures/index.json", index)

    payload = derive_visual_requirements_from_paper(run_dir)

    covered = [item for item in payload["requirements"] if item["status"] == "covered"]
    assert [item["requirement_id"] for item in covered] == ["VR-Q1-model_understanding"]
    assert covered[0]["covered_by_figure_ids"] == ["current-argument-1"]
    assert payload["summary"] == {"total": 5, "covered": 1, "open": 4}


def test_refresh_preserves_existing_visual_review_state(tmp_path: Path) -> None:
    """论文需求刷新不能抹掉已经完成的视觉批评或选择。"""
    run_dir = _visual_run(tmp_path)
    build_visual_requirements_from_paper(run_dir)
    path = run_dir / "figures/visual-opportunities.json"
    pool = load_json(path)
    pool["opportunities"][0].update(
        {
            "status": "drop",
            "critic_verdict": "DROP",
            "critic_path": "figures/reviews/kept.md",
        }
    )
    atomic_json(path, pool)

    build_visual_requirements_from_paper(run_dir)
    refreshed = load_json(path)

    assert len(refreshed["opportunities"]) == 5
    assert refreshed["opportunities"][0]["status"] == "drop"
    assert refreshed["opportunities"][0]["critic_verdict"] == "DROP"


def test_open_paper_requirement_blocks_candidate_closure(tmp_path: Path) -> None:
    """已启用新闭环后，未评阅的论文视觉需求不能被旧 Figure Plan 绕过。"""
    run_dir = _visual_run(tmp_path)
    build_visual_requirements_from_paper(run_dir)

    errors = validate_paper_visual_requirement_closure(run_dir)

    assert len(errors) == 5
    assert all(error.startswith("VISUAL_REQUIREMENT_OPEN") for error in errors)


def test_cold_reader_add_figure_routes_to_living_opportunity_pool(tmp_path: Path) -> None:
    """普通 ADD_FIGURE 与伴随图一样必须进入视觉生产入口。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "cold-reader-figure",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    build_visual_opportunity_pool(run_dir, opportunities=[])
    pdf = run_dir / "paper/longform-draft.pdf"
    pdf.write_bytes(b"paper")

    record_paper_cold_reader_actions(
        run_dir,
        reviewer_context_id="fresh-cold-reader",
        actions=[
            {
                "action_id": "add-q1-mechanism",
                "action": "ADD_FIGURE",
                "target_id": "Q1-mechanism",
                "reason": "核心机制仅靠文字无法快速理解。",
                "expected_benefit": "直接显示活跃约束如何决定答案。",
                "figure": {
                    "question_id": "Q1",
                    "visual_question": "哪个活跃约束决定正式答案？",
                    "atomic_claim": "活跃约束而非平均水平决定最优值。",
                    "candidate_archetypes": ["active-constraint plot"],
                },
            }
        ],
    )
    pool = load_json(run_dir / "figures/visual-opportunities.json")

    assert pool["opportunities"][0]["opportunity_id"] == "add-q1-mechanism"
    assert pool["opportunities"][0]["origin"] == "paper_cold_reader"


def test_fulfilled_author_visual_request_routes_to_opportunity_pool(tmp_path: Path) -> None:
    """Author 的视觉缺口被接受后必须形成可执行视觉机会。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "author-visual-request",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    atomic_json(
        run_dir / "paper/AUTHOR_REQUESTS.json",
        {
            "schema_name": "author_request",
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "requests": [
                {
                    "gap_id": "gap-q1-boundary",
                    "kind": "visual",
                    "affected_argument": "阈值变化决定方案切换。",
                    "request": "需要展示阈值两侧的决策变化。",
                    "why_needed": "文字难以表达切换边界。",
                    "can_continue_without_it": True,
                    "fallback": "使用正文解释边界。",
                    "recommended_route": "visual",
                    "expected_benefit": "让边界条件可见。",
                    "estimated_cost": "low",
                }
            ],
        },
    )

    decide_author_request(
        run_dir,
        [
            {
                "gap_id": "gap-q1-boundary",
                "decision": "fulfill",
                "route": "visual",
                "reason": "该图能直接补齐核心边界论证。",
            }
        ],
    )
    pool = load_json(run_dir / "figures/visual-opportunities.json")

    assert pool["opportunities"][0]["opportunity_id"] == "author-gap-q1-boundary"
    assert pool["opportunities"][0]["origin"] == "author_request"
