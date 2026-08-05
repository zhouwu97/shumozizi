"""从长篇论文源文件提取可追溯的论证单元。

提取器只生成候选论证，不替作者判断科学事实。它保留正文段落和源码位置，
再把具有明确比较、机制、边界或数学对象信号的段落交给视觉需求层；没有
这些信号的普通叙述不会被强行变成图任务。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from shumozizi.core.io import atomic_json, load_json, sha256_file
from shumozizi.core.schema import require_valid
from shumozizi.simple.state import read_simple_state, utc_now

PAPER_ARGUMENT_UNITS_PATH = Path("paper/generated/PAPER_ARGUMENT_UNITS.json")
_ROLE_SIGNALS: dict[str, tuple[str, ...]] = {
    "mechanism": ("主要来自", "决定", "瓶颈", "活跃约束", "驱动", "因为", "由于"),
    "boundary": ("边界", "阈值", "适用范围", "仅在", "超过", "低于", "敏感性"),
    "decisive_evidence": ("优于", "相比", "对照", "差异", "优势", "提升", "降低"),
    "model_understanding": ("模型", "变量", "轨迹", "空间", "集合", "调度", "状态"),
}
_CHINESE_QUESTION = {
    "一": "Q1",
    "二": "Q2",
    "三": "Q3",
    "四": "Q4",
    "五": "Q5",
    "六": "Q6",
}


def _source_path(root: Path) -> tuple[Path, str] | None:
    """选择当前实际论文源文件，优先内部稿，兼容外部交接稿。"""
    for relative in (
        "paper/longform-source.tex",
        "paper/longform-source.typ",
        "paper/external-author/draft.tex",
    ):
        path = root / relative
        if path.is_file() and path.stat().st_size > 0:
            return path, relative
    return None


def _clean_markup(value: str) -> str:
    """去掉常见 LaTeX/Typst 外壳，保留正文语义。"""
    value = re.sub(r"(?<!\\)%[^\n]*", "", value)
    value = re.sub(r"\\(?:textbf|textit|emph|underline|section|subsection|paragraph)\{([^{}]*)\}", r"\1", value)
    value = re.sub(r"#(?:strong|emph|text)\(([^()]*)\)", r"\1", value)
    value = re.sub(r"\\[A-Za-z]+(?:\[[^\]]*\])?\s*", "", value)
    value = value.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", value).strip()


def _question_id(value: str) -> str | None:
    """从标题或段落提取 Q 编号。"""
    match = re.search(r"\bQ\s*([1-9]\d*)\b", value, re.IGNORECASE)
    if match:
        return f"Q{match.group(1)}"
    match = re.search(r"问题\s*([一二三四五六七八九十\d]+)", value)
    if not match:
        return None
    token = match.group(1)
    return f"Q{token}" if token.isdigit() else _CHINESE_QUESTION.get(token)


def _answer_result_ids(root: Path) -> dict[str, list[str]]:
    """读取正式答案结果绑定，避免把正文数字绑定到推荐层。"""
    payload: dict[str, Any] = {}
    for relative in ("paper/answer-map.json", "analysis/answer_map.json"):
        path = root / relative
        if path.is_file():
            payload = load_json(path)
            break
    answers = payload.get("answers", payload)
    result_ids: dict[str, list[str]] = {}
    if not isinstance(answers, dict):
        return result_ids
    for question_id, item in answers.items():
        if not isinstance(item, dict):
            continue
        ids = [str(value) for value in item.get("result_ids", []) if isinstance(value, str)]
        primary = item.get("primary_result_id")
        if isinstance(primary, str) and primary not in ids:
            ids.insert(0, primary)
        result_ids[str(question_id)] = ids
    return result_ids


def _existing_figures(root: Path) -> dict[str, list[str]]:
    """读取同一问题已有的 current 图，供论证提取结果展示现状。"""
    path = root / "figures/index.json"
    if not path.is_file():
        return {}
    payload = load_json(path)
    grouped: dict[str, list[str]] = {}
    for item in payload.get("figures", []):
        if (
            isinstance(item, dict)
            and item.get("status") == "current"
            and isinstance(item.get("question_id"), str)
            and isinstance(item.get("figure_id"), str)
        ):
            grouped.setdefault(item["question_id"], []).append(item["figure_id"])
    return grouped


def _role_for_text(text: str) -> tuple[str | None, str]:
    """给正文候选分配角色和可视化等级。"""
    scores = {
        role: sum(1 for token in signals if token in text)
        for role, signals in _ROLE_SIGNALS.items()
    }
    role, score = max(scores.items(), key=lambda item: item[1])
    if score == 0:
        return None, "low"
    numeric_or_structural = bool(re.search(r"\d|约束|区间|方案|日期|天|时段|比例", text))
    return role, "high" if score >= 2 or numeric_or_structural else "medium"


def _digest(argument: dict[str, Any]) -> str:
    """计算不含生成时间的稳定论证摘要。"""
    fields = {
        key: argument[key]
        for key in (
            "argument_id",
            "question_id",
            "claim",
            "role",
            "source_span",
            "source_result_ids",
            "visualizability",
        )
        if key in argument
    }
    encoded = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def extract_paper_argument_units(run_dir: Path, *, write: bool = True) -> dict[str, Any]:
    """从当前论文源提取候选论证单元并绑定源码摘要。"""
    root = run_dir.resolve()
    state = read_simple_state(root)
    source = _source_path(root)
    if source is None:
        payload = {
            "schema_name": "paper_argument_units",
            "schema_version": "1.0",
            "run_id": state["run_id"],
            "source_path": None,
            "source_sha256": None,
            "extraction_method": "structured_text_heuristic",
            "arguments": [],
            "generated_at": utc_now(),
        }
    else:
        path, relative = source
        text = path.read_text(encoding="utf-8", errors="replace")
        result_ids = _answer_result_ids(root)
        existing_figures = _existing_figures(root)
        required = {str(item) for item in state.get("required_questions", [])}
        arguments: list[dict[str, Any]] = []
        question_counts: dict[str, int] = {}
        current_question: str | None = None
        for raw_match in re.finditer(
            r"(?s)(?:^|\n\s*\n)(.*?)(?=\n\s*\n|$)", text
        ):
            raw = raw_match.group(0).strip()
            if not raw:
                continue
            cleaned = _clean_markup(raw)
            detected_question = _question_id(cleaned)
            if detected_question:
                current_question = detected_question
            if len(cleaned) < 24:
                continue
            question_id = detected_question or current_question
            if question_id not in required:
                continue
            role, visualizability = _role_for_text(cleaned)
            explicit_id = re.search(r"(?:label|argument[_-]?id)\s*[:=]?[{(]?([A-Za-z0-9_.:-]+)", raw, re.IGNORECASE)
            if role is None and not explicit_id:
                continue
            start_line = text.count("\n", 0, raw_match.start()) + 1
            end_line = text.count("\n", 0, raw_match.end()) + 1
            question_counts[question_id] = question_counts.get(question_id, 0) + 1
            argument_id = (
                str(explicit_id.group(1))
                if explicit_id
                else f"PA-{question_id}-{question_counts[question_id]:02d}"
            )
            item = {
                "argument_id": argument_id,
                "question_id": question_id,
                "claim": cleaned[:1000],
                "role": role or "claim",
                "source_span": f"{relative}:{start_line}-{end_line}",
                "source_result_ids": result_ids.get(question_id, []),
                "visualizability": visualizability,
                "existing_figure_ids": existing_figures.get(question_id, []),
            }
            item["argument_digest"] = _digest(item)
            arguments.append(item)
        payload = {
            "schema_name": "paper_argument_units",
            "schema_version": "1.0",
            "run_id": state["run_id"],
            "source_path": relative,
            "source_sha256": sha256_file(path),
            "extraction_method": "structured_text_heuristic",
            "arguments": arguments,
            "generated_at": utc_now(),
        }
    require_valid(payload, "paper_argument_units")
    if write:
        atomic_json(root / PAPER_ARGUMENT_UNITS_PATH, payload)
    return payload
