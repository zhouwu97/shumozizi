"""解析论文引用并生成关键主张到真实来源的覆盖报告。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from shumozizi.core.io import atomic_json, load_json

_REPORT_PATH = Path("paper/generated/citation_coverage.json")
_SOURCE_SUFFIXES = {".tex", ".typ"}
_IGNORED_PARTS = {"generated", "submission", "work", "archive"}
_PLACEHOLDERS = {
    "",
    "-",
    "待填写",
    "citation key",
    "cite_key",
    "key",
    "todo",
    "tbd",
}
_CATEGORY_ALIASES = {
    "background": "background",
    "背景": "background",
    "题型背景": "background",
    "领域背景": "background",
    "core_method": "core_method",
    "core method": "core_method",
    "核心方法": "core_method",
    "核心数学方法": "core_method",
    "validation": "validation",
    "验证": "validation",
    "评价指标": "validation",
    "uncertainty": "uncertainty",
    "不确定性": "uncertainty",
    "稳健性": "uncertainty",
    "extension": "extension",
    "扩展": "extension",
    "可选扩展": "extension",
}
_ALLOWED_CATEGORIES = {"background", "core_method", "validation", "uncertainty", "extension"}
_METHOD_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "bootstrap",
        "uncertainty",
        re.compile(r"bootstrap|自助法|自助采样", re.IGNORECASE),
    ),
    (
        "confidence_or_prediction_interval",
        "uncertainty",
        re.compile(r"confidence interval|prediction interval|置信区间|预测区间", re.IGNORECASE),
    ),
    (
        "monte_carlo",
        "core_method",
        re.compile(r"monte[ -]?carlo|蒙特卡[罗洛]", re.IGNORECASE),
    ),
    (
        "named_optimization_algorithm",
        "core_method",
        re.compile(
            r"genetic algorithm|particle swarm|simulated annealing|"
            r"differential evolution|NSGA-?II|NSGA-?III|遗传算法|粒子群|"
            r"模拟退火|差分进化|蚁群算法",
            re.IGNORECASE,
        ),
    ),
    (
        "named_statistical_or_ml_model",
        "core_method",
        re.compile(
            r"random forest|support vector machine|XGBoost|LightGBM|"
            r"ARIMA|LSTM|k-?means|principal component analysis|"
            r"随机森林|支持向量机|主成分分析|层次聚类",
            re.IGNORECASE,
        ),
    ),
    (
        "multi_criteria_method",
        "core_method",
        re.compile(r"TOPSIS|AHP|analytic hierarchy process|熵权法|层次分析法", re.IGNORECASE),
    ),
    (
        "statistical_test",
        "validation",
        re.compile(
            r"(?:t|z|f)[ -]?test|chi[ -]?square|Kolmogorov|Shapiro|"
            r"Mann[ -]?Whitney|Wilcoxon|假设检验|卡方检验|正态性检验",
            re.IGNORECASE,
        ),
    ),
    (
        "external_evaluation_metric",
        "validation",
        re.compile(
            r"\b(?:RMSE|MAE|MAPE|AUC|F1)[ -]?(?:score)?\b|"
            r"均方根误差|平均绝对误差|交叉验证",
            re.IGNORECASE,
        ),
    ),
)


def _read_text(path: Path) -> str:
    """读取可选文本文件，无法解码时返回空文本。"""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _paper_files(run_dir: Path, suffixes: set[str]) -> list[Path]:
    """返回论文目录中可审计且非生成态的源文件。"""
    paper_dir = run_dir / "paper"
    if not paper_dir.is_dir():
        return []
    return sorted(
        path
        for path in paper_dir.rglob("*")
        if path.is_file()
        and path.suffix.casefold() in suffixes
        and not any(part.casefold() in _IGNORED_PARTS for part in path.relative_to(paper_dir).parts)
    )


def _latex_without_comments(line: str) -> str:
    """去除 LaTeX 行注释，同时保留转义百分号。"""
    for index, character in enumerate(line):
        if character != "%":
            continue
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and line[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 0:
            return line[:index]
    return line


def _bibliography_keys(run_dir: Path) -> set[str]:
    """提取 BibTeX 与 ``bibitem`` 定义的去重引用键。"""
    keys: set[str] = set()
    bib_pattern = re.compile(
        r"(?mi)^\s*@(?!comment\b|string\b|preamble\b)[a-z]+\s*[({]\s*([^,\s]+)\s*,"
    )
    for path in _paper_files(run_dir, {".bib"}):
        keys.update(match.group(1).strip() for match in bib_pattern.finditer(_read_text(path)))
    bibitem_pattern = re.compile(r"\\bibitem(?:\s*\[[^]]*\])?\s*\{([^}]+)\}")
    for path in _paper_files(run_dir, {".tex"}):
        text = "\n".join(_latex_without_comments(line) for line in _read_text(path).splitlines())
        keys.update(match.group(1).strip() for match in bibitem_pattern.finditer(text))
    return {key for key in keys if key}


def _latex_occurrences(path: Path, run_dir: Path) -> list[dict[str, Any]]:
    """提取 LaTeX 的显式 citation key 及其章节位置。"""
    occurrences: list[dict[str, Any]] = []
    section = "未识别章节"
    section_pattern = re.compile(r"\\(?:sub)*section\*?\s*\{([^}]+)\}")
    citation_pattern = re.compile(
        r"\\(?:cite|citep|citet|parencite|textcite|autocite)\*?"
        r"(?:\s*\[[^]]*\]){0,2}\s*\{([^}]+)\}",
        re.IGNORECASE,
    )
    for line_number, raw_line in enumerate(_read_text(path).splitlines(), start=1):
        line = _latex_without_comments(raw_line)
        section_match = section_pattern.search(line)
        if section_match:
            section = section_match.group(1).strip()
        for match in citation_pattern.finditer(line):
            for key in match.group(1).split(","):
                normalized = key.strip()
                if normalized:
                    occurrences.append(
                        {
                            "key": normalized,
                            "path": path.relative_to(run_dir).as_posix(),
                            "line": line_number,
                            "section": section,
                        }
                    )
    return occurrences


def _typst_labels(run_dir: Path) -> set[str]:
    """提取 Typst 本地标签，避免把图表和公式交叉引用误判为 citation。"""
    labels: set[str] = set()
    angle_pattern = re.compile(r"<([A-Za-z][\w:./-]*)>")
    function_pattern = re.compile(r"\blabel\s*\(\s*[\"']([^\"']+)[\"']\s*\)")
    for path in _paper_files(run_dir, {".typ"}):
        text = _read_text(path)
        labels.update(match.group(1) for match in angle_pattern.finditer(text))
        labels.update(match.group(1) for match in function_pattern.finditer(text))
    return labels


def _typst_occurrences(
    path: Path, run_dir: Path, *, local_labels: set[str]
) -> list[dict[str, Any]]:
    """提取 Typst 的 ``@key`` 引用及其标题位置。"""
    occurrences: list[dict[str, Any]] = []
    section = "未识别章节"
    heading_pattern = re.compile(r"^\s*=+\s+(.+?)\s*$")
    citation_pattern = re.compile(r"(?<![\w@])@([A-Za-z][\w:./-]*)")
    in_block_comment = False
    for line_number, raw_line in enumerate(_read_text(path).splitlines(), start=1):
        line = raw_line
        if in_block_comment:
            end = line.find("*/")
            if end < 0:
                continue
            line = line[end + 2 :]
            in_block_comment = False
        while "/*" in line:
            start = line.find("/*")
            end = line.find("*/", start + 2)
            if end < 0:
                line = line[:start]
                in_block_comment = True
                break
            line = line[:start] + line[end + 2 :]
        line = line.split("//", 1)[0]
        heading_match = heading_pattern.match(line)
        if heading_match:
            section = heading_match.group(1).strip()
        for match in citation_pattern.finditer(line):
            if match.group(1) in local_labels:
                continue
            occurrences.append(
                {
                    "key": match.group(1),
                    "path": path.relative_to(run_dir).as_posix(),
                    "line": line_number,
                    "section": section,
                }
            )
    return occurrences


def _citation_occurrences(run_dir: Path) -> list[dict[str, Any]]:
    """提取正文显式引用；普通 ``[1]`` 编号不视为引用。"""
    occurrences: list[dict[str, Any]] = []
    typst_labels = _typst_labels(run_dir)
    for path in _paper_files(run_dir, _SOURCE_SUFFIXES):
        if path.suffix.casefold() == ".tex":
            occurrences.extend(_latex_occurrences(path, run_dir))
        else:
            occurrences.extend(_typst_occurrences(path, run_dir, local_labels=typst_labels))
    return occurrences


def _split_markdown_row(line: str) -> list[str]:
    """按未转义竖线拆分 Markdown 表格行。"""
    body = line.strip().strip("|")
    return [cell.replace(r"\|", "|").strip() for cell in re.split(r"(?<!\\)\|", body)]


def _plan_bindings(run_dir: Path) -> tuple[list[dict[str, str]], bool, bool]:
    """读取引用计划绑定，并返回存在性及类别列能力。"""
    path = run_dir / "paper" / "CITATION_PLAN.md"
    text = _read_text(path)
    if not text:
        return [], False, False
    lines = text.splitlines()
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if "citation key" in line.casefold() and "|" in line
        ),
        None,
    )
    if header_index is None:
        return [], True, False
    headers = [cell.casefold() for cell in _split_markdown_row(lines[header_index])]
    category_index = next(
        (index for index, value in enumerate(headers) if value in {"类别", "category"}),
        None,
    )
    bindings: list[dict[str, str]] = []
    for line in lines[header_index + 2 :]:
        if not line.strip().startswith("|"):
            if bindings:
                break
            continue
        cells = _split_markdown_row(line)
        if not cells:
            continue
        key = cells[0].strip()
        if key.casefold() in _PLACEHOLDERS or set(key) <= {"-", ":"}:
            continue
        if category_index is None:
            source_index, location_index, claim_index = 1, 2, 3
            category = ""
        else:
            source_index, location_index, claim_index = 2, 3, 4
            raw_category = cells[category_index].strip() if category_index < len(cells) else ""
            category = _CATEGORY_ALIASES.get(raw_category.casefold(), raw_category.casefold())
        bindings.append(
            {
                "key": key,
                "category": category,
                "source": cells[source_index].strip() if source_index < len(cells) else "",
                "location": cells[location_index].strip() if location_index < len(cells) else "",
                "claim": cells[claim_index].strip() if claim_index < len(cells) else "",
            }
        )
    return bindings, True, category_index is not None


def _method_signals(run_dir: Path) -> list[dict[str, str]]:
    """从建模合同识别高置信度、通常需要外部来源的方法。"""
    path = run_dir / "analysis" / "MODELING_UNITS.json"
    if not path.is_file():
        return []
    try:
        document = load_json(path)
    except (OSError, TypeError, ValueError):
        return []
    signals: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for unit in document.get("units", []):
        if not isinstance(unit, dict):
            continue
        question_id = str(unit.get("question_id", "unknown"))
        # 只检查结构化建模合同，避免从论文修辞反推出并不存在的方法义务。
        text = json.dumps(unit, ensure_ascii=False, sort_keys=True)
        for method, category, pattern in _METHOD_PATTERNS:
            if not pattern.search(text) or (question_id, method) in seen:
                continue
            seen.add((question_id, method))
            signals.append(
                {"question_id": question_id, "method": method, "required_category": category}
            )
    return signals


def _is_introduction_section(section: str) -> bool:
    """判断章节是否只承担摘要、引言或问题背景角色。"""
    return bool(
        re.search(
            r"摘要|引言|绪论|问题(?:重述|背景)|background|introduction|abstract",
            section,
            re.IGNORECASE,
        )
    )


def build_citation_coverage(run_dir: Path) -> dict[str, Any]:
    """生成并写入论文引用覆盖报告。

    Args:
        run_dir: 当前 Competition-First 运行目录。

    Returns:
        已写入 ``paper/generated/citation_coverage.json`` 的报告。
    """
    bibliography_keys = _bibliography_keys(run_dir)
    occurrences = _citation_occurrences(run_dir)
    cited_keys = {item["key"] for item in occurrences}
    bindings, plan_exists, plan_has_category = _plan_bindings(run_dir)
    plan_keys = {item["key"] for item in bindings}
    realized_bindings = [
        item for item in bindings if item["key"] in cited_keys and item["key"] in bibliography_keys
    ]
    category_coverage: dict[str, list[str]] = {}
    for item in realized_bindings:
        if item["category"]:
            category_coverage.setdefault(item["category"], []).append(item["key"])
    category_coverage = {
        category: sorted(set(keys)) for category, keys in sorted(category_coverage.items())
    }
    occurrences_by_key: dict[str, list[dict[str, Any]]] = {}
    for item in occurrences:
        occurrences_by_key.setdefault(item["key"], []).append(item)
    introduction_only_keys = sorted(
        key
        for key, items in occurrences_by_key.items()
        if items and all(_is_introduction_section(str(item["section"])) for item in items)
    )
    signals = _method_signals(run_dir)
    missing_method_categories = sorted(
        {
            signal["required_category"]
            for signal in signals
            if not category_coverage.get(signal["required_category"])
        }
    )
    categories_by_key: dict[str, set[str]] = {}
    for item in realized_bindings:
        if item["category"]:
            categories_by_key.setdefault(item["key"], set()).add(item["category"])
    invalid_plan_categories = sorted(
        {
            item["category"]
            for item in bindings
            if plan_has_category and item["category"] not in _ALLOWED_CATEGORIES
        }
    )
    incomplete_plan_keys = sorted(
        {
            item["key"]
            for item in bindings
            if plan_has_category
            and any(
                not item[field].strip() or item[field].strip().casefold() in _PLACEHOLDERS
                for field in ("category", "source", "location", "claim")
            )
        }
    )
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "bibliography_keys": sorted(bibliography_keys),
        "cited_keys": sorted(cited_keys),
        "citation_occurrences": occurrences,
        "plan_exists": plan_exists,
        "plan_has_category_column": plan_has_category,
        "plan_bindings": bindings,
        "undefined_keys": sorted(cited_keys - bibliography_keys),
        "unused_bibliography_keys": sorted(bibliography_keys - cited_keys),
        "undefined_plan_keys": sorted(plan_keys - bibliography_keys),
        "unrealized_plan_keys": sorted(plan_keys - cited_keys),
        "invalid_plan_categories": invalid_plan_categories,
        "incomplete_plan_keys": incomplete_plan_keys,
        "category_coverage": category_coverage,
        "method_signals": signals,
        "missing_method_categories": missing_method_categories,
        "introduction_only_keys": introduction_only_keys,
        "multi_category_single_source": {
            key: sorted(categories)
            for key, categories in sorted(categories_by_key.items())
            if len(categories) > 1
        },
    }
    atomic_json(run_dir / _REPORT_PATH, report)
    return report


def citation_coverage_errors(document: Mapping[str, Any]) -> list[str]:
    """返回引用覆盖中的高置信度合同错误。"""
    errors: list[str] = []
    undefined = document.get("undefined_keys", [])
    if undefined:
        errors.append("正文引用 key 未在参考文献中定义: " + ", ".join(undefined))
    undefined_plan = document.get("undefined_plan_keys", [])
    if undefined_plan:
        errors.append("CITATION_PLAN 引用 key 未在参考文献中定义: " + ", ".join(undefined_plan))
    unrealized = document.get("unrealized_plan_keys", [])
    if unrealized:
        errors.append("CITATION_PLAN 已声明但正文未实际引用: " + ", ".join(unrealized))
    invalid_categories = document.get("invalid_plan_categories", [])
    if invalid_categories:
        errors.append("CITATION_PLAN 使用了未支持的类别: " + ", ".join(invalid_categories))
    incomplete = document.get("incomplete_plan_keys", [])
    if incomplete:
        errors.append("CITATION_PLAN 存在未填写完整的来源、位置或具体判断: " + ", ".join(incomplete))
    if document.get("plan_has_category_column"):
        missing_categories = document.get("missing_method_categories", [])
        if missing_categories:
            errors.append(
                "结构化建模合同使用外部方法，但缺少已在正文兑现的来源类别: "
                + ", ".join(missing_categories)
            )
    return errors


def citation_coverage_warnings(document: Mapping[str, Any]) -> list[str]:
    """返回数量、位置、未使用条目和来源多样性的建议。"""
    bibliography = document.get("bibliography_keys", [])
    cited = document.get("cited_keys", [])
    count = len(bibliography)
    warnings: list[str] = []
    if count == 0:
        warnings.append(
            "未检测到方法或背景文献；请按 CITATION_PLAN.md 的题型背景、核心方法、验证与不确定性类别补充约 6–12 条可核验参考文献。"
        )
    elif not 6 <= count <= 12:
        warnings.append(
            f"当前检测到约 {count} 条参考文献；建议按 CITATION_PLAN.md 补齐题型背景、核心方法、验证与不确定性类别，6–12 条只是紧凑性建议，不构成硬门。"
        )
    if count and not cited:
        warnings.append(
            "检测到文后参考文献但正文没有可识别的引用绑定；请在具体方法、指标、验证或背景判断后加入对应 citation key。"
        )
    if not document.get("plan_exists"):
        warnings.append(
            "缺少 paper/CITATION_PLAN.md；建议先按来源类别和正文判断建立引用计划，避免只列文献不引用。"
        )
    elif not document.get("plan_has_category_column"):
        warnings.append(
            "CITATION_PLAN.md 仍为旧四列表格；建议增加“类别”列后再核对核心方法、验证与不确定性来源覆盖。"
        )
    unused = document.get("unused_bibliography_keys", [])
    if unused:
        warnings.append("参考文献存在未被正文使用的条目: " + ", ".join(unused))
    if cited and len(cited) == 1:
        warnings.append("正文只使用一个不同来源，无法独立覆盖背景、核心方法和验证类别。")
    intro_only = document.get("introduction_only_keys", [])
    if intro_only and set(intro_only) == set(cited):
        warnings.append("全部引用只出现在摘要、引言或问题背景，核心方法与验证段尚无来源绑定。")
    multi_category = document.get("multi_category_single_source", {})
    if multi_category:
        details = "; ".join(
            f"{key}=>{','.join(categories)}" for key, categories in multi_category.items()
        )
        warnings.append("同一来源单独承担多个引用类别，请人工复核相关性与来源多样性: " + details)
    if document.get("method_signals") and not document.get("plan_has_category_column"):
        warnings.append("检测到通常需要外部来源的方法，但旧引用计划无法机械确认类别覆盖。")
    return warnings
