"""B4 原子模式、反模式、独立晋级与 postmortem 测试。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import shumozizi.knowledge.patterns as patterns_module
from shumozizi.core.io import ContractError, atomic_json, sha256_file
from shumozizi.knowledge.patterns import (
    ANTIPATTERN_TYPES,
    ATOMIC_PATTERN_TYPES,
    build_pattern_indexes,
    promote_pattern,
    write_postmortem_pattern,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _isolated_pattern_repo(tmp_path: Path) -> tuple[Path, Path]:
    source = REPO_ROOT / "knowledge/patterns/atomic/validation-independent-oracle.json"
    target = tmp_path / "knowledge/patterns/atomic/validation-independent-oracle.json"
    target.parent.mkdir(parents=True)
    shutil.copy2(source, target)
    atomic_json(
        tmp_path / "knowledge/reviews/atomic_pattern_review_registry.json",
        {
            "schema_name": "atomic_pattern_review_registry",
            "schema_version": "1.0",
            "default_status": "provisional",
            "patterns": {},
        },
    )
    return tmp_path, target


def test_seed_library_covers_all_atomic_and_antipattern_types() -> None:
    indexes = build_pattern_indexes(REPO_ROOT)
    provisional = indexes["provisional"]["patterns"]
    atomic_types = {
        item["pattern_type"]
        for item in provisional
        if item["schema_name"] == "atomic_knowledge_pattern"
    }
    antipattern_types = {
        item["pattern_type"]
        for item in provisional
        if item["schema_name"] == "knowledge_antipattern"
    }

    assert atomic_types == ATOMIC_PATTERN_TYPES
    assert antipattern_types == ANTIPATTERN_TYPES
    assert indexes["provisional"]["pattern_count"] == 15
    assert indexes["verified"]["pattern_count"] == 0


def test_postmortem_can_only_create_provisional_pattern(tmp_path: Path) -> None:
    root, _ = _isolated_pattern_repo(tmp_path)
    payload = {
        "pattern_id": "postmortem-negative-result",
        "pattern_type": "negative_result",
        "title": "保留未达到阈值的结果",
        "applicable_when": ["实验未达到预设阈值"],
        "not_applicable_when": ["实验本身无效"],
        "required_evidence": ["预设阈值和真实指标"],
        "common_misuses": ["把失败结果改写为成功"],
        "counterexamples": ["没有预注册判据"],
        "source_paper_ids": ["paper-a"],
        "authoring_session_id": "postmortem-session",
        "review_status": "verified",
    }

    with pytest.raises(ContractError, match="只能生成 provisional"):
        write_postmortem_pattern(root, payload)

    payload["review_status"] = "provisional"
    path = write_postmortem_pattern(root, payload)
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["origin"] == "postmortem"
    assert written["review_status"] == "provisional"
    assert build_pattern_indexes(root)["verified"]["pattern_count"] == 0


def test_independent_pattern_review_can_promote_one_pattern(tmp_path: Path) -> None:
    root, pattern_path = _isolated_pattern_repo(tmp_path)
    review_path = root / "knowledge/reviews/pattern_reports/validation.json"
    atomic_json(
        review_path,
        {
            "schema_name": "atomic_pattern_review_report",
            "schema_version": "1.0",
            "pattern_id": "validation-independent-oracle",
            "pattern_sha256": sha256_file(pattern_path),
            "review_session_id": "independent-pattern-review",
            "reviewer_identity": "pattern-reviewer",
            "verdict": "verified",
            "findings": [],
            "reviewed_at": "2026-07-20T02:00:00Z",
        },
    )

    receipt = promote_pattern(root, "validation-independent-oracle", review_path)
    indexes = build_pattern_indexes(root)

    assert receipt.is_file()
    assert indexes["verified"]["pattern_count"] == 1
    assert indexes["provisional"]["pattern_count"] == 0


def test_pattern_authoring_and_review_sessions_must_differ(tmp_path: Path) -> None:
    root, pattern_path = _isolated_pattern_repo(tmp_path)
    review_path = root / "knowledge/reviews/pattern_reports/validation.json"
    atomic_json(
        review_path,
        {
            "schema_name": "atomic_pattern_review_report",
            "schema_version": "1.0",
            "pattern_id": "validation-independent-oracle",
            "pattern_sha256": sha256_file(pattern_path),
            "review_session_id": "b4-seed-session",
            "reviewer_identity": "same-session-reviewer",
            "verdict": "verified",
            "findings": [],
            "reviewed_at": "2026-07-20T02:00:00Z",
        },
    )

    with pytest.raises(ContractError, match="独立会话"):
        promote_pattern(root, "validation-independent-oracle", review_path)


def test_manual_verified_status_without_receipt_is_rejected(tmp_path: Path) -> None:
    root, _ = _isolated_pattern_repo(tmp_path)
    registry_path = root / "knowledge/reviews/atomic_pattern_review_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["patterns"]["validation-independent-oracle"] = {
        "review_status": "verified",
        "promotion_receipt": None,
        "promotion_receipt_sha256": None,
    }
    atomic_json(registry_path, registry)

    with pytest.raises(ContractError, match="缺少晋级回执"):
        build_pattern_indexes(root)


def test_pattern_promotion_recovers_after_registry_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, pattern_path = _isolated_pattern_repo(tmp_path)
    review_path = root / "knowledge/reviews/pattern_reports/validation.json"
    atomic_json(
        review_path,
        {
            "schema_name": "atomic_pattern_review_report",
            "schema_version": "1.0",
            "pattern_id": "validation-independent-oracle",
            "pattern_sha256": sha256_file(pattern_path),
            "review_session_id": "independent-pattern-review",
            "reviewer_identity": "pattern-reviewer",
            "verdict": "verified",
            "findings": [],
            "reviewed_at": "2026-07-20T02:00:00Z",
        },
    )
    real_atomic_json = patterns_module.atomic_json

    def fail_registry_write(path: Path, document: dict) -> None:
        if path.name == "atomic_pattern_review_registry.json":
            raise OSError("injected registry failure")
        real_atomic_json(path, document)

    monkeypatch.setattr(patterns_module, "atomic_json", fail_registry_write)
    with pytest.raises(OSError, match="injected registry failure"):
        promote_pattern(root, "validation-independent-oracle", review_path)
    receipt_path = (
        root
        / "knowledge/reviews/pattern_promotions/validation-independent-oracle.json"
    )
    receipt_sha256 = sha256_file(receipt_path)

    monkeypatch.setattr(patterns_module, "atomic_json", real_atomic_json)
    recovered = promote_pattern(root, "validation-independent-oracle", review_path)

    assert sha256_file(recovered) == receipt_sha256
    assert build_pattern_indexes(root)["verified"]["pattern_count"] == 1


def test_pattern_promotion_rejects_mismatched_existing_receipt(tmp_path: Path) -> None:
    root, pattern_path = _isolated_pattern_repo(tmp_path)
    review_path = root / "knowledge/reviews/pattern_reports/validation.json"
    atomic_json(
        review_path,
        {
            "schema_name": "atomic_pattern_review_report",
            "schema_version": "1.0",
            "pattern_id": "validation-independent-oracle",
            "pattern_sha256": sha256_file(pattern_path),
            "review_session_id": "independent-pattern-review",
            "reviewer_identity": "pattern-reviewer",
            "verdict": "verified",
            "findings": [],
            "reviewed_at": "2026-07-20T02:00:00Z",
        },
    )
    receipt_path = promote_pattern(
        root, "validation-independent-oracle", review_path
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["reviewer_identity"] = "tampered-reviewer"
    atomic_json(receipt_path, receipt)

    with pytest.raises(ContractError, match="晋级回执与当前晋级事实不一致"):
        promote_pattern(root, "validation-independent-oracle", review_path)
