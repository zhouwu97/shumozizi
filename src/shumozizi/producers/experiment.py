"""实验生产器：只生成有界 baseline/primary/robustness 清单。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import atomic_json, load_json
from shumozizi.core.schema import require_valid


def create_experiment_manifest(
    run_dir: Path,
    *,
    question_id: str,
    cycle: str,
    execution_id: str,
    script: str,
    output: str,
    input_files: list[str] | None = None,
    timeout_seconds: int = 600,
    random_seed: int | None = 42,
) -> Path:
    """为一个问题的一轮实验生成清单并执行三轮预算检查。"""
    if cycle not in {"baseline", "primary", "robustness", "ablation"}:
        raise ValueError("cycle 必须是 baseline、primary、robustness 或 ablation")
    model_spec = run_dir / "brief" / "model_spec.json"
    if model_spec.is_file() and question_id not in {item["question_id"] for item in load_json(model_spec)["questions"]}:
        raise ValueError("question_id 不在当前模型规格中")
    manifest = {
        "schema_name": "execution_manifest",
        "schema_version": "2.0",
        "execution_id": execution_id,
        "program": "python",
        "args": [script, output],
        "cwd": ".",
        "timeout_seconds": timeout_seconds,
        "input_files": input_files or [script],
        "expected_outputs": [output],
        "random_seed": random_seed,
    }
    require_valid(manifest, "execution_manifest")
    path = run_dir / "executions" / "manifests" / f"{execution_id}.json"
    if path.exists():
        raise FileExistsError(f"实验清单已存在，拒绝覆盖: {path}")
    atomic_json(path, manifest)
    return path
