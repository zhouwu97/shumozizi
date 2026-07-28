"""把仓内论文卡检索接入 Competition-First v3.2 运行。"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    load_json,
    relative_inside,
    resolve_inside,
)
from shumozizi.core.schema import require_valid
from shumozizi.knowledge.papers import read_paper_card, retrieve_papers

ANALYSIS_RETRIEVAL_PATH = Path("knowledge/analysis-retrieval.json")
PAPER_APPLICATION_PATH = Path("paper/KNOWLEDGE_APPLICATION.md")
RETRIEVAL_STATUSES = frozenset({"matched", "no_relevant_match", "unavailable_with_reason"})
FORBIDDEN_TRANSFER = (
    "原题参数",
    "公式和代码",
    "数值结论",
    "奖项评价",
)
_MIN_STRUCTURAL_SIMILARITY = 0.30
_PLACEHOLDER_PATTERN = re.compile(r"待判断|待填写|待补充|TODO|TBD", re.IGNORECASE)
_UNSAFE_PATTERN = re.compile(
    r"\d|```|`{3}|[$=∑∫]|\\(?:begin|end|frac|sum|int)|"
    r"\b(?:import|from|def|class|return|function|select)\b",
    re.IGNORECASE,
)


def _atomic_text(path: Path, value: str) -> None:
    """在同一目录原子写入文本，避免中断后留下半个迁移计划。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _text(value: Any, label: str) -> str:
    """规整必填文本。"""
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"任务指纹缺少非空字段 {label}")
    return value.strip()


def _text_list(value: Any, label: str, *, required: bool = False) -> list[str]:
    """规整文本数组并去重。"""
    if value is None and not required:
        return []
    if not isinstance(value, list):
        raise ContractError(f"任务指纹字段 {label} 必须是文本数组")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ContractError(f"任务指纹字段 {label} 只能包含非空文本")
        text = item.strip()
        if text not in normalized:
            normalized.append(text)
    if required and not normalized:
        raise ContractError(f"任务指纹字段 {label} 不能为空")
    return normalized


def normalize_task_fingerprint(run_dir: Path, fingerprint: dict[str, Any]) -> dict[str, Any]:
    """把扩展任务指纹规整为检索器和运行记录共用的稳定结构。"""
    return {
        "problem_type": _text(fingerprint.get("problem_type"), "problem_type"),
        "data_structure": _text(fingerprint.get("data_structure"), "data_structure"),
        "task_types": _text_list(fingerprint.get("task_types"), "task_types", required=True),
        "statistical_units": _text_list(
            fingerprint.get("statistical_units"), "statistical_units"
        ),
        "mathematical_difficulties": _text_list(
            fingerprint.get("mathematical_difficulties"), "mathematical_difficulties"
        ),
        "objective_structures": _text_list(
            fingerprint.get("objective_structures"), "objective_structures"
        ),
        "constraint_types": _text_list(
            fingerprint.get("constraint_types"), "constraint_types"
        ),
        "validation_risks": _text_list(
            fingerprint.get("validation_risks"), "validation_risks"
        ),
        "question_chain": _text_list(fingerprint.get("question_chain"), "question_chain"),
        "structural_tags": _text_list(
            fingerprint.get("structural_tags"), "structural_tags"
        ),
        "keywords": _text_list(fingerprint.get("keywords"), "keywords"),
    }


def _card_section(body: str, section_name: str) -> str:
    """读取论文卡的单个二级小节。"""
    lines = body.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        if line.startswith("## ") and section_name in line:
            start = index + 1
            break
    if start is None:
        return ""
    content: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        content.append(line)
    return "\n".join(content).strip()


def _candidate_patterns(body: str, *, limit: int = 3) -> list[str]:
    """只提取不含数字、公式或代码的结构模式。"""
    section = _card_section(body, "可迁移模式")
    safe_lines: list[str] = []
    inside_code = False
    for line in section.splitlines():
        if line.strip().startswith("```"):
            inside_code = not inside_code
            continue
        if not inside_code:
            safe_lines.append(line)
    candidates: list[str] = []
    for paragraph in re.split(r"\n+|；", "\n".join(safe_lines)):
        pattern = re.sub(r"^\s*[-*+]\s*", "", paragraph).strip().strip("。")
        pattern = pattern.replace("`", "")
        if len(pattern) < 8 or _UNSAFE_PATTERN.search(pattern):
            continue
        if pattern not in candidates:
            candidates.append(pattern)
        if len(candidates) >= limit:
            break
    return candidates


def _decision_lists(
    existing: dict[str, Any] | None,
    decisions: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """优先使用显式判断，否则保留已有判断。"""
    source = decisions if decisions is not None else existing or {}
    accepted = source.get("accepted_patterns", [])
    rejected = source.get("rejected_patterns", [])
    return (
        list(accepted) if isinstance(accepted, list) else [],
        list(rejected) if isinstance(rejected, list) else [],
    )


def write_analysis_knowledge_retrieval(
    run_dir: Path,
    index_path: Path | None,
    fingerprint: dict[str, Any],
    *,
    decisions: dict[str, Any] | None = None,
    unavailable_reason: str | None = None,
    limit: int = 6,
) -> Path:
    """检索论文卡并写入一次轻量、可判断的分析阶段记录。

    该记录不绑定论文索引哈希。知识库后续更新不会使已经执行的实验失效；
    只有主动重跑检索时，候选模式才会变化。
    """
    normalized = normalize_task_fingerprint(run_dir, fingerprint)
    output_path = run_dir / ANALYSIS_RETRIEVAL_PATH
    existing = load_json(output_path) if output_path.is_file() else None
    accepted, rejected = _decision_lists(existing, decisions)
    matched_cards: list[dict[str, Any]] = []
    no_match_reason: str | None = None
    recorded_unavailable_reason: str | None = None

    if unavailable_reason is not None:
        recorded_unavailable_reason = _text(unavailable_reason, "unavailable_reason")
        if len(recorded_unavailable_reason) < 12:
            raise ContractError("知识检索不可用原因至少需要 12 个字符")
        status = "unavailable_with_reason"
    else:
        if index_path is None:
            raise ContractError("分析阶段知识检索缺少论文卡索引路径")
        try:
            structural_tags = [
                *normalized["structural_tags"],
                *normalized["statistical_units"],
                *normalized["mathematical_difficulties"],
                *normalized["objective_structures"],
                *normalized["constraint_types"],
                *normalized["validation_risks"],
            ]
            matches = retrieve_papers(
                index_path,
                problem_type=normalized["problem_type"],
                data_structure=normalized["data_structure"],
                task_types=normalized["task_types"],
                keywords=normalized["keywords"],
                structural_tags=structural_tags,
                limit=limit,
            )
            repo_root = index_path.resolve().parents[2]
            for item in matches:
                if float(item["structural_similarity"]) < _MIN_STRUCTURAL_SIMILARITY:
                    continue
                indexed_card_path = Path(str(item["card_path"]))
                if indexed_card_path.is_absolute():
                    relative_inside(repo_root, indexed_card_path)
                    card_path = indexed_card_path.resolve()
                    if not card_path.is_file():
                        raise ContractError(f"文件不存在: {card_path}")
                else:
                    card_path = resolve_inside(
                        repo_root, indexed_card_path.as_posix(), must_exist=True
                    )
                card = read_paper_card(card_path)
                patterns = _candidate_patterns(card["body"])
                if not patterns:
                    continue
                matched_cards.append(
                    {
                        "paper_id": str(item["paper_id"]),
                        "title": str(item["title"]),
                        "score": float(item["score"]),
                        "structural_similarity": float(item["structural_similarity"]),
                        "domain_similarity": float(item["domain_similarity"]),
                        "matched_on": [str(reason) for reason in item["match_reasons"]],
                        "candidate_patterns": [
                            {
                                "pattern_id": f"{item['paper_id']}:P{pattern_index}",
                                "pattern": pattern,
                            }
                            for pattern_index, pattern in enumerate(patterns, start=1)
                        ],
                    }
                )
        except (ContractError, OSError, ValueError) as exc:
            status = "unavailable_with_reason"
            recorded_unavailable_reason = f"论文卡索引或卡片当前不可读取：{exc}"
        else:
            status = "matched" if matched_cards else "no_relevant_match"
            if not matched_cards:
                no_match_reason = "没有达到结构相似度下限且包含安全可迁移模式的论文卡。"

    if status != "matched":
        # 降级状态没有候选模式，不能残留上一次检索的采用或拒绝判断。
        accepted, rejected = [], []

    document = {
        "schema_name": "knowledge_retrieval",
        "schema_version": "1.0",
        "stage": "analysis",
        "run_id": run_dir.name,
        "status": status,
        "task_fingerprint": normalized,
        "matched_cards": matched_cards,
        "accepted_patterns": accepted,
        "rejected_patterns": rejected,
        "forbidden_transfer": list(FORBIDDEN_TRANSFER),
        "no_match_reason": no_match_reason,
        "unavailable_reason": recorded_unavailable_reason,
    }
    require_valid(document, "knowledge_retrieval")
    atomic_json(output_path, document)
    return output_path


def record_analysis_knowledge_decisions(
    run_dir: Path,
    *,
    accepted_patterns: list[dict[str, Any]],
    rejected_patterns: list[dict[str, Any]],
) -> Path:
    """记录对全部候选模式的采用或拒绝判断。"""
    path = run_dir / ANALYSIS_RETRIEVAL_PATH
    document = load_json(path)
    document["accepted_patterns"] = accepted_patterns
    document["rejected_patterns"] = rejected_patterns
    _validate_analysis_retrieval_document(run_dir, document)
    atomic_json(path, document)
    return path


def _decision_map(document: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    """校验采用与拒绝记录，并返回按模式 ID 索引的判断。"""
    decisions: dict[str, tuple[str, dict[str, Any]]] = {}
    for decision, field in (("adopted", "accepted_patterns"), ("rejected", "rejected_patterns")):
        for item in document.get(field, []):
            if not isinstance(item, dict):
                raise ContractError(f"{field} 只能包含对象")
            pattern_id = item.get("pattern_id")
            reason = item.get("reason")
            if not isinstance(pattern_id, str) or not pattern_id.strip():
                raise ContractError(f"{field} 缺少 pattern_id")
            if pattern_id in decisions:
                raise ContractError(f"候选模式 {pattern_id} 被重复判断")
            if not isinstance(reason, str) or len(reason.strip()) < 8:
                raise ContractError(f"候选模式 {pattern_id} 的判断理由至少需要 8 个字符")
            if decision == "adopted":
                application = item.get("route_application")
                if not isinstance(application, str) or len(application.strip()) < 8:
                    raise ContractError(f"采用模式 {pattern_id} 必须说明如何改造当前路线")
            decisions[pattern_id] = (decision, item)
    return decisions


def _validate_analysis_retrieval_document(
    run_dir: Path, document: dict[str, Any]
) -> dict[str, Any]:
    """执行 JSON Schema 之外的模式覆盖和证据边界检查。"""
    require_valid(document, "knowledge_retrieval")
    if document.get("run_id") != run_dir.name or document.get("stage") != "analysis":
        raise ContractError("分析知识检索记录与当前运行不匹配")
    status = document.get("status")
    if status not in RETRIEVAL_STATUSES:
        raise ContractError("分析知识检索记录状态无效")
    if document.get("forbidden_transfer") != list(FORBIDDEN_TRANSFER):
        raise ContractError("分析知识检索记录必须声明完整的禁止迁移边界")
    if status == "no_relevant_match" and not document.get("no_match_reason"):
        raise ContractError("no_relevant_match 必须说明无匹配原因")
    if status == "unavailable_with_reason":
        reason = document.get("unavailable_reason")
        if not isinstance(reason, str) or len(reason.strip()) < 12:
            raise ContractError("unavailable_with_reason 必须说明具体原因")

    expected = {
        pattern["pattern_id"]
        for card in document.get("matched_cards", [])
        for pattern in card.get("candidate_patterns", [])
    }
    decisions = _decision_map(document)
    unknown = sorted(set(decisions) - expected)
    missing = sorted(expected - set(decisions))
    if unknown:
        raise ContractError("知识迁移判断包含未知模式: " + ", ".join(unknown))
    if status == "matched" and missing:
        raise ContractError("进入实验前必须逐项采用或拒绝候选模式: " + ", ".join(missing))
    if status != "matched" and expected:
        raise ContractError(f"状态 {status} 不应包含候选模式")
    return document


def require_analysis_knowledge_retrieval(run_dir: Path) -> dict[str, Any]:
    """要求路线正式进入实验前已消费一次仓内知识检索。"""
    path = run_dir / ANALYSIS_RETRIEVAL_PATH
    if not path.is_file():
        raise ContractError(
            "进入实验前必须执行仓内知识检索并完成 knowledge/analysis-retrieval.json"
        )
    return _validate_analysis_retrieval_document(run_dir, load_json(path))


def _analysis_decisions(document: dict[str, Any]) -> dict[str, str]:
    """返回供写作模板展示的分析阶段判断。"""
    return {
        pattern_id: decision
        for pattern_id, (decision, _item) in _decision_map(document).items()
    }


def write_paper_knowledge_application(run_dir: Path, *, overwrite: bool = False) -> Path:
    """根据分析检索生成写作阶段逐项判断模板。"""
    analysis = require_analysis_knowledge_retrieval(run_dir)
    output_path = run_dir / PAPER_APPLICATION_PATH
    if output_path.is_file() and not overwrite:
        return output_path
    decisions = _analysis_decisions(analysis)
    lines = [
        "# KNOWLEDGE_APPLICATION",
        "",
        f"- 分析检索状态：`{analysis['status']}`",
        "- 证据边界：知识卡只提供路线与论证模式，知识卡不是当前题证据。",
        "",
        "## 禁止迁移",
        "",
        "- 原题参数",
        "- 公式和代码",
        "- 数值结论",
        "- 奖项评价",
        "",
        "## 候选模式判断",
        "",
    ]
    patterns = [
        (card["paper_id"], pattern)
        for card in analysis["matched_cards"]
        for pattern in card["candidate_patterns"]
    ]
    if not patterns:
        lines.extend(
            [
                "本次没有可供写作迁移的候选模式，论文仍只依据当前题面、数据和真实结果组织。",
                "",
            ]
        )
    for paper_id, pattern in patterns:
        pattern_id = pattern["pattern_id"]
        lines.extend(
            [
                f"## `{pattern_id}`",
                "",
                f"- 来源卡片：`{paper_id}`",
                f"- 候选模式：{pattern['pattern']}",
                f"- 分析阶段判断：{decisions[pattern_id]}",
                "- 写作决定：待判断",
                "- 理由：待填写",
                "- 应用位置：待填写",
                "- 当前题证据：待填写",
                "",
            ]
        )
    _atomic_text(output_path, "\n".join(lines))
    return output_path


def _field(section: str, label: str) -> str | None:
    """读取写作迁移模板中的单行字段。"""
    match = re.search(rf"(?m)^-\s*{re.escape(label)}[：:]\s*(.+?)\s*$", section)
    return match.group(1).strip() if match else None


def _paper_sections(text: str) -> dict[str, str]:
    """按二级标题切分写作迁移判断。"""
    sections: dict[str, str] = {}
    for chunk in re.split(r"(?m)^##\s+", text)[1:]:
        heading, _, body = chunk.partition("\n")
        sections[heading.strip().strip("`")] = body
    return sections


def require_paper_knowledge_application(run_dir: Path) -> Path:
    """要求首版可审阅论文前逐项完成写作迁移判断。"""
    analysis = require_analysis_knowledge_retrieval(run_dir)
    path = run_dir / PAPER_APPLICATION_PATH
    if not path.is_file():
        raise ContractError(
            "首版论文论证前必须完成 paper/KNOWLEDGE_APPLICATION.md 的采用或拒绝判断"
        )
    text = path.read_text(encoding="utf-8")
    if "知识卡不是当前题证据" not in text:
        raise ContractError("KNOWLEDGE_APPLICATION.md 必须声明知识卡不是当前题证据")
    for boundary in FORBIDDEN_TRANSFER:
        if boundary not in text:
            raise ContractError(f"KNOWLEDGE_APPLICATION.md 缺少禁止迁移边界：{boundary}")

    sections = _paper_sections(text)
    for card in analysis["matched_cards"]:
        for pattern in card["candidate_patterns"]:
            pattern_id = pattern["pattern_id"]
            section = sections.get(pattern_id)
            if section is None:
                raise ContractError(f"KNOWLEDGE_APPLICATION.md 缺少候选模式 {pattern_id}")
            decision = _field(section, "写作决定")
            reason = _field(section, "理由")
            if decision not in {"采用", "拒绝"}:
                raise ContractError(f"候选模式 {pattern_id} 必须明确采用或拒绝")
            if reason is None or len(reason) < 8 or _PLACEHOLDER_PATTERN.search(reason):
                raise ContractError(f"候选模式 {pattern_id} 必须给出实质写作判断理由")
            if decision == "采用":
                application = _field(section, "应用位置")
                evidence = _field(section, "当前题证据")
                if (
                    application is None
                    or len(application) < 4
                    or _PLACEHOLDER_PATTERN.search(application)
                ):
                    raise ContractError(f"采用模式 {pattern_id} 必须说明论文应用位置")
                if (
                    evidence is None
                    or len(evidence) < 8
                    or _PLACEHOLDER_PATTERN.search(evidence)
                    or not re.search(r"当前题|当前运行|题面|数据|实验|结果|模型", evidence)
                ):
                    raise ContractError(f"采用模式 {pattern_id} 必须绑定当前题证据")
    return path
