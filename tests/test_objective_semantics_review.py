"""验证实验前目标语义预审能阻断共享题意误解。"""

from __future__ import annotations

from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.review import (
    build_review_packet,
    import_objective_semantics_review,
    objective_semantics_review_status,
)
from shumozizi.simple.state import update_simple_state


def _assessment(run_id: str, *, ambiguous: bool = False) -> dict:
    """构造含求和、并集和交集备选目标的最小评估。"""
    return {
        "schema_name": "objective_semantics_assessment",
        "schema_version": "1.0",
        "run_id": run_id,
        "source_scope": "problem_only",
        "network_used": False,
        "questions": [
            {
                "question_id": "Q5",
                "interpretations": [
                    {
                        "objective_id": "sum_per_missile",
                        "formula": "sum_i mu(U_i)",
                        "unit": "s",
                        "aggregation": "sum_per_entity",
                        "language_basis": ["题面要求总有效干扰时长"],
                    },
                    {
                        "objective_id": "union_any",
                        "formula": "mu(union_i U_i)",
                        "unit": "s",
                        "aggregation": "union_any",
                        "language_basis": ["至少一个对象受干扰的时间并集"],
                    },
                    {
                        "objective_id": "intersection_all",
                        "formula": "mu(intersection_i U_i)",
                        "unit": "s",
                        "aggregation": "intersection_all",
                        "language_basis": ["全部对象同一时刻受干扰"],
                    },
                ],
                "selected_objective_id": "sum_per_missile",
                "selection_basis": "language_evidence" if ambiguous else "declared_assumption",
                "selection_confidence": "ambiguous" if ambiguous else "high",
                "materiality": "high" if ambiguous else "low",
                "human_confirmation_required": ambiguous,
                "diagnostic_objective_ids": ["union_any", "intersection_all"],
                "ambiguity_note": "同时可能描述动作安排，而非三重交集" if ambiguous else "",
                "language_evidence_ref": {
                    "source_file": "statement.md",
                    "page_or_line": "1",
                    "excerpt": "题面要求总有效干扰时长",
                    "how_it_excludes_alternatives": "明确使用'总'字表明求和语义"
                } if ambiguous else {},
                "decision_space": {
                    "action_cardinality": "variable",
                    "allowed_action_count": 15,
                    "language_basis": ["题面允许每个平台投放至多三枚。"],
                },
            }
        ],
    }


def _prepare_run(tmp_path: Path) -> Path:
    """创建带正式题面和单个必答问题的生产运行。"""
    statement = tmp_path / "statement.md"
    statement.write_text("问题五：同时干扰三枚来袭目标，并求总有效干扰时长。", encoding="utf-8")
    return initialize_simple_run(
        tmp_path,
        "objective-semantics",
        problem_path=statement,
        required_questions=["Q5"],
    )


def _manifest_relative(packet: dict) -> str:
    """返回审查包清单的运行内路径。"""
    return f"review/packet/{packet['packet_kind']}/{packet['packet_id']}/manifest.json"


def test_formal_problem_cannot_enter_capability_route_without_semantics_review(
    tmp_path: Path,
) -> None:
    """正式题面必须先由只读题面的独立任务确认目标语义。"""
    run_dir = _prepare_run(tmp_path)

    with pytest.raises(ContractError, match="目标语义预审"):
        update_simple_state(run_dir, phase="capability_route")

    packet = build_review_packet(run_dir, kind="objective-semantics")
    manifest = load_json(run_dir / _manifest_relative(packet))
    assert {item["source"].split("/", 1)[0] for item in manifest["files"]} == {"problem"}


def test_ambiguous_interpretation_cannot_claim_language_evidence_is_decisive(
    tmp_path: Path,
) -> None:
    """仍有多种合理聚合时必须记录裁决或显式假设。"""
    run_dir = _prepare_run(tmp_path)
    packet = build_review_packet(run_dir, kind="objective-semantics")
    atomic_json(run_dir / "review" / "OBJECTIVE_SEMANTICS.json", _assessment(run_dir.name, ambiguous=True))
    (run_dir / "review" / "OBJECTIVE_SEMANTICS_REVIEW.md").write_text(
        "# 目标语义预审\n\n仅依据题面比较了求和、并集和交集。\n",
        encoding="utf-8",
    )

    with pytest.raises(ContractError, match="用户裁决或显式建模假设"):
        import_objective_semantics_review(
            run_dir,
            manifest_file=_manifest_relative(packet),
            verdict="pass",
            highest_severity="none",
            reviewer_thread_id="objective-review-thread",
        )


def test_passed_semantics_review_is_hash_bound_and_required_for_route(tmp_path: Path) -> None:
    """目标选择通过后可进入路由，评估漂移后立即失效。"""
    run_dir = _prepare_run(tmp_path)
    packet = build_review_packet(run_dir, kind="objective-semantics")
    assessment_path = run_dir / "review" / "OBJECTIVE_SEMANTICS.json"
    # 使用单一聚合 + user_decision 避免语义冲突机器判定阻断
    # Q5 有三解释 → 有冲突 → 需要 user_decision 而不是 language_evidence
    assessment = _assessment(run_dir.name, ambiguous=True)
    assessment["questions"][0]["selection_basis"] = "user_decision"
    atomic_json(assessment_path, assessment)
    # 必须绑定人工裁决文件
    atomic_json(
        run_dir / "state" / "ambiguity-decisions.json",
        {
            "schema_name": "ambiguity_decisions",
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "decisions": [
                {
                    "question_id": "Q5",
                    "selected_objective_id": "sum_per_missile",
                    "confirmed": True,
                    "raw_user_response": "按逐目标有效时长求和作为主目标。",
                }
            ],
            "confirmed_at": "2026-07-24T00:00:00Z",
        },
    )
    (run_dir / "review" / "OBJECTIVE_SEMANTICS_REVIEW.md").write_text(
        "# 目标语义预审\n\n仅依据题面确认主目标，其他口径只作诊断。\n",
        encoding="utf-8",
    )
    import_objective_semantics_review(
        run_dir,
        manifest_file=_manifest_relative(packet),
        verdict="pass",
        highest_severity="none",
        reviewer_thread_id="objective-review-thread",
    )

    update_simple_state(run_dir, phase="capability_route")
    update_simple_state(run_dir, phase="analysis")
    changed = _assessment(run_dir.name)
    changed["questions"][0]["selected_objective_id"] = "intersection_all"
    atomic_json(assessment_path, changed)

    assert not objective_semantics_review_status(run_dir)["allowed"]
    with pytest.raises(ContractError, match="目标语义预审"):
        update_simple_state(run_dir, phase="capability_route")


def test_high_materiality_ambiguity_requires_hash_bound_human_decision(tmp_path: Path) -> None:
    """高影响目标歧义必须绑定用户原话，裁决漂移后立即失效。"""
    run_dir = _prepare_run(tmp_path)
    packet = build_review_packet(run_dir, kind="objective-semantics")
    assessment = _assessment(run_dir.name, ambiguous=True)
    assessment["questions"][0]["selection_basis"] = "user_decision"
    atomic_json(run_dir / "review" / "OBJECTIVE_SEMANTICS.json", assessment)
    atomic_json(
        run_dir / "state" / "ambiguity-decisions.json",
        {
            "schema_name": "ambiguity_decisions",
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "decisions": [
                {
                    "question_id": "Q5",
                    "selected_objective_id": "sum_per_missile",
                    "confirmed": True,
                    "raw_user_response": "按逐目标有效时长求和作为主目标。",
                }
            ],
            "confirmed_at": "2026-07-24T00:00:00Z",
        },
    )
    (run_dir / "review" / "OBJECTIVE_SEMANTICS_REVIEW.md").write_text(
        "# 目标语义预审\n\n保留备选解释，并绑定了用户对主目标的明确裁决。\n",
        encoding="utf-8",
    )
    receipt = import_objective_semantics_review(
        run_dir,
        manifest_file=_manifest_relative(packet),
        verdict="pass",
        highest_severity="none",
        reviewer_thread_id="objective-human-review-thread",
    )

    assert "ambiguity_decisions" in receipt
    decisions = load_json(run_dir / "state" / "ambiguity-decisions.json")
    decisions["decisions"][0]["raw_user_response"] = "改为并集口径。"
    atomic_json(run_dir / "state" / "ambiguity-decisions.json", decisions)
    assert not objective_semantics_review_status(run_dir)["allowed"]


def test_medium_confidence_with_conflicting_aggregations_is_machine_blocked(
    tmp_path: Path,
) -> None:
    """回归：machine 判定不能通过把 selection_confidence 写成 medium 绕过。

    当同一问题同时存在 sum_per_entity 和 intersection_all 两种聚合，
    且题面语言不能唯一排除时，必须要求用户裁决，不论 AI 自评 confidence 为何。
    """
    run_dir = _prepare_run(tmp_path)
    packet = build_review_packet(run_dir, kind="objective-semantics")

    # 构造 exact 绕过场景：高影响 + medium 置信度 + declared_assumption
    assessment = _assessment(run_dir.name)
    assessment["questions"][0]["materiality"] = "high"
    assessment["questions"][0]["selection_confidence"] = "medium"
    assessment["questions"][0]["selection_basis"] = "declared_assumption"
    assessment["questions"][0]["human_confirmation_required"] = False
    assessment["questions"][0]["ambiguity_note"] = "题面未唯一规定跨三枚导弹求和或交集"

    atomic_json(run_dir / "review" / "OBJECTIVE_SEMANTICS.json", assessment)
    (run_dir / "review" / "OBJECTIVE_SEMANTICS_REVIEW.md").write_text(
        "# 目标语义预审\n\n题面可解释为求和或交集，选择求和作为建模假设。\n",
        encoding="utf-8",
    )

    # 应被 machine 字段拦截，不再允许绕过
    with pytest.raises(ContractError, match=r"用户裁决|绕过"):
        import_objective_semantics_review(
            run_dir,
            manifest_file=_manifest_relative(packet),
            verdict="pass",
            highest_severity="none",
            reviewer_thread_id="objective-review-thread",
        )


def test_machine_derived_fields_are_populated_on_valid_assessment(
    tmp_path: Path,
) -> None:
    """非冲突评估也应补充 machine 字段，便于下游统一消费。"""
    run_dir = _prepare_run(tmp_path)
    packet = build_review_packet(run_dir, kind="objective-semantics")

    # 使用 user_decision + 显式冲突裁决避免 language_evidence 语义冲突拦截
    assessment = _assessment(run_dir.name, ambiguous=True)
    assessment["questions"][0]["selection_basis"] = "user_decision"
    atomic_json(run_dir / "review" / "OBJECTIVE_SEMANTICS.json", assessment)
    # 必须绑定人工裁决文件
    atomic_json(
        run_dir / "state" / "ambiguity-decisions.json",
        {
            "schema_name": "ambiguity_decisions",
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "decisions": [
                {
                    "question_id": "Q5",
                    "selected_objective_id": "sum_per_missile",
                    "confirmed": True,
                    "raw_user_response": "求和为主目标。",
                }
            ],
            "confirmed_at": "2026-07-24T00:00:00Z",
        },
    )
    (run_dir / "review" / "OBJECTIVE_SEMANTICS_REVIEW.md").write_text(
        "# 目标语义预审\n\n确认主目标。\n",
        encoding="utf-8",
    )
    receipt = import_objective_semantics_review(
        run_dir,
        manifest_file=_manifest_relative(packet),
        verdict="pass",
        highest_severity="none",
        reviewer_thread_id="objective-review-thread",
    )

    # 读取评估以验证 machine 字段已被补入
    assessment = load_json(run_dir / "review" / "OBJECTIVE_SEMANTICS.json")
    q = assessment["questions"][0]
    assert "distinct_aggregation_count" in q
    assert "distinct_aggregations" in q
    assert "changes_primary_result" in q
    assert isinstance(q["changes_primary_result"], bool)
    assert "user_decision_required" in q
    # 该评估有 3 种不同聚合（sum_per_entity, union_any, intersection_all）
    # 包含 sum+intersection 冲突对 → changes_primary_result=true
    assert q["changes_primary_result"] is True
    assert q["distinct_aggregation_count"] == 3
    # 冲突存在 + language 不能唯一排除 + 但已显式 user_decision
    # → user_decision_required=False (因 selection_basis 已是 user_decision)
    assert q["user_decision_required"] is True
    assert q["changes_primary_result"] is True
    assert receipt["verdict"] == "pass"


def test_conflicting_aggregations_with_user_decision_marks_decision_required(
    tmp_path: Path,
) -> None:
    """当 AI 选择 declared_assumption 而非 language_evidence 时，冲突必须要求用户裁决。"""
    run_dir = _prepare_run(tmp_path)
    packet = build_review_packet(run_dir, kind="objective-semantics")

    assessment = _assessment(run_dir.name, ambiguous=True)
    assessment["questions"][0]["selection_basis"] = "declared_assumption"
    atomic_json(run_dir / "review" / "OBJECTIVE_SEMANTICS.json", assessment)
    (run_dir / "review" / "OBJECTIVE_SEMANTICS_REVIEW.md").write_text(
        "# 目标语义预审\n\n存在冲突聚合，选择求和作为建模假设。\n",
        encoding="utf-8",
    )

    with pytest.raises(ContractError, match=r"用户裁决|绕过"):
        import_objective_semantics_review(
            run_dir,
            manifest_file=_manifest_relative(packet),
            verdict="pass",
            highest_severity="none",
            reviewer_thread_id="objective-review-thread",
        )
