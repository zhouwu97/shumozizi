"""B2 路线知识快照及锁后稳定性测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.knowledge.papers import build_paper_indexes, write_retrieval_artifacts
from shumozizi.knowledge.snapshot import verify_retrieval_snapshot
from shumozizi.producers.route import write_route_candidates
from shumozizi.workflow.approval import (
    create_approval_request,
    materialize_route_approval,
    verify_route_approval,
)
from tests.test_knowledge_verified_only import _build, _promote, _write_card, _write_registry
from tests.test_production_closure import _route_run
from tests.test_semantic_schemas import route_candidates


def _retrieve(root: Path) -> tuple[Path, dict[str, Path]]:
    card = _write_card(root)
    _build(root, _promote(root, card))
    run_dir = root / "runs/snapshot-run"
    outputs = write_retrieval_artifacts(
        run_dir,
        root / "knowledge/indexes/papers_verified.json",
        {
            "problem_type": "optimization",
            "data_structure": "tabular",
            "task_types": ["scheduling"],
            "keywords": ["优化"],
            "canonical_problem_id": "unseen-2026-b",
            "problem_asset_sha256": "f" * 64,
        },
    )
    return run_dir, outputs


def test_snapshot_freezes_index_policy_input_and_selected_cards(tmp_path: Path) -> None:
    run_dir, outputs = _retrieve(tmp_path)
    snapshot = json.loads(outputs["retrieval_snapshot"].read_text(encoding="utf-8"))

    assert snapshot["verified_index_sha256"] == sha256_file(
        tmp_path / "knowledge/indexes/papers_verified.json"
    )
    assert snapshot["retrieval_input"]["canonical_problem_id"] == "unseen-2026-b"
    assert [item["paper_id"] for item in snapshot["selected_cards"]] == ["paper-a"]
    assert verify_retrieval_snapshot(run_dir)["valid"] is True


def test_locked_snapshot_survives_later_verified_index_change(tmp_path: Path) -> None:
    run_dir, outputs = _retrieve(tmp_path)
    snapshot_sha256 = sha256_file(outputs["retrieval_snapshot"])
    index_path = tmp_path / "knowledge/indexes/papers_verified.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["paper_count"] = 0
    index["papers"] = []
    atomic_json(index_path, index)

    report = verify_retrieval_snapshot(run_dir)

    assert report["valid"] is True
    assert report["warnings"] == ["当前 verified 索引已变化；已锁路线继续使用原快照"]
    assert sha256_file(outputs["retrieval_snapshot"]) == snapshot_sha256


def test_deleted_card_stays_in_old_snapshot_but_new_index_cannot_select_it(
    tmp_path: Path,
) -> None:
    _, outputs = _retrieve(tmp_path)
    snapshot = json.loads(outputs["retrieval_snapshot"].read_text(encoding="utf-8"))
    (tmp_path / "knowledge/cards/papers/paper-a.md").unlink()
    documents = build_paper_indexes(
        tmp_path / "knowledge/cards/papers",
        tmp_path / "knowledge/reviews/paper_card_review_registry.json",
        tmp_path / "knowledge/indexes/papers_provisional.json",
        tmp_path / "knowledge/indexes/papers_verified.json",
    )

    assert [item["paper_id"] for item in snapshot["selected_cards"]] == ["paper-a"]
    assert documents["verified"]["paper_count"] == 0


def test_retrieval_policy_tampering_invalidates_snapshot(tmp_path: Path) -> None:
    run_dir, outputs = _retrieve(tmp_path)
    snapshot = json.loads(outputs["retrieval_snapshot"].read_text(encoding="utf-8"))
    snapshot["retrieval_policy"]["score_weights"]["structural"] = 0.1
    atomic_json(outputs["retrieval_snapshot"], snapshot)

    report = verify_retrieval_snapshot(run_dir)

    assert report["valid"] is False
    assert "retrieval_policy_sha256 不匹配" in report["errors"]


def test_route_candidates_bind_current_snapshot(tmp_path: Path) -> None:
    run_dir, outputs = _retrieve(tmp_path)
    config = run_dir / "config/RUN_CONFIG_LOCK.json"
    atomic_json(config, {"placeholder": True})
    document = route_candidates()

    path = write_route_candidates(run_dir, document)
    written = json.loads(path.read_text(encoding="utf-8"))

    assert written["retrieval_snapshot_path"] == "knowledge/RETRIEVAL_SNAPSHOT.json"
    assert written["retrieval_snapshot_sha256"] == sha256_file(outputs["retrieval_snapshot"])


def test_new_route_candidates_require_retrieval_snapshot(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs/missing-snapshot"
    atomic_json(run_dir / "config/RUN_CONFIG_LOCK.json", {"placeholder": True})

    with pytest.raises(ContractError, match="RETRIEVAL_SNAPSHOT"):
        write_route_candidates(run_dir, route_candidates())


def test_route_approval_requires_snapshot_file(tmp_path: Path) -> None:
    run_dir = _route_run(tmp_path, snapshot=False)

    with pytest.raises(ContractError, match="RETRIEVAL_SNAPSHOT"):
        create_approval_request(
            run_dir,
            "route",
            {
                "run_config_lock": run_dir / "config/RUN_CONFIG_LOCK.json",
                "route_candidates": run_dir / "brief/route_candidates.json",
            },
        )


def test_route_approval_and_lock_bind_snapshot_without_live_index_drift(
    tmp_path: Path,
) -> None:
    run_dir = _route_run(tmp_path)
    (tmp_path / "knowledge/cards/papers").mkdir(parents=True, exist_ok=True)
    _build(tmp_path, _write_registry(tmp_path, {}))
    outputs = write_retrieval_artifacts(
        run_dir,
        tmp_path / "knowledge/indexes/papers_verified.json",
        {
            "problem_type": "deterministic",
            "data_structure": "scalar",
            "task_types": ["calculation"],
            "keywords": ["标量"],
            "canonical_problem_id": "sample-closure",
            "problem_asset_sha256": "e" * 64,
        },
    )
    candidates_path = run_dir / "brief/route_candidates.json"
    candidates = load_json(candidates_path)
    candidates["retrieval_snapshot_path"] = "knowledge/RETRIEVAL_SNAPSHOT.json"
    candidates["retrieval_snapshot_sha256"] = sha256_file(outputs["retrieval_snapshot"])
    atomic_json(candidates_path, candidates)
    request = create_approval_request(
        run_dir,
        "route",
        {
            "run_config_lock": run_dir / "config/RUN_CONFIG_LOCK.json",
            "route_candidates": candidates_path,
        },
    )
    receipt, lock_path = materialize_route_approval(
        run_dir,
        raw_user_response="明确批准 route_a",
        selected_route_id="route_a",
        approved_by="human-reviewer",
    )
    lock = load_json(lock_path)

    assert load_json(request)["bindings"]["retrieval_snapshot"] == sha256_file(
        outputs["retrieval_snapshot"]
    )
    assert load_json(receipt)["bindings"]["retrieval_snapshot"] == lock[
        "retrieval_snapshot_sha256"
    ]
    assert lock["retrieval_snapshot_path"] == "knowledge/RETRIEVAL_SNAPSHOT.json"
    report = verify_route_approval(run_dir)
    assert report["valid"] is True, report["errors"]
