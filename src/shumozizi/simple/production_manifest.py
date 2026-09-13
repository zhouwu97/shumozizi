"""生成唯一生产事实清单，作为论文、图表和提交件的共同来源。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import read_simple_state, utc_now

MANIFEST_PATH = Path("state/production-manifest.json")


def _candidates(run_dir: Path, question_id: str) -> list[dict[str, Any]]:
    """返回某问可作为正式答案的 current production 结果。"""
    rows = [
        item
        for item in read_result_index(run_dir)["results"]
        if item.get("question_id") == question_id
        and item.get("status") == "current"
        and item.get("execution_mode") == "production"
        and item.get("execution_valid") is True
        and item.get("scientific_status", "valid") != "invalidated"
        and item.get("paper_allowed", True) is not False
    ]
    priority = {"primary": 0, "adapter-exact_scorer": 1, "final": 2, "production": 3, "baseline": 9}
    return sorted(rows, key=lambda row: (priority.get(str(row.get("kind")), 5), str(row.get("created_at", ""))))


def build_production_manifest(run_dir: Path, *, write: bool = True) -> dict[str, Any]:
    """按 answer-map 或明确的结果优先级构造每问唯一正式结果。"""
    state = read_simple_state(run_dir)
    answer_path = run_dir / "paper/answer-map.json"
    if not answer_path.is_file():
        answer_path = run_dir / "analysis/answer_map.json"
    answers = load_json(answer_path) if answer_path.is_file() else {}
    answers = answers.get("answers", answers)
    selected: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for question_id in state.get("required_questions", []):
        rows = _candidates(run_dir, question_id)
        mapped = answers.get(question_id, {}) if isinstance(answers, dict) else {}
        mapped_id = mapped.get("primary_result_id") if isinstance(mapped, dict) else None
        if isinstance(mapped_id, str):
            match = next((row for row in rows if row.get("result_id") == mapped_id), None)
            if match is None:
                errors.append(f"{question_id} 的 primary_result_id 不在 current production 中")
                continue
        elif rows:
            match = rows[0]
        else:
            errors.append(f"{question_id} 缺少 current production 结果")
            continue
        selected[question_id] = match
    if errors:
        raise ContractError("production manifest 未闭合: " + "；".join(errors))
    payload: dict[str, Any] = {
        "schema_name": "production_manifest",
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "status": "ready",
        "selection_basis": "paper.answer-map.primary_result_id" if answer_path.is_file() else "current production priority",
        "results": {
            question_id: {
                "result_id": row["result_id"],
                "kind": row.get("kind"),
                "output_files": row.get("output_files", []),
                "input_hashes": row.get("input_hashes", {}),
                "output_hashes": row.get("output_hashes", {}),
            }
            for question_id, row in selected.items()
        },
        "created_at": utc_now(),
    }
    if write:
        atomic_json(run_dir / MANIFEST_PATH, payload)
    return payload


def require_production_manifest(run_dir: Path) -> dict[str, Any]:
    """要求 manifest 与当前结果索引保持一致。"""
    path = run_dir / MANIFEST_PATH
    if not path.is_file():
        return build_production_manifest(run_dir)
    payload = load_json(path)
    if payload.get("run_id") != read_simple_state(run_dir)["run_id"]:
        raise ContractError("production manifest run_id 不一致")
    fresh = build_production_manifest(run_dir, write=False)
    if payload.get("results") != fresh.get("results"):
        raise ContractError("production manifest 已过期，请从当前结果重新生成")
    return payload
