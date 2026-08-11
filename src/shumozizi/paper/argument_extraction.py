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

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.core.schema import require_valid
from shumozizi.paper.publication import (
    publication_entrypoint,
    publication_source_digest,
    publication_text_sources,
)
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


def _source_paths(root: Path, source_role: str) -> list[tuple[Path, str]]:
    """按创作或发布语义选择源码，避免长稿冒充最终提交稿。"""
    if source_role == "author_draft":
        for relative in ("paper/longform-source.tex", "paper/longform-source.typ"):
            path = root / relative
            if path.is_file() and path.stat().st_size > 0:
                return [(path, relative)]
    if source_role not in {"author_draft", "publication"}:
        raise ContractError("source_role 必须为 author_draft 或 publication")
    try:
        return [
            (path, path.relative_to(root).as_posix())
            for path in publication_text_sources(root)
        ]
    except ContractError:
        return []


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


def _heading_title(raw: str) -> str | None:
    """提取 LaTeX、Typst 或 Markdown 的真实标题文本。"""
    stripped = raw.strip()
    latex = re.match(
        r"\\(?:section|subsection|subsubsection|paragraph)\*?(?:\[[^\]]*\])?\{([^{}]+)\}",
        stripped,
    )
    if latex:
        return _clean_markup(latex.group(1))
    first_line = stripped.splitlines()[0].strip() if stripped else ""
    if re.match(r"^(?:#{1,6}|={1,6})\s+", first_line):
        return _clean_markup(re.sub(r"^(?:#{1,6}|={1,6})\s+", "", first_line))
    return None


def _question_profiles(root: Path) -> dict[str, str]:
    """从正式问题合同构造语义标题匹配语料，避免依赖正文中的 Q 提及。"""
    path = root / "analysis/MODELING_UNITS.json"
    if not path.is_file():
        return {}
    try:
        payload = load_json(path)
    except ContractError:
        return {}
    profiles: dict[str, list[str]] = {}
    story = payload.get("research_story", {})
    for item in story.get("question_progression", []) if isinstance(story, dict) else []:
        if not isinstance(item, dict) or not isinstance(item.get("question_id"), str):
            continue
        profiles.setdefault(item["question_id"], []).extend(
            str(item.get(key, ""))
            for key in ("role", "upgrade", "new_difficulty", "new_mechanism", "answer_increment")
        )
    for unit in payload.get("units", []):
        if not isinstance(unit, dict) or not isinstance(unit.get("question_id"), str):
            continue
        question_id = unit["question_id"]
        answer = unit.get("answer_contract", {})
        delta = unit.get("question_delta", {})
        endpoint = answer.get("primary_endpoint", {}) if isinstance(answer, dict) else {}
        profiles.setdefault(question_id, []).extend(
            [
                str(unit.get("unit_id", "")),
                str(answer.get("required_output", "")) if isinstance(answer, dict) else "",
                str(answer.get("decision_scope", "")) if isinstance(answer, dict) else "",
                str(endpoint.get("name", "")) if isinstance(endpoint, dict) else "",
                str(endpoint.get("definition", "")) if isinstance(endpoint, dict) else "",
                str(delta.get("possible_objective_change", "")) if isinstance(delta, dict) else "",
            ]
        )
    return {
        question_id: re.sub(r"\s+", " ", " ".join(parts)).strip()
        for question_id, parts in profiles.items()
    }


def _semantic_heading_question_id(title: str, profiles: dict[str, str]) -> str | None:
    """以问题合同中的区分性字符片段识别未写 Q 编号的语义标题。"""
    compact = re.sub(r"\s+", "", title)
    chunks = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]+", compact)
    grams = {
        chunk[start : start + width]
        for chunk in chunks
        for width in (2, 3, 4)
        for start in range(max(0, len(chunk) - width + 1))
        if len(chunk) >= width
    }
    if not grams or not profiles:
        return None
    frequencies = {
        gram: sum(gram.casefold() in profile.casefold() for profile in profiles.values())
        for gram in grams
    }
    scores = {
        question_id: sum(
            len(gram) ** 2 * (len(profiles) - frequencies[gram] + 1)
            for gram in grams
            if gram.casefold() in profile.casefold()
        )
        for question_id, profile in profiles.items()
    }
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked or ranked[0][1] < 24:
        return None
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    return ranked[0][0] if ranked[0][1] >= runner_up * 1.35 else None


def _heading_question_id(raw: str, profiles: dict[str, str]) -> str | None:
    """只从真实标题或独立短标签更新当前问题，拒绝正文中的偶然 Q 提及。"""
    stripped = raw.strip()
    title = _heading_title(raw)
    if title is not None:
        return _question_id(title) or _semantic_heading_question_id(title, profiles)
    cleaned = _clean_markup(stripped)
    if len(cleaned) <= 24 and re.fullmatch(
        r"(?:Q\s*[1-9]\d*|问题\s*[一二三四五六七八九十\d]+)\s*[:：.]?",
        cleaned,
        re.IGNORECASE,
    ):
        return _question_id(cleaned)
    return None


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


def extract_paper_argument_units(
    run_dir: Path,
    *,
    write: bool = True,
    source_role: str = "author_draft",
) -> dict[str, Any]:
    """从作者长稿或正式发布稿提取候选论证单元并绑定源码摘要。

    Args:
        run_dir: 当前运行目录。
        write: 是否写入兼容的论证单元产物。
        source_role: ``author_draft`` 用于 Author Pass，``publication`` 只读取最终入口闭包。
    """
    root = run_dir.resolve()
    state = read_simple_state(root)
    sources = _source_paths(root, source_role)
    if not sources:
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
        result_ids = _answer_result_ids(root)
        existing_figures = _existing_figures(root)
        question_profiles = _question_profiles(root)
        required = {str(item) for item in state.get("required_questions", [])}
        arguments: list[dict[str, Any]] = []
        question_counts: dict[str, int] = {}
        for path, relative in sources:
            text = path.read_text(encoding="utf-8", errors="replace")
            current_question: str | None = None
            for raw_match in re.finditer(
                r"(?s)(?:^|\n\s*\n)(.*?)(?=\n\s*\n|$)", text
            ):
                raw = raw_match.group(0).strip()
                if not raw:
                    continue
                cleaned = _clean_markup(raw)
                detected_question = _heading_question_id(raw, question_profiles)
                if detected_question:
                    current_question = detected_question
                if len(cleaned) < 24:
                    continue
                question_id = current_question
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
        try:
            primary_path = publication_entrypoint(root) if source_role == "publication" else sources[0][0]
            source_path = primary_path.relative_to(root).as_posix()
            source_sha256 = (
                publication_source_digest(root, entrypoint=primary_path)
                if source_role == "publication"
                else sha256_file(primary_path)
            )
        except ContractError:
            source_path = sources[0][1]
            source_sha256 = sha256_file(sources[0][0])
        payload = {
            "schema_name": "paper_argument_units",
            "schema_version": "1.0",
            "run_id": state["run_id"],
            "source_path": source_path,
            "source_sha256": source_sha256,
            "extraction_method": "structured_text_heuristic",
            "arguments": arguments,
            "generated_at": utc_now(),
        }
    require_valid(payload, "paper_argument_units")
    if write:
        atomic_json(root / PAPER_ARGUMENT_UNITS_PATH, payload)
    return payload
