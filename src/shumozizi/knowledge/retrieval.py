"""把仓内论文卡检索接入 Competition-First v3.2 运行。"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

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
_MANUSCRIPT_SUFFIXES = frozenset({".tex", ".typ"})
_UNSAFE_PATTERN = re.compile(
    r"\d|```|`{3}|[$=∑∫]|\\(?:begin|end|frac|sum|int)|"
    r"\b(?:import|from|def|class|return|function|select)\b",
    re.IGNORECASE,
)
_FAILURE_MODE_SECTIONS = {
    "key_interpretation_decision": "关键题意裁决",
    "tempting_wrong_interpretation": "最诱人的错误解释",
    "minimal_discriminating_counterexample": "最小判别反例",
    "decomposition_conditions": "分解的成立条件",
    "validity_scope": "结论有效范围",
}
_GENERIC_PAPER_PATTERNS = (
    "先给数据画像或题面对象图，再进入统一模型",
    "共享符号、状态与判据只建立一次，后问只写增量",
    "每问按直接答案—机制解释—局部验证—边界闭环",
    "名义最优与稳健建议分栏呈现，避免相互替换",
    "主图承担一个清晰论点，稳定性与机械复算进入附录",
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


def _candidate_patterns(body: str, *, limit: int = 2) -> list[str]:
    """只提取不含数字、公式或代码的结构模式。"""
    limit = min(max(limit, 1), 2)
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


def _failure_mode_lessons(body: str) -> dict[str, str]:
    """提取论文卡中的可选失败模式，不复制数字、公式或代码。"""
    lessons: dict[str, str] = {}
    for field, section_name in _FAILURE_MODE_SECTIONS.items():
        section = _card_section(body, section_name)
        for paragraph in re.split(r"\n+|；", section):
            text = re.sub(r"^\s*[-*+]\s*", "", paragraph).strip().strip("。")
            text = text.replace("`", "")
            if len(text) >= 8 and not _UNSAFE_PATTERN.search(text):
                lessons[field] = text
                break
    return lessons


def _visual_patterns(body: str, paper_id: str) -> list[dict[str, Any]]:
    """从论文卡的“视觉模式”小节读取结构化作图语法。

    视觉卡只保存面板、阅读顺序和适用边界，不保存来源论文的坐标、数据、
    数值结论或代码；缺少该小节的旧卡继续按纯文字模式兼容。
    """
    section = _card_section(body, "视觉模式")
    if not section:
        return []
    fenced = re.search(r"```(?:yaml|yml)\s*(.*?)```", section, re.IGNORECASE | re.DOTALL)
    source = fenced.group(1) if fenced else section
    try:
        parsed = yaml.safe_load(source)
    except yaml.YAMLError as exc:
        raise ContractError(f"论文卡 {paper_id} 的视觉模式 YAML 无法解析: {exc}") from exc
    if isinstance(parsed, dict):
        parsed = parsed.get("visual_patterns", [parsed])
    if not isinstance(parsed, list):
        raise ContractError(f"论文卡 {paper_id} 的视觉模式必须是数组")
    patterns: list[dict[str, Any]] = []
    for index, item in enumerate(parsed, start=1):
        if not isinstance(item, dict):
            raise ContractError(f"论文卡 {paper_id} 的视觉模式第 {index} 项必须是对象")
        pattern = dict(item)
        pattern_id = pattern.get("pattern_id") or f"{paper_id}:V{index}"
        if not isinstance(pattern_id, str) or len(pattern_id.strip()) < 3:
            raise ContractError(f"论文卡 {paper_id} 的视觉模式缺少有效 pattern_id")
        pattern["pattern_id"] = pattern_id.strip()
        required = (
            "visual_archetype",
            "argument_roles",
            "reading_order",
            "visible_elements",
            "required_data_fields",
            "applicable_when",
            "not_applicable_when",
            "transferable_principle",
        )
        missing = [field for field in required if not pattern.get(field)]
        if missing:
            raise ContractError(
                f"论文卡 {paper_id} 的视觉模式 {pattern['pattern_id']} 缺少: {', '.join(missing)}"
            )
        patterns.append(pattern)
    if len(patterns) > 4:
        raise ContractError(f"论文卡 {paper_id} 的视觉模式最多保留 4 项")
    return patterns


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
    limit: int = 3,
) -> Path:
    """检索论文卡并写入一次轻量、可判断的分析阶段记录。

    该记录不绑定论文索引哈希。知识库后续更新不会使已经执行的实验失效；
    只有主动重跑检索时，候选模式才会变化。
    """
    normalized = normalize_task_fingerprint(run_dir, fingerprint)
    limit = min(max(limit, 1), 3)
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
                # 混合四字段分低于阈值时，若 structural_tags 上的受控结构概念重叠
                # 足够强（>=3 个共享概念且重叠率 >=0.5），仍视为结构命中。这修复
                # “强统计结构匹配被 0.15 权重稀释到 0.30 混合阈值以下”的漏召回。
                blended_ok = float(item["structural_similarity"]) >= _MIN_STRUCTURAL_SIMILARITY
                concept_ok = (
                    float(item.get("structural_tag_concepts_overlap", 0.0)) >= 0.5
                    and int(item.get("structural_tag_shared_concepts", 0)) >= 3
                )
                if not (blended_ok or concept_ok):
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
                matched_card = {
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
                visual_patterns = _visual_patterns(card["body"], str(item["paper_id"]))
                if visual_patterns:
                    matched_card["visual_patterns"] = visual_patterns
                failure_lessons = _failure_mode_lessons(card["body"])
                if failure_lessons:
                    matched_card["failure_mode_lessons"] = failure_lessons
                matched_cards.append(matched_card)
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
    document = _validate_analysis_retrieval_document(run_dir, load_json(path))
    from shumozizi.knowledge.usage import build_knowledge_usage_report, knowledge_usage_errors

    usage = build_knowledge_usage_report(run_dir, stage="analysis")
    errors = knowledge_usage_errors(usage)
    if errors:
        raise ContractError("采用知识尚未绑定当前建模或图表合同: " + "；".join(errors))
    return document


def _analysis_decisions(document: dict[str, Any]) -> dict[str, str]:
    """返回供写作模板展示的分析阶段判断。"""
    return {
        pattern_id: decision
        for pattern_id, (decision, _item) in _decision_map(document).items()
    }


def write_paper_knowledge_application(
    run_dir: Path,
    *,
    overwrite: bool = False,
    reopen_pattern_ids: list[str] | None = None,
) -> Path:
    """生成写作判断模板，只重审分析已采用或显式重新打开的模式。"""
    analysis = require_analysis_knowledge_retrieval(run_dir)
    output_path = run_dir / PAPER_APPLICATION_PATH
    if output_path.is_file() and not overwrite:
        return output_path
    decision_records = _decision_map(analysis)
    decisions = _analysis_decisions(analysis)
    reopened = list(dict.fromkeys(reopen_pattern_ids or []))
    unknown_reopened = sorted(set(reopened) - set(decision_records))
    invalid_reopened = sorted(
        pattern_id
        for pattern_id in reopened
        if pattern_id in decision_records and decision_records[pattern_id][0] != "rejected"
    )
    if unknown_reopened:
        raise ContractError("重新打开判断包含未知模式: " + ", ".join(unknown_reopened))
    if invalid_reopened:
        raise ContractError("只有分析阶段已拒绝的模式可以重新打开: " + ", ".join(invalid_reopened))
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
        "## 写作阶段待判断模式",
        "",
        "默认只重审分析阶段已采用的模式；分析阶段已拒绝的模式自动继承为拒绝。"
        "只有显式 reopen 才重新判断。写作阶段最多采用来自 2 张论文卡的模式。",
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
                "本次没有结构相似论文卡。以下通用结构模式仅用于组织论文，"
                "不提供当前题事实、方法选择、数值结论或引用：",
                "",
                *[f"- {pattern}" for pattern in _GENERIC_PAPER_PATTERNS],
                "",
                "论文的模型、答案和证据仍只依据当前题面、数据和真实结果。",
                "",
            ]
        )
    inherited_rejections = [
        (paper_id, pattern)
        for paper_id, pattern in patterns
        if decisions[pattern["pattern_id"]] == "rejected"
        and pattern["pattern_id"] not in reopened
    ]
    if inherited_rejections:
        lines.extend(["## 分析阶段已拒绝（自动继承）", ""])
        for paper_id, pattern in inherited_rejections:
            reason = decision_records[pattern["pattern_id"]][1]["reason"]
            lines.append(
                f"- `{pattern['pattern_id']}`（`{paper_id}`）：{reason}"
            )
        lines.append("")
    for paper_id, pattern in patterns:
        pattern_id = pattern["pattern_id"]
        if decisions[pattern_id] == "rejected" and pattern_id not in reopened:
            continue
        lines.extend(
            [
                f"## `{pattern_id}`",
                "",
                f"- 来源卡片：`{paper_id}`",
                f"- 候选模式：{pattern['pattern']}",
                f"- 分析阶段判断：{decisions[pattern_id]}",
                *(
                    ["- 重新打开：是", "- 重新打开理由：待填写"]
                    if pattern_id in reopened
                    else []
                ),
                "- 写作决定：待判断",
                "- 理由：待填写",
                "- 应用位置：待填写",
                "- 当前题证据：待填写",
                "- 正文源码：待填写",
                "- 兑现锚点：待填写",
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


def _validated_paper_knowledge_application(
    run_dir: Path,
) -> tuple[Path, dict[str, Any]]:
    """校验写作迁移判断并返回可供本地成稿审计使用的结构。"""
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
    analysis_decisions = _decision_map(analysis)
    adopted_patterns: list[dict[str, str]] = []
    rejected_patterns: list[dict[str, str]] = []
    for card in analysis["matched_cards"]:
        for pattern in card["candidate_patterns"]:
            pattern_id = pattern["pattern_id"]
            section = sections.get(pattern_id)
            if section is None:
                decision, decision_item = analysis_decisions[pattern_id]
                if decision == "adopted":
                    raise ContractError(
                        f"KNOWLEDGE_APPLICATION.md 缺少分析阶段已采用模式 {pattern_id}"
                    )
                rejected_patterns.append(
                    {
                        "pattern_id": pattern_id,
                        "paper_id": card["paper_id"],
                        "pattern": pattern["pattern"],
                        "reason": decision_item["reason"],
                        "decision_source": "inherited_analysis_rejection",
                    }
                )
                continue
            source_card = _field(section, "来源卡片")
            recorded_pattern = _field(section, "候选模式")
            if source_card is None or source_card.strip("`") != card["paper_id"]:
                raise ContractError(f"候选模式 {pattern_id} 的来源卡片与分析检索不一致")
            if recorded_pattern != pattern["pattern"]:
                raise ContractError(f"候选模式 {pattern_id} 的安全模式文本已漂移")
            analysis_decision, _analysis_item = analysis_decisions[pattern_id]
            if analysis_decision == "rejected":
                reopen = _field(section, "重新打开")
                reopen_reason = _field(section, "重新打开理由")
                if reopen != "是":
                    raise ContractError(
                        f"分析阶段已拒绝模式 {pattern_id} 只有显式 reopen 才能重新判断"
                    )
                if (
                    reopen_reason is None
                    or len(reopen_reason) < 8
                    or _PLACEHOLDER_PATTERN.search(reopen_reason)
                ):
                    raise ContractError(f"重新打开模式 {pattern_id} 必须说明实质理由")
            decision = _field(section, "写作决定")
            reason = _field(section, "理由")
            if decision not in {"采用", "拒绝"}:
                raise ContractError(f"候选模式 {pattern_id} 必须明确采用或拒绝")
            if reason is None or len(reason) < 8 or _PLACEHOLDER_PATTERN.search(reason):
                raise ContractError(f"候选模式 {pattern_id} 必须给出实质写作判断理由")
            if decision == "采用":
                application = _field(section, "应用位置")
                evidence = _field(section, "当前题证据")
                source_path = _field(section, "正文源码")
                realization_anchor = _field(section, "兑现锚点")
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
                if source_path is None or _PLACEHOLDER_PATTERN.search(source_path):
                    raise ContractError(f"采用模式 {pattern_id} 必须声明实际正文源码")
                source_path = source_path.strip("`")
                source = resolve_inside(run_dir, source_path, must_exist=False)
                source_relative = relative_inside(run_dir, source).as_posix()
                if (
                    not source_relative.startswith("paper/")
                    or Path(source_relative).suffix.casefold() not in _MANUSCRIPT_SUFFIXES
                ):
                    raise ContractError(
                        f"采用模式 {pattern_id} 的正文源码必须是 paper/ 下的实际稿件源文件"
                    )
                if (
                    realization_anchor is None
                    or len(realization_anchor) < 4
                    or _PLACEHOLDER_PATTERN.search(realization_anchor)
                ):
                    raise ContractError(f"采用模式 {pattern_id} 必须声明正文兑现锚点")
                adopted_patterns.append(
                    {
                        "pattern_id": pattern_id,
                        "paper_id": card["paper_id"],
                        "pattern": pattern["pattern"],
                        "reason": reason,
                        "decision_source": (
                            "explicit_reopen"
                            if analysis_decision == "rejected"
                            else "paper_reassessment"
                        ),
                        "planned_location": application,
                        "current_evidence": evidence,
                        "source_path": source_relative,
                        "realization_anchor": realization_anchor,
                    }
                )
            else:
                rejected_patterns.append(
                    {
                        "pattern_id": pattern_id,
                        "paper_id": card["paper_id"],
                        "pattern": pattern["pattern"],
                        "reason": reason,
                        "decision_source": (
                            "explicit_reopen"
                            if analysis_decision == "rejected"
                            else "paper_reassessment"
                        ),
                    }
                )
    selected_cards = list(
        dict.fromkeys(item["paper_id"] for item in adopted_patterns)
    )
    if len(selected_cards) > 2:
        raise ContractError("写作阶段最多采用 2 张论文卡中的可迁移模式")
    return path, {
        "analysis_status": analysis["status"],
        "selected_cards": selected_cards,
        "adopted_patterns": adopted_patterns,
        "rejected_patterns": rejected_patterns,
        "evidence_boundary": "knowledge_cards_are_not_current_evidence",
    }


def require_paper_knowledge_application(run_dir: Path) -> Path:
    """要求首版可审阅论文前逐项完成写作迁移判断。"""
    path, _application = _validated_paper_knowledge_application(run_dir)
    return path


def read_paper_knowledge_application(run_dir: Path) -> dict[str, Any]:
    """读取已验证的写作迁移决定，供本地论文兑现审计使用。

    Args:
        run_dir: 当前 Competition-First v3.2 运行目录。

    Returns:
        选中的卡片、采用/拒绝模式、计划位置与当前题证据边界。
    """
    _path, application = _validated_paper_knowledge_application(run_dir)
    return application


def _manuscript_source_closure(run_dir: Path) -> set[str]:
    """解析主稿递归包含的 LaTeX/Typst 源文件集合。"""
    paper_dir = (run_dir / "paper").resolve()
    relative_inside(run_dir, paper_dir)
    if not paper_dir.is_dir():
        raise ContractError("运行目录缺少 paper/ 稿件目录")
    entrypoint = next(
        (path for path in (paper_dir / "main.tex", paper_dir / "main.typ") if path.is_file()),
        None,
    )
    if entrypoint is None:
        raise ContractError("paper/ 下缺少 main.tex 或 main.typ 主稿入口")
    closure: set[str] = set()
    pending = [entrypoint]
    while pending:
        source = pending.pop()
        relative = relative_inside(run_dir, source).as_posix()
        if relative in closure:
            continue
        closure.add(relative)
        try:
            text = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ContractError(f"无法读取稿件源码 {relative}: {exc}") from exc
        if source.suffix.casefold() == ".tex":
            text = re.sub(r"(?m)(?<!\\)%.*$", "", text)
            references = re.findall(
                r"\\(?:input|include|subfile)\s*\{([^}]+)\}", text
            )
            default_suffix = ".tex"
        else:
            text = re.sub(r"(?m)//.*$", "", text)
            # import 只加载定义，不能证明其中的叙事文本会进入 PDF。
            references = re.findall(r'#include\s+"([^"]+)"', text)
            default_suffix = ".typ"
        for reference in references:
            value = Path(reference.strip())
            if not value.suffix:
                value = value.with_suffix(default_suffix)
            candidates = (source.parent / value, paper_dir / value)
            target = next((item for item in candidates if item.is_file()), None)
            if target is None:
                continue
            target_relative = relative_inside(paper_dir, target).as_posix()
            resolved = resolve_inside(paper_dir, target_relative, must_exist=True)
            if resolved.suffix.casefold() in _MANUSCRIPT_SUFFIXES:
                pending.append(resolved)
    return closure


def evaluate_paper_knowledge_consumption(run_dir: Path) -> dict[str, Any]:
    """核对采用的论文卡模式已经进入实际稿件源码。

    Args:
        run_dir: 当前 Competition-First v3.2 运行目录。

    Returns:
        每个采用模式的源码锚点检查及阻断错误。
    """
    application = read_paper_knowledge_application(run_dir)
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        source_closure = _manuscript_source_closure(run_dir)
        closure_error = None
    except ContractError as exc:
        source_closure = set()
        closure_error = str(exc)
    for item in application["adopted_patterns"]:
        issue: str | None = closure_error
        if issue is None and item["source_path"] not in source_closure:
            issue = "声明的正文源码未进入 main.tex/main.typ 编译包含链"
        if issue is None:
            try:
                source = resolve_inside(run_dir, item["source_path"], must_exist=True)
                text = source.read_text(encoding="utf-8")
                if source.suffix.casefold() == ".tex":
                    text = re.sub(r"(?m)(?<!\\)%.*$", "", text)
                else:
                    text = re.sub(r"(?s)/\*.*?\*/", "", text)
                    text = re.sub(r"(?m)//.*$", "", text)
                normalized_text = re.sub(r"\s+", "", text).casefold()
                normalized_anchor = re.sub(
                    r"\s+", "", item["realization_anchor"]
                ).casefold()
                if normalized_anchor not in normalized_text:
                    issue = "实际稿件源码中未找到声明的兑现锚点"
            except (ContractError, OSError, UnicodeError) as exc:
                issue = f"无法读取声明的实际稿件源码: {exc}"
        checks.append(
            {
                "pattern_id": item["pattern_id"],
                "source_path": item["source_path"],
                "realization_anchor": item["realization_anchor"],
                "status": "present" if issue is None else "missing",
                "issue": issue,
            }
        )
        if issue is not None:
            errors.append(f"知识模式 {item['pattern_id']} 未被正文消费: {issue}")
    return {"checks": checks, "errors": errors}
