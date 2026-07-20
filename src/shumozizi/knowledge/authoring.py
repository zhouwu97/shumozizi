"""根据运行锁和知识包生成作者侧蓝图与论证地图。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from shumozizi.core.io import atomic_json, load_json, sha256_file


def _file_digest(path: Path) -> str:
    return sha256_file(path) if path.is_file() else hashlib.sha256(b"").hexdigest()


def _claim_evidence_digest(run_dir: Path) -> str:
    root = run_dir / "claims"
    digest = hashlib.sha256()
    if root.is_dir():
        for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name != "ARGUMENT_MAP.json"):
            digest.update(path.relative_to(run_dir).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def _authoring_digests(run_dir: Path) -> dict[str, str]:
    lock_path = run_dir / "config" / "RUN_CONFIG_LOCK.json"
    lock = load_json(lock_path)
    route_path = run_dir / "brief" / "ROUTE_LOCK.json"
    registry_path = run_dir / "results" / "result_registry.json"
    accepted_results = ""
    if registry_path.is_file():
        registry = load_json(registry_path)
        accepted = [
            item for item in registry.get("results", [])
            if item.get("status") == "accepted" and item.get("paper_allowed") is True
        ]
        accepted_results = hashlib.sha256(
            json.dumps(accepted, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    return {
        "knowledge_pack_sha256": lock.get("knowledge_pack", {}).get("sha256", ""),
        "route_lock_sha256": _file_digest(route_path) if route_path.is_file() else "",
        "accepted_results_digest": accepted_results,
        "claim_evidence_digest": _claim_evidence_digest(run_dir),
    }


def write_paper_blueprint(run_dir: Path, questions: list[dict[str, Any]]) -> Path:
    """生成给人和 AI 使用的轻量论文工作台，不生成结论。"""
    lock = load_json(run_dir / "config" / "RUN_CONFIG_LOCK.json")
    digests = _authoring_digests(run_dir)
    lines = [
        "# PAPER_BLUEPRINT",
        "",
        "本文件是作者侧工作台，不是论文成稿；所有结论必须回到 accepted/sealed result。",
        f"- run_id: `{lock['run_id']}`",
        f"- run_config_lock_sha256: `{sha256_file(run_dir / 'config' / 'RUN_CONFIG_LOCK.json')}`",
        f"- knowledge_pack: `{lock.get('knowledge_pack', {}).get('pack_id', 'none')}`",
        f"- knowledge_pack_sha256: `{digests['knowledge_pack_sha256']}`",
        f"- route_lock_sha256: `{digests['route_lock_sha256']}`",
        f"- accepted_results_digest: `{digests['accepted_results_digest']}`",
        f"- claim_evidence_digest: `{digests['claim_evidence_digest']}`",
        "",
    ]
    for index, question in enumerate(questions, start=1):
        question_id = str(question.get("question_id", f"q{index}"))
        lines.extend(
            [
                f"## {question_id}",
                "",
                f"- 本问需要回答：{question.get('question', '待路线确认')}",
                f"- 模型与理由：{question.get('model', '待路线确认')}",
                f"- 核心假设：{question.get('assumptions', '待路线确认')}",
                f"- 变量和公式：{question.get('variables_and_formulae', '待数学规格')}",
                f"- 求解步骤：{question.get('solution_steps', '待实验计划')}",
                f"- 基线或对照：{question.get('baseline', '必须登记 baseline')}",
                f"- 需要的结果和图表：{question.get('results_and_figures', '待结果准入')}",
                f"- 验证方式：{question.get('validation', '待验证计划')}",
                f"- 允许形成的结论：{question.get('allowed_conclusion', '仅限证据支持范围')}",
                f"- 结论边界：{question.get('boundary', '不得越过结果状态')}",
                "",
            ]
        )
    path = run_dir / "paper" / "PAPER_BLUEPRINT.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path


def write_argument_map(run_dir: Path, claims: list[dict[str, Any]]) -> Path:
    """生成允许负结果和不确定结果的结构化主张地图。"""
    lock = load_json(run_dir / "config" / "RUN_CONFIG_LOCK.json")
    digests = _authoring_digests(run_dir)
    payload = {
        "schema_name": "argument_map",
        "schema_version": "1.0.0",
        "run_id": lock["run_id"],
        "run_config_lock_sha256": sha256_file(run_dir / "config" / "RUN_CONFIG_LOCK.json"),
        "knowledge_pack": lock.get("knowledge_pack"),
        **digests,
        "claims": claims,
    }
    path = run_dir / "claims" / "ARGUMENT_MAP.json"
    atomic_json(path, payload)
    return path


def verify_argument_map(run_dir: Path) -> dict[str, Any]:
    """检查论证地图绑定的输入摘要，发现知识、路线或结果变化后的过期状态。"""
    path = run_dir / "claims" / "ARGUMENT_MAP.json"
    if not path.is_file():
        return {"valid": False, "errors": ["缺少 ARGUMENT_MAP.json"]}
    document = load_json(path)
    expected = {
        "run_config_lock_sha256": sha256_file(run_dir / "config" / "RUN_CONFIG_LOCK.json"),
        **_authoring_digests(run_dir),
    }
    errors = [f"{key} 已变化" for key, value in expected.items() if document.get(key) != value]
    return {"valid": not errors, "errors": errors}
