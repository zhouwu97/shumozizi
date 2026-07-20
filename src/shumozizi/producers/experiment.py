"""实验生产器：为三个有界实验族生成可复验执行清单。"""

from __future__ import annotations

from pathlib import Path

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
    model_fits: int = 1,
    optimization_evaluations: int = 0,
    invalid_tuning_attempts: int = 0,
) -> Path:
    """为一个问题的实验族生成清单并检查计划预算。"""
    if cycle not in {"baseline", "primary", "robustness", "ablation"}:
        raise ValueError("cycle 必须是 baseline、primary、robustness 或 ablation")
    model_spec = run_dir / "brief" / "model_spec.json"
    if model_spec.is_file() and question_id not in {item["question_id"] for item in load_json(model_spec)["questions"]}:
        raise ValueError("question_id 不在当前模型规格中")
    route_lock_path = run_dir / "brief" / "ROUTE_LOCK.json"
    if route_lock_path.is_file():
        limits = load_json(route_lock_path)["resource_limits"]
        existing_usage = {
            "timeout_seconds": 0,
            "model_fits": 0,
            "optimization_evaluations": 0,
            "invalid_tuning_attempts": 0,
        }
        manifests_dir = run_dir / "executions" / "manifests"
        if manifests_dir.is_dir():
            for existing_path in manifests_dir.glob("*.json"):
                existing = load_json(existing_path)
                if (
                    existing.get("question_id") != question_id
                    or existing.get("experiment_family") != cycle
                ):
                    continue
                existing_usage["timeout_seconds"] += int(existing.get("timeout_seconds", 0))
                usage = existing.get("planned_budget_usage", {})
                for name in (
                    "model_fits",
                    "optimization_evaluations",
                    "invalid_tuning_attempts",
                ):
                    existing_usage[name] += int(usage.get(name, 0))
        comparisons = {
            "timeout_seconds": (
                existing_usage["timeout_seconds"] + timeout_seconds,
                limits.get("max_execution_seconds_per_family", timeout_seconds),
            ),
            "model_fits": (
                existing_usage["model_fits"] + model_fits,
                limits.get("max_model_fits_per_family", model_fits),
            ),
            "optimization_evaluations": (
                existing_usage["optimization_evaluations"] + optimization_evaluations,
                limits.get("max_optimization_evaluations_per_family", optimization_evaluations),
            ),
            "invalid_tuning_attempts": (
                existing_usage["invalid_tuning_attempts"] + invalid_tuning_attempts,
                limits.get("max_invalid_tuning_attempts_per_family", invalid_tuning_attempts),
            ),
        }
        exceeded = [name for name, (planned, maximum) in comparisons.items() if planned > maximum]
        if exceeded:
            raise ValueError("实验族计划预算超限: " + ", ".join(exceeded))
    manifest = {
        "schema_name": "execution_manifest",
        "schema_version": "2.0",
        "execution_id": execution_id,
        "question_id": question_id,
        "experiment_family": cycle,
        "planned_budget_usage": {
            "model_fits": model_fits,
            "optimization_evaluations": optimization_evaluations,
            "invalid_tuning_attempts": invalid_tuning_attempts,
        },
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
