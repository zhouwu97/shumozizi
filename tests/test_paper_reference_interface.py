"""验证离线论文卡只能作为受限的生产写作参考。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json
from shumozizi.core.schema import validate_document
from shumozizi.paper.references import (
    register_paper_references,
    verify_paper_references,
    writing_reference_cards,
)
from tests.test_semantic_schemas import claim_evidence


def _write_state(run_dir: Path, *, phase: str = "paper") -> None:
    """写入论文参考测试所需的最小 production 状态。"""
    atomic_json(
        run_dir / "state" / "run.json",
        {
            "schema_version": "3.0",
            "run_id": run_dir.name,
            "workflow": "capability-first-v3",
            "phase": phase,
            "execution_mode": "production",
            "revision": 4,
            "competition": "synthetic",
            "problem_id": "paper-reference",
            "required_questions": ["Q1"],
            "current_question": "Q1",
            "completed_questions": ["Q1"],
            "selected_route": "route-a",
            "fallback_route": None,
            "artifacts": {},
            "time_budget": {"total_hours": 1, "remaining_hours": 0.5},
            "token_budget": {"soft_cap": 1000, "used_estimate": 100},
            "updated_at": "2026-07-22T00:00:00Z",
        },
    )


def _write_paper_index(root: Path) -> Path:
    """写入不含论文正文的最小登记索引和离线卡。"""
    card = root / "knowledge" / "cards" / "papers" / "offline-card.md"
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text(
        "---\n"
        "paper_id: offline-card\n"
        "title: 离线卡\n"
        "source_file: offline.pdf\n"
        f"source_sha256: {'a' * 64}\n"
        "problem_type: synthetic\n"
        "data_structure: synthetic\n"
        "task_types:\n"
        "  - optimization\n"
        "---\n"
        "## 核心问题\n内容\n"
        "## 各问问题链\n内容\n"
        "## 共享数学对象\n内容\n"
        "## 模型选择依据\n内容\n"
        "## baseline设计\n内容\n"
        "## 验证设计\n内容\n"
        "## 论文论证结构\n内容\n"
        "## 图表承担的作用\n内容\n"
        "## 可迁移模式\n内容\n"
        "## 不可迁移内容\n内容\n"
        "## 论文不足\n内容\n"
        "## 缺失验证\n内容\n"
        "## 复现风险\n内容\n"
        "## 来源页码\n内容\n",
        encoding="utf-8",
    )
    index = root / "knowledge" / "indexes" / "papers.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(
        json.dumps(
            {
                "schema_name": "paper_card_index",
                "schema_version": "1.0",
                "paper_count": 1,
                "papers": [
                    {
                        "paper_id": "offline-card",
                        "title": "离线卡",
                        "problem_type": "synthetic",
                        "data_structure": "synthetic",
                        "task_types": ["optimization"],
                        "domain_terms": [],
                        "structural_tags": [],
                        "source_sha256": "a" * 64,
                        "card_path": "knowledge/cards/papers/offline-card.md",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return index


def _use_controlled_paper_index(monkeypatch, index_path: Path) -> None:
    """把测试索引作为当前仓库唯一允许的论文卡索引。"""
    monkeypatch.setattr(
        "shumozizi.paper.references._default_index_path",
        lambda: index_path,
    )


def test_paper_card_without_current_valid_result_cannot_register_reference(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """离线论文卡不能在缺少当前有效生产结果时支撑论文事实。"""
    run_dir = tmp_path / "run-no-result"
    _write_state(run_dir)
    index_path = _write_paper_index(tmp_path)
    _use_controlled_paper_index(monkeypatch, index_path)

    with pytest.raises(ContractError, match="有效.*production.*结果"):
        register_paper_references(
            run_dir,
            card_ids=["offline-card"],
            production_result_ids=["Q1-R1"],
        )


def test_paper_card_is_non_rendering_writing_reference_not_claim_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """冻结结果放行后，论文卡只能登记为非渲染写作参考。"""
    run_dir = tmp_path / "run-with-result"
    _write_state(run_dir)
    index_path = _write_paper_index(tmp_path)
    _use_controlled_paper_index(monkeypatch, index_path)
    monkeypatch.setattr(
        "shumozizi.paper.references.quality_allows_paper",
        lambda _run_dir, result_id: result_id == "Q1-R1",
    )

    receipt = register_paper_references(
        run_dir,
        card_ids=["offline-card"],
        production_result_ids=["Q1-R1"],
    )
    cards = writing_reference_cards(run_dir)

    assert receipt["reference_role"] == "offline_writing_reference"
    assert receipt["cards"][0]["allowed_uses"] == [
        "section_organization",
        "model_explanation",
        "validation_narrative",
        "figure_contract",
    ]
    assert "rendering" in receipt["prohibited_uses"]
    assert "evidence" in receipt["prohibited_uses"]
    assert "citation" in receipt["prohibited_uses"]
    assert "referenced_result_ids" not in receipt
    assert cards == [
        {
            "paper_id": "offline-card",
            "card_path": "knowledge/cards/papers/offline-card.md",
            "allowed_uses": [
                "section_organization",
                "model_explanation",
                "validation_narrative",
                "figure_contract",
            ],
        }
    ]

    evidence = claim_evidence()
    evidence["paper_references"] = [receipt["cards"][0]]
    errors = validate_document(evidence, "claim_evidence")
    assert any("paper_references" in error for error in errors)


def test_paper_reference_remains_valid_during_final_review(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """新增终审阶段仍属于 production 结果冻结后的论文阶段。"""
    run_dir = tmp_path / "run-final-review"
    _write_state(run_dir, phase="final_review")
    index_path = _write_paper_index(tmp_path)
    _use_controlled_paper_index(monkeypatch, index_path)
    monkeypatch.setattr(
        "shumozizi.paper.references.quality_allows_paper",
        lambda _run_dir, result_id: result_id == "Q1-R1",
    )

    receipt = register_paper_references(
        run_dir,
        card_ids=["offline-card"],
        production_result_ids=["Q1-R1"],
    )

    assert receipt["frozen_phase"] == "final_review"
    assert verify_paper_references(run_dir)["valid"] is True


def test_paper_reference_rejects_tampered_index_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """收据必须绑定登记时的索引相对路径，不能只依赖外部传入路径。"""
    run_dir = tmp_path / "run-index-path-drift"
    _write_state(run_dir)
    index_path = _write_paper_index(tmp_path)
    _use_controlled_paper_index(monkeypatch, index_path)
    monkeypatch.setattr(
        "shumozizi.paper.references.quality_allows_paper",
        lambda _run_dir, result_id: result_id == "Q1-R1",
    )
    receipt = register_paper_references(
        run_dir,
        card_ids=["offline-card"],
        production_result_ids=["Q1-R1"],
    )
    receipt["paper_index"]["path"] = "knowledge/indexes/forged.json"
    atomic_json(run_dir / "paper" / "paper_references.json", receipt)

    verified = verify_paper_references(run_dir)

    assert not verified["valid"]
    assert any("索引路径" in error for error in verified["errors"])


def test_paper_reference_rejects_card_source_metadata_drift(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """索引只能登记由离线学习产出的真实论文卡，不能接受伪造来源。"""
    run_dir = tmp_path / "run-card-metadata-drift"
    _write_state(run_dir)
    index_path = _write_paper_index(tmp_path)
    _use_controlled_paper_index(monkeypatch, index_path)
    card = tmp_path / "knowledge" / "cards" / "papers" / "offline-card.md"
    card.write_text(
        card.read_text(encoding="utf-8").replace("source_sha256: " + "a" * 64, "source_sha256: " + "b" * 64),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "shumozizi.paper.references.quality_allows_paper",
        lambda _run_dir, result_id: result_id == "Q1-R1",
    )

    with pytest.raises(ContractError, match="source_sha256"):
        register_paper_references(
            run_dir,
            card_ids=["offline-card"],
            production_result_ids=["Q1-R1"],
        )


def test_paper_reference_rejects_external_index_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """生产写作不能以参数注入另一个目录的论文索引。"""
    run_dir = tmp_path / "run-external-index"
    _write_state(run_dir)
    controlled_index = _write_paper_index(tmp_path)
    external_index = _write_paper_index(tmp_path / "external-repository")
    _use_controlled_paper_index(monkeypatch, controlled_index)
    monkeypatch.setattr(
        "shumozizi.paper.references.quality_allows_paper",
        lambda _run_dir, result_id: result_id == "Q1-R1",
    )

    with pytest.raises(ContractError, match="受控.*papers.json"):
        register_paper_references(
            run_dir,
            card_ids=["offline-card"],
            production_result_ids=["Q1-R1"],
            index_path=external_index,
        )


def test_paper_reference_rejects_card_outside_controlled_cards_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """即使索引被篡改，也只能读取 cards/papers 目录中的离线论文卡。"""
    run_dir = tmp_path / "run-external-card"
    _write_state(run_dir)
    index_path = _write_paper_index(tmp_path)
    _use_controlled_paper_index(monkeypatch, index_path)
    rogue_card = tmp_path / "knowledge" / "cards" / "rogue-card.md"
    rogue_card.write_text(
        (tmp_path / "knowledge" / "cards" / "papers" / "offline-card.md").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["papers"][0]["card_path"] = "knowledge/cards/rogue-card.md"
    atomic_json(index_path, index)
    monkeypatch.setattr(
        "shumozizi.paper.references.quality_allows_paper",
        lambda _run_dir, result_id: result_id == "Q1-R1",
    )

    with pytest.raises(ContractError, match="cards/papers"):
        register_paper_references(
            run_dir,
            card_ids=["offline-card"],
            production_result_ids=["Q1-R1"],
        )
