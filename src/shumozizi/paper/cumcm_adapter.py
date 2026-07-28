"""把现有科学论证稿轻量映射到 CUMCM 外层结构。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pypdf import PdfReader

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    load_json,
    resolve_inside,
    sha256_file,
)
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.core.schema import require_valid
from shumozizi.simple.state import (
    is_competition_first_v32_state,
    read_simple_state,
)

STRUCTURE_MAP_PATH = Path("paper/CUMCM_STRUCTURE_MAP.json")
LAYOUT_AUDIT_PATH = Path("paper/CUMCM_LAYOUT_AUDIT.json")

SECTION_TARGETS = (
    "摘要",
    "一、问题重述",
    "二、问题分析",
    "三、模型假设",
    "四、符号说明与数据处理",
    "五、模型的建立与求解",
    "六、模型的综合分析与检验",
    "七、模型评价",
    "八、参考文献",
    "附录",
)
STRUCTURE_CHECKS = (
    "problem_restatement",
    "problem_analysis",
    "assumptions",
    "symbols_and_data",
    "four_questions",
    "model_evaluation",
)
ARGUMENT_DEPTH_FIELDS = (
    "mathematical_difficulty",
    "mathematical_object",
    "modeling_basis",
    "derivation",
    "solver",
    "main_result",
    "mechanism",
    "competing_route_or_counterexample",
    "claim_specific_validation",
    "direct_answer",
)
ALLOWED_ADAPTATIONS = (
    "map_sections",
    "move_paragraphs",
    "rewrite_headings",
    "deduplicate_repetition",
    "reorder_figures",
    "repair_cross_references",
)
FORBIDDEN_ADAPTATIONS = (
    "change_model",
    "select_or_modify_numbers",
    "create_new_conclusions",
)
ISSUE_FIELDS = (
    "figures_too_small",
    "broken_sentences_by_float",
    "formula_overflow",
    "cross_chapter_inconsistencies",
    "symbol_definition_issues",
)


def cumcm_adapter_required(run_dir: Path) -> bool:
    """仅对 Competition-First v3.2 的 CUMCM 运行启用适配器。"""
    state = read_simple_state(run_dir)
    return bool(
        is_competition_first_v32_state(state)
        and str(state.get("competition", "")).strip().casefold() == "cumcm"
    )


def _require_cumcm_run(run_dir: Path) -> dict[str, Any]:
    """返回当前 CUMCM v3.2 状态，否则拒绝写入专用产物。"""
    state = read_simple_state(run_dir)
    if not cumcm_adapter_required(run_dir):
        raise ContractError("CUMCM 结构适配器只适用于 Competition-First v3.2 的 cumcm 运行")
    return state


def _nonempty_text(value: Any, label: str, *, minimum: int = 1) -> str:
    """校验并规整非空文本。"""
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise ContractError(f"{label} 必须是至少 {minimum} 个字符的非空文本")
    return value.strip()


def resolve_cumcm_reference_docx(run_dir: Path, document: dict[str, Any]) -> Path:
    """按结构映射声明解析 Word 参考模板。"""
    template = document["template"]
    raw_path = Path(template["reference_docx"])
    scope = template["path_scope"]
    if scope == "absolute":
        if not raw_path.is_absolute():
            raise ContractError("path_scope=absolute 时 reference_docx 必须是绝对路径")
        path = raw_path.resolve()
    elif scope == "run":
        path = resolve_inside(run_dir, raw_path.as_posix(), must_exist=True)
    elif scope == "repository":
        path = resolve_inside(
            resolve_repo_root(Path(__file__)), raw_path.as_posix(), must_exist=True
        )
    else:
        raise ContractError("Word 模板 path_scope 必须为 absolute、run 或 repository")
    if not path.is_file() or path.suffix.casefold() != ".docx" or path.stat().st_size == 0:
        raise ContractError(f"CUMCM Word 参考模板不存在、为空或不是 .docx: {path}")
    return path


def _validate_structure_map(run_dir: Path, document: dict[str, Any]) -> dict[str, Any]:
    """校验结构映射完整，但不评价或修改科学内容。"""
    state = _require_cumcm_run(run_dir)
    require_valid(document, "cumcm_structure_map")
    if document["run_id"] != run_dir.name:
        raise ContractError("CUMCM_STRUCTURE_MAP 与当前运行不匹配")
    if document["adaptation_rules"]["allowed"] != list(ALLOWED_ADAPTATIONS):
        raise ContractError("CUMCM 适配器允许动作必须保持为轻量结构改写集合")
    if document["adaptation_rules"]["forbidden"] != list(FORBIDDEN_ADAPTATIONS):
        raise ContractError("CUMCM 适配器必须禁止改模型、选数字和创造结论")
    if document["template"]["usage"] != "styles_and_outer_structure_only":
        raise ContractError("Word 模板只能用于样式和外层结构")
    if document["template"]["placeholder_content_authoritative"] is not False:
        raise ContractError("Word 模板占位文案不得作为科学写作规范")
    resolve_cumcm_reference_docx(run_dir, document)

    source_of_truth = document["source_of_truth"]
    for name, relative in source_of_truth.items():
        try:
            resolve_inside(run_dir, relative, must_exist=True)
        except ContractError as exc:
            raise ContractError(f"结构映射事实来源 {name} 无效: {exc}") from exc

    sections = {item["target"]: item for item in document["sections"]}
    missing = [target for target in SECTION_TARGETS if target not in sections]
    extras = sorted(set(sections) - set(SECTION_TARGETS))
    if missing or extras or len(sections) != len(document["sections"]):
        raise ContractError(
            "CUMCM 结构映射章节不完整或重复: "
            + ("缺少 " + ", ".join(missing) if missing else "")
            + ("；额外 " + ", ".join(extras) if extras else "")
        )
    valid_sources = {*source_of_truth, *state["required_questions"]}
    for section in document["sections"]:
        unknown = sorted(set(section["sources"]) - valid_sources)
        if unknown:
            raise ContractError(
                f"章节 {section['target']} 引用了未知事实来源: {', '.join(unknown)}"
            )
    model_section = sections["五、模型的建立与求解"]
    missing_questions = [
        question_id
        for question_id in state["required_questions"]
        if question_id not in model_section["sources"]
    ]
    if missing_questions or model_section["preserve_argument_order"] is not True:
        raise ContractError("模型建立与求解必须覆盖全部问题并保留各问特有论证顺序")
    if sections["六、模型的综合分析与检验"]["scope"] != "cross_question_only":
        raise ContractError("综合检验章只能汇总跨问题检验，近端验证必须留在各问正文")
    restatement_forbidden = set(sections["一、问题重述"]["forbidden_content"])
    if not {"模型名称", "最终数值", "大段题面复制"}.issubset(restatement_forbidden):
        raise ContractError("问题重述必须禁止模型名称、最终数值和大段题面复制")
    planning = document["page_planning"]
    if planning != {
        "recommended_body_pages": [24, 30],
        "inspect_below_pages": 18,
        "hard_gate": False,
    }:
        raise ContractError("CUMCM 页数只能使用 24–30 页软规划和 18 页以下复核提示")
    return document


def write_cumcm_structure_map(run_dir: Path, payload: dict[str, Any]) -> Path:
    """原子写入 CUMCM 结构映射，不生成或改写论文章节。"""
    document = {
        **payload,
        "schema_name": "cumcm_structure_map",
        "schema_version": "1.0",
        "run_id": run_dir.name,
    }
    _validate_structure_map(run_dir, document)
    path = run_dir / STRUCTURE_MAP_PATH
    atomic_json(path, document)
    return path


def require_cumcm_structure_map(run_dir: Path) -> dict[str, Any] | None:
    """CUMCM 正式论文编译前要求已有当前结构映射。"""
    if not cumcm_adapter_required(run_dir):
        return None
    path = run_dir / STRUCTURE_MAP_PATH
    if not path.is_file():
        raise ContractError("CUMCM 正式论文编译前缺少 paper/CUMCM_STRUCTURE_MAP.json")
    return _validate_structure_map(run_dir, load_json(path))


def _core_questions(run_dir: Path, required_questions: list[str]) -> set[str]:
    """读取核心问题；旧或不完整计划退化为检查全部必答问题。"""
    try:
        modeling = load_json(run_dir / "analysis" / "MODELING_UNITS.json")
    except ContractError:
        return set(required_questions)
    core = {
        str(unit.get("question_id"))
        for unit in modeling.get("units", [])
        if isinstance(unit, dict) and unit.get("core_question") is True
    }
    return core or set(required_questions)


def _review_blockers(run_dir: Path, document: dict[str, Any]) -> list[str]:
    """返回论文论证和叙事审查中的阻断项。"""
    state = read_simple_state(run_dir)
    blockers: list[str] = []
    for name in STRUCTURE_CHECKS:
        if document["structure"].get(name) != "pass":
            blockers.append(f"结构项 {name} 未通过")
    argument_depth = document["argument_depth"]
    if set(argument_depth) != set(state["required_questions"]):
        blockers.append("论证深度审查未完整覆盖必答问题")
    for question_id in _core_questions(run_dir, state["required_questions"]):
        assessment = argument_depth.get(question_id, {})
        missing = [field for field in ARGUMENT_DEPTH_FIELDS if assessment.get(field) is not True]
        if missing:
            blockers.append(f"核心问题 {question_id} 论证不足: {', '.join(missing)}")
    progression = document["question_progression"]
    if progression["status"] != "pass" or progression["interchangeable_questions"] is True:
        blockers.append("各问缺少不可任意交换的继承关系")
    for risk in document["narrative_risks"]:
        if risk["severity"] in {"P0", "P1"} and risk["status"] == "open":
            blockers.append(f"未解决 {risk['severity']} 叙事风险: {risk['location']}")
    return blockers


def _validate_review_audit(run_dir: Path, document: dict[str, Any]) -> list[str]:
    """校验综合审计的论文评审部分并返回阻断项。"""
    require_valid(document, "cumcm_layout_audit")
    if document["run_id"] != run_dir.name:
        raise ContractError("CUMCM_LAYOUT_AUDIT 与当前运行不匹配")
    require_cumcm_structure_map(run_dir)
    pdf = run_dir / "paper" / "final.pdf"
    if not pdf.is_file() or document["reviewed_pdf_sha256"] != sha256_file(pdf):
        raise ContractError("CUMCM 论证审查未绑定当前 paper/final.pdf")
    blockers = _review_blockers(run_dir, document)
    verdict = document["paper_review_verdict"]
    if verdict in {"pass", "conditional_pass"} and blockers:
        raise ContractError("论文评审结论与阻断项冲突: " + "；".join(blockers))
    if verdict == "rework" and not blockers and not document["narrative_risks"]:
        raise ContractError("rework 必须至少有一个具体阻断项或叙事风险")
    return blockers


def write_cumcm_paper_review_audit(run_dir: Path, payload: dict[str, Any]) -> Path:
    """在 paper_review 阶段记录论证深度和反工作报告审查。"""
    state = _require_cumcm_run(run_dir)
    if state["phase"] != "paper_review":
        raise ContractError("CUMCM 论证审计只能在 paper_review 阶段记录")
    require_cumcm_structure_map(run_dir)
    pdf = run_dir / "paper" / "final.pdf"
    if not pdf.is_file():
        raise ContractError("CUMCM 论证审计缺少 paper/final.pdf")
    document = {
        "schema_name": "cumcm_layout_audit",
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "reviewed_pdf_sha256": sha256_file(pdf),
        "structure": payload.get("structure", {}),
        "argument_depth": payload.get("argument_depth", {}),
        "question_progression": payload.get("question_progression", {}),
        "narrative_risks": payload.get("narrative_risks", []),
        "paper_review_verdict": payload.get("paper_review_verdict"),
        "review_summary": payload.get("review_summary"),
        "layout": {
            "status": "pending",
            "pdf_total_pages": None,
            "body_pages": None,
            "page_assessment": None,
            "page_review_note": None,
            "underdevelopment_found": False,
            "underdevelopment_note": None,
            "official_page_limit_checked": False,
            "docx_status": "pending",
            "docx_note": None,
            **{field: [] for field in ISSUE_FIELDS},
        },
        "overall_verdict": "rework" if payload.get("paper_review_verdict") == "rework" else "pending",
    }
    _validate_review_audit(run_dir, document)
    path = run_dir / LAYOUT_AUDIT_PATH
    atomic_json(path, document)
    return path


def require_cumcm_paper_review_audit(run_dir: Path) -> dict[str, Any] | None:
    """进入 verify 前要求 CUMCM 论证与叙事审核已通过。"""
    if not cumcm_adapter_required(run_dir):
        return None
    path = run_dir / LAYOUT_AUDIT_PATH
    if not path.is_file():
        raise ContractError("进入 verify 前缺少 paper/CUMCM_LAYOUT_AUDIT.json 的论证审查")
    document = load_json(path)
    blockers = _validate_review_audit(run_dir, document)
    if document["paper_review_verdict"] not in {"pass", "conditional_pass"} or blockers:
        detail = "；".join(blockers) or f"审查结论为 {document['paper_review_verdict']}"
        raise ContractError("CUMCM 论文论证或叙事审查尚未通过: " + detail)
    return document


def _page_assessment(body_pages: int) -> str:
    """按软页数规划返回人工复核类别。"""
    if body_pages < 18:
        return "under_18_review_required"
    if body_pages < 24:
        return "compression_review_required"
    if body_pages <= 30:
        return "normal_range"
    return "over_30_limit_review_required"


def finalize_cumcm_layout_audit(run_dir: Path, payload: dict[str, Any]) -> Path:
    """在 verify 阶段用现有机械 QA 事实闭合版面审计。"""
    state = _require_cumcm_run(run_dir)
    if state["phase"] != "verify":
        raise ContractError("CUMCM 版面审计只能在 verify 阶段闭合")
    document = require_cumcm_paper_review_audit(run_dir)
    assert document is not None
    from shumozizi.simple.review import mechanical_qa_status

    mechanical = mechanical_qa_status(run_dir)
    if not mechanical["allowed"]:
        raise ContractError("CUMCM 版面审计前机械 QA 尚未通过: " + mechanical["reason"])
    pdf = run_dir / "paper" / "final.pdf"
    total_pages = len(PdfReader(str(pdf)).pages)
    body_pages = payload.get("body_pages")
    if not isinstance(body_pages, int) or isinstance(body_pages, bool) or body_pages < 1:
        raise ContractError("body_pages 必须是正整数")
    if body_pages > total_pages:
        raise ContractError("body_pages 不能超过 PDF 总页数")
    assessment = _page_assessment(body_pages)
    note = payload.get("page_review_note")
    if assessment != "normal_range":
        _nonempty_text(note, "page_review_note", minimum=12)
    elif note is not None and not isinstance(note, str):
        raise ContractError("page_review_note 必须是文本或 null")
    official_checked = payload.get("official_page_limit_checked") is True
    if assessment == "over_30_limit_review_required" and not official_checked:
        raise ContractError("正文超过 30 页时必须确认当年官方页数限制")

    issues: dict[str, list[str]] = {}
    for field in ISSUE_FIELDS:
        value = payload.get(field, [])
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise ContractError(f"{field} 必须是非空文本数组")
        issues[field] = [item.strip() for item in value]

    docx = run_dir / "paper" / "final.docx"
    docx_note = payload.get("docx_note")
    if docx.is_file():
        docx_report_path = run_dir / "qa" / "docx-structure.json"
        if not docx_report_path.is_file():
            raise ContractError("已有 final.docx 但缺少 qa/docx-structure.json")
        docx_report = load_json(docx_report_path)
        if docx_report.get("success") is not True:
            raise ContractError("DOCX 结构 QA 未通过")
        if docx_report.get("render_pdf"):
            docx_status = "render_checked"
        else:
            docx_status = "structure_checked_render_unavailable"
            _nonempty_text(docx_note, "docx_note", minimum=12)
    else:
        docx_status = "unavailable_with_reason"
        _nonempty_text(docx_note, "docx_note", minimum=12)

    underdevelopment_found = payload.get("underdevelopment_found") is True
    underdevelopment_note = payload.get("underdevelopment_note")
    if underdevelopment_found:
        _nonempty_text(underdevelopment_note, "underdevelopment_note", minimum=12)
    elif underdevelopment_note is not None and not isinstance(underdevelopment_note, str):
        raise ContractError("underdevelopment_note 必须是文本或 null")
    hard_layout_issue = any(issues.values()) or underdevelopment_found
    soft_conditions = bool(
        assessment != "normal_range"
        or docx_status != "render_checked"
        or document["paper_review_verdict"] == "conditional_pass"
    )
    if hard_layout_issue:
        overall_verdict = "rework"
    elif soft_conditions:
        overall_verdict = "conditional_pass"
    else:
        overall_verdict = "pass"
    document["layout"] = {
        "status": "checked",
        "pdf_total_pages": total_pages,
        "body_pages": body_pages,
        "page_assessment": assessment,
        "page_review_note": note,
        "underdevelopment_found": underdevelopment_found,
        "underdevelopment_note": underdevelopment_note,
        "official_page_limit_checked": official_checked,
        "docx_status": docx_status,
        "docx_note": docx_note,
        **issues,
    }
    document["overall_verdict"] = overall_verdict
    require_valid(document, "cumcm_layout_audit")
    path = run_dir / LAYOUT_AUDIT_PATH
    atomic_json(path, document)
    return path


def require_cumcm_layout_audit(run_dir: Path) -> dict[str, Any] | None:
    """标记 complete 前要求综合审计绑定当前 PDF 且无版面阻断项。"""
    if not cumcm_adapter_required(run_dir):
        return None
    document = require_cumcm_paper_review_audit(run_dir)
    assert document is not None
    if document["layout"]["status"] != "checked":
        raise ContractError("CUMCM_LAYOUT_AUDIT 尚未完成 verify 版面闭环")
    if document["overall_verdict"] not in {"pass", "conditional_pass"}:
        raise ContractError("CUMCM 综合审计要求返工")
    if any(document["layout"][field] for field in ISSUE_FIELDS):
        raise ContractError("CUMCM 综合审计仍有未解决的版面或一致性问题")
    return document
