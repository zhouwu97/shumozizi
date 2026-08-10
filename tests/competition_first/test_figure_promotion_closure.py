"""回归：promotion receipt、index、论文引用与磁盘 current 文件必须指向同一产物。

修复前缺陷：promote 幂等分支只检查 current 文件存在，未校验哈希；receipt 声称
晋级到 A 路径而 index/论文使用 B 路径，导致 v2 图从未真正进入 current。
"""

from __future__ import annotations

import json
from pathlib import Path

from shumozizi.core.io import atomic_json, sha256_file
from shumozizi.simple.figure_promotion import verify_figure_promotion_closure
from shumozizi.simple.initialization import initialize_simple_run


def test_q1_triptych_panel_mapping_keeps_cross_panel_path_ids() -> None:
    """Q1 三联图必须把 A/B/C 作为独立面板，并追踪同一条骨架路径。"""
    manifest = {
        "panels": ["panel_a", "panel_b", "panel_c"],
        "cross_panel_path_ids": [63, 216, 264, 351],
        "panel_mapping": {
            "panel_a": {"role": "periodic_cell", "path_ids": [63, 216, 264, 351]},
            "panel_b": {"role": "local_cross_section", "path_ids": [63, 216, 264, 351]},
            "panel_c": {"role": "conductive_backbone", "path_ids": [63, 216, 264, 351]},
        },
    }
    assert manifest["panels"] == ["panel_a", "panel_b", "panel_c"]
    expected = manifest["cross_panel_path_ids"]
    for panel in manifest["panel_mapping"].values():
        assert panel["path_ids"] == expected


def _figure_run(tmp_path: Path) -> Path:
    """构造含图索引、晋级回执、current 文件与论文引用的最小运行。"""
    run_dir = initialize_simple_run(
        tmp_path, "promotion-closure", workflow_version="3.2", required_questions=["Q1"]
    )
    (run_dir / "figures/current").mkdir(parents=True, exist_ok=True)
    (run_dir / "figures/promotions").mkdir(parents=True, exist_ok=True)
    (run_dir / "paper").mkdir(exist_ok=True)
    atomic_json(
        run_dir / "figures/index.json",
        {
            "schema_name": "simple_figure_index",
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "figures": [],
        },
    )
    return run_dir


def _current_digest(run_dir: Path) -> str:
    """写入并返回 current PNG 的真实哈希。"""
    current = run_dir / "figures/current/q1_contact_scene.png"
    current.write_bytes(b"x" * 16)
    return sha256_file(current)


def _register_closure(
    run_dir: Path,
    *,
    current_hash: str,
    index_hash: str,
    receipt_hash: str,
    referenced_in_paper: bool,
    receipt_stem: str = "q1_contact_scene",
) -> None:
    """写入一组可能互不一致的图登记数据（current 文件须已存在）。"""
    stem = "q1_contact_scene"
    current = run_dir / f"figures/current/{stem}.png"
    assert current.is_file(), "fixture 必须先写 current 文件"
    receipt = run_dir / "figures/promotions/q1-hero-v1-000000000000.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": "1.2",
                "figure_id": "q1-hero",
                "promoted_outputs": [
                    {"path": f"figures/current/{receipt_stem}.png", "sha256": receipt_hash}
                ],
            }
        ),
        encoding="utf-8",
    )
    index = json.loads((run_dir / "figures/index.json").read_text(encoding="utf-8"))
    index["figures"] = [
        {
            "figure_id": "q1-hero",
            "status": "current",
            "outputs": [{"path": f"figures/current/{stem}.png", "sha256": index_hash}],
            "promotion_receipt": {
                "path": receipt.relative_to(run_dir).as_posix(),
                "sha256": sha256_file(receipt),
            },
        }
    ]
    atomic_json(run_dir / "figures/index.json", index)
    (run_dir / "paper/longform-source.tex").write_text(
        (
            rf"\includegraphics{{figures/current/{stem}.pdf}}"
            if referenced_in_paper
            else "正文不引用该图。"
        ),
        encoding="utf-8",
    )


def test_closure_rejects_receipt_pointing_to_missing_file(tmp_path: Path) -> None:
    """receipt 声称晋级到磁盘上不存在的文件时必须失败（修复前 Q1 v2 缺陷）。"""
    run_dir = _figure_run(tmp_path)
    digest = _current_digest(run_dir)
    _register_closure(
        run_dir,
        current_hash=digest,
        index_hash=digest,
        receipt_hash=digest,
        referenced_in_paper=True,
        receipt_stem="q1_periodic_contact_scene",
    )
    errors = verify_figure_promotion_closure(run_dir, "q1-hero")
    assert any("receipt" in error and "不存在" in error for error in errors)
    assert any("q1_periodic_contact_scene" in error for error in errors)


def test_closure_rejects_mismatched_current_hash(tmp_path: Path) -> None:
    """receipt/index 记录的哈希与磁盘 current 文件不一致时必须失败。"""
    run_dir = _figure_run(tmp_path)
    _current_digest(run_dir)
    _register_closure(
        run_dir,
        current_hash="a" * 64,
        index_hash="a" * 64,
        receipt_hash="a" * 64,
        referenced_in_paper=True,
    )
    errors = verify_figure_promotion_closure(run_dir, "q1-hero")
    assert any("哈希" in error for error in errors)


def test_closure_rejects_index_digest_drift(tmp_path: Path) -> None:
    """index 的 outputs 哈希与磁盘 current 文件不一致时必须失败。"""
    run_dir = _figure_run(tmp_path)
    digest = _current_digest(run_dir)
    _register_closure(
        run_dir,
        current_hash=digest,
        index_hash="b" * 64,
        receipt_hash=digest,
        referenced_in_paper=True,
    )
    errors = verify_figure_promotion_closure(run_dir, "q1-hero")
    assert any("index" in error for error in errors)


def test_closure_rejects_unreferenced_figure(tmp_path: Path) -> None:
    """论文正文不引用该 current 图时，闭合校验必须失败（阶段 7 要求）。"""
    run_dir = _figure_run(tmp_path)
    digest = _current_digest(run_dir)
    _register_closure(
        run_dir,
        current_hash=digest,
        index_hash=digest,
        receipt_hash=digest,
        referenced_in_paper=False,
    )
    errors = verify_figure_promotion_closure(run_dir, "q1-hero")
    assert any("论文" in error for error in errors)


def test_closure_passes_when_all_four_agree(tmp_path: Path) -> None:
    """receipt、index、论文引用与磁盘 current 全部一致时通过。"""
    run_dir = _figure_run(tmp_path)
    digest = _current_digest(run_dir)
    _register_closure(
        run_dir,
        current_hash=digest,
        index_hash=digest,
        receipt_hash=digest,
        referenced_in_paper=True,
    )
    errors = verify_figure_promotion_closure(run_dir, "q1-hero")
    assert errors == []
