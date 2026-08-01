"""验证 v3.4 外部草稿导入审计：数字/主张/图/引用绑定与事实候选确认。

Test E/F/G（设计文档 §43）：
- Test E：错误数字 → 硬阻断；
- Test F：存在全局证书 → 合法强主张通过；
- Test G：仅有 best-known → 越界强主张 → unsupported_claim。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.paper.handoff import _package_digests
from shumozizi.paper.import_audit import (
    classify_fact_candidates,
    extract_numbers,
    import_external_draft,
    require_import_audit_passed,
)
from shumozizi.simple.authoring import mark_authoring_status, set_authoring_mode
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.state import read_simple_state, utc_now, write_simple_state

QUESTION_ANSWERS = {
    "Q1": "Q1 需要 12 人。",
    "Q2": "Q2 需要 8 人。",
    "Q3": "Q3 最少需要 581 人。",
}


def _answer_and_claims(
    run_dir: Path,
    *,
    q3_safe: list[str] | None = None,
    q3_forbidden: list[str] | None = None,
) -> dict[str, object]:
    """构造受控的 answer-and-claims 文档。"""
    return {
        "schema_name": "answer_and_claims",
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "questions": [
            {
                "question_id": "Q1",
                "must_answer": "12 人",
                "safe_claims": [],
                "forbidden_upgrades": [],
                "key_boundaries": [],
                "source_result_ids": ["r-Q1"],
                "claim_ids": [],
            },
            {
                "question_id": "Q2",
                "must_answer": "8 人",
                "safe_claims": [],
                "forbidden_upgrades": [],
                "key_boundaries": [],
                "source_result_ids": ["r-Q2"],
                "claim_ids": [],
            },
            {
                "question_id": "Q3",
                "must_answer": "581 人",
                "safe_claims": q3_safe or [],
                "forbidden_upgrades": q3_forbidden or [],
                "key_boundaries": ["证据等级: 下界+可行构造"],
                "source_result_ids": ["r-Q3"],
                "claim_ids": ["c-q3"],
            },
        ],
        "generated_at": utc_now(),
    }


def _package_run(
    tmp_path: Path,
    name: str,
    *,
    q3_safe: list[str] | None = None,
    q3_forbidden: list[str] | None = None,
    figure_ids: tuple[str, ...] = (),
    citation_keys: tuple[str, ...] = (),
) -> Path:
    """构造处于 waiting_external_author 且带最小 handoff 包的运行。"""
    run_dir = initialize_simple_run(
        tmp_path,
        name,
        required_questions=["Q1", "Q2", "Q3"],
        workflow_version="3.2",
    )
    state = read_simple_state(run_dir)
    state["phase"] = "paper"
    write_simple_state(run_dir, state)
    set_authoring_mode(run_dir, "external_handoff", reason="测试")
    mark_authoring_status(run_dir, "handoff_ready")
    mark_authoring_status(run_dir, "waiting_external_author")

    handoff_dir = run_dir / "paper/writer-handoff"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    answers = _answer_and_claims(run_dir, q3_safe=q3_safe, q3_forbidden=q3_forbidden)
    atomic_json(handoff_dir / "answer-and-claims.json", answers)
    (handoff_dir / "FIGURE_CATALOG.md").write_text(
        "\n".join(f"## {figure_id}" for figure_id in figure_ids),
        encoding="utf-8",
    )
    (handoff_dir / "CITATION_PACKET.md").write_text(
        "\n".join(f"| {key} | 可用于解释其方法基本思想 |" for key in citation_keys),
        encoding="utf-8",
    )
    answers_path = handoff_dir / "answer-and-claims.json"
    catalog_path = handoff_dir / "FIGURE_CATALOG.md"
    packet_path = handoff_dir / "CITATION_PACKET.md"
    digests = _package_digests(run_dir, answers_path, catalog_path, packet_path)
    manifest = {
        "schema_name": "writer_handoff_manifest",
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "handoff_revision": 1,
        "paper_policy_fingerprint": digests["paper_policy_fingerprint"],
        "formal_result_digest": digests["formal_result_digest"],
        "material_pool_digest": digests["material_pool_digest"],
        "storyboard_digest": digests["storyboard_digest"],
        "claim_boundary_digest": digests["claim_boundary_digest"],
        "figure_catalog_digest": digests["figure_catalog_digest"],
        "citation_packet_digest": digests["citation_packet_digest"],
        "writer_files": {},
        "generated_at": utc_now(),
    }
    atomic_json(handoff_dir / "manifest.json", manifest)
    if figure_ids:
        atomic_json(
            run_dir / "figures/FIGURE_PLAN.json",
            {
                "schema_name": "figure_plan",
                "schema_version": "2.1",
                "run_id": run_dir.name,
                "figures": [
                    {"figure_id": figure_id, "question_id": "Q3", "required": False}
                    for figure_id in figure_ids
                ],
            },
        )
    if citation_keys:
        references = "\n".join(f"\\bibitem{{{key}}} 文献说明" for key in citation_keys)
        (run_dir / "paper/references.tex").write_text(references, encoding="utf-8")
    return run_dir


def _write_draft(run_dir: Path, tmp_path: Path, body: str) -> Path:
    """写入外部草稿文件并返回其路径。"""
    draft = tmp_path / f"{run_dir.name}-draft.tex"
    draft.write_text(body, encoding="utf-8")
    return draft


def test_wrong_number_blocks_import(tmp_path: Path) -> None:
    """Test E：formal=581，草稿写 582 → 硬阻断并确认事实失败。"""
    run_dir = _package_run(tmp_path, "wrong-number")
    draft = _write_draft(
        run_dir,
        tmp_path,
        "\\section{Q1}\nQ1 需要 12 人。\n"
        "\\section{Q2}\nQ2 需要 8 人。\n"
        "\\section{Q3}\nQ3 最少需要 582 人。\n",
    )
    receipt = import_external_draft(run_dir, draft_source=draft, compile_draft=False)
    assert receipt["status"] == "blocked"
    assert any(item["class"] == "wrong_number" for item in receipt["audit"]["findings"])
    confirmed = load_json(run_dir / "review/confirmed-scientific-fact-failures.json")
    assert confirmed["failures"]
    assert confirmed["failures"][0]["formal_value"] == "581"
    assert confirmed["failures"][0]["draft_value"] == "582"
    with pytest.raises(ContractError, match="科学事实错误"):
        require_import_audit_passed(run_dir)


def test_correct_answer_numbers_pass(tmp_path: Path) -> None:
    """草稿数字与正式答案一致时不产生事实候选。"""
    run_dir = _package_run(tmp_path, "correct")
    draft = _write_draft(
        run_dir,
        tmp_path,
        "\\section{Q1}\nQ1 需要 12 人。\n"
        "\\section{Q2}\nQ2 需要 8 人。\n"
        "\\section{Q3}\nQ3 最少需要 581 人。\n",
    )
    receipt = import_external_draft(run_dir, draft_source=draft, compile_draft=False)
    assert receipt["status"] == "draft_imported"
    assert receipt["confirmed_fact_failures"] == []
    assert receipt["audit"]["objective_failures"] == []


def test_partial_draft_is_accepted(tmp_path: Path) -> None:
    """Test C 前置：缺少某问答案只是 advisory，不阻断导入。"""
    run_dir = _package_run(tmp_path, "partial")
    draft = _write_draft(
        run_dir,
        tmp_path,
        "\\section{Q1}\nQ1 需要 12 人。\n\\section{Q2}\nQ2 需要 8 人。\n",
    )
    receipt = import_external_draft(run_dir, draft_source=draft, compile_draft=False)
    assert receipt["status"] == "draft_imported"
    classes = {item["class"] for item in receipt["audit"]["findings"]}
    assert "missing_formal_answer" in classes
    assert "wrong_number" not in classes


def test_supported_global_claim_allowed(tmp_path: Path) -> None:
    """Test F：存在全局证书 → 『全局最优』是受支持的合法主张。"""
    run_dir = _package_run(
        tmp_path,
        "claim-supported",
        q3_safe=["Q3 全局最优 581 已有计算证书支持"],
    )
    draft = _write_draft(
        run_dir,
        tmp_path,
        "\\section{Q1}\nQ1 需要 12 人。\n"
        "\\section{Q2}\nQ2 需要 8 人。\n"
        "\\section{Q3}\n该方案达到全局最优，需要 581 人。\n",
    )
    receipt = import_external_draft(run_dir, draft_source=draft, compile_draft=False)
    assert receipt["status"] == "draft_imported"
    assert "unsupported_claim" not in {item["class"] for item in receipt["audit"]["findings"]}


def test_unsupported_global_claim_blocks(tmp_path: Path) -> None:
    """Test G：仅有 best-known → 『全局最优』是越界主张并阻断。"""
    run_dir = _package_run(
        tmp_path,
        "claim-blocked",
        q3_forbidden=["无全局最优性证书：不得写全局最优"],
    )
    draft = _write_draft(
        run_dir,
        tmp_path,
        "\\section{Q1}\nQ1 需要 12 人。\n"
        "\\section{Q2}\nQ2 需要 8 人。\n"
        "\\section{Q3}\n该方案达到全局最优，需要 581 人。\n",
    )
    receipt = import_external_draft(run_dir, draft_source=draft, compile_draft=False)
    assert receipt["status"] == "blocked"
    assert any(item["class"] == "unsupported_claim" for item in receipt["audit"]["findings"])


def test_unknown_figure_blocks(tmp_path: Path) -> None:
    """草稿引用图目录之外的图 → unknown_figure 客观失败。"""
    run_dir = _package_run(tmp_path, "unknown-fig", figure_ids=("fig-q3-coverage",))
    draft = _write_draft(
        run_dir,
        tmp_path,
        "\\section{Q3}\n如图 \\ref{fig-q3-other} 所示，需要 581 人。\n",
    )
    receipt = import_external_draft(run_dir, draft_source=draft, compile_draft=False)
    assert receipt["status"] == "blocked"
    assert any(item["class"] == "unknown_figure" for item in receipt["audit"]["findings"])


def test_unknown_citation_blocks(tmp_path: Path) -> None:
    """草稿引用未登记文献键 → unknown_citation 客观失败。"""
    run_dir = _package_run(tmp_path, "unknown-cit", citation_keys=("ref-a",))
    draft = _write_draft(
        run_dir,
        tmp_path,
        "\\section{Q3}\n采用整数规划 \\cite{ref-ghost}，需要 581 人。\n",
    )
    receipt = import_external_draft(run_dir, draft_source=draft, compile_draft=False)
    assert receipt["status"] == "blocked"
    assert any(item["class"] == "unknown_citation" for item in receipt["audit"]["findings"])


def test_freshness_stale_leads_to_needs_rebase(tmp_path: Path) -> None:
    """上游材料变化导致 handoff stale 时，草稿保留并标 needs_rebase。"""
    run_dir = _package_run(tmp_path, "stale-handoff")
    draft = _write_draft(
        run_dir,
        tmp_path,
        "\\section{Q3}\nQ3 最少需要 581 人。\n",
    )
    # 篡改 answer-and-claims，使 manifest 的 claim_boundary_digest 失配。
    answers = load_json(run_dir / "paper/writer-handoff/answer-and-claims.json")
    answers["generated_at"] = utc_now()
    atomic_json(run_dir / "paper/writer-handoff/answer-and-claims.json", answers)
    receipt = import_external_draft(run_dir, draft_source=draft, compile_draft=False)
    assert receipt["status"] == "needs_rebase"
    assert (run_dir / "paper/external-author/draft.tex").is_file()


def test_number_in_other_question_does_not_mask_error() -> None:
    """Q1 出现 581 不能掩盖 Q3 的 582 错误——数字按本问段落逐问绑定。"""
    document = {
        "questions": [
            {"question_id": "Q1", "must_answer": "12 人"},
            {"question_id": "Q3", "must_answer": "581 人"},
        ]
    }
    # Q1 同时包含自己的答案 12 与"样本数 581"；Q3 写错为 582。
    draft = (
        "\\section{Q1}\nQ1 需要 12 人，数据集共有 581 个样本。\n"
        "\\section{Q3}\nQ3 最少需要 582 人。\n"
    )
    findings = extract_numbers(draft, document)
    wrong = [item for item in findings if item["class"] == "wrong_number"]
    assert len(wrong) == 1
    assert wrong[0]["location"].startswith("Q3")
    assert wrong[0]["formal_value"] == "581"
    assert wrong[0]["draft_value"] == "582"


def test_wrong_number_detects_magnitude_error() -> None:
    """formal 12 + draft 120：12 不能被子串 120 掩盖，必须判定写错。"""
    document = {"questions": [{"question_id": "Q1", "must_answer": "12 人"}]}
    draft = "\\section{Q1}\nQ1 需要 120 人。\n"
    findings = extract_numbers(draft, document)
    wrong = [item for item in findings if item["class"] == "wrong_number"]
    assert len(wrong) == 1
    assert wrong[0]["formal_value"] == "12"
    assert wrong[0]["draft_value"] == "120"


def test_numeric_normalization_matches_equivalent_forms() -> None:
    """formal 581.0 + draft 581：数值等价，不产生 finding。"""
    document = {"questions": [{"question_id": "Q3", "must_answer": "581.0 人"}]}
    draft = "\\section{Q3}\nQ3 最少需要 581 人。\n"
    assert extract_numbers(draft, document) == []


def test_classify_fact_candidates_rejects_matching_numbers(tmp_path: Path) -> None:
    """machine binding 证明正文数字正确时，fact candidate 被驳回。"""
    run_dir = _package_run(tmp_path, "binding")
    audit = {
        "fact_candidates": [
            {
                "finding_id": "AUD-Q3-NUM-01",
                "formal_value": "581",
                "draft_value": "581",
            }
        ]
    }
    confirmed = classify_fact_candidates(run_dir, audit)
    assert confirmed["failures"] == []
