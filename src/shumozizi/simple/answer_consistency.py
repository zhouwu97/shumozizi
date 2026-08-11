"""ANSWER_CONSISTENCY_GATE：每题正式答案必须形成可追溯的单一生产事实链。

权威定义（不以文件名或登记状态本身为权威，而以可追踪链闭合为准）：

    frozen answer（analysis/answer_map.json）
      -> registered production result（results/index.json + 真实工件）
      -> paper answer map（paper/answer-map.json）
      -> figure source

任一环节断裂即 ``RENDER_FORBIDDEN``。检查项：

- ``analysis_answer_result_not_registered``：冻结答案引用的 result_id 未登记。
- ``registered_artifact_missing``：已登记结果声明的输出工件在磁盘缺失
  （这正是 fresh run 中 _v2 最终运行 .json 丢失、只剩日志的情形）。
- ``paper_answer_map_not_aligned``：论文 answer-map 引用的结果集合不包含
  冻结答案的 primary result，或引用了未登记结果。
- ``figure_source_not_production``：current 图声明的 source_files 未落在任一
  已登记结果工件上（图源必须是 production truth，不是手工/派生数据）。

本门只做结构一致性，不比较具体数值；“字段齐全但值来自旧版本”的场景
（resolver 判 direct_render 而答案已漂移）由本门在 resolver/render 之前拦截。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, load_json

_PASS = "pass"
_BLOCKED = "blocked"


def _optional_json(root: Path, relative: str) -> dict[str, Any]:
    """读取可选 JSON；缺失时返回空对象，不把缺失当成一致。"""
    path = root / relative
    if not path.is_file():
        return {}
    value = load_json(path)
    return value if isinstance(value, dict) else {}


def _answers(payload: dict[str, Any]) -> dict[str, Any]:
    """规范 answer map 的 answers 结构。"""
    answers = payload.get("answers", payload)
    return answers if isinstance(answers, dict) else {}


def _paper_result_ids(paper: dict[str, Any], question_id: str) -> set[str]:
    """论文 answer-map 对该问引用的全部 result_id。"""
    raw = _answers(paper).get(question_id, {})
    if not isinstance(raw, dict):
        return set()
    ids = {str(item) for item in raw.get("result_ids", []) if isinstance(item, str)}
    primary = raw.get("primary_result_id")
    if isinstance(primary, str) and primary.strip():
        ids.add(primary)
    return ids


def answer_consistency_gate(run_dir: Path) -> dict[str, Any]:
    """检查每题的生产事实链是否闭合；返回 pass 或 blocked 与违规明细。"""
    root = run_dir.resolve()
    analysis = _optional_json(root, "analysis/answer_map.json")
    paper = _optional_json(root, "paper/answer-map.json")
    index = _optional_json(root, "results/index.json")
    state = _optional_json(root, "state/run.json")

    registered: dict[str, dict[str, Any]] = {}
    for result in index.get("results", []):
        if isinstance(result, dict) and isinstance(result.get("result_id"), str):
            registered[result["result_id"]] = result

    questions = [str(q) for q in state.get("required_questions", ["Q1", "Q2", "Q3", "Q4"])]
    violations: list[dict[str, Any]] = []

    analysis_answers = _answers(analysis)
    for question_id in questions:
        ana = analysis_answers.get(question_id, {})
        ana_primary = None
        if isinstance(ana, dict):
            objective = ana.get("objective_answer", {})
            if isinstance(objective, dict):
                value = objective.get("result_id")
                ana_primary = str(value) if isinstance(value, str) and value.strip() else None

        # 1) 冻结答案引用的 primary result 必须已登记。
        if ana_primary and ana_primary not in registered:
            violations.append(
                {
                    "question_id": question_id,
                    "code": "analysis_answer_result_not_registered",
                    "detail": f"frozen answer 引用 {ana_primary}，但 results/index 未登记该结果",
                }
            )
        # 2) 已登记结果的输出工件必须真实存在。
        elif ana_primary:
            for relative in registered[ana_primary].get("output_files", []):
                if not isinstance(relative, str) or not relative.strip():
                    continue
                if not (root / relative).is_file():
                    violations.append(
                        {
                            "question_id": question_id,
                            "code": "registered_artifact_missing",
                            "detail": f"{ana_primary} 登记输出 {relative} 在磁盘缺失",
                        }
                    )
        # 2b) 已登记结果的指标必须非空且可追溯；空 metrics 说明是占位登记，
        #     不能支撑正式答案（如 q3_threshold_search 的 metrics={}）。
        if ana_primary and ana_primary in registered:
            metrics = registered[ana_primary].get("metrics")
            if not isinstance(metrics, dict) or not metrics:
                violations.append(
                    {
                        "question_id": question_id,
                        "code": "registered_result_empty_metrics",
                        "detail": f"{ana_primary} 的登记指标为空，不能作为正式答案证据",
                    }
                )
        # 3) 论文 answer-map 必须引用冻结答案的 primary result，且全部已登记。
        paper_ids = _paper_result_ids(paper, question_id)
        if paper_ids:
            unregistered = sorted(paper_ids - registered.keys())
            if unregistered:
                violations.append(
                    {
                        "question_id": question_id,
                        "code": "paper_answer_map_unregistered_result",
                        "detail": "论文 answer-map 引用未登记结果: " + "、".join(unregistered),
                    }
                )
            if ana_primary and ana_primary not in paper_ids:
                violations.append(
                    {
                        "question_id": question_id,
                        "code": "paper_answer_map_not_aligned",
                        "detail": f"论文 answer-map 未引用冻结答案 primary {ana_primary}",
                    }
                )

    # 4) current 图的 source_files 必须落在已登记结果工件上（图源 = production truth）。
    figures = _optional_json(root, "figures/index.json").get("figures", [])
    production_artifacts = {
        str(item)
        for result in registered.values()
        for item in result.get("output_files", [])
        if isinstance(item, str)
    }
    for figure in figures:
        if not isinstance(figure, dict) or figure.get("status") != "current":
            continue
        # 结构解释图（explanatory_structure）没有 production 数据源：它解释论证结构，
        # 不承担数值证据，来源是论文正文本身，不强制绑定生产工件。
        if str(figure.get("provenance_type", "")) == "explanatory_structure":
            continue
        for source in figure.get("source_files", []):
            path = str(source.get("path", source)) if isinstance(source, dict) else str(source)
            if not path:
                continue
            normalized = path.lstrip("./")
            if not any(normalized == artifact.lstrip("./") for artifact in production_artifacts):
                violations.append(
                    {
                        "question_id": str(figure.get("question_id", "")),
                        "code": "figure_source_not_production",
                        "detail": f"current 图 {figure.get('figure_id')} 的 source {path} 不是已登记生产工件",
                    }
                )

    return {
        "status": _PASS if not violations else _BLOCKED,
        "violations": violations,
        "summary": {
            "questions_checked": questions,
            "registered_results": sorted(registered),
            "violation_count": len(violations),
        },
    }


def require_answer_consistency(run_dir: Path) -> dict[str, Any]:
    """渲染前的硬门：生产事实链未闭合时抛 ContractError，禁止渲染。"""
    verdict = answer_consistency_gate(run_dir)
    if verdict["status"] != _PASS:
        detail = "\n".join(
            f"- {v.get('question_id')} [{v.get('code')}] {v.get('detail')}"
            for v in verdict["violations"]
        )
        raise ContractError(
            "ANSWER_CONSISTENCY_GATE: RENDER_FORBIDDEN，生产事实链未闭合：\n" + detail
        )
    return verdict


__all__ = [
    "answer_consistency_gate",
    "require_answer_consistency",
    "_PASS",
    "_BLOCKED",
]
