"""识别数学建模论文中的高置信度错误与报告式写作风险。

可直接定位的内部术语、机械报账、摘要流水账、核心问空壳和主图未消费进入
``errors``；需要结合页面与上下文判断的信号仍只进入 ``warnings``。
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, load_json, relative_inside

_SOURCE_SUFFIXES = frozenset({".tex", ".typ", ".md"})
_EXCLUDED_PARTS = frozenset(
    {"generated", "submission", "source_appendix", "archive", "work"}
)
_HEADING_PATTERN = re.compile(
    r"\\(?P<latex_level>section|subsection|subsubsection)\*?\{(?P<latex_title>[^{}]+)\}"
    r"|^(?P<markdown_marks>#{1,4}|={1,4})\s*(?P<markdown_title>.+?)\s*$",
    re.MULTILINE,
)
_QUESTION_PATTERN = re.compile(
    r"\bQ(?P<arabic>[1-9]\d*)\b|问题\s*(?P<cn>[一二三四五六七八九十]+)|"
    r"第\s*(?P<cn_alt>[一二三四五六七八九十]+)\s*问",
    re.IGNORECASE,
)
_BLOCKING_INTERNAL_TERMS = {
    "result_id": re.compile(r"\bresult_id\b", re.IGNORECASE),
    "scorer": re.compile(r"\bscorer\b", re.IGNORECASE),
    "晋级结果": re.compile(r"晋级结果"),
    "fallback": re.compile(r"\bfallback(?:_selected)?\b", re.IGNORECASE),
    "production result": re.compile(r"\bproduction result\b", re.IGNORECASE),
    "生产结果": re.compile(r"生产结果"),
    "task receipt": re.compile(r"\btask receipt\b", re.IGNORECASE),
    "回执": re.compile(r"回执"),
    "objective_answer": re.compile(r"\bobjective_answer\b", re.IGNORECASE),
    "current result": re.compile(r"\bcurrent result\b", re.IGNORECASE),
    # 规划层元评审措辞（结构地图 reason/叙事竞争 risks 等）只描述"如何被审核"，
    # 不是论文对读者的论证语言，泄漏进正文一律视为 E001。
    "证据桥": re.compile(r"证据桥"),
    "可信边界": re.compile(r"可信边界"),
    "结构证据": re.compile(r"结构证据"),
    "支持边界": re.compile(r"支持边界"),
    "关键验证证据": re.compile(r"关键验证证据"),
}
_ADVISORY_INTERNAL_TERMS = (
    "oracle",
    "endpoint",
    "challenger",
    "工作流",
)
_REPORT_PHRASE_PATTERNS = {
    "本问采用": re.compile(r"本问(?:采用|使用|选用)", re.IGNORECASE),
    "结果如表图": re.compile(
        r"(?:运行|求解|计算)?结果(?:如|见)(?:表|图)|由(?:表|图).{0,8}可知",
        re.IGNORECASE,
    ),
    "最终得到": re.compile(r"(?:最终|最后)(?:得到|获得|求得)", re.IGNORECASE),
    "清单引导": re.compile(r"具体结果如下|参数设置如下", re.IGNORECASE),
}
_ABSTRACT_UNIFIED_PATTERNS = (
    re.compile(r"困难|非显然|关键矛盾|冲突"),
    re.compile(r"统一|共享|联合|共同|贯穿|整体|建模结构"),
    re.compile(r"机制|原因|规律|活跃约束|边际收益|权衡|瓶颈|可信边界"),
)
_DERIVATION_PATTERN = re.compile(
    r"关键推导|命题|证明|由此可得|从而得到|可推出|"
    r"\\begin\{equation|\\\[|\$\$",
    re.IGNORECASE,
)
_MECHANISM_PATTERN = re.compile(
    r"机制|原因在于|这是因为|活跃约束|边际收益|权衡|瓶颈|意味着",
    re.IGNORECASE,
)
_OBSERVATION_PATTERN = re.compile(
    r"观察|显示|呈现|可见|可以看出|表明|随着|高于|低于|上升|下降|拐点|集中",
    re.IGNORECASE,
)
_FIGURE_MECHANISM_PATTERN = re.compile(
    r"原因|机制|因为|源于|导致|活跃约束|约束开始|瓶颈|权衡|边际",
    re.IGNORECASE,
)
_CONCLUSION_IMPACT_PATTERN = re.compile(
    r"因此|从而|意味着|对(?:主)?结论|决策|策略|建议|应当|可判定|支持",
    re.IGNORECASE,
)
_FORMULA_EXPLANATION_PATTERN = re.compile(
    r"其中|表示|定义|记作|令|可得|由此|因此|约束|含义|意味着|说明|即",
    re.IGNORECASE,
)
_FORMULA_BLOCK_PATTERN = re.compile(
    r"\\begin\{(?:equation|equation\*|align|align\*)\}.*?"
    r"\\end\{(?:equation|equation\*|align|align\*)\}|"
    r"\\\[.*?\\\]|\$\$.*?\$\$",
    re.IGNORECASE | re.DOTALL,
)
_GENERIC_HEADING_ROLES = (
    ("问题分析", re.compile(r"^(?:问题)?分析$")),
    ("模型建立与求解", re.compile(r"模型(?:的)?建立与求解")),
    ("模型求解结果", re.compile(r"模型求解结果")),
    ("结果分析与结论", re.compile(r"结果分析.*(?:结论|答案)")),
    ("模型建立", re.compile(r"^(?:问题)?模型(?:的)?建立$|^模型建立$")),
    ("模型求解", re.compile(r"^(?:参数估计与)?模型求解(?:方法)?$|^模型求解$")),
    ("结果分析", re.compile(r"^结果分析$")),
    ("模型检验", re.compile(r"^模型(?:的)?检验$|^模型检验$")),
)
_APPENDIX_START_PATTERN = re.compile(
    r"\\appendix\b|\\(?:chapter|section)\*?\{\s*(?:附录|Appendix)\b",
    re.IGNORECASE,
)
_CN_DIGITS = {character: value for value, character in enumerate("零一二三四五六七八九")}


def _manuscript_sources(run_dir: Path) -> list[Path]:
    """收集真实正文源文件，排除控制文档、生成物和源码附件。"""
    paper_dir = run_dir / "paper"
    if not paper_dir.is_dir():
        return []

    # 外部作者模式下 draft.tex 是唯一待审正文；交接说明与隔离编译副本不是论文。
    # 优先返回这一文件，避免同一正文被重复计数，也避免内部交接字段触发正文泄漏误报。
    external_draft = paper_dir / "external-author" / "draft.tex"
    if external_draft.is_file():
        return [external_draft]

    sources: list[Path] = []
    for path in sorted(paper_dir.rglob("*")):
        if (
            not path.is_file()
            or path.suffix.casefold() not in _SOURCE_SUFFIXES
            or any(part.casefold() in _EXCLUDED_PARTS for part in path.parts)
            or "appendix" in path.stem.casefold()
            or "附录" in path.stem
            or path.name.startswith("PAPER_")
            or path.name in {
                "ARGUMENT_PLAN.md",
                "STORYBOARD.md",
                "RESEARCH_STORYBOARD.md",
                "CITATION_PLAN.md",
            }
        ):
            continue
        sources.append(path)
    return sources


def _formal_body_text(text: str) -> str:
    """截去同文件中的附录，避免把允许保留的运行说明判为正文泄漏。"""
    match = _APPENDIX_START_PATTERN.search(text)
    return text[: match.start()] if match else text


def _headings(text: str) -> list[tuple[int, str, int]]:
    """提取 LaTeX、Typst 或 Markdown 标题及其位置。"""
    records: list[tuple[int, str, int]] = []
    levels = {"section": 1, "subsection": 2, "subsubsection": 3}
    for match in _HEADING_PATTERN.finditer(text):
        if match.group("latex_level"):
            level = levels[match.group("latex_level")]
            title = match.group("latex_title")
        else:
            marks = match.group("markdown_marks")
            level = len(marks.lstrip("=")) if marks.startswith("#") else len(marks)
            title = match.group("markdown_title")
        records.append((level, title.strip(), match.start()))
    return records


def _question_key(title: str) -> str | None:
    """从章节标题提取稳定问题标识。"""
    match = _QUESTION_PATTERN.search(title)
    if match is None:
        return None
    raw = (
        match.group("arabic")
        or match.group("cn")
        or match.group("cn_alt")
    )
    return _normalize_question_id(raw)


def _normalize_question_id(raw: str) -> str:
    """把简单中文题号统一为阿拉伯数字，避免同一问题被重复计数。"""
    if raw.isascii() and raw.isdigit():
        return str(int(raw))
    if "十" not in raw:
        return str(_CN_DIGITS.get(raw, raw))
    left, right = raw.split("十", maxsplit=1)
    tens = _CN_DIGITS.get(left, 1) if left else 1
    units = _CN_DIGITS.get(right, 0) if right else 0
    return str(tens * 10 + units)


def _normalize_heading(title: str) -> str:
    """移除编号与题号，比较不同问题是否机械复制标题模板。"""
    normalized = _QUESTION_PATTERN.sub("", title)
    normalized = re.sub(r"^[\d一二三四五六七八九十.、\s]+", "", normalized)
    return re.sub(r"\s+", "", normalized).casefold()


def _question_sections(text: str) -> dict[str, tuple[str, list[str]]]:
    """按任意层级的问题标题切分正文并保留其下级标题序列。"""
    headings = _headings(text)
    sections: dict[str, tuple[str, list[str]]] = {}
    for index, (level, title, start) in enumerate(headings):
        question = _question_key(title)
        if question is None:
            continue
        end = len(text)
        subheadings: list[str] = []
        for next_level, next_title, next_start in headings[index + 1 :]:
            if next_level <= level:
                end = next_start
                break
            if next_level > level:
                normalized = _normalize_heading(next_title)
                if normalized:
                    subheadings.append(normalized)
        body = text[start:end]
        if question in sections:
            previous_body, previous_headings = sections[question]
            sections[question] = (
                f"{previous_body}\n{body}",
                [*previous_headings, *subheadings],
            )
        else:
            sections[question] = (body, subheadings)
    return sections


def _merged_question_sections(
    sources: list[tuple[Path, str]],
) -> dict[str, tuple[str, list[str]]]:
    """合并同一问题散落在不同正文源文件中的论证片段。"""
    merged: dict[str, tuple[str, list[str]]] = {}
    for _, text in sources:
        for question, (body, headings) in _question_sections(text).items():
            previous_body, previous_headings = merged.get(question, ("", []))
            merged[question] = (
                "\n".join(part for part in (previous_body, body) if part),
                [*previous_headings, *headings],
            )
    return merged


def _generic_heading_role(title: str) -> str | None:
    """把通用流程标题归并为稳定功能角色，题目特定标题保持未分类。"""
    normalized = _normalize_heading(title)
    for role, pattern in _GENERIC_HEADING_ROLES:
        if pattern.search(normalized):
            return role
    return None


def _generic_question_heading_usage(
    sources: list[tuple[Path, str]],
) -> dict[str, set[str]]:
    """统计各通用标题角色覆盖的问题，兼容国赛常见的嵌套章节。"""
    usage: dict[str, set[str]] = {}
    for _, text in sources:
        active_question: tuple[int, str] | None = None
        for level, title, _ in _headings(text):
            question = _question_key(title)
            if question is not None:
                active_question = (level, question)
            elif active_question is not None and level <= active_question[0]:
                active_question = None
            if active_question is None:
                continue
            role = _generic_heading_role(title)
            if role is not None:
                usage.setdefault(role, set()).add(active_question[1])
    return usage


def _generic_heading_repetition_threshold(root: Path) -> int:
    """按必答问题数设置保守阈值，两问论文也能识别完整模板复用。"""
    state_path = root / "state" / "run.json"
    if not state_path.is_file():
        return 3
    try:
        state = load_json(state_path)
    except (ContractError, OSError, ValueError):
        return 3
    required_questions = state.get("required_questions", [])
    if isinstance(required_questions, list) and 1 <= len(required_questions) <= 2:
        return 2
    return 3


def _abstract_text(sources: list[tuple[Path, str]], combined: str) -> str:
    """定位摘要源文件或正文摘要段。"""
    named = [
        text
        for path, text in sources
        if "abstract" in path.stem.casefold() or "摘要" in path.stem
    ]
    if named:
        return "\n".join(named)
    match = re.search(
        r"(?:\\section\*?\{摘要\}|^#{1,3}\s*摘要\s*$|^=+\s*摘要\s*$)"
        r"(?P<body>.*?)(?=\\section|^#{1,3}\s|^=+\s|\Z)",
        combined,
        re.MULTILINE | re.DOTALL,
    )
    return match.group("body") if match else ""


def _question_ids(text: str) -> set[str]:
    """提取文本中互异的问题编号。"""
    return {
        _normalize_question_id(
            match.group("arabic") or match.group("cn") or match.group("cn_alt")
        )
        for match in _QUESTION_PATTERN.finditer(text)
    }


def _list_item_count(text: str) -> int:
    """统计 LaTeX、Markdown 和编号列表项。"""
    return len(
        re.findall(
            r"\\item\b|^\s*[-*+]\s+|^\s*\d+[.)、]\s+",
            text,
            re.MULTILINE,
        )
    )


def _table_count(text: str) -> int:
    """统计 LaTeX 与 Markdown 表格的保守结构信号。"""
    latex_tables = len(re.findall(r"\\begin\{(?:table\*?|tabular\*?)\}", text))
    markdown_tables = len(
        re.findall(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$", text, re.MULTILINE)
    )
    return latex_tables + markdown_tables


def _continuous_prose_paragraphs(text: str) -> int:
    """估计具有连续论述能力的自然段数量。"""
    count = 0
    for paragraph in re.split(r"\n\s*\n", text):
        if re.search(r"\\(?:item|begin\{(?:table|tabular|itemize|enumerate))", paragraph):
            continue
        prose = re.sub(r"\\[A-Za-z]+\*?(?:\[[^]]*\])?(?:\{[^{}]*\})?", "", paragraph)
        compact = re.sub(r"\s+", "", prose)
        if len(compact) >= 45 and re.search(r"[。！？.!?；;]", prose):
            count += 1
    return count


def _core_question_ids(run_dir: Path) -> set[str]:
    """读取 1.4 建模单元中的核心问题；缺失时不猜测。"""
    path = run_dir / "analysis" / "MODELING_UNITS.json"
    if not path.is_file():
        return set()
    try:
        payload = load_json(path)
    except (OSError, ValueError):
        return set()
    return {
        str(unit.get("question_id"))
        for unit in payload.get("units", [])
        if isinstance(unit, dict)
        and unit.get("core_question") is True
        and isinstance(unit.get("question_id"), str)
    }


def _figure_argument_findings(
    run_dir: Path, combined: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """检查正文图是否被引用并获得附近的实质性解释。

    图注后的论证可以按论文自然语序展开；审计只确认读者能从正文得到
    一段可复述的观察、关系或结论含义，不把固定三联句当成科学证据。
    """
    path = run_dir / "figures" / "FIGURE_PLAN.json"
    if not path.is_file():
        return [], []
    try:
        plan = load_json(path)
    except (OSError, ValueError):
        return [], []
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for figure in plan.get("figures", []):
        is_body_figure = isinstance(figure, dict) and (
            figure.get("placement") == "body"
            or figure.get("presentation_role")
            in {"question_hero", "data_portrait", "supporting"}
        )
        if (
            not isinstance(figure, dict)
            or not is_body_figure
            or figure.get("placement") == "appendix"
            or figure.get("role") == "stability"
            or figure.get("presentation_role") == "appendix"
        ):
            continue
        label = figure.get("latex_label")
        if not isinstance(label, str):
            continue
        reference_patterns = (
            rf"\\(?:auto|page|c)?ref\{{{re.escape(label)}\}}",
            rf"@{re.escape(label)}\b",
        )
        references = [
            match
            for pattern in reference_patterns
            for match in re.finditer(pattern, combined)
        ]
        figure_id = str(figure.get("figure_id", label))
        if not references:
            warnings.append(
                {
                    "code": "E005",
                    "message": f"正文图 {figure_id} 未被正文引用，无法进入论文论证。",
                    "count": 1,
                    "figure_id": figure_id,
                    "missing_links": ["reference"],
                }
            )
            warnings.append(
                {
                    "code": "hero_figure_not_in_argument",
                    "message": f"主图 {figure_id} 未被正文交叉引用，仍像附件而非论证证据。",
                    "count": 1,
                }
            )
            continue

        best_missing = ["substantive_explanation"]
        for reference in references:
            # 解释应紧邻引用，避免正文只放一个孤立的交叉引用。
            context = combined[reference.end() : min(len(combined), reference.end() + 700)]
            substantive = any(
                pattern.search(context) is not None
                for pattern in (
                    _OBSERVATION_PATTERN,
                    _FIGURE_MECHANISM_PATTERN,
                    _CONCLUSION_IMPACT_PATTERN,
                    _FORMULA_EXPLANATION_PATTERN,
                )
            )
            if substantive:
                best_missing = []
                break
        if best_missing:
            warnings.append(
                {
                    "code": "E005",
                    "message": f"正文图 {figure_id} 的引用附近缺少实质性解释。",
                    "count": 1,
                    "figure_id": figure_id,
                    "missing_links": best_missing,
                }
            )
            warnings.append(
                {
                    "code": "hero_figure_without_interpretation",
                    "message": f"主图 {figure_id} 附近缺少可复述的实质解释。",
                    "count": 1,
                }
            )
            warnings.append(
                {
                    "code": "FIGURE_WITHOUT_INTERPRETATION",
                    "message": f"图 {figure_id} 已进入正文，但缺少可复述的实质解释。",
                    "count": 1,
                    "figure_id": figure_id,
                    "missing_links": best_missing,
                }
            )
    return errors, warnings


def _formula_explanation_findings(combined: str) -> list[dict[str, Any]]:
    """识别公式后没有任何语义解释的段落。"""
    findings: list[dict[str, Any]] = []
    for index, match in enumerate(_FORMULA_BLOCK_PATTERN.finditer(combined), 1):
        context = combined[match.end() : min(len(combined), match.end() + 500)]
        next_heading = re.search(r"\\(?:section|subsection)\*?\{|\n#{1,4}\s", context)
        if next_heading is not None:
            context = context[: next_heading.start()]
        if not _FORMULA_EXPLANATION_PATTERN.search(context):
            findings.append(
                {
                    "code": "FORMULA_WITHOUT_EXPLANATION",
                    "message": f"第 {index} 个公式后未说明变量含义、判据作用或推导后果。",
                    "count": 1,
                    "formula_index": index,
                }
            )
    return findings


def _pdf_page_count(run_dir: Path) -> int | None:
    """读取已存在 PDF 页数；没有 PDF 时返回空值，不伪造版式判断。"""
    candidates = (
        run_dir / "paper/final.pdf",
        run_dir / "paper/longform-draft.pdf",
        run_dir / "paper/draft-1.pdf",
    )
    pdf_path = next((path for path in candidates if path.is_file()), None)
    if pdf_path is None:
        return None
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(pdf_path)).pages)
    except (OSError, ValueError, TypeError):
        return None


def _scarcity_findings(
    run_dir: Path, *, core_questions: set[str], combined: str, figure_count: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """对复杂论文的篇幅和正文图数给出非阻断复核提醒。"""
    warnings: list[dict[str, Any]] = []
    pages = _pdf_page_count(run_dir)
    compact_characters = len(re.sub(r"\s+", "", combined))
    if len(core_questions) >= 3 and (
        (pages is not None and pages < 15) or (pages is None and compact_characters < 7000)
    ):
        warnings.append(
            {
                "code": "NARRATIVE_SCARCITY_REVIEW",
                "message": "多核心问题论文的正文可能过短；请人工确认推导、机制和边界没有被压缩掉。",
                "count": 1,
                "core_questions": sorted(core_questions),
                "page_count": pages,
            }
        )
    if core_questions and figure_count <= 3:
        warnings.append(
            {
                "code": "VISUAL_SCARCITY_REVIEW",
                "message": "正文图数不超过 3 张；请人工确认数学结构、机制与边界不应有互补视觉证据。",
                "count": 1,
                "core_questions": sorted(core_questions),
                "body_figure_count": figure_count,
            }
        )
    return warnings, {"page_count": pages, "body_figure_count": figure_count}


def _visual_rhythm_findings(
    *,
    core_questions: set[str],
    question_sections: dict[str, tuple[str, list[str]]],
    combined: str,
    body_figure_count: int,
) -> list[dict[str, Any]]:
    """检查图是否过度集中在单问或集中堆叠，提示页面节奏人工复核。"""
    if len(core_questions) < 2:
        return []
    references_by_question = {
        question: len(re.findall(r"\\(?:auto|page|c)?ref\{fig:[^}]+\}|@fig:[A-Za-z0-9._:-]+", body))
        for question, (body, _) in question_sections.items()
    }
    total_references = sum(references_by_question.values())
    if total_references == 0:
        return []
    dominant = max(references_by_question.values())
    if dominant / total_references < 0.75:
        return []
    return [
        {
            "code": "VISUAL_RHYTHM_REVIEW",
            "message": "正文图表主要集中在一个问题；请检查跨问递进和图后留白是否形成可读节奏。",
            "count": 1,
            "references_by_question": references_by_question,
            "body_figure_count": body_figure_count,
        }
    ]


def audit_report_like_manuscript(run_dir: Path) -> dict[str, Any]:
    """检测高置信度写作错误和需要人工复核的文风信号。

    Args:
        run_dir: 当前数学建模运行目录。

    Returns:
        含 ``errors`` 与 ``warnings`` 的可机读结果。E001--E005 可作为候选稿
        硬门；warning 仍需作者或盲评者结合 PDF 判断。
    """
    root = run_dir.resolve()
    paths = _manuscript_sources(root)
    sources = [
        (path, _formal_body_text(path.read_text(encoding="utf-8"))) for path in paths
    ]
    combined = "\n".join(text for _, text in sources)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not combined.strip():
        return {
            "advisory_only": True,
            "source_files": [],
            "errors": [],
            "warnings": [],
            "metrics": {},
            "limitations": "尚无正文源文件，未执行报告式写作检测。",
        }

    blocking_internal_counts = {
        term: len(pattern.findall(combined))
        for term, pattern in _BLOCKING_INTERNAL_TERMS.items()
    }
    blocking_internal_total = sum(blocking_internal_counts.values())
    if blocking_internal_total:
        used = [term for term, count in blocking_internal_counts.items() if count]
        errors.append(
            {
                "code": "E001",
                "message": (
                    f"正式正文暴露工作流内部术语 {blocking_internal_total} 次"
                    f"（{'、'.join(used)}）。"
                ),
                "count": blocking_internal_total,
                "terms": used,
            }
        )

    advisory_internal_counts = {
        term: len(re.findall(re.escape(term), combined, re.IGNORECASE))
        for term in _ADVISORY_INTERNAL_TERMS
    }
    advisory_internal_total = sum(advisory_internal_counts.values())
    if blocking_internal_total + advisory_internal_total >= 3:
        used = [
            term
            for term, count in {
                **blocking_internal_counts,
                **advisory_internal_counts,
            }.items()
            if count
        ]
        warnings.append(
            {
                "code": "internal_workflow_vocabulary",
                "message": (
                    "正文密集出现可能属于内部工作流的词汇 "
                    f"（{'、'.join(used)}），应结合语境改写为自然学术语言。"
                ),
                "count": blocking_internal_total + advisory_internal_total,
            }
        )

    report_phrase_counts = {
        name: len(pattern.findall(combined))
        for name, pattern in _REPORT_PHRASE_PATTERNS.items()
    }
    report_phrase_count = sum(report_phrase_counts.values())
    repeated_templates = {
        name: count for name, count in report_phrase_counts.items() if count >= 3
    }
    if repeated_templates:
        warnings.append(
            {
                "code": "E002",
                "message": "同一任务报账模板在正文中至少重复三次，需要按数学关系重写。",
                "count": sum(repeated_templates.values()),
                "templates": repeated_templates,
            }
        )
    if report_phrase_count >= 3:
        warnings.append(
            {
                "code": "report_phrase_repetition",
                "message": "“本问采用/结果见表”等工作报告句式重复出现，需改写为判断—证据—机制链。",
                "count": report_phrase_count,
            }
        )
        warnings.append(
            {
                "code": "REPORT_STYLE_PATTERN",
                "message": "正文多次重复“采用方法—结果见表—得到结论”的报告式模板，需改写为研究判断链。",
                "count": report_phrase_count,
                "signals": sorted(repeated_templates),
            }
        )

    abstract = _abstract_text(sources, combined)
    abstract_questions = _question_ids(abstract)
    if len(abstract_questions) >= 3:
        unified_signals = sum(
            pattern.search(abstract) is not None
            for pattern in _ABSTRACT_UNIFIED_PATTERNS
        )
        if unified_signals < 2:
            warnings.append(
                {
                    "code": "E003",
                    "message": (
                        "摘要连续枚举至少三个问题，却未形成统一困难、建模主线与结果规律。"
                    ),
                    "count": len(abstract_questions),
                    "question_ids": sorted(abstract_questions),
                    "unified_signal_groups": unified_signals,
                }
            )
        else:
            warnings.append(
                {
                    "code": "abstract_question_enumeration",
                    "message": (
                        "摘要出现至少三个问题编号；虽检测到统一主线信号，仍需盲评确认是否流水报账。"
                    ),
                    "count": len(abstract_questions),
                }
            )

    question_sections = _merged_question_sections(sources)
    sequences = [
        tuple(subheadings)
        for _, subheadings in question_sections.values()
        if len(subheadings) >= 3
    ]
    if len(sequences) >= 3:
        sequence, frequency = Counter(sequences).most_common(1)[0]
        if frequency >= 3:
            warnings.append(
                {
                    "code": "repetitive_question_template",
                    "message": (
                        f"{frequency} 个问题机械复用了同一小节序列 "
                        f"（{' → '.join(sequence)}），应按共享对象与新增困难重组。"
                    ),
                    "count": frequency,
                }
            )
            warnings.append(
                {
                    "code": "REPORT_STYLE_PATTERN",
                    "message": "多个问题复用同一流程标题，可能掩盖问题继承和新增困难。",
                    "count": frequency,
                    "signals": ["repeated_question_subheadings"],
                }
            )

    list_items = _list_item_count(combined)
    sentence_count = max(
        1,
        len(re.findall(r"[。！？.!?]", re.sub(r"\\[A-Za-z]+", "", combined))),
    )
    if list_items >= 8 and list_items / sentence_count > 0.35:
        warnings.append(
            {
                "code": "excessive_list_density",
                "message": "正文列表密度过高，可能用条目堆叠替代连续推导和机制讨论。",
                "count": list_items,
            }
        )

    heading_count = sum(len(_headings(text)) for _, text in sources)
    compact_characters = len(re.sub(r"\s+", "", combined))
    if heading_count >= 12 and compact_characters / heading_count < 220:
        warnings.append(
            {
                "code": "fragmented_heading_structure",
                "message": "标题过碎且段落平均承载内容偏少，正文可能退化为检查清单。",
                "count": heading_count,
            }
        )

    core_questions = _core_question_ids(root)
    for question_id in sorted(core_questions):
        key = _normalize_question_id(
            re.sub(r"^Q", "", question_id, flags=re.IGNORECASE)
        )
        section = question_sections.get(key)
        if section is None:
            continue
        body = section[0]
        has_derivation = _DERIVATION_PATTERN.search(body) is not None
        has_mechanism = _MECHANISM_PATTERN.search(body) is not None
        section_list_items = _list_item_count(body)
        section_tables = _table_count(body)
        prose_paragraphs = _continuous_prose_paragraphs(body)
        if (
            not has_derivation
            and not has_mechanism
            and (section_list_items >= 3 or section_tables >= 1)
            and prose_paragraphs <= 2
        ):
            warnings.append(
                {
                    "code": "E004",
                    "message": (
                        f"核心问题 {question_id} 由列表或表格主导，且同时缺少连续推导与机制解释。"
                    ),
                    "count": 1,
                    "question_id": question_id,
                    "list_items": section_list_items,
                    "tables": section_tables,
                    "prose_paragraphs": prose_paragraphs,
                }
            )
        if not has_derivation:
            warnings.append(
                {
                    "code": "core_question_without_derivation",
                    "message": f"核心问题 {question_id} 未检测到实质推导或公式语境。",
                    "count": 1,
                }
            )
        if not has_mechanism:
            warnings.append(
                {
                    "code": "core_question_without_mechanism",
                    "message": f"核心问题 {question_id} 未检测到机制、活跃约束、权衡或瓶颈讨论。",
                    "count": 1,
                }
            )
        answer_signal = re.search(r"直接答案|答案预览|结论|最优|可行解", body, re.IGNORECASE)
        missing_roles = [
            label
            for label, present in (
                ("关键推导", has_derivation),
                ("结构观察", bool(_OBSERVATION_PATTERN.search(body))),
                ("机制解释", has_mechanism),
                ("边界说明", bool(re.search(r"边界|限制|适用|不能外推", body, re.IGNORECASE))),
            )
            if not present
        ]
        if answer_signal is not None and len(missing_roles) >= 2:
            warnings.append(
                {
                    "code": "PAPER_SECTION_UNDERDEVELOPED",
                    "message": (
                        f"核心问题 {question_id} 已出现答案或结论，但仍缺少 "
                        + "、".join(missing_roles)
                        + "；答案预览不能替代展开论证。"
                    ),
                    "count": 1,
                    "question_id": question_id,
                    "missing_roles": missing_roles,
                }
            )

    generic_usage = _generic_question_heading_usage(sources)
    generic_repetition_threshold = _generic_heading_repetition_threshold(root)
    repeated_generic_roles = {
        role: len(questions)
        for role, questions in generic_usage.items()
        if len(questions) >= generic_repetition_threshold
    }
    if repeated_generic_roles:
        warnings.append(
            {
                "code": "generic_question_heading_repetition",
                "message": (
                    f"至少{generic_repetition_threshold}个问题复用了通用流程标题，"
                    "应改为包含当前数学对象、"
                    "约束或机制的题目特定标题。"
                ),
                "count": sum(repeated_generic_roles.values()),
                "question_ids": sorted(
                    {
                        question
                        for role in repeated_generic_roles
                        for question in generic_usage[role]
                    }
                ),
                "generic_roles": repeated_generic_roles,
            }
        )

    figure_errors, figure_warnings = _figure_argument_findings(root, combined)
    errors.extend(figure_errors)
    warnings.extend(figure_warnings)
    warnings.extend(_formula_explanation_findings(combined))
    body_figure_count = 0
    figure_plan_path = root / "figures/FIGURE_PLAN.json"
    if figure_plan_path.is_file():
        try:
            figure_plan = load_json(figure_plan_path)
            body_figure_count = sum(
                1
                for item in figure_plan.get("figures", [])
                if isinstance(item, dict)
                and item.get("placement", "body") == "body"
                and item.get("presentation_role") != "appendix"
                and item.get("role") != "stability"
            )
        except (ContractError, OSError, ValueError, TypeError):
            body_figure_count = 0
    scarcity_warnings, scarcity_metrics = _scarcity_findings(
        root,
        core_questions=core_questions,
        combined=combined,
        figure_count=body_figure_count,
    )
    warnings.extend(scarcity_warnings)
    rhythm_warnings = _visual_rhythm_findings(
        core_questions=core_questions,
        question_sections=question_sections,
        combined=combined,
        body_figure_count=body_figure_count,
    )
    warnings.extend(rhythm_warnings)
    return {
        "advisory_only": not errors,
        "source_files": [
            relative_inside(root, path).as_posix() for path in paths
        ],
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "characters": compact_characters,
            "headings": heading_count,
            "list_items": list_items,
            "sentences": sentence_count,
            "internal_workflow_terms": (
                blocking_internal_total + advisory_internal_total
            ),
            "blocking_internal_workflow_terms": blocking_internal_total,
            "report_phrases": report_phrase_count,
            **scarcity_metrics,
            "visual_rhythm_review": bool(rhythm_warnings),
        },
        "limitations": (
            "只有 E001 控制层术语泄漏属于提交完整性错误；E002--E005 与其他"
            "写作信号均由独立 PDF 冷读判断，不能凭启发式规则阻断创作或编译。"
        ),
    }


def audit_page_visual_rhythm(run_dir: Path) -> dict[str, Any]:
    """返回页面视觉节奏的非阻断检查结果。"""
    report = audit_report_like_manuscript(run_dir)
    findings = [
        item
        for item in report.get("warnings", [])
        if item.get("code") in {"VISUAL_RHYTHM_REVIEW", "VISUAL_SCARCITY_REVIEW"}
    ]
    return {
        "advisory_only": True,
        "success": True,
        "findings": findings,
        "metrics": report.get("metrics", {}),
        "limitations": "未读取版面设计者意图；最终判断仍需人工阅读 PDF。",
    }
