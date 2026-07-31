"""解析论文蓝图并生成逐问论证义务覆盖矩阵。"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    load_json,
    relative_inside,
    resolve_inside,
    sha256_file,
)
from shumozizi.core.schema import require_valid

PAPER_BLUEPRINT_PATH = Path("paper/PAPER_BLUEPRINT.md")
ARGUMENT_COVERAGE_PATH = Path("paper/generated/argument_coverage.json")

COMMON_OBLIGATIONS = (
    "problem_requirement",
    "inheritance",
    "new_difficulty",
    "mathematical_object",
    "modeling_basis",
    "key_derivation",
    "solver_or_algorithm",
    "main_result",
    "result_interpretation",
    "mechanism_or_pattern",
    "validation",
    "boundary",
    "direct_answer",
)
CORE_OBLIGATIONS = (
    "key_judgment",
    "computational_evidence",
    "alternative_explanation",
)

_LABEL_ALIASES: dict[str, tuple[str, ...]] = {
    "problem_requirement": ("problem_requirement", "题面要求", "题目要求", "题面输出"),
    "inheritance": ("inheritance", "与前问的继承", "从前问继承", "继承"),
    "new_difficulty": ("new_difficulty", "新增困难", "新困难"),
    "mathematical_object": (
        "mathematical_object",
        "数学对象",
        "核心数学对象",
        "新数学对象",
    ),
    "modeling_basis": ("modeling_basis", "建模依据", "模型依据", "采用理由"),
    "key_derivation": ("key_derivation", "关键推导", "数学推导", "推导"),
    "solver_or_algorithm": (
        "solver_or_algorithm",
        "求解过程",
        "求解算法",
        "算法/伪代码",
        "算法步骤",
        "算法",
    ),
    "main_result": ("main_result", "主结果", "主要结果", "主结果与机制"),
    "result_interpretation": (
        "result_interpretation",
        "结果解释",
        "结果说明",
        "主结果与机制",
    ),
    "mechanism_or_pattern": (
        "mechanism_or_pattern",
        "机制解释",
        "机制或规律",
        "规律",
        "主结果与机制",
        "讨论要点",
    ),
    "validation": ("validation", "近端验证", "验证", "局部验证", "验证边界"),
    "boundary": ("boundary", "适用边界", "结论边界", "边界", "验证边界"),
    "direct_answer": ("direct_answer", "直接答案", "直接答案表", "本问结论"),
    "key_judgment": ("key_judgment", "关键判断", "要支持的判断", "关键命题"),
    "computational_evidence": (
        "computational_evidence",
        "计算证据",
        "独立对照",
        "结果与独立对照",
    ),
    "alternative_explanation": (
        "alternative_explanation",
        "替代解释",
        "竞争解释",
        "模型对照",
        "竞争解释与排除",
    ),
}

_PLACEHOLDER_PATTERN = re.compile(r"待填写|待补充|TODO|TBD|^[-—/\\]*$", re.IGNORECASE)


def _normalize_label(value: str) -> str:
    """统一 Markdown 字段名，以兼容中英文和轻微标点差异。"""
    return re.sub(r"[\s`*_：:（）()]+", "", value).lower()


def _label_to_obligations(label: str) -> tuple[str, ...]:
    """把作者可读字段名映射为一个或多个后台义务。"""
    normalized = _normalize_label(label)
    matched = []
    for obligation, aliases in _LABEL_ALIASES.items():
        if any(_normalize_label(alias) == normalized for alias in aliases):
            matched.append(obligation)
    return tuple(matched)


def _meaningful(value: object) -> bool:
    """判断字段是否包含可审阅内容，而非空白或占位符。"""
    if not isinstance(value, str):
        return False
    compact = re.sub(r"\s+", "", value)
    return len(compact) >= 2 and _PLACEHOLDER_PATTERN.search(compact) is None


def _markdown_tables(markdown: str) -> Iterable[tuple[list[str], list[list[str]]]]:
    """逐个返回 Markdown 表头和数据行。"""
    lines = markdown.splitlines()
    index = 0
    while index + 1 < len(lines):
        header = lines[index].strip()
        divider = lines[index + 1].strip()
        if "|" not in header or not re.fullmatch(r"\|?[\s:|-]+\|?", divider):
            index += 1
            continue
        headings = [cell.strip() for cell in header.strip("|").split("|")]
        rows: list[list[str]] = []
        index += 2
        while index < len(lines) and "|" in lines[index]:
            rows.append([cell.strip() for cell in lines[index].strip().strip("|").split("|")])
            index += 1
        yield headings, rows


def _question_sections(markdown: str, question_ids: Iterable[str]) -> dict[str, str]:
    """提取以问题编号命名的 Markdown 章节。"""
    sections: dict[str, str] = {}
    for question_id in question_ids:
        heading = re.compile(
            rf"^(?P<marks>#{{1,6}})[^\n]*\b{re.escape(question_id)}\b[^\n]*$",
            re.MULTILINE | re.IGNORECASE,
        )
        match = heading.search(markdown)
        if match is None:
            continue
        level = len(match.group("marks"))
        following = re.compile(rf"^#{{1,{level}}}\s+", re.MULTILINE).search(
            markdown, match.end()
        )
        end = following.start() if following is not None else len(markdown)
        sections[question_id] = markdown[match.end() : end].strip()
    return sections


def _section_fields(section: str) -> dict[str, str]:
    """从逐问章节中的字段行和子标题读取论证内容。"""
    fields: dict[str, str] = {}
    field_line = re.compile(
        r"^(?:[-*+]\s*)?(?:\*\*)?(?P<label>[\w\u4e00-\u9fff/（）() ]+)"
        r"(?:\*\*)?\s*[：:]\s*(?P<value>.+)$",
        re.MULTILINE,
    )
    for match in field_line.finditer(section):
        value = match.group("value").strip()
        for obligation in _label_to_obligations(match.group("label")):
            if _meaningful(value):
                fields.setdefault(obligation, value)

    heading = re.compile(r"^(?P<marks>#{3,6})\s+(?P<label>[^\n]+)$", re.MULTILINE)
    matches = list(heading.finditer(section))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        value = section[match.end() : end].strip()
        for obligation in _label_to_obligations(match.group("label")):
            if _meaningful(value):
                fields.setdefault(obligation, value)
    return fields


def _table_fields(markdown: str, question_ids: Iterable[str]) -> dict[str, dict[str, str]]:
    """读取逐问完整性表，并展开合并表头承担的多项义务。"""
    expected = set(question_ids)
    fields: dict[str, dict[str, str]] = {question_id: {} for question_id in expected}
    for headings, rows in _markdown_tables(markdown):
        question_column = next(
            (
                index
                for index, heading in enumerate(headings)
                if _normalize_label(heading) in {"问题", "问题id", "questionid"}
            ),
            None,
        )
        if question_column is None:
            continue
        for row in rows:
            if question_column >= len(row):
                continue
            question_id = row[question_column].strip().upper()
            if question_id not in expected:
                continue
            for index, heading in enumerate(headings):
                if index >= len(row) or not _meaningful(row[index]):
                    continue
                for obligation in _label_to_obligations(heading):
                    fields[question_id].setdefault(obligation, row[index].strip())
    return fields


def parse_paper_blueprint(
    markdown: str,
    *,
    run_id: str,
    required_questions: Iterable[str],
    core_questions: Iterable[str] = (),
    source_path: str = "paper/PAPER_BLUEPRINT.md",
    source_sha256: str | None = None,
) -> dict[str, Any]:
    """解析 Markdown 蓝图并返回论证义务覆盖文档。

    Args:
        markdown: ``PAPER_BLUEPRINT.md`` 的完整文本。
        run_id: 当前运行标识。
        required_questions: 题面要求回答的问题 ID。
        core_questions: 需要额外完整论证单元的问题 ID。
        source_path: 蓝图在运行目录内的相对路径。
        source_sha256: 可选的源文件摘要。

    Returns:
        可直接写入 ``argument_coverage.json`` 的结构化文档。
    """
    questions = tuple(dict.fromkeys(str(item).strip().upper() for item in required_questions))
    core = {str(item).strip().upper() for item in core_questions}
    if not questions or any(not item for item in questions):
        raise ContractError("论证覆盖矩阵至少需要一个非空必答问题")
    unknown_core = sorted(core - set(questions))
    if unknown_core:
        raise ContractError(f"核心问题不属于必答问题: {', '.join(unknown_core)}")

    from_tables = _table_fields(markdown, questions)
    sections = _question_sections(markdown, questions)
    coverage = []
    for question_id in questions:
        values = dict(from_tables[question_id])
        values.update(_section_fields(sections.get(question_id, "")))
        required = list(COMMON_OBLIGATIONS)
        if question_id in core:
            required.extend(CORE_OBLIGATIONS)
        obligations = {
            obligation: {
                "covered": _meaningful(values.get(obligation)),
                "content": values.get(obligation, "").strip(),
            }
            for obligation in required
        }
        coverage.append(
            {
                "question_id": question_id,
                "core_question": question_id in core,
                "obligations": obligations,
                "missing_obligations": [
                    key for key, value in obligations.items() if not value["covered"]
                ],
            }
        )
    document = {
        "schema_name": "argument_coverage",
        "schema_version": "2.0",
        "run_id": run_id,
        "source": {
            "path": source_path,
            "sha256": source_sha256 or "0" * 64,
        },
        "required_questions": list(questions),
        "core_questions": sorted(core),
        "questions": coverage,
        "complete": all(not item["missing_obligations"] for item in coverage),
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    require_valid(document, "argument_coverage")
    return document


def validate_argument_coverage(document: Mapping[str, Any]) -> list[str]:
    """返回覆盖矩阵的语义错误，供 readiness 等调用者复用。"""
    errors: list[str] = []
    required_questions = document.get("required_questions")
    questions = document.get("questions")
    if not isinstance(required_questions, list) or not all(
        isinstance(item, str) and item for item in required_questions
    ):
        return ["argument_coverage.required_questions 必须是非空问题 ID 数组"]
    if not isinstance(questions, list):
        return ["argument_coverage.questions 必须是数组"]
    by_id = {
        item.get("question_id"): item
        for item in questions
        if isinstance(item, Mapping) and isinstance(item.get("question_id"), str)
    }
    for question_id in required_questions:
        item = by_id.get(question_id)
        if item is None:
            errors.append(f"{question_id} 缺少论证覆盖记录")
            continue
        obligations = item.get("obligations")
        if not isinstance(obligations, Mapping):
            errors.append(f"{question_id} 缺少 obligations")
            continue
        required = list(COMMON_OBLIGATIONS)
        if item.get("core_question") is True:
            required.extend(CORE_OBLIGATIONS)
        for obligation in required:
            value = obligations.get(obligation)
            if not isinstance(value, Mapping) or value.get("covered") is not True:
                errors.append(f"{question_id} 缺少论证义务 {obligation}")
            elif not _meaningful(value.get("content")):
                errors.append(f"{question_id}.{obligation} 仍是空白或占位内容")
    return errors


def require_argument_coverage(document: Mapping[str, Any]) -> None:
    """要求覆盖矩阵完整，否则抛出聚合后的协议异常。"""
    errors = validate_argument_coverage(document)
    if errors:
        raise ContractError("论文论证义务未覆盖: " + "；".join(errors))


def _question_sets(run_dir: Path) -> tuple[list[str], list[str]]:
    """从 v3.2 状态和建模单元读取必答问题与核心问题。"""
    from shumozizi.simple.state import read_simple_state

    state = read_simple_state(run_dir)
    required = [str(item).upper() for item in state.get("required_questions", [])]
    modeling_path = run_dir / "analysis" / "MODELING_UNITS.json"
    core: list[str] = []
    if modeling_path.is_file():
        modeling = load_json(modeling_path)
        core = [
            str(item.get("question_id")).upper()
            for item in modeling.get("units", [])
            if isinstance(item, dict)
            and item.get("core_question") is True
            and isinstance(item.get("question_id"), str)
        ]
    return required, core


def build_argument_coverage(
    run_dir: Path,
    *,
    blueprint_path: str = PAPER_BLUEPRINT_PATH.as_posix(),
    output_path: str = ARGUMENT_COVERAGE_PATH.as_posix(),
) -> dict[str, Any]:
    """解析运行内蓝图并原子写入派生覆盖矩阵。

    Args:
        run_dir: 当前 Competition-First 运行目录。
        blueprint_path: 运行目录内的蓝图相对路径。
        output_path: 运行目录内的派生 JSON 相对路径。

    Returns:
        已写入磁盘的覆盖矩阵。
    """
    root = run_dir.resolve()
    source = resolve_inside(root, blueprint_path, must_exist=True)
    output = resolve_inside(root, output_path)
    required, core = _question_sets(root)
    document = parse_paper_blueprint(
        source.read_text(encoding="utf-8"),
        run_id=root.name,
        required_questions=required,
        core_questions=core,
        source_path=relative_inside(root, source).as_posix(),
        source_sha256=sha256_file(source),
    )
    atomic_json(output, document)
    return document


def paper_blueprint_review_prompt(run_dir: Path, *, problem_summary_path: str) -> str:
    """生成只包含允许材料的写作前独立蓝图审核提示。

    Args:
        run_dir: 当前运行目录。
        problem_summary_path: 位于 ``problem/`` 内的题目需求摘要相对路径。

    Returns:
        可直接交给独立审核上下文的固定提示词。
    """
    root = run_dir.resolve()
    summary = resolve_inside(root, problem_summary_path, must_exist=True)
    if not relative_inside(root, summary).as_posix().startswith("problem/"):
        raise ContractError("题目需求摘要必须位于运行目录的 problem/ 内")
    blueprint = resolve_inside(root, PAPER_BLUEPRINT_PATH.as_posix(), must_exist=True)
    answer_map = resolve_inside(root, "paper/answer-map.json", must_exist=True)
    figure_plan = resolve_inside(root, "figures/FIGURE_PLAN.json", must_exist=True)
    figures = load_json(figure_plan).get("figures", [])
    figure_digest = [
        {
            key: item.get(key)
            for key in (
                "figure_id",
                "caption",
                "visual_question",
                "expected_observation",
                "decision_consequence",
                "claim",
            )
            if item.get(key) is not None
        }
        for item in figures
        if isinstance(item, dict)
    ]
    allowed_material = {
        "problem_requirement_summary": summary.read_text(encoding="utf-8"),
        "paper_blueprint": blueprint.read_text(encoding="utf-8"),
        "answer_map": load_json(answer_map),
        "figure_plan": load_json(figure_plan),
        "figure_titles_visual_questions_and_takeaways": figure_digest,
    }
    return (
        "你是写作前独立论文蓝图审核者。只能依据下方 INPUT_BOUNDARY 内的题目需求摘要、"
        "PAPER_BLUEPRINT、answer-map、FIGURE_PLAN 及图的标题/视觉问题/takeaway。不得假设你"
        "看过最终 PDF、作者解释、工作流日志或任何前序审核结论。\n\n"
        "固定审核问题：\n"
        "1. 全篇中心数学对象是什么？\n"
        "2. 各问如何继承并增加困难？\n"
        "3. 每问的直接答案在哪里？\n"
        "4. 哪些内容目前只有密集文字，没有适合的图或表？\n"
        "5. 哪些图只是证明结果，没有解释模型？\n"
        "6. 哪些小节可能写成工作报告？\n"
        "7. 摘要计划是否形成统一主线？\n"
        "8. 是否缺少模型理解、算法过程、机制、不确定性或决策表达？\n"
        "9. 最多给出 5 项最高价值修改。\n\n"
        "阻断条件：中心数学对象无法复述；多问递进不清；核心问题缺完整论证单元；"
        "结构性视觉任务无图且无有效豁免；摘要明显逐问报账；主体仍是方法-结果-验证清单。\n\n"
        "只输出一个 JSON 对象，不要 Markdown 代码围栏。字段必须为："
        "schema_name='paper_blueprint_review'、schema_version='1.0'、decision（只能是 "
        "continue_writing 或 return_blueprint）、central_mathematical_object、"
        "question_progression、direct_answer_locations、text_only_gaps、result_only_figures、"
        "report_like_sections、abstract_assessment、missing_expression_roles、findings。"
        "findings 最多 5 项；每项包含 finding_id、severity(P0-P3)、finding、impact、"
        "repair_type、affected_argument_units、target_files、expected_benefit、estimated_cost、"
        "acceptance_test、stop_condition。\n\n"
        "<INPUT_BOUNDARY>\n"
        + json.dumps(allowed_material, ensure_ascii=False, indent=2)
        + "\n</INPUT_BOUNDARY>"
    )
