"""识别数学建模论文中的工作报告式写作模式。

本模块只产生可解释 warning，不把启发式文本特征升级为科学硬门。最终判断仍由
独立 PDF 盲评完成。
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from shumozizi.core.io import load_json, relative_inside

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
_INTERNAL_TERMS = (
    "result_id",
    "production result",
    "生产结果",
    "晋级",
    "fallback",
    "oracle",
    "scorer",
    "endpoint",
    "challenger",
    "task receipt",
    "回执",
    "工作流",
)
_REPORT_PHRASE_PATTERN = re.compile(
    r"本问(?:采用|使用|选用|得到)|结果见(?:表|图)|由(?:表|图).{0,8}可知|"
    r"具体结果如下|参数设置如下",
    re.IGNORECASE,
)
_ABSTRACT_QUESTION_PATTERN = re.compile(
    r"\bQ[1-9]\b|问题[一二三四五六七八九十]|第[一二三四五六七八九十]问",
    re.IGNORECASE,
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
_EXPLANATION_PATTERN = re.compile(
    r"表明|说明|可见|意味着|原因|机制|因此|由此|约束|边界|权衡",
    re.IGNORECASE,
)


def _manuscript_sources(run_dir: Path) -> list[Path]:
    """收集真实正文源文件，排除控制文档、生成物和源码附件。"""
    paper_dir = run_dir / "paper"
    if not paper_dir.is_dir():
        return []
    sources: list[Path] = []
    for path in sorted(paper_dir.rglob("*")):
        if (
            not path.is_file()
            or path.suffix.casefold() not in _SOURCE_SUFFIXES
            or any(part.casefold() in _EXCLUDED_PARTS for part in path.parts)
            or path.name.startswith("PAPER_")
            or path.name in {"ARGUMENT_PLAN.md", "STORYBOARD.md"}
        ):
            continue
        sources.append(path)
    return sources


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
    return (
        match.group("arabic")
        or match.group("cn")
        or match.group("cn_alt")
    )


def _normalize_heading(title: str) -> str:
    """移除编号与题号，比较不同问题是否机械复制标题模板。"""
    normalized = _QUESTION_PATTERN.sub("", title)
    normalized = re.sub(r"^[\d一二三四五六七八九十.、\s]+", "", normalized)
    return re.sub(r"\s+", "", normalized).casefold()


def _question_sections(text: str) -> dict[str, tuple[str, list[str]]]:
    """按问题一级标题切分正文并保留其子标题序列。"""
    headings = _headings(text)
    sections: dict[str, tuple[str, list[str]]] = {}
    for index, (level, title, start) in enumerate(headings):
        question = _question_key(title) if level == 1 else None
        if question is None:
            continue
        end = len(text)
        subheadings: list[str] = []
        for next_level, next_title, next_start in headings[index + 1 :]:
            if next_level == 1:
                end = next_start
                break
            if next_level >= 2:
                normalized = _normalize_heading(next_title)
                if normalized:
                    subheadings.append(normalized)
        sections[question] = (text[start:end], subheadings)
    return sections


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


def _hero_figure_warnings(run_dir: Path, combined: str) -> list[dict[str, Any]]:
    """检查主图是否被正文引用并参与观察—机制—结论链。"""
    path = run_dir / "figures" / "FIGURE_PLAN.json"
    if not path.is_file():
        return []
    try:
        plan = load_json(path)
    except (OSError, ValueError):
        return []
    warnings: list[dict[str, Any]] = []
    for figure in plan.get("figures", []):
        if (
            not isinstance(figure, dict)
            or figure.get("presentation_role") != "question_hero"
        ):
            continue
        label = figure.get("latex_label")
        if not isinstance(label, str):
            continue
        reference_patterns = (
            rf"\\(?:auto|page|c)?ref\{{{re.escape(label)}\}}",
            rf"@{re.escape(label)}\b",
        )
        reference = next(
            (
                match
                for pattern in reference_patterns
                if (match := re.search(pattern, combined))
            ),
            None,
        )
        if reference is None:
            warnings.append(
                {
                    "code": "hero_figure_not_in_argument",
                    "message": f"主图 {figure.get('figure_id')} 未被正文交叉引用，仍像附件而非论证证据。",
                    "count": 1,
                }
            )
            continue
        context = combined[
            max(0, reference.start() - 180) : min(len(combined), reference.end() + 260)
        ]
        if not _EXPLANATION_PATTERN.search(context):
            warnings.append(
                {
                    "code": "hero_figure_without_interpretation",
                    "message": f"主图 {figure.get('figure_id')} 附近缺少观察、机制或决策后果解释。",
                    "count": 1,
                }
            )
    return warnings


def audit_report_like_manuscript(run_dir: Path) -> dict[str, Any]:
    """检测工作报告式语言和重复结构，返回非阻断告警。

    Args:
        run_dir: 当前数学建模运行目录。

    Returns:
        advisory 审计结果；warning 需要作者或盲评者结合 PDF 判断。
    """
    root = run_dir.resolve()
    paths = _manuscript_sources(root)
    sources = [(path, path.read_text(encoding="utf-8")) for path in paths]
    combined = "\n".join(text for _, text in sources)
    warnings: list[dict[str, Any]] = []
    if not combined.strip():
        return {
            "advisory_only": True,
            "source_files": [],
            "warnings": [],
            "metrics": {},
            "limitations": "尚无正文源文件，未执行报告式写作检测。",
        }

    internal_counts = {
        term: len(re.findall(re.escape(term), combined, re.IGNORECASE))
        for term in _INTERNAL_TERMS
    }
    internal_total = sum(internal_counts.values())
    if internal_total >= 3:
        used = "、".join(term for term, count in internal_counts.items() if count)
        warnings.append(
            {
                "code": "internal_workflow_vocabulary",
                "message": f"正文出现内部工作流词 {internal_total} 次（{used}），应改写为自然学术语言。",
                "count": internal_total,
            }
        )

    report_phrase_count = len(_REPORT_PHRASE_PATTERN.findall(combined))
    if report_phrase_count >= 3:
        warnings.append(
            {
                "code": "report_phrase_repetition",
                "message": "“本问采用/结果见表”等工作报告句式重复出现，需改写为判断—证据—机制链。",
                "count": report_phrase_count,
            }
        )

    abstract = _abstract_text(sources, combined)
    abstract_questions = set(_ABSTRACT_QUESTION_PATTERN.findall(abstract))
    if len(abstract_questions) >= 3:
        warnings.append(
            {
                "code": "abstract_question_enumeration",
                "message": "摘要按至少三个问题编号流水罗列，应围绕核心困难、结构、结果规律与边界重写。",
                "count": len(abstract_questions),
            }
        )

    question_sections: dict[str, tuple[str, list[str]]] = {}
    for _, text in sources:
        question_sections.update(_question_sections(text))
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

    list_items = len(
        re.findall(
            r"\\item\b|^\s*[-*+]\s+|^\s*\d+[.)、]\s+",
            combined,
            re.MULTILINE,
        )
    )
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
        key = re.sub(r"^Q", "", question_id, flags=re.IGNORECASE)
        section = question_sections.get(key)
        if section is None:
            continue
        body = section[0]
        if not _DERIVATION_PATTERN.search(body):
            warnings.append(
                {
                    "code": "core_question_without_derivation",
                    "message": f"核心问题 {question_id} 未检测到实质推导或公式语境。",
                    "count": 1,
                }
            )
        if not _MECHANISM_PATTERN.search(body):
            warnings.append(
                {
                    "code": "core_question_without_mechanism",
                    "message": f"核心问题 {question_id} 未检测到机制、活跃约束、权衡或瓶颈讨论。",
                    "count": 1,
                }
            )

    warnings.extend(_hero_figure_warnings(root, combined))
    return {
        "advisory_only": True,
        "source_files": [
            relative_inside(root, path).as_posix() for path in paths
        ],
        "warnings": warnings,
        "metrics": {
            "characters": compact_characters,
            "headings": heading_count,
            "list_items": list_items,
            "sentences": sentence_count,
            "internal_workflow_terms": internal_total,
            "report_phrases": report_phrase_count,
        },
        "limitations": (
            "该检测只识别高价值文本信号，不能判断数学正确性、文风优劣或实际阅读体验；"
            "所有告警必须在独立 PDF 盲评中复核。"
        ),
    }
