"""模型规格生产器。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import atomic_json, load_json, sha256_file
from shumozizi.core.schema import require_valid


def create_model_spec(run_dir: Path, questions: list[dict[str, Any]]) -> Path:
    """根据当前路线锁生成可编码模型规格。"""
    lock_path = run_dir / "brief" / "ROUTE_LOCK.json"
    lock = load_json(lock_path)
    if lock.get("approved") is not True:
        raise ValueError("模型规格只能从 approved ROUTE_LOCK 生成")
    document = {
        "schema_name": "model_spec",
        "schema_version": "2.0",
        "run_id": run_dir.name,
        "route_lock_sha256": sha256_file(lock_path),
        "questions": questions,
    }
    require_valid(document, "model_spec")
    path = run_dir / "brief" / "model_spec.json"
    if path.exists():
        raise FileExistsError(f"模型规格已存在，拒绝覆盖: {path}")
    atomic_json(path, document)
    return path
