"""仓内优秀论文材料清点测试。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from shumozizi.knowledge.papers import inventory_sources, write_source_inventory


def test_inventory_hashes_supported_files_without_copying_sources(tmp_path: Path) -> None:
    source = tmp_path / "external-cache"
    source.mkdir()
    pdf = source / "paper.pdf"
    notes = source / "notes.txt"
    ignored = source / "preview.png"
    pdf.write_bytes(b"%PDF-test")
    notes.write_text("只读笔记\n", encoding="utf-8")
    ignored.write_bytes(b"PNG")
    before = {path.name: path.read_bytes() for path in source.iterdir()}

    output = tmp_path / "knowledge/training/pilot/source_inventory.json"
    document = inventory_sources([source])
    write_source_inventory([source], output)

    assert document["file_count"] == 2
    assert document["extension_counts"] == {".pdf": 1, ".txt": 1}
    pdf_item = next(item for item in document["files"] if item["relative_path"] == "paper.pdf")
    assert pdf_item["sha256"] == hashlib.sha256(b"%PDF-test").hexdigest()
    assert output.is_file()
    assert {path.name: path.read_bytes() for path in source.iterdir()} == before
    assert not (output.parent / "paper.pdf").exists()

