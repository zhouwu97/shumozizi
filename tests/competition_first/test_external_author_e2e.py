"""v3.4 External Author Handoff 真实 E2E 闭环。

从 CLI 一路走到 final.pdf，并验证最终 PDF 的正文确实来自外部 Author
（EXTERNAL SENTINEL 在、INTERNAL SENTINEL 不在）。

流程：ready run → prepare_writer_handoff CLI → waiting_external_author
→ external draft + AUTHOR_REQUESTS → resolve → import → draft_imported
→ materialize → fresh reviewer(PDF SHA) → adjudication → author_pass_accepted
→ compile_paper（外部入口）→ final.pdf → sentinel 校验。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from pypdf import PdfReader
from test_competition_first_v32 import (
    _actual,
    _objective_candidates,
    _plan,
    _record_fixture_knowledge_retrieval,
    _register_objective_probes,
    _register_result,
)

from shumozizi.core.io import atomic_json, load_json, sha256_file
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.paper.adjudication import record_adjudication
from shumozizi.paper.compiler import compile_paper
from shumozizi.paper.external_author import decide_author_request
from shumozizi.paper.import_audit import import_external_draft, materialize_external_draft
from shumozizi.paper.policy import policy_fingerprint
from shumozizi.paper.templates import materialize_selected_template, select_paper_template
from shumozizi.simple import review as simple_review
from shumozizi.simple.authoring import read_authoring
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.modeling_units import write_modeling_units
from shumozizi.simple.objective_consequences import write_objective_candidates
from shumozizi.simple.review_focus import (
    record_scientific_challenge_evidence,
    record_stronger_alternative,
)
from shumozizi.simple.review_tasks import (
    create_review_task_receipt,
    persist_review_task_creation_event,
)
from shumozizi.simple.state import (
    read_simple_state,
    update_simple_state,
    utc_now,
    write_simple_state,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _science_ready_run(tmp_path: Path, name: str = "e2e") -> Path:
    """构造通过 require_paper_generation_allowed 且模板/结构映射就绪的 v3.2 运行。"""
    run_dir = initialize_simple_run(
        tmp_path,
        name,
        competition="cumcm",
        required_questions=["Q1"],
        workflow_version="3.2",
    )
    (run_dir / "problem/statement.md").write_text("最小化总成本。", encoding="utf-8")

    # CUMCM 结构映射（先建，science 夹具随后会恢复 MODELING_UNITS）。
    # 只创建缺失的事实来源文件，绝不动已由 init 写好的 MODELING_UNITS.json。
    from test_cumcm_adapter import _map_payload

    from shumozizi.paper.cumcm_adapter import write_cumcm_structure_map

    sources = {
        "argument_plan": "paper/ARGUMENT_PLAN.md",
        "storyboard": "paper/STORYBOARD.md",
        "figure_plan": "figures/FIGURE_PLAN.json",
        "results": "results/RESULT_REGISTRY.json",
        "modeling_units": "analysis/MODELING_UNITS.json",
    }
    for relative in sources.values():
        path = run_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file():
            path.write_text("当前测试事实来源。\n", encoding="utf-8")
    template = run_dir.parent / "国赛参考模板.docx"
    template.write_bytes(b"PK\x03\x04minimal-reference-docx")
    structure_payload = _map_payload(run_dir, template)
    for section in structure_payload["sections"]:
        if "Q2" in section.get("sources", []):
            section["sources"] = ["Q1"]
    write_cumcm_structure_map(run_dir, structure_payload)
    # figures/FIGURE_PLAN.json 为合法空计划，避免 handoff visual 层误判。
    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "schema_name": "figure_plan",
            "schema_version": "2.1",
            "run_id": run_dir.name,
            "figures": [],
        },
    )

    plan = _plan(run_dir)
    write_modeling_units(run_dir, plan)
    write_objective_candidates(run_dir, _objective_candidates(run_dir, with_actual=False))
    _record_fixture_knowledge_retrieval(run_dir)
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
    _register_objective_probes(run_dir)
    _actual(plan)
    write_modeling_units(run_dir, plan)
    write_objective_candidates(run_dir, _objective_candidates(run_dir))

    packet = simple_review.build_review_packet(run_dir, kind="scientific")
    manifest_file = f"review/packet/scientific/{packet['packet_id']}/manifest.json"
    (run_dir / "review/SCIENTIFIC_CHALLENGE.md").write_text(
        "# 科学挑战\n\n- **P0：** 无。\n",
        encoding="utf-8",
    )
    bindings = {
        "packet": {
            "manifest_file": manifest_file,
            "manifest_sha256": sha256_file(run_dir / manifest_file),
        }
    }
    task_dir = run_dir / "review/tasks/scientific-v32"
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
            "raw_task_id": "v32-e2e-task",
            "raw_thread_id": "v32-e2e-thread",
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
        findings=[],
    )
    record_stronger_alternative(run_dir, found=False)
    simple_review.require_paper_generation_allowed(run_dir)

    # 素材池 + 故事板 + 主张门禁 + 视觉决策（handoff readiness 必需）。
    from shumozizi.paper.materials import build_material_pool
    from shumozizi.paper.storyboard import build_research_storyboard

    pool_materials = [
        {
            "material_id": "Q1-answer",
            "category": "Direct Answer",
            "title": "Q1 直接答案",
            "content": "正式答案由活动约束的互补松弛条件唯一决定。",
            "question_id": "Q1",
            "source_result_ids": ["final"],
            "source_figure_ids": [],
            "inclusion": "body",
        },
        {
            "material_id": "Q1-derivation",
            "category": "Mathematical Derivation",
            "title": "Q1 推导",
            "content": "由拉格朗日函数的 KKT 条件导出判据。",
            "question_id": "Q1",
            "source_result_ids": ["final"],
            "source_figure_ids": [],
            "inclusion": "body",
        },
        {
            "material_id": "Q1-mechanism",
            "category": "Mechanism",
            "title": "Q1 机制",
            "content": "容量约束活跃后边际收益递减。",
            "question_id": "Q1",
            "source_result_ids": ["final"],
            "source_figure_ids": [],
            "inclusion": "body",
        },
        {
            "material_id": "Q1-boundary",
            "category": "Boundary/Robustness",
            "title": "Q1 边界",
            "content": "该结论只覆盖已测试的参数区间。",
            "question_id": "Q1",
            "source_result_ids": ["final"],
            "source_figure_ids": [],
            "inclusion": "body",
        },
    ]
    build_material_pool(run_dir, materials=pool_materials)
    build_research_storyboard(
        run_dir,
        cards=[
            {
                "question_id": "Q1",
                "reader_needs": "需要先定位共享模型下的直接答案。",
                "phenomenon": "结果呈现明显容量拐点。",
                "why_math_object": "需要引入统一决策变量与约束集。",
                "model_evolution": "Q1 建立基本数学对象与评价指标。",
                "key_derivation": "由互补松弛条件导出活动约束判据。",
                "structural_finding": "答案由唯一活动约束决定。",
                "decision_determinant": "正式答案绑定 objective_answer 结果。",
                "mechanism": "边际收益在容量约束活跃后递减。",
                "contrast": "与放宽容量约束的替代方案对照。",
                "boundary": "结论只适用于已测试的参数区间。",
                "best_media": ["表格"],
                "material_ids": [
                    "Q1-answer",
                    "Q1-derivation",
                    "Q1-mechanism",
                    "Q1-boundary",
                ],
            }
        ],
    )
    atomic_json(
        run_dir / "paper/claim_gate.json",
        {
            "schema_name": "paper_claim_gate",
            "schema_version": "2.0",
            "run_id": run_dir.name,
            "evaluator_version": "e2e",
            "stale": False,
            "claimability": "claims",
            "claims": [
                {
                    "claim_id": "c-q1",
                    "question_id": "Q1",
                    "status": "supported",
                    "reference_allowed": True,
                    "contribution_mode": "full",
                    "allowed_uses": ["contribution", "results", "limitations"],
                    "reason": "Q1 答案由当前生产结果支持。",
                }
            ],
        },
    )
    atomic_json(
        run_dir / "figures/FIGURE_PLAN.json",
        {
            "schema_name": "figure_plan",
            "schema_version": "2.1",
            "run_id": run_dir.name,
            "visual_strategy": "fixed_contract",
            "figures": [],
            "visual_decisions": [
                {
                    "question_id": "Q1",
                    "scope": "Q1",
                    "status": "waived",
                    "reason": "E2E 夹具：Q1 无需必需展示图，以表格与文字解释替代",
                }
            ],
        },
    )

    select_paper_template(
        run_dir,
        language="zh",
        engine="latex",
        selection_reason="E2E 夹具使用默认 LaTeX 学术模板，选择原因足够长以满足校验要求。",
    )
    materialize_selected_template(run_dir)
    sections = run_dir / "paper/sections/questions.tex"
    sections.write_text(
        sections.read_text(encoding="utf-8") + "\nINTERNAL SENTINEL\n", encoding="utf-8"
    )
    state = read_simple_state(run_dir)
    state["phase"] = "paper"
    write_simple_state(run_dir, state)
    return run_dir


def _pdf_text(path: Path) -> str:
    """提取 PDF 文本。"""
    return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


def _q1_answer_number(run_dir: Path) -> str:
    """读取交接包中 Q1 的正式答案数字，供外部草稿使用。"""
    answers = load_json(run_dir / "paper/writer-handoff/answer-and-claims.json")
    q1 = next(item for item in answers["questions"] if item["question_id"] == "Q1")
    numbers = re.findall(r"\d+(?:\.\d+)?", str(q1["must_answer"]))
    assert numbers, "Q1 must_answer 缺少正式答案数字"
    return numbers[0]


def _write_external_draft(run_dir: Path, tmp_path: Path) -> Path:
    """写入独立的、可编译的外部草稿（EXTERNAL SENTINEL + 正确答案数字）。"""
    number = _q1_answer_number(run_dir)
    body = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\section{Q1}\n"
        f"Q1 answer needs {number} people.\n\n"
        "EXTERNAL SENTINEL\n"
        "\\end{document}\n"
    )
    path = tmp_path / f"{run_dir.name}-external-draft.tex"
    path.write_text(body, encoding="utf-8")
    return path


def _write_author_requests(run_dir: Path) -> None:
    """写入一个可豁免的 clarification 请求。"""
    document = {
        "schema_name": "author_request",
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "requests": [
            {
                "gap_id": "GAP-E2E-01",
                "kind": "clarification",
                "affected_argument": "Q1 直接答案单位",
                "request": "希望确认直接答案单位。",
                "why_needed": "避免单位歧义。",
                "can_continue_without_it": True,
                "fallback": "按正式结果原始单位书写。",
                "recommended_route": "author",
                "expected_benefit": "降低单位歧义。",
                "estimated_cost": "low",
            }
        ],
    }
    requests_path = run_dir / "paper/external-author/AUTHOR_REQUESTS.json"
    requests_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(requests_path, document)


def _write_reviewer_findings(run_dir: Path) -> None:
    """绑定当前 draft.pdf 的 Fresh Reviewer 回执。"""
    pdf = run_dir / "paper/external-author/draft.pdf"
    draft = run_dir / "paper/external-author/draft.tex"
    assert pdf.is_file(), "导入时应编译出 draft.pdf"
    document = {
        "schema_name": "paper_reviewer_findings",
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "source_pdf": "paper/external-author/draft.pdf",
        "source_pdf_sha256": sha256_file(pdf),
        "reviewer_context_id": "e2e-fresh-reviewer",
        "paper_policy_fingerprint": policy_fingerprint(resolve_repo_root(Path(__file__)), "paper"),
        "external_draft_sha256": sha256_file(draft),
        "findings": [
            {
                "finding_id": "REV-E2E-01",
                "finding_class": "argument",
                "severity_recommendation": "P3",
                "location": "Q1",
                "observation": "论证整体成立。",
                "why_it_matters": "无。",
                "suggested_route": "author",
                "minimum_fix": "无。",
                "acceptance_test": "无。",
            }
        ],
        "generated_at": utc_now(),
    }
    atomic_json(run_dir / "review/paper-reviewer-findings.json", document)


def test_external_author_e2e_closed_loop(tmp_path: Path) -> None:
    """真实闭环：外部稿最终成为正式 final.pdf，且不混入内部模板正文。"""
    run_dir = _science_ready_run(tmp_path)

    # 1. prepare_writer_handoff CLI（subprocess，真正走完状态迁移）。
    script = REPO_ROOT / "scripts/paper/prepare_writer_handoff.py"
    completed = subprocess.run(
        [sys.executable, str(script), str(run_dir)],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert '"status": "WRITER_HANDOFF_READY"' in completed.stdout
    assert read_authoring(run_dir)["authoring_status"] == "waiting_external_author"
    assert read_simple_state(run_dir)["phase"] == "paper"  # 非 blocked

    # 2. 外部草稿 + AUTHOR_REQUESTS + 裁决。
    draft_path = _write_external_draft(run_dir, tmp_path)
    _write_author_requests(run_dir)
    ledger = decide_author_request(
        run_dir,
        [
            {
                "gap_id": "GAP-E2E-01",
                "decision": "waive",
                "route": "author",
                "reason": "单位按正式结果原始写法即可。",
            }
        ],
    )
    assert ledger["decisions"][0]["decision"] == "waive"

    # 3. 导入（真实编译外部草稿）。
    receipt = import_external_draft(run_dir, draft_source=draft_path, compile_draft=True)
    assert receipt["status"] == "draft_imported", receipt
    assert receipt["audit"]["objective_failures"] == []
    assert (run_dir / "paper/external-author/draft.tex").is_file()

    # 4. 物化外部稿为正式编译入口。
    materialize_external_draft(run_dir)
    assert (run_dir / "paper/imported-author/main.tex").is_file()

    # 5. Fresh Reviewer（绑定 PDF SHA）+ 裁决 → author_pass_accepted。
    _write_reviewer_findings(run_dir)
    adjudication = record_adjudication(
        run_dir,
        [
            {
                "finding_id": "REV-E2E-01",
                "confirmed": True,
                "confirmed_severity": "P3",
                "route": "author",
                "decision": "accept",
                "reason": "论证整体成立，无需返修。",
            }
        ],
    )
    assert adjudication["decisions"][0]["decision"] == "accept"
    assert read_authoring(run_dir)["authoring_status"] == "author_pass_accepted"

    # 6. compile_paper 从外部入口编译正式 final.pdf。
    compile_receipt = compile_paper(run_dir, revision_impact="argument")
    assert compile_receipt["external_author_compile"] is True
    assert compile_receipt["external_draft_sha256"] == sha256_file(
        run_dir / "paper/external-author/draft.tex"
    )
    from shumozizi.paper.compiler import verify_paper_compile_receipt

    verified = verify_paper_compile_receipt(run_dir)
    assert verified["valid"], verified["errors"]

    # 7. sentinel 校验：正文来自外部 Author，不是内部模板。
    text = _pdf_text(run_dir / "paper/final.pdf")
    assert "EXTERNAL SENTINEL" in text
    assert "INTERNAL SENTINEL" not in text
