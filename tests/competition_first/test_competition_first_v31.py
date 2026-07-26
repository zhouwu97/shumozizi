"""覆盖 Competition-First v3.1 的核心门禁收缩与事实保留。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.paper.readiness import (
    build_argument_map_from_current_artifacts,
    check_paper_readiness,
)
from shumozizi.simple import review as review_module
from shumozizi.simple.competition import (
    validate_next_experiments,
    validate_route_competition,
    write_answer_map,
)
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.method_facts import write_method_facts
from shumozizi.simple.objective_semantics import (
    objective_semantics_for_question,
    objective_semantics_review_required,
)
from shumozizi.simple.results import register_result
from shumozizi.simple.review import (
    build_review_packet,
    mechanical_qa_status,
    paper_blind_review_prompt,
    paper_blind_review_prompt_sha256,
    record_paper_blind_review_skip,
)
from shumozizi.simple.review_focus import (
    record_scientific_challenge_evidence,
    verify_scientific_challenge_evidence,
    write_focused_followup,
)
from shumozizi.simple.review_tasks import (
    create_review_task_receipt,
    persist_review_task_creation_event,
    validate_review_task_receipt,
)
from shumozizi.simple.state import read_simple_state, update_simple_state, utc_now
from tests.quality_protocol_helpers import record_passing_scientific_review


def _run_dir(tmp_path: Path, run_id: str = "competition-first") -> Path:
    """创建一个最小 v3.1 运行目录。"""
    return initialize_simple_run(tmp_path, run_id, required_questions=["Q1"])


def _register_current_result(
    run_dir: Path,
    *,
    result_id: str = "q1_primary",
    objective: float = 1.0,
    method_facts: dict[str, bool | str] | None = None,
    output_name: str = "q1.json",
) -> None:
    """登记一个可供 answer map 使用的真实当前结果。"""
    source = run_dir / "code" / "q1.py"
    output = run_dir / "results" / "raw" / output_name
    source.write_text("print('ok')\n", encoding="utf-8")
    output.write_text(json.dumps({"metrics": {"objective": objective}}), encoding="utf-8")
    now = utc_now()
    register_result(
        run_dir,
        result_id=result_id,
        question_id="Q1",
        kind="primary",
        command="python code/q1.py",
        source_script="code/q1.py",
        input_files=["code/q1.py"],
        output_files=[f"results/raw/{output_name}"],
        metrics={"objective": objective},
        metric_sources={
            "objective": {
                "file": f"results/raw/{output_name}",
                "json_path": "metrics.objective",
            }
        },
        exit_code=0,
        stdout_path="results/q1.stdout.log",
        stderr_path="results/q1.stderr.log",
        started_at=now,
        finished_at=now,
        duration_seconds=0.1,
        objective_semantics_sha256="a" * 64,
        method_facts=method_facts,
    )


def test_new_run_uses_reduced_phase_set(tmp_path: Path) -> None:
    """新运行不再需要 capability route 才能进入实验。"""
    run_dir = _run_dir(tmp_path)

    state = update_simple_state(run_dir, phase="experiment")

    assert state["schema_version"] == "3.1"
    assert state["workflow"] == "competition-first-v3.1"
    assert state["phase"] == "experiment"


def test_old_phase_maps_in_memory_and_migrates_on_write(tmp_path: Path) -> None:
    """旧 v3 状态可读，不在读取时改写文件。"""
    run_dir = _run_dir(tmp_path, "legacy-run")
    state_path = run_dir / "state" / "run.json"
    old = json.loads(state_path.read_text(encoding="utf-8"))
    old["schema_version"] = "3.0"
    old["phase"] = "scientific_review"
    atomic_json(state_path, old)

    mapped = read_simple_state(run_dir)

    assert mapped["phase"] == "experiment"
    assert mapped["legacy_phase"] == "scientific_review"
    assert json.loads(state_path.read_text(encoding="utf-8"))["phase"] == "scientific_review"

    update_simple_state(run_dir, current_question="Q1")

    written = json.loads(state_path.read_text(encoding="utf-8"))
    migration = json.loads((run_dir / "state" / "migrations.json").read_text(encoding="utf-8"))
    assert written["schema_version"] == "3.1"
    assert migration["original_phase"] == "scientific_review"


def test_objective_review_is_conditional(tmp_path: Path) -> None:
    """普通措辞差异不触发，未决高影响歧义才触发。"""
    run_dir = _run_dir(tmp_path)
    path = run_dir / "analysis" / "objective-ambiguities.json"
    atomic_json(
        path,
        {
            "ambiguities": [
                {
                    "question_id": "Q1",
                    "candidate_interpretations": ["逐对象求和"],
                    "can_change_primary_result": False,
                    "resolved_by_problem_text": True,
                    "resolution": "题面公式",
                }
            ]
        },
    )
    assert not objective_semantics_review_required(run_dir)

    atomic_json(
        path,
        {
            "ambiguities": [
                {
                    "question_id": "Q1",
                    "candidate_interpretations": ["逐对象求和", "时间并集"],
                    "can_change_primary_result": True,
                    "resolved_by_problem_text": False,
                    "resolution": None,
                }
            ]
        },
    )
    assert objective_semantics_review_required(run_dir)


def test_unambiguous_formal_problem_can_bind_production_result(tmp_path: Path) -> None:
    """正式题面不再因为没有无关的目标语义审核而阻断实验。"""
    run_dir = _run_dir(tmp_path)
    (run_dir / "problem" / "statement.md").write_text("目标为最小化成本。", encoding="utf-8")

    digest = objective_semantics_for_question(run_dir, "Q1")

    assert len(digest) == 64


def test_route_tournament_rejects_solver_variants_only() -> None:
    """同一数学结构的不同求解器不能伪装成路线竞争。"""
    payload = {
        "baseline": {"mathematical_structure": "固定目标的整数规划"},
        "candidates": [
            {"mathematical_structure": "固定目标的整数规划", "probe": "更换遗传算法"}
        ],
    }

    assert validate_route_competition(payload)
    assert validate_next_experiments({"experiments": [{"name": "装饰性图"}]})


def test_paper_readiness_uses_answer_map_not_manual_argument_map(tmp_path: Path) -> None:
    """v3.1 从当前答案和结果自动生成后台 argument map。"""
    run_dir = _run_dir(tmp_path)
    _register_current_result(run_dir)
    write_answer_map(
        run_dir,
        {
            "Q1": {
                "result_ids": ["q1_primary"],
                "direct_answer_location": "paper/sections/q1.tex",
            }
        },
    )

    status = check_paper_readiness(run_dir)
    generated = build_argument_map_from_current_artifacts(run_dir)

    assert status["ready"], status
    assert generated["claims"][0]["result_ids"] == ["q1_primary"]
    assert (run_dir / "paper" / "generated" / "argument_map.json").is_file()


def test_scientific_challenge_requires_real_current_execution(tmp_path: Path) -> None:
    """自由挑战必须绑定实际执行结果，不能只由报告文字放行。"""
    run_dir = _run_dir(tmp_path)
    _register_current_result(run_dir)

    record_scientific_challenge_evidence(
        run_dir,
        result_ids=["q1_primary"],
        attack_description="用独立小规模实例攻击当前目标排序。",
    )

    assert verify_scientific_challenge_evidence(run_dir)["valid"]


def test_scientific_challenge_accepts_registered_legacy_output_file_evidence(
    tmp_path: Path,
) -> None:
    """旧文件级挑战证据仍须同时匹配登记输出哈希和实际输出文件。"""
    run_dir = _run_dir(tmp_path)
    _register_current_result(run_dir)
    output = run_dir / "results" / "raw" / "q1.json"
    atomic_json(
        run_dir / "review" / "scientific-challenge-evidence.json",
        {
            "schema_version": "1.1",
            "run_id": run_dir.name,
            "attack_description": "独立复算当前结果。",
            "results": [
                {
                    "result_id": "q1_primary",
                    "file": "results/raw/q1.json",
                    "sha256": sha256_file(output),
                }
            ],
        },
    )

    assert verify_scientific_challenge_evidence(run_dir)["valid"]

    output.write_text('{"metrics": {"objective": 2.0}}', encoding="utf-8")

    assert not verify_scientific_challenge_evidence(run_dir)["valid"]


def test_scientific_challenge_keeps_intact_superseded_comparison_evidence(
    tmp_path: Path,
) -> None:
    """已验证的生产级路线对照不应因 winner 更新而被误判为漂移。"""
    run_dir = _run_dir(tmp_path)
    _register_current_result(
        run_dir,
        result_id="q1_comparison",
        objective=1.0,
        output_name="q1-comparison.json",
    )
    _register_current_result(
        run_dir,
        result_id="q1_selected",
        objective=2.0,
        output_name="q1-selected.json",
    )

    receipt = record_scientific_challenge_evidence(
        run_dir,
        result_ids=["q1_selected"],
        comparison_result_ids=["q1_comparison"],
        attack_description="保留路线收益与稳健性取舍的已验证反例。",
    )

    assert receipt["schema_version"] == "1.2"
    assert verify_scientific_challenge_evidence(run_dir)["valid"]

    (run_dir / "results" / "raw" / "q1-comparison.json").write_text(
        '{"metrics": {"objective": 3.0}}', encoding="utf-8"
    )

    assert not verify_scientific_challenge_evidence(run_dir)["valid"]


def test_explicit_result_method_facts_override_heuristic_inference(tmp_path: Path) -> None:
    """实验登记的事实优先于指标名和源码关键词。"""
    run_dir = _run_dir(tmp_path)
    _register_current_result(
        run_dir,
        method_facts={
            "uses_continuous_time": True,
            "uses_discrete_approximation": True,
            "uses_proxy_objective": False,
        },
    )

    facts = write_method_facts(run_dir)

    assert facts["facts"]["uses_continuous_time"] is True
    assert facts["facts"]["uses_discrete_approximation"] is True
    assert facts["facts"]["uses_proxy_objective"] is False


def test_scientific_followup_is_limited_to_one(tmp_path: Path) -> None:
    """集中挑战只允许一个决定性专项追问。"""
    run_dir = _run_dir(tmp_path)
    write_focused_followup(
        run_dir,
        "# 决定性追问\n\n执行独立小规模枚举，确认当前排序是否翻转，并记录可复现输入、输出和结论。",
    )

    with pytest.raises(ContractError, match="最多允许一个"):
        write_focused_followup(run_dir, "# 第二次追问\n\n这不应被允许，因为同一轮已经存在专项追问。")


def _force_paper_review_with_pdf(run_dir: Path) -> None:
    """为盲审合同单测构造最小 paper_review 状态。"""
    state_path = run_dir / "state" / "run.json"
    state = load_json(state_path)
    state["phase"] = "paper_review"
    atomic_json(state_path, state)
    (run_dir / "paper" / "final.pdf").write_bytes(b"%PDF-1.4\nminimal")


def test_final_blind_review_uses_fresh_pdf_only_prompt(tmp_path: Path) -> None:
    """最终盲审包只暴露冻结 PDF，并为全新顶层任务生成固定提示词。"""
    run_dir = _run_dir(tmp_path, "paper-blind-fresh-context")
    _force_paper_review_with_pdf(run_dir)

    packet = build_review_packet(run_dir, kind="paper-blind")
    manifest_file = f"review/packet/paper-blind/{packet['packet_id']}/manifest.json"
    manifest = load_json(run_dir / manifest_file)
    copied = {item["source"] for item in manifest["files"]}
    prompt = paper_blind_review_prompt(run_dir, manifest_file)
    frozen_pdf = (
        run_dir
        / "review"
        / "packet"
        / "paper-blind"
        / packet["packet_id"]
        / "paper"
        / "final.pdf"
    ).resolve()

    assert copied == {"paper/final.pdf"}
    assert prompt.startswith("严格审核这份冻结 PDF")
    assert "学术论文，而非内部技术或审核报告" in prompt
    assert str(frozen_pdf) in prompt
    assert "SCIENTIFIC_CHALLENGE" not in prompt
    assert "results" not in prompt


def test_final_blind_review_receipt_rejects_changed_prompt(tmp_path: Path) -> None:
    """最终盲审任务回执不能用任意提示词哈希冒充全新严格审核。"""
    run_dir = _run_dir(tmp_path, "paper-blind-prompt-binding")
    _force_paper_review_with_pdf(run_dir)
    packet = build_review_packet(run_dir, kind="paper-blind")
    manifest_file = f"review/packet/paper-blind/{packet['packet_id']}/manifest.json"
    report = run_dir / "review" / "PAPER_BLIND_REVIEW.md"
    report.write_text("# 严格审核\n\n发现一项需要修复的问题。\n", encoding="utf-8")
    bindings = {
        "packet": {
            "manifest_file": manifest_file,
            "manifest_sha256": sha256_file(run_dir / manifest_file),
        }
    }
    receipt = create_review_task_receipt(
        run_dir,
        task_id="paper-blind-wrong-prompt",
        task_type="paper_blind_open",
        thread_id="fresh-top-level-thread",
        model_id="fixture-model",
        prompt_sha256="4" * 64,
        input_bindings=bindings,
        report_file=report.relative_to(run_dir).as_posix(),
    )

    with pytest.raises(ContractError, match="规定的独立审核提示词"):
        validate_review_task_receipt(
            run_dir,
            receipt.relative_to(run_dir).as_posix(),
            expected_type="paper_blind_open",
            expected_report=report.relative_to(run_dir).as_posix(),
            expected_input_bindings=bindings,
            expected_prompt_sha256=paper_blind_review_prompt_sha256(
                run_dir, manifest_file
            ),
        )


def test_production_blind_review_skip_does_not_allow_complete(tmp_path: Path) -> None:
    """生产运行的盲评跳过只能继续 QA，不能伪装成 complete。"""
    run_dir = _run_dir(tmp_path)
    _register_current_result(run_dir)
    record_passing_scientific_review(run_dir)
    record_paper_blind_review_skip(run_dir, "独立盲评服务当前不可用，已记录故障编号和恢复后的补审计划。")

    status = review_module.completion_status(run_dir)

    assert not status["allowed"]
    assert status["status"] == "unreviewed"
    assert status["completion_status"] == "unreviewed"
    assert not status["submission_ready"]
    assert "生产运行" in status["reason"]


def test_exploration_blind_review_skip_is_explicitly_unreviewed(tmp_path: Path) -> None:
    """探索运行也不能把盲评跳过标记为 submission_ready。"""
    run_dir = _run_dir(tmp_path)
    _register_current_result(run_dir)
    record_passing_scientific_review(run_dir)
    update_simple_state(run_dir, execution_mode="exploration")
    record_paper_blind_review_skip(run_dir, "探索性试验尚未具备独立盲评条件，后续将重新执行完整评审。")

    status = review_module.completion_status(run_dir)

    assert not status["allowed"]
    assert status["status"] == "unreviewed"
    assert status["completion_status"] == "unreviewed"
    assert not status["submission_ready"]
    assert "探索运行" in status["reason"]


def test_completion_rechecks_scientific_challenge_currentness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """最终放行必须先重新读取科学挑战，而不是复用进入论文时的旧结论。"""
    run_dir = _run_dir(tmp_path)
    observed: list[Path] = []

    def stale_challenge(path: Path) -> dict[str, object]:
        observed.append(path)
        return {"allowed": False, "reason": "科学挑战包已失效", "competition_strength": "unknown"}

    monkeypatch.setattr(review_module, "_competition_scientific_review_status", stale_challenge)

    status = review_module.completion_status(run_dir)

    assert observed == [run_dir]
    assert not status["allowed"]
    assert status["status"] == "scientific_challenge_unavailable"
    assert "科学挑战包已失效" in status["reason"]


def test_result_change_after_scientific_challenge_blocks_completion(tmp_path: Path) -> None:
    """替换 current production 结果后，必须重新完成科学挑战。"""
    run_dir = _run_dir(tmp_path)
    _register_current_result(run_dir)
    record_passing_scientific_review(run_dir)
    assert review_module._competition_scientific_review_status(run_dir)["allowed"]

    _register_current_result(run_dir, result_id="q1_replacement", objective=2.0)

    status = review_module.completion_status(run_dir)

    assert not status["allowed"]
    assert status["status"] == "scientific_challenge_unavailable"
    assert "科学挑战" in status["reason"]


def test_scientific_release_requires_current_gap_report(tmp_path: Path) -> None:
    """全面科学报告和 runner 证据均存在时，缺少查漏报告仍必须阻断。"""
    run_dir = _run_dir(tmp_path)
    _register_current_result(run_dir)
    record_passing_scientific_review(run_dir)
    (run_dir / "review" / "gaps" / "round-1.json").unlink()

    status = review_module._competition_scientific_review_status(run_dir)

    assert not status["allowed"]
    assert "查漏" in status["reason"]


def test_pdf_blind_review_import_accepts_when_contracts_met(tmp_path: Path) -> None:
    """v3.1 PDF 盲评在满足所有合同条件时（不同对话 + 冻结 PDF + 独立任务回执）应直接通过。

    v3.1/v3.2 Competition-First 的 PDF 盲评不使用旧覆盖率查漏体系；隔离由
    冻结 PDF + 独立任务回执 + fresh thread 三者保证，故单纯缺少 gaps 文件不阻断。
    """
    run_dir = _run_dir(tmp_path, "paper-gap-required")
    _register_current_result(run_dir)
    record_passing_scientific_review(run_dir)
    _force_paper_review_with_pdf(run_dir)
    packet = build_review_packet(run_dir, kind="paper-blind")
    manifest_file = f"review/packet/paper-blind/{packet['packet_id']}/manifest.json"
    report = run_dir / "review" / "PAPER_BLIND_REVIEW.md"
    report.write_text("# PDF 全面盲审\n\n论文需要进一步修订。\n", encoding="utf-8")
    bindings = {
        "packet": {
            "manifest_file": manifest_file,
            "manifest_sha256": sha256_file(run_dir / manifest_file),
        }
    }
    event = persist_review_task_creation_event(
        run_dir,
        event_file="review/tasks/creation-events/paper-open.json",
        raw_event={
            "schema_name": "review_task_creation_event",
            "schema_version": "1.0",
            "provider": "codex",
            "raw_task_id": "paper-open-task",
            "raw_thread_id": "paper-open-thread",
            "creation_mode": "create_thread",
            "parent_context_inherited": False,
            "created_at": "2026-07-25T00:00:00Z",
        },
    )
    receipt = create_review_task_receipt(
        run_dir,
        task_id="paper-open",
        task_type="paper_blind_open",
        model_id="fixture-model",
        prompt_sha256=paper_blind_review_prompt_sha256(run_dir, manifest_file),
        input_bindings=bindings,
        report_file="review/PAPER_BLIND_REVIEW.md",
        creation_event_file=event.relative_to(run_dir).as_posix(),
    )

    # 满足所有 v3.1 合同条件（fresh thread + 独立回执），应成功导入。
    summary = review_module.import_paper_blind_review(
        run_dir,
        manifest_file=manifest_file,
        verdict="pass",
        highest_severity="none",
        reviewer_thread_id="paper-open-thread",
        task_receipt_file=receipt.relative_to(run_dir).as_posix(),
    )
    assert "paper_blind_review" in summary
    assert summary["paper_blind_review"]["verdict"] == "pass"


def test_mechanical_qa_requires_scientific_challenge_release(tmp_path: Path) -> None:
    """v3.1 机械 QA 不能遗漏当前科学挑战的放行检查。"""
    run_dir = _run_dir(tmp_path)
    pdf = run_dir / "paper" / "final.pdf"
    pdf.write_bytes(b"%PDF-1.4\nfixture\n")
    check_ids = {
        "state-phase",
        "paper-template-manifest",
        "paper-compile-receipt",
        "paper-blind-review-release",
        "pdf",
        "paper-structure-signals",
        "placeholders",
        "result-references",
        "numeric-consistency",
        "current-result-files",
        "current-figure-files",
        "contact-sheet",
    }
    atomic_json(
        run_dir / "qa" / "mechanical-qa.json",
        {
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "workflow": "competition-first-v3.1",
            "status": "pass",
            "generator_id": "shumozizi.qa.run_final_checks",
            "generated_at": "2026-07-25T00:00:00Z",
            "final_pdf": "paper/final.pdf",
            "final_pdf_sha256": sha256_file(pdf),
            "checks": [{"id": check_id, "passed": True} for check_id in check_ids],
        },
    )

    status = mechanical_qa_status(run_dir)

    assert not status["allowed"]
    assert "scientific-challenge-release" in status["reason"]
