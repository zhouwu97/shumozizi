"""根据运行事实和仓内知识产物生成作者侧论文工作台。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from shumozizi.core.io import atomic_json, load_json, sha256_file
from shumozizi.core.schema import require_valid


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
    load_json(lock_path)
    route_path = run_dir / "brief" / "ROUTE_LOCK.json"
    registry_path = run_dir / "results" / "result_registry.json"
    repo_root = run_dir.parent.parent
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
        "paper_index_sha256": _file_digest(repo_root / "knowledge" / "indexes" / "papers.json"),
        "task_fingerprint_sha256": _file_digest(
            run_dir / "knowledge" / "TASK_FINGERPRINT.json"
        ),
        "pattern_transfer_plan_sha256": _file_digest(
            run_dir / "knowledge" / "PATTERN_TRANSFER_PLAN.md"
        ),
        "route_lock_sha256": _file_digest(route_path) if route_path.is_file() else "",
        "accepted_results_digest": accepted_results,
        "claim_evidence_digest": _claim_evidence_digest(run_dir),
    }


def write_paper_blueprint(
    run_dir: Path,
    questions: list[dict[str, Any]],
    *,
    research_story: str = "共享数学对象建立 -> 各问递进 -> 对照验证 -> 结论边界",
    shared_symbols: str = "待数学规格统一定义",
    shared_objects: str = "待路线锁与问题依赖共同确定",
    summary_results: str = "仅从 accepted 且 paper_allowed 的 sealed result 选取",
    literature_roles: str = "文献只支持模型选择、假设和方法依据，不替代当前题证据",
) -> Path:
    """生成给人和 AI 使用的轻量论文工作台，不生成结论。"""
    lock = load_json(run_dir / "config" / "RUN_CONFIG_LOCK.json")
    digests = _authoring_digests(run_dir)
    lines = [
        "# PAPER_BLUEPRINT",
        "",
        "本文件是作者侧工作台，不是论文成稿；所有结论必须回到 accepted/sealed result。",
        f"- run_id: `{lock['run_id']}`",
        f"- run_config_lock_sha256: `{sha256_file(run_dir / 'config' / 'RUN_CONFIG_LOCK.json')}`",
        f"- paper_index_sha256: `{digests['paper_index_sha256']}`",
        f"- task_fingerprint_sha256: `{digests['task_fingerprint_sha256']}`",
        f"- pattern_transfer_plan_sha256: `{digests['pattern_transfer_plan_sha256']}`",
        f"- route_lock_sha256: `{digests['route_lock_sha256']}`",
        f"- accepted_results_digest: `{digests['accepted_results_digest']}`",
        f"- claim_evidence_digest: `{digests['claim_evidence_digest']}`",
        "",
        "## 全文研究故事",
        "",
        research_story,
        "",
        "## 共享符号与数学对象",
        "",
        f"- 共享符号：{shared_symbols}",
        f"- 共享数学对象：{shared_objects}",
        "",
        "## 摘要结果与文献职责",
        "",
        f"- 摘要准备使用的真实结果：{summary_results}",
        f"- 文献应支持的判断：{literature_roles}",
        "",
        "## 各问章节职责",
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
                f"- 核心公式：{question.get('core_formulae', '待数学规格')}",
                f"- 求解步骤：{question.get('solution_steps', '待实验计划')}",
                f"- 基线或对照：{question.get('baseline', '必须登记 baseline')}",
                f"- 需要的结果和图表：{question.get('results_and_figures', '待结果准入')}",
                f"- 验证方式：{question.get('validation', '待验证计划')}",
                f"- 直接答案位置：{question.get('direct_answer_location', '本问章节末尾')}",
                f"- 章节职责：{question.get('chapter_role', '回答本问并承接下一问')}",
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
    normalized_claims = []
    for claim in claims:
        claim_id = str(claim["claim_id"])
        normalized_claims.append(
            {
                "claim_id": claim_id,
                "question_id": str(claim.get("question_id", claim_id.split("-")[0])),
                "claim": str(claim["claim"]),
                "motivation": str(claim.get("motivation", "说明该主张为何需要回答题目")),
                "baseline_limitation": str(
                    claim.get("baseline_limitation", "待与已登记 baseline 比较")
                ),
                "model_support": str(claim.get("model_support", claim.get("model", "待模型规格"))),
                "result_ids": list(claim.get("result_ids", claim.get("result_keys", []))),
                "comparison_evidence": list(
                    claim.get("comparison_evidence", claim.get("evidence", []))
                ),
                "validation_evidence": list(
                    claim.get("validation_evidence", claim.get("validation", []))
                ),
                "figure_ids": list(claim.get("figure_ids", [])),
                "boundary": str(claim.get("boundary", claim.get("scope", "仅限当前数据与情景"))),
                "outcome": str(claim.get("outcome", "inconclusive")),
                "paper_location": str(claim.get("paper_location", "待定")),
            }
        )
    payload = {
        "schema_name": "argument_map",
        "schema_version": "2.0",
        "run_id": lock["run_id"],
        "run_config_lock_sha256": sha256_file(run_dir / "config" / "RUN_CONFIG_LOCK.json"),
        **digests,
        "claims": normalized_claims,
    }
    require_valid(payload, "argument_map")
    path = run_dir / "claims" / "ARGUMENT_MAP.json"
    atomic_json(path, payload)
    return path


def write_figure_storyboard(run_dir: Path, figures: list[dict[str, Any]]) -> Path:
    """规划每张图要证明的主张、数据和正文位置，不生成装饰性图表。"""
    required = {
        "figure_id",
        "question_id",
        "data",
        "claim",
        "why_needed",
        "figure_type",
        "axes_and_units",
        "paper_location",
    }
    lines = [
        "# FIGURE_STORYBOARD",
        "",
        "每张图必须服务于一个可验证主张，并使用已接受结果或明确标记的待生成数据。",
        "",
    ]
    for figure in figures:
        missing = sorted(required - figure.keys())
        if missing:
            raise ValueError("图表故事板缺少字段: " + ", ".join(missing))
        lines.extend(
            [
                f"## {figure['figure_id']}",
                "",
                f"- 对应问题：{figure['question_id']}",
                f"- 使用数据：{figure['data']}",
                f"- 待证明主张：{figure['claim']}",
                f"- 为什么需要：{figure['why_needed']}",
                f"- 预期图型：{figure['figure_type']}",
                f"- 坐标轴与单位：{figure['axes_and_units']}",
                f"- 正文解释位置：{figure['paper_location']}",
                "",
            ]
        )
    path = run_dir / "paper" / "FIGURE_STORYBOARD.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
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
