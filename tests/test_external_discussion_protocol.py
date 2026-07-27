"""测试网页讨论的本地先行、延迟揭示与新对话总结边界。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, load_json
from shumozizi.knowledge.external_discussion import (
    EXTERNAL_DISCUSSION_COMPARISON_PATH,
    EXTERNAL_DISCUSSION_SYNTHESIS_PATH,
    LOCAL_ROUTE_SNAPSHOT_PATH,
    create_implementation_synthesis,
    record_external_discussion_comparison,
    record_external_discussion_launch,
    validate_external_discussion_protocol_if_present,
    write_local_route_snapshot,
)
from shumozizi.simple.initialization import initialize_simple_run


def _run(tmp_path: Path) -> Path:
    """创建带题面的最小 v3.2 运行。"""
    run_dir = initialize_simple_run(
        tmp_path,
        "external-discussion",
        competition="cumcm",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    (run_dir / "problem" / "statement.md").write_text("在约束下最大化覆盖时间。", encoding="utf-8")
    return run_dir


def _local_route() -> dict[str, object]:
    """提供只依赖题面的路线快照输入。"""
    return {
        "question_id": "Q1",
        "local_route": {
            "objective": "用统一 exact 遮蔽时间比较可行策略。",
            "baseline": {
                "mathematical_structure": "离散事件规则模型",
                "summary": "先建立可复算的可行性和时间并集口径。",
            },
            "competitive_routes": [
                {
                    "route_id": "continuous",
                    "mathematical_structure": "连续约束优化",
                    "summary": "直接优化连续投放和起爆变量。",
                },
                {
                    "route_id": "decomposition",
                    "mathematical_structure": "集合覆盖分解",
                    "summary": "先构造候选库，再做时间区间组合。",
                },
            ],
            "fallback": "若 exact 与 proxy 排序反转，停止使用 proxy 并只保留可行下界。",
            "discriminating_probes": ["比较完整评分与快速 proxy 的排序是否一致。"],
            "post_first_feasible_rule": "首个可行解后必须使用结构不同的路线继续攻击 incumbent。",
        },
    }


def test_local_route_snapshot_rejects_external_reading(tmp_path: Path) -> None:
    """本地快照不能把网页回应伪装成只依题面的路线。"""
    run_dir = _run(tmp_path)
    payload = _local_route()
    payload["external_material_read"] = True

    # 写入函数固定该字段为 False；篡改落盘内容仍必须在校验时被拒绝。
    snapshot = write_local_route_snapshot(run_dir, payload)
    snapshot["external_material_read"] = True
    (run_dir / LOCAL_ROUTE_SNAPSHOT_PATH).write_text(
        json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(ContractError, match="不得读取网页回应"):
        validate_external_discussion_protocol_if_present(run_dir)


def test_comparison_requires_local_freeze_then_generates_fresh_synthesis(tmp_path: Path) -> None:
    """网页建议只能在本地路线冻结后比较，并只能导向新对话总结。"""
    run_dir = _run(tmp_path)

    with pytest.raises(ContractError, match="LOCAL_ROUTE_SNAPSHOT"):
        record_external_discussion_launch(run_dir, {"discussion_id": "web-1"})

    write_local_route_snapshot(run_dir, _local_route())
    session = record_external_discussion_launch(run_dir, {"discussion_id": "web-1"})
    assert session["local_route_disclosed"] is False
    assert session["response_read"] is False
    assert session["online_answer_search_used"] is False

    comparison = record_external_discussion_comparison(
        run_dir,
        {
            "items": [
                {
                    "local_element": "将完整评分作为最终排序口径。",
                    "external_suggestion": "先用小规模反例攻击 proxy。",
                    "relationship": "agrees",
                    "local_decision": "保留为 P0 probe。",
                    "verification": "在同一候选集上比较 proxy 与 exact 排序。",
                }
            ]
        },
    )
    assert comparison["response_read_after_local_freeze"] is True
    assert comparison["advisory_only"] is True

    synthesis = create_implementation_synthesis(run_dir)
    assert synthesis["fresh_thread_required"] is True
    assert synthesis["resume_existing_forbidden"] is True
    assert synthesis["online_answer_search_prohibited"] is True
    assert "本地 exact scorer" in synthesis["prompt"]
    assert (run_dir / EXTERNAL_DISCUSSION_COMPARISON_PATH).is_file()
    assert (run_dir / EXTERNAL_DISCUSSION_SYNTHESIS_PATH).is_file()
    validate_external_discussion_protocol_if_present(run_dir)


def test_synthesis_is_invalidated_when_local_route_changes(tmp_path: Path) -> None:
    """本地路线修订后，旧网页会话和总结都不能继续冒充当前输入。"""
    run_dir = _run(tmp_path)
    write_local_route_snapshot(run_dir, _local_route())
    record_external_discussion_launch(run_dir, {"discussion_id": "web-2"})
    record_external_discussion_comparison(
        run_dir,
        {
            "items": [
                {
                    "local_element": "连续优化路线。",
                    "external_suggestion": "增加独立 oracle。",
                    "relationship": "new_hypothesis",
                    "local_decision": "仅在几何边界触发时加入。",
                    "verification": "用独立实现复算切线与端点案例。",
                }
            ]
        },
    )
    create_implementation_synthesis(run_dir)

    revised = _local_route()
    route = revised["local_route"]
    assert isinstance(route, dict)
    route["fallback"] = "发现可行性冲突时退回保守内判据。"
    write_local_route_snapshot(run_dir, revised)

    with pytest.raises(ContractError, match="未绑定当前冻结"):
        validate_external_discussion_protocol_if_present(run_dir)
    assert load_json(run_dir / LOCAL_ROUTE_SNAPSHOT_PATH)["revision"] == 2


def test_web_paper_audit_is_pdf_only_and_requires_targeted_p0_p1_repairs(tmp_path: Path) -> None:
    """网页 PDF 审核必须绑定当前文件，并将严重问题落实到局部修复。"""
    from shumozizi.knowledge.external_discussion import (
        create_web_paper_audit_prompt,
        record_web_paper_audit,
        validate_web_paper_audit_if_present,
        web_paper_audit_status,
        write_web_paper_repair_plan,
    )

    run_dir = _run(tmp_path)
    final_pdf = run_dir / "paper" / "final.pdf"
    final_pdf.write_bytes(b"%PDF-1.4\nfixture\n")
    prompt = create_web_paper_audit_prompt(run_dir)
    assert prompt["only_pdf_and_prompt"] is True
    assert prompt["fresh_web_chat_required"] is True
    assert prompt["provider"] == "chatgpt_web"
    assert prompt["creation_mode"] == "manual_new_chat"
    assert prompt["status"] == "waiting_external_review"
    waiting = web_paper_audit_status(run_dir)
    assert waiting["status"] == "waiting_external_review"

    audit = record_web_paper_audit(
        run_dir,
        {
            "web_chat_id": "web-paper-1",
            "report": {
                "overall_assessment": "模型叙事完整，但关键结论需要更明确的证据边界。",
                "competitive_position": "相对普通参赛稿有清晰模型主线，但尚不能据此推断奖项。",
                "readability": "符号定义应靠近首次使用位置。",
                "argument_and_evidence": "一个结论没有把图与指标直接对应。",
                "format_and_aesthetics": "表格列宽需要收紧。",
                "figures": "一张图的图例与曲线距离过近。",
                "repair_strategy": "优先补证据引用和图例，再重新编译复核。",
            },
            "findings": [
                {
                    "finding_id": "web-p1-evidence",
                    "priority": "P1",
                    "location": "第 4 节结论段",
                    "issue": "结论未直接对应指标和图。",
                    "impact": "读者无法判断结论的证据范围。",
                    "proposed_fix": "在结论后补充结果编号、图号和限制。",
                    "verification": "重新编译后逐项核对正文、图注和指标。",
                },
                {
                    "finding_id": "web-p2-legend",
                    "priority": "P2",
                    "location": "图 3",
                    "issue": "图例可能与曲线过近。",
                    "impact": "降低局部可读性。",
                    "proposed_fix": "移动图例并扩大边距。",
                    "verification": "渲染 PDF 页面并人工查看。",
                },
            ],
        },
    )
    assert audit["online_answer_search_used"] is False
    assert audit["provider"] == "chatgpt_web"
    assert audit["creation_mode"] == "manual_new_chat"
    assert audit["status"] == "review_received"
    status = web_paper_audit_status(run_dir)
    assert status["allowed"] is False
    assert status["blocking_findings"] == ["web-p1-evidence"]

    # P0/P1 必须出现在修复计划里；只闭合 P2 会被拒绝。
    # （disposition=defer_with_limit 本身是允许的，审核者可以写明限制而不修改。）
    with pytest.raises(ContractError, match="P0/P1"):
        write_web_paper_repair_plan(
            run_dir,
            {
                "repairs": [
                    {
                        "finding_id": "web-p2-legend",
                        "disposition": "fix",
                        "files": ["figures/current/figure.png"],
                        "action": "移动图例。",
                        "revalidation": ["PDF 渲染"],
                    },
                ],
                "stop_criterion": "没有未修复 P0/P1，且修复页通过 PDF 渲染与机械 QA。",
            },
        )

    plan = write_web_paper_repair_plan(
        run_dir,
        {
            "repairs": [
                {
                    "finding_id": "web-p1-evidence",
                    "disposition": "fix",
                    "files": ["paper/sections/results.tex"],
                    "action": "补充对应的结果编号、图号和限制。",
                    "revalidation": ["重新编译", "机械 QA"],
                },
                {
                    "finding_id": "web-p2-legend",
                    "disposition": "fix",
                    "files": ["figures/current/figure.png"],
                    "action": "移动图例并扩大边距。",
                    "revalidation": ["PDF 渲染"],
                },
            ],
            "stop_criterion": "没有未修复 P0/P1，且修复页通过 PDF 渲染与机械 QA。",
        },
    )
    assert plan["full_rewrite"] is False
    assert plan["competition_rank_guarantee"] is False
    validate_web_paper_audit_if_present(run_dir)

    final_pdf.write_bytes(b"%PDF-1.4\nchanged\n")
    with pytest.raises(ContractError, match="PDF 已发生变化"):
        validate_web_paper_audit_if_present(run_dir)


def test_legacy_web_paper_audit_files_remain_compatible(tmp_path: Path) -> None:
    """新增人工等待状态后，旧 v3.2 网页审核文件仍可继续复验。"""
    from shumozizi.core.io import atomic_json
    from shumozizi.knowledge.external_discussion import (
        WEB_PAPER_AUDIT_PATH,
        WEB_PAPER_AUDIT_PROMPT_PATH,
        create_web_paper_audit_prompt,
        record_web_paper_audit,
        validate_web_paper_audit_if_present,
        web_paper_audit_status,
    )

    run_dir = _run(tmp_path)
    (run_dir / "paper/final.pdf").write_bytes(b"%PDF-1.4\nlegacy-web-audit\n")
    prompt = create_web_paper_audit_prompt(run_dir)
    for field in ("provider", "creation_mode", "status"):
        prompt.pop(field)
    atomic_json(run_dir / WEB_PAPER_AUDIT_PROMPT_PATH, prompt)
    audit = record_web_paper_audit(
        run_dir,
        {
            "web_chat_id": "legacy-web-paper",
            "report": "未发现新的 P0/P1，建议继续机械 QA。",
            "findings": [],
        },
    )
    for field in ("provider", "creation_mode", "status"):
        audit.pop(field)
    atomic_json(run_dir / WEB_PAPER_AUDIT_PATH, audit)

    validate_web_paper_audit_if_present(run_dir)
    status = web_paper_audit_status(run_dir)

    assert status["allowed"] is True
    assert status["status"] == "review_closed"


def test_web_paper_audit_stops_after_max_unresolved_rounds(tmp_path: Path) -> None:
    """达到轮次上限仍有 P0/P1 时必须复盘，且不得继续创建下一轮审核。

    轮次上限由 WEB_PAPER_AUDIT_MAX_ROUNDS 决定（当前为 1 轮），测试不写死轮数，
    这样上限调整时不会留下一个仍然断言旧轮数的过期测试。
    """
    from shumozizi.knowledge.external_discussion import (
        WEB_PAPER_AUDIT_FAILURE_PATH,
        WEB_PAPER_AUDIT_HISTORY_DIR,
        WEB_PAPER_AUDIT_MAX_ROUNDS,
        create_web_paper_audit_prompt,
        record_web_paper_audit,
        web_paper_audit_status,
        write_web_paper_audit_failure,
    )

    run_dir = _run(tmp_path)
    final_pdf = run_dir / "paper" / "final.pdf"
    final_pdf.write_bytes(b"%PDF-1.4\nround-1\n")

    for round_number in range(1, WEB_PAPER_AUDIT_MAX_ROUNDS + 1):
        prompt = create_web_paper_audit_prompt(run_dir)
        assert prompt["round_number"] == round_number
        record_web_paper_audit(
            run_dir,
            {
                "web_chat_id": f"web-paper-{round_number}",
                "report": {
                    "overall_assessment": "关键主张仍缺少可由论文内部核对的证据。",
                    "competitive_position": "暂不能据此推断奖项。",
                    "readability": "结果段需要更清楚地定位证据。",
                    "argument_and_evidence": "主结论没有对应到当前指标。",
                    "format_and_aesthetics": "版式仍需局部整理。",
                    "figures": "图表需要明确支撑关系。",
                    "repair_strategy": "优先修复主结论证据链。",
                },
                "findings": [
                    {
                        "finding_id": f"round-{round_number}-p1",
                        "priority": "P1",
                        "location": "第 4 节结论段",
                        "issue": "主结论未绑定指标和图表。",
                        "impact": "无法判断结论的证据范围。",
                        "proposed_fix": "补充结果编号、图号和限制。",
                        "verification": "重编译后核对正文、图注和指标。",
                    }
                ],
            },
        )
        if round_number < WEB_PAPER_AUDIT_MAX_ROUNDS:
            final_pdf.write_bytes(f"%PDF-1.4\nround-{round_number + 1}\n".encode())

    blocked = web_paper_audit_status(run_dir)
    assert blocked["allowed"] is False
    assert blocked["round_count"] == WEB_PAPER_AUDIT_MAX_ROUNDS
    assert "必须写入失败复盘" in blocked["reason"]
    # 每轮开始时归档上一轮，因此历史数量比总轮数少一。
    history = list((run_dir / WEB_PAPER_AUDIT_HISTORY_DIR).glob("*.json"))
    assert len(history) == WEB_PAPER_AUDIT_MAX_ROUNDS - 1

    failure = write_web_paper_audit_failure(
        run_dir,
        {
            "summary": "达到网页审核轮次上限后，核心论证链仍未达到可提交标准。",
            "workflow_issues": ["过晚才把关键结论映射到可复算证据。"],
            "modeling_issues": ["模型假设与结论边界没有充分闭合。"],
            "evidence_issues": ["关键指标、图表与主张之间缺少直接绑定。"],
            "paper_issues": ["结论段未清楚区分观察、机制和限制。"],
            "next_actions": ["回到建模与实验阶段补齐证据后再重写相关章节。"],
        },
    )
    assert failure["status"] == "not_submission_ready"
    assert (run_dir / WEB_PAPER_AUDIT_FAILURE_PATH).is_file()
    assert "已写入失败复盘" in web_paper_audit_status(run_dir)["reason"]

    with pytest.raises(ContractError, match=f"{WEB_PAPER_AUDIT_MAX_ROUNDS} 轮上限"):
        create_web_paper_audit_prompt(run_dir)
