"""路线生产器的确定性落盘部分。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import atomic_json, load_json, sha256_file
from shumozizi.core.schema import require_valid


def write_route_candidates(run_dir: Path, document: dict[str, Any]) -> Path:
    """校验路线候选并写入简报 JSON；批准仍需人工回执物化。"""
    document = {**document, "run_id": run_dir.name}
    document["run_config_lock_sha256"] = sha256_file(run_dir / "config" / "RUN_CONFIG_LOCK.json")
    require_valid(document, "route_candidates")
    path = run_dir / "brief" / "route_candidates.json"
    atomic_json(path, document)
    return path
