"""把现有科学论证稿轻量映射到 CUMCM 外层结构。"""

from __future__ import annotations

import re
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
    record_layout_audit,
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
CLASSIC_ROLE_BY_TARGET = {
    "摘要": "problem_restatement",
    "一、问题重述": "problem_restatement",
    "二、问题分析": "problem_analysis",
    "三、模型假设": "assumptions",
    "四、符号说明与数据处理": "symbols_or_data_definition",
    "五、模型的建立与求解": "question_solution",
    "六、模型的综合分析与检验": "local_validation",
    "七、模型评价": "overall_evaluation",
    "八、参考文献": "references",
    "附录": "appendix",
}
LEGACY_SEMANTIC_REQUIRED_ROLES = frozenset(
    {
        "problem_restatement",
        "problem_analysis",
        "assumptions",
        "symbols_or_data_definition",
        "data_processing",
        "question_solution",
        "local_validation",
        "overall_evaluation",
        "references",
        "appendix",
    }
)
SEMANTIC_REQUIRED_ROLES = frozenset(
    {
        "abstract",
        "problem_restatement",
        "problem_analysis",
        "assumptions",
        "symbols_or_data_definition",
        "shared_model",
        "question_solution",
        "local_validation",
        "overall_evaluation",
        "conclusion",
        "references",
        "appendix",
    }
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


def recommend_cumcm_structure_profile(run_dir: Path) -> dict[str, Any]:
    """根据问题链证据推荐 CUMCM 结构画像。

    Args:
        run_dir: Competition-First v3.2 运行目录。

    Returns:
        包含推荐画像、判定信号和可读理由的字典。只有三问以上、存在共享
        数学对象和继承边，并且后问新增资源、共享约束或聚合层时，才推荐
        使用保留国赛外壳的 ``semantic`` 画像。
    """
    state = _require_cumcm_run(run_dir)
    questions = list(state["required_questions"])
    modeling_path = run_dir / "analysis" / "MODELING_UNITS.json"
    try:
        modeling = load_json(modeling_path)
    except (ContractError, OSError, ValueError):
        modeling = {}

    story = modeling.get("research_story")
    if not isinstance(story, dict):
        story = {}
    central_object = story.get("central_mathematical_object")
    shared_object_declared = bool(
        isinstance(central_object, str)
        and len(central_object.strip()) >= 12
        and "待填写" not in central_object
    )
    progression = story.get("question_progression")
    if not isinstance(progression, list):
        progression = []
    inheritance_edges = 0
    for item in progression:
        if not isinstance(item, dict):
            continue
        inherited = item.get("inherits_from")
        if isinstance(inherited, list):
            inheritance_edges += len(
                [question_id for question_id in inherited if question_id in questions]
            )

    progressive_deltas: list[str] = []
    units = modeling.get("units")
    if not isinstance(units, list):
        units = []
    for unit in units:
        if not isinstance(unit, dict):
            continue
        delta = unit.get("question_delta")
        if not isinstance(delta, dict):
            continue
        has_progression = any(
            isinstance(delta.get(field), list) and bool(delta[field])
            for field in ("added_resources", "shared_resources", "changed_constraints")
        ) or delta.get("must_recheck_aggregation") is True
        question_id = unit.get("question_id")
        if has_progression and isinstance(question_id, str):
            progressive_deltas.append(question_id)

    signals = {
        "at_least_three_questions": len(questions) >= 3,
        "shared_mathematical_object": shared_object_declared
        and inheritance_edges >= 1,
        "resource_constraint_or_aggregation_progression": bool(progressive_deltas),
    }
    profile = "semantic" if all(signals.values()) else "classic"
    if profile == "semantic":
        reason = (
            "必答问题不少于三问，问题链共享同一数学对象，且后问新增资源、"
            "共享约束或聚合层；采用经典国赛外壳下的语义内核。"
        )
    else:
        missing = [name for name, present in signals.items() if not present]
        reason = (
            "尚无充分的问题链证据自动合并章节，使用 classic 稳定兜底；"
            "缺少信号：" + "、".join(missing)
        )
    return {
        "profile": profile,
        "reason": reason,
        "signals": signals,
        "inheritance_edges": inheritance_edges,
        "progressive_questions": sorted(set(progressive_deltas)),
    }


def _section_roles(section: dict[str, Any]) -> frozenset[str]:
    """兼容读取单角色旧映射与多角色 semantic 章节。"""
    declared: list[str] = []
    role = section.get("role")
    if isinstance(role, str):
        declared.append(role)
    roles = section.get("roles")
    if isinstance(roles, list):
        declared.extend(item for item in roles if isinstance(item, str))
    if not declared:
        raise ContractError(f"章节 {section.get('target', '<unknown>')} 缺少语义角色")
    if len(declared) != len(set(declared)):
        raise ContractError(f"章节 {section.get('target', '<unknown>')} 的语义角色重复")
    return frozenset(declared)


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

    version = document["schema_version"]
    profile = document.get("profile", "classic")
    section_items = document["sections"]
    sections = {item["target"]: item for item in section_items}
    if profile == "classic":
        if any("roles" in item for item in section_items):
            raise ContractError("classic 结构每章只能声明单一 role")
        missing = [target for target in SECTION_TARGETS if target not in sections]
        extras = sorted(set(sections) - set(SECTION_TARGETS))
        if missing or extras or len(sections) != len(section_items):
            raise ContractError(
                "CUMCM classic sections 结构映射章节不完整或重复: "
                + ("缺少 " + ", ".join(missing) if missing else "")
                + ("；额外 " + ", ".join(extras) if extras else "")
            )
        if version in {"1.1", "1.2"}:
            wrong_roles = [
                item["target"]
                for item in section_items
                if item["role"] != CLASSIC_ROLE_BY_TARGET[item["target"]]
            ]
            if wrong_roles:
                raise ContractError("classic 章节语义角色不匹配: " + ", ".join(wrong_roles))
    elif profile == "semantic":
        if version == "1.1":
            _validate_legacy_semantic_sections(state, section_items)
        else:
            _validate_semantic_sections(state, section_items)
    else:
        raise ContractError("CUMCM 结构画像必须为 classic 或 semantic")
    valid_sources = {*source_of_truth, *state["required_questions"]}
    for section in document["sections"]:
        unknown = sorted(set(section["sources"]) - valid_sources)
        if unknown:
            raise ContractError(
                f"章节 {section['target']} 引用了未知事实来源: {', '.join(unknown)}"
            )
    if profile == "classic":
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
        restatement = sections["一、问题重述"]
    else:
        restatement = next(
            item
            for item in section_items
            if "problem_restatement" in _section_roles(item)
        )
    restatement_forbidden = set(restatement["forbidden_content"])
    if not {"模型名称", "最终数值", "大段题面复制"}.issubset(restatement_forbidden):
        raise ContractError("问题重述必须禁止模型名称、最终数值和大段题面复制")
    planning = document["page_planning"]
    if planning != {
        "recommended_body_pages": [24, 30],
        "inspect_below_pages": 18,
        "hard_gate": False,
    }:
        raise ContractError("CUMCM 页数只能使用 24–30 页软规划和 18 页以下复核提示")
    if version in {"1.1", "1.2"}:
        _validate_presentation_contract(run_dir, state, document["presentation_contract"])
    return document


def _validate_presentation_decision(value: dict[str, Any], label: str) -> None:
    """校验呈现任务的 required/waived 与 figure_id 一致。"""
    if value["status"] == "required" and not value.get("figure_id"):
        raise ContractError(f"{label} 声明 required 时必须给出 figure_id")
    if value["status"] == "waived" and value.get("figure_id") is not None:
        raise ContractError(f"{label} 声明 waived 时 figure_id 必须为 null")


def _validate_presentation_contract(
    run_dir: Path, state: dict[str, Any], contract: dict[str, Any]
) -> None:
    """确定性校验阅读路线、源码锚点和逐问主图声明。"""
    opening = contract["opening_reading_route"]
    if opening["target_pages"][0] > opening["target_pages"][1]:
        raise ContractError("opening_reading_route.target_pages 必须按升序填写")
    for label, item in (
        ("opening_reading_route", opening),
        ("cross_question_story", contract["cross_question_story"]),
    ):
        try:
            resolve_inside(run_dir, item["source_path"], must_exist=True)
        except ContractError as exc:
            raise ContractError(f"{label} 的 source_path 无效: {exc}") from exc
    overview = contract["answer_overview"]
    if overview["required"]:
        if not overview.get("source_path") or not overview.get("explanation_anchor"):
            raise ContractError("answer_overview 声明 required 时必须给出源码路径和解释锚点")
        resolve_inside(run_dir, overview["source_path"], must_exist=True)
    elif overview.get("source_path") is not None or overview.get("explanation_anchor") is not None:
        raise ContractError("answer_overview 不要求时源码路径和解释锚点必须为 null")

    _validate_presentation_decision(contract["data_portrait"], "data_portrait")
    heroes = contract["question_hero_figures"]
    if set(heroes) != set(state["required_questions"]):
        raise ContractError("question_hero_figures 必须逐项覆盖全部必答问题")
    for question_id, decision in heroes.items():
        _validate_presentation_decision(decision, f"question_hero_figures.{question_id}")


def _validate_semantic_sections(
    state: dict[str, Any], sections: list[dict[str, Any]]
) -> None:
    """校验 semantic 的经典外壳、共享主线、逐问覆盖和章节顺序。"""
    section_ids = [item["section_id"] for item in sections]
    if len(section_ids) != len(set(section_ids)):
        raise ContractError("semantic 结构的 section_id 不能重复")
    section_roles = [_section_roles(item) for item in sections]
    all_roles = frozenset().union(*section_roles)
    missing_roles = sorted(SEMANTIC_REQUIRED_ROLES - all_roles)
    if missing_roles:
        raise ContractError("semantic 结构缺少语义角色: " + ", ".join(missing_roles))
    if any(item["preserve_argument_order"] is not True for item in sections):
        raise ContractError("semantic 结构必须保留 PAPER_BLUEPRINT 的论证顺序")

    assumptions_entry = [
        (item, roles)
        for item, roles in zip(sections, section_roles, strict=True)
        if {"assumptions", "symbols_or_data_definition"}.issubset(roles)
    ]
    if len(assumptions_entry) != 1:
        raise ContractError(
            "semantic 结构必须保留一个明确的“模型假设与符号”入口，"
            "同一章节需同时声明 assumptions 与 symbols_or_data_definition"
        )
    assumptions_title = assumptions_entry[0][0]["target"]
    if "假设" not in assumptions_title or "符号" not in assumptions_title:
        raise ContractError("semantic 的假设与符号入口标题必须同时包含“假设”和“符号”")

    required_questions = list(state["required_questions"])
    known = set(required_questions)
    covered: list[str] = []
    for item, roles in zip(sections, section_roles, strict=True):
        question_ids = item.get("question_ids", [])
        unknown = sorted(set(question_ids) - known)
        if unknown:
            raise ContractError("semantic 章节引用未知问题: " + ", ".join(unknown))
        if "question_solution" in roles:
            if not question_ids:
                raise ContractError("semantic 的求解章节必须声明至少一个 question_id")
            covered.extend(question_ids)
    missing_questions = [item for item in required_questions if item not in covered]
    if missing_questions:
        raise ContractError("semantic 结构未覆盖必答问题: " + ", ".join(missing_questions))
    first_positions = [covered.index(item) for item in required_questions]
    if first_positions != sorted(first_positions):
        raise ContractError("semantic 逐问首次出现顺序必须遵循 required_questions")

    def first_position(role: str) -> int:
        """返回某角色首次出现的章节位置。"""
        return next(index for index, roles in enumerate(section_roles) if role in roles)

    def last_position(role: str) -> int:
        """返回某角色最后出现的章节位置。"""
        return max(index for index, roles in enumerate(section_roles) if role in roles)

    first_solution = first_position("question_solution")
    last_solution = last_position("question_solution")
    assumptions_position = first_position("assumptions")
    symbols_position = first_position("symbols_or_data_definition")
    data_positions = [
        index for index, roles in enumerate(section_roles) if "data_processing" in roles
    ]
    if not (
        first_position("abstract") < first_position("problem_restatement")
        and first_position("problem_restatement")
        <= first_position("problem_analysis")
        < assumptions_position
        and assumptions_position == symbols_position
        < first_position("shared_model")
        < first_solution
        and all(position < first_solution for position in data_positions)
        and first_position("local_validation") >= first_solution
        and first_position("overall_evaluation") > last_solution
        and first_position("conclusion") >= first_position("overall_evaluation")
        and first_position("references") > first_position("conclusion")
        and first_position("appendix") > first_position("references")
    ):
        raise ContractError(
            "semantic 结构必须遵循“摘要—问题重述与分析—模型假设与符号—"
            "共享模型—问题链求解—检验评价与结论—参考文献—附录”的国赛外壳"
        )


def _validate_legacy_semantic_sections(
    state: dict[str, Any], sections: list[dict[str, Any]]
) -> None:
    """只读兼容 CUMCM_STRUCTURE_MAP 1.1 的实验性 semantic 合同。"""
    section_ids = [item["section_id"] for item in sections]
    if len(section_ids) != len(set(section_ids)):
        raise ContractError("semantic 结构的 section_id 不能重复")
    roles = [item["role"] for item in sections]
    missing_roles = sorted(LEGACY_SEMANTIC_REQUIRED_ROLES - set(roles))
    if missing_roles:
        raise ContractError("semantic 结构缺少语义角色: " + ", ".join(missing_roles))
    if any(item["preserve_argument_order"] is not True for item in sections):
        raise ContractError("semantic 结构必须保留 PAPER_BLUEPRINT 的论证顺序")

    required_questions = list(state["required_questions"])
    known = set(required_questions)
    covered: list[str] = []
    for item in sections:
        question_ids = item.get("question_ids", [])
        unknown = sorted(set(question_ids) - known)
        if unknown:
            raise ContractError("semantic 章节引用未知问题: " + ", ".join(unknown))
        if item["role"] == "question_solution":
            covered.extend(question_ids)
    missing_questions = [item for item in required_questions if item not in covered]
    if missing_questions:
        raise ContractError("semantic 结构未覆盖必答问题: " + ", ".join(missing_questions))
    first_positions = [covered.index(item) for item in required_questions]
    if first_positions != sorted(first_positions):
        raise ContractError("semantic 逐问首次出现顺序必须遵循 required_questions")

    first_solution = roles.index("question_solution")
    last_solution = len(roles) - 1 - roles[::-1].index("question_solution")
    if not (
        roles.index("problem_restatement") < roles.index("problem_analysis") < first_solution
        and roles.index("assumptions") < first_solution
        and roles.index("symbols_or_data_definition") < first_solution
        and roles.index("data_processing") < first_solution
        and roles.index("overall_evaluation") > last_solution
        and roles.index("references") > roles.index("overall_evaluation")
        and roles.index("appendix") > roles.index("references")
    ):
        raise ContractError("semantic 结构的定义、逐问求解、评价、文献和附录顺序无效")


def write_cumcm_structure_map(run_dir: Path, payload: dict[str, Any]) -> Path:
    """原子写入 CUMCM 结构映射，不生成或改写论文章节。"""
    version = payload.get("schema_version")
    if version is None:
        if "presentation_contract" in payload and "profile" not in payload:
            version = "1.2"
        else:
            version = "1.1" if "profile" in payload else "1.0"
    profile = payload.get("profile")
    if version == "1.2" and (profile is None or profile == "auto"):
        # 自动选择只消费分析阶段已经冻结的问题链事实，不新增作者填表。
        profile = recommend_cumcm_structure_profile(run_dir)["profile"]
    document = {
        **payload,
        "schema_name": "cumcm_structure_map",
        "schema_version": version,
        "run_id": run_dir.name,
    }
    if version in {"1.1", "1.2"}:
        document["profile"] = profile
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


def _normalized_text(value: str) -> str:
    """规整空白以便稳定核对 LaTeX/Markdown 中的声明锚点。"""
    return re.sub(r"\s+", "", value)


def _normalized_graphics_path(value: str) -> str:
    """规整 LaTeX 图片路径，忽略扩展名和上级目录写法。"""
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("../"):
        normalized = normalized[3:]
    suffix = Path(normalized).suffix.casefold()
    if suffix in {".pdf", ".png", ".jpg", ".jpeg"}:
        normalized = normalized[: -len(suffix)]
    return normalized


def _source_anchor_check(
    run_dir: Path,
    *,
    check_id: str,
    source_path: str,
    anchor: str,
    classification: str,
) -> dict[str, Any]:
    """核对一个计划锚点已进入声明的论文源码。"""
    location = source_path
    try:
        path = resolve_inside(run_dir, source_path, must_exist=True)
        text = path.read_text(encoding="utf-8")
    except (ContractError, OSError, UnicodeError) as exc:
        return {
            "check_id": check_id,
            "status": "missing",
            "location": location,
            "issue": f"无法读取声明的论文源码: {exc}",
            "classification": classification,
        }
    present = _normalized_text(anchor) in _normalized_text(text)
    return {
        "check_id": check_id,
        "status": "present" if present else "missing",
        "location": location,
        "issue": None if present else "论文源码中未找到声明的解释锚点",
        "classification": classification,
    }


def _figure_realization_check(
    run_dir: Path,
    *,
    check_id: str,
    decision: dict[str, Any],
    expected_role: str,
    expected_question: str | None,
    classification: str,
) -> dict[str, Any]:
    """核对呈现图已在计划、current 登记和 LaTeX 消费三处兑现。"""
    if decision["status"] == "waived":
        return {
            "check_id": check_id,
            "status": "present",
            "location": "figures/FIGURE_PLAN.json",
            "issue": None,
            "classification": "advisory",
        }
    figure_id = decision["figure_id"]
    issues: list[str] = []
    try:
        plan = load_json(run_dir / "figures" / "FIGURE_PLAN.json")
        figures = [
            item
            for item in plan.get("figures", [])
            if isinstance(item, dict) and item.get("figure_id") == figure_id
        ]
    except (ContractError, OSError, TypeError, ValueError) as exc:
        figures = []
        issues.append(f"无法读取 FIGURE_PLAN: {exc}")
    if len(figures) != 1:
        issues.append("FIGURE_PLAN 中没有且仅有一个同 ID 图")
        figure = None
    else:
        figure = figures[0]
        if figure.get("presentation_role") != expected_role:
            issues.append(f"presentation_role 应为 {expected_role}")
        if expected_question is not None and figure.get("question_id") != expected_question:
            issues.append("question_id 与结构合同不一致")

    try:
        index = load_json(run_dir / "figures" / "index.json")
        current = {
            item.get("figure_id"): item
            for item in index.get("figures", [])
            if isinstance(item, dict) and item.get("status") == "current"
        }
        registered = current.get(figure_id)
        if registered is None:
            issues.append("图尚未登记为 current")
        elif registered.get("presentation_role") not in {None, expected_role}:
            issues.append("current 图的 presentation_role 与结构合同不一致")
    except (ContractError, OSError, TypeError, ValueError):
        registered = None
        issues.append("无法确认图的 current 登记")

    location = "figures/FIGURE_PLAN.json"
    if figure is not None:
        location = str(figure.get("paper_section", location))
        if registered is not None and figure.get("source_files"):
            planned_sources = set(figure["source_files"])
            registered_sources = {
                item.get("path")
                for item in registered.get("source_files", [])
                if isinstance(item, dict)
            }
            if planned_sources != registered_sources:
                issues.append("current 图没有绑定计划声明的冻结输入文件")
        try:
            section = resolve_inside(run_dir, location, must_exist=True)
            text = section.read_text(encoding="utf-8")
            includes = [
                _normalized_graphics_path(value)
                for value in re.findall(
                    r"\\includegraphics(?:\[[^]]*\])?\{([^}]+)\}", text
                )
            ]
            output = _normalized_graphics_path(str(figure.get("output", "")))
            if not any(
                value.endswith(output) or output.endswith(value)
                for value in includes
                if output
            ):
                issues.append("声明章节没有消费计划输出")
            label = str(figure.get("latex_label", ""))
            if not label or f"\\label{{{label}}}" not in text:
                issues.append("声明章节缺少图 label")
            if not label or (
                f"\\ref{{{label}}}" not in text and f"\\autoref{{{label}}}" not in text
            ):
                issues.append("正文没有交叉引用该图")
            anchor = str(figure.get("explanation_anchor", ""))
            if not anchor or _normalized_text(anchor) not in _normalized_text(text):
                issues.append("正文没有兑现图的解释锚点")
        except (ContractError, OSError, UnicodeError) as exc:
            issues.append(f"无法读取声明章节: {exc}")

    if not issues:
        status = "present"
    elif figure is None:
        status = "missing"
    else:
        status = "partial"
    return {
        "check_id": check_id,
        "status": status,
        "location": location,
        "issue": "；".join(issues) if issues else None,
        "classification": classification,
    }


def evaluate_presentation_contract(run_dir: Path) -> dict[str, Any] | None:
    """复验 CUMCM 1.1 呈现合同已被论文源码和图表消费。

    Args:
        run_dir: 当前运行目录。

    Returns:
        结构化兑现检查；1.0 映射或非 CUMCM 运行返回 ``None``。
    """
    document = require_cumcm_structure_map(run_dir)
    if document is None or document.get("schema_version") not in {"1.1", "1.2"}:
        return None
    contract = document["presentation_contract"]
    classification = "blocking" if contract["mode"] == "required" else "advisory"
    checks = [
        _source_anchor_check(
            run_dir,
            check_id="opening_reading_route",
            source_path=contract["opening_reading_route"]["source_path"],
            anchor=contract["opening_reading_route"]["explanation_anchor"],
            classification=classification,
        ),
        _source_anchor_check(
            run_dir,
            check_id="cross_question_story",
            source_path=contract["cross_question_story"]["source_path"],
            anchor=contract["cross_question_story"]["explanation_anchor"],
            classification=classification,
        ),
    ]
    overview = contract["answer_overview"]
    if overview["required"]:
        checks.append(
            _source_anchor_check(
                run_dir,
                check_id="answer_overview",
                source_path=overview["source_path"],
                anchor=overview["explanation_anchor"],
                classification=classification,
            )
        )
    else:
        checks.append(
            {
                "check_id": "answer_overview",
                "status": "present",
                "location": "paper/CUMCM_STRUCTURE_MAP.json",
                "issue": None,
                "classification": "advisory",
            }
        )
    checks.append(
        _figure_realization_check(
            run_dir,
            check_id="data_portrait",
            decision=contract["data_portrait"],
            expected_role="data_portrait",
            expected_question=None,
            classification=classification,
        )
    )
    for question_id, decision in contract["question_hero_figures"].items():
        checks.append(
            _figure_realization_check(
                run_dir,
                check_id=f"question_hero_figures.{question_id}",
                decision=decision,
                expected_role="question_hero",
                expected_question=question_id,
                classification=classification,
            )
        )
    blockers = [
        item["check_id"]
        for item in checks
        if item["status"] != "present" and item["classification"] == "blocking"
    ]
    warnings = [
        item["check_id"]
        for item in checks
        if item["status"] != "present" and item["classification"] == "advisory"
    ]
    return {
        "mode": contract["mode"],
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
    }


def build_learning_realization(
    run_dir: Path,
    assessments: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """把写作前选定的论文卡模式与冻结 PDF 人工核对结果合并。

    该检查在 PDF-only 冷读完成后本地执行。它只判断预先声明的结构模式是否
    兑现，不比较奖项水平，也不允许论文卡成为当前题的事实或证据。

    Args:
        run_dir: 当前 Competition-First v3.2 运行目录。
        assessments: 每个已采用模式的 PDF 兑现判断。

    Returns:
        可写入 ``CUMCM_LAYOUT_AUDIT`` 的 advisory 兑现记录。

    Raises:
        ContractError: 判断缺失、重复、包含未知模式或缺少具体发现。
    """
    from shumozizi.knowledge.retrieval import read_paper_knowledge_application

    application = read_paper_knowledge_application(run_dir)
    expected = {
        item["pattern_id"]: item for item in application["adopted_patterns"]
    }
    supplied = assessments or []
    if not isinstance(supplied, list):
        raise ContractError("learning_checks 必须是数组")
    recorded: dict[str, dict[str, Any]] = {}
    for item in supplied:
        if not isinstance(item, dict):
            raise ContractError("learning_checks 只能包含对象")
        pattern_id = item.get("pattern_id")
        if not isinstance(pattern_id, str) or not pattern_id.strip():
            raise ContractError("learning_checks 缺少 pattern_id")
        if pattern_id in recorded:
            raise ContractError(f"学习兑现判断重复模式 {pattern_id}")
        realization = item.get("pdf_realization")
        if realization not in {"pass", "partial", "fail"}:
            raise ContractError(f"学习模式 {pattern_id} 的 pdf_realization 无效")
        finding = item.get("finding")
        if realization in {"partial", "fail"}:
            finding = _nonempty_text(
                finding, f"学习模式 {pattern_id} 的 finding", minimum=8
            )
        elif finding is not None:
            finding = _nonempty_text(
                finding, f"学习模式 {pattern_id} 的 finding", minimum=8
            )
        recorded[pattern_id] = {
            "pdf_realization": realization,
            "finding": finding,
        }
    unknown = sorted(set(recorded) - set(expected))
    missing = sorted(set(expected) - set(recorded))
    if unknown:
        raise ContractError("learning_checks 包含未采用模式: " + ", ".join(unknown))
    if missing:
        raise ContractError("learning_checks 未覆盖已采用模式: " + ", ".join(missing))

    checks = [
        {
            "pattern_id": pattern_id,
            "paper_id": item["paper_id"],
            "pattern": item["pattern"],
            "planned_location": item["planned_location"],
            "current_evidence": item["current_evidence"],
            "source_path": item["source_path"],
            "realization_anchor": item["realization_anchor"],
            **recorded[pattern_id],
        }
        for pattern_id, item in expected.items()
    ]
    statuses = {item["pdf_realization"] for item in checks}
    if not checks:
        status = "not_applicable"
        summary = "本轮未采用论文卡模式，无需执行成稿兑现比较。"
    elif "fail" in statuses:
        status = "fail"
        summary = "至少一个写作前采用的论文卡模式未在当前 PDF 中兑现。"
    elif "partial" in statuses:
        status = "partial"
        summary = "写作前采用的论文卡模式仅在当前 PDF 中部分兑现。"
    else:
        status = "pass"
        summary = "写作前采用的论文卡模式均已在当前 PDF 中明确兑现。"
    return {
        "advisory_only": True,
        "input_scope": "knowledge_application_and_frozen_pdf",
        "source_application": "paper/KNOWLEDGE_APPLICATION.md",
        "comparison_scope": "planned_transfer_patterns_only",
        "evidence_boundary": application["evidence_boundary"],
        "selected_cards": application["selected_cards"],
        "checks": checks,
        "status": status,
        "summary": summary,
    }


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


def _current_blind_review_record(run_dir: Path) -> dict[str, Any]:
    """读取与当前 PDF 同修订的结构化独立盲评记录。"""
    from shumozizi.simple.review import require_current_paper_blind_review_record

    return require_current_paper_blind_review_record(run_dir)


def _blind_review_source(run_dir: Path, review: dict[str, Any]) -> dict[str, Any]:
    """构造版式审计对独立盲评记录、报告和任务身份的绑定。"""
    record_file = Path("review/paper-blind-review.json")
    return {
        "record_file": record_file.as_posix(),
        "record_sha256": sha256_file(run_dir / record_file),
        "report_file": review["report"]["file"],
        "report_sha256": review["report"]["sha256"],
        "task_id": review["task_receipt"]["task_id"],
        "thread_id": review["reviewer"]["thread_id"],
        "paper_render_revision": review["paper_render_revision"],
    }


def _review_blockers(run_dir: Path, document: dict[str, Any]) -> list[str]:
    """返回论文论证和叙事审查中的阻断项。"""
    state = read_simple_state(run_dir)
    blockers: list[str] = []
    for name in STRUCTURE_CHECKS:
        if document["structure"].get(name) != "pass":
            blockers.append(f"结构项 {name} 未通过")
    if document.get("schema_version") == "1.3":
        argument_findings = document["argument_findings"]
        if set(argument_findings) != set(state["required_questions"]):
            blockers.append("独立盲评论证发现未完整覆盖必答问题")
        for question_id in _core_questions(run_dir, state["required_questions"]):
            missing = argument_findings.get(question_id, {}).get("missing_roles", [])
            if missing:
                blockers.append(
                    f"核心问题 {question_id} 论证不足: {', '.join(missing)}"
                )
    else:
        argument_depth = document["argument_depth"]
        if set(argument_depth) != set(state["required_questions"]):
            blockers.append("论证深度审查未完整覆盖必答问题")
        for question_id in _core_questions(run_dir, state["required_questions"]):
            assessment = argument_depth.get(question_id, {})
            missing = [
                field
                for field in ARGUMENT_DEPTH_FIELDS
                if assessment.get(field) is not True
            ]
            if missing:
                blockers.append(
                    f"核心问题 {question_id} 论证不足: {', '.join(missing)}"
                )
    progression = document["question_progression"]
    if progression["status"] != "pass" or progression["interchangeable_questions"] is True:
        blockers.append("各问缺少不可任意交换的继承关系")
    for risk in document["narrative_risks"]:
        if risk["severity"] in {"P0", "P1"} and risk["status"] == "open":
            blockers.append(f"未解决 {risk['severity']} 叙事风险: {risk['location']}")
    if document.get("schema_version") in {"1.1", "1.2", "1.3"}:
        blockers.extend(document["adjudication"]["blocking_findings"])
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
    if document.get("schema_version") in {"1.1", "1.2", "1.3"}:
        state = read_simple_state(run_dir)
        cold_read = document["cold_read"]
        answers = cold_read["direct_answers_found_within_3_minutes"]
        if set(answers) != set(state["required_questions"]):
            raise ContractError("cold_read 必须逐项覆盖全部必答问题的三分钟答案检索")
        unknown_heroes = set(cold_read["hero_figures_identified"]) - set(
            state["required_questions"]
        )
        if unknown_heroes:
            raise ContractError("cold_read.hero_figures_identified 包含未知问题")
        expected_realization = evaluate_presentation_contract(run_dir)
        if expected_realization != document["authoring_realization"]:
            raise ContractError("authoring_realization 已与当前论文源码或图表消费关系漂移")
        expected_probe = probe_pdf_page_rhythm(pdf)
        if expected_probe != document["presentation_probe"]:
            raise ContractError("presentation_probe 已与当前 PDF 漂移")
        learning_realization = None
        if document.get("schema_version") in {"1.2", "1.3"}:
            assessments = [
                {
                    "pattern_id": item["pattern_id"],
                    "pdf_realization": item["pdf_realization"],
                    "finding": item["finding"],
                }
                for item in document["learning_realization"]["checks"]
            ]
            learning_realization = build_learning_realization(run_dir, assessments)
            if learning_realization != document["learning_realization"]:
                raise ContractError(
                    "learning_realization 已与当前知识应用计划或 PDF 判断漂移"
                )
        expected_adjudication = _presentation_adjudication(
            state,
            expected_realization,
            cold_read,
            expected_probe,
            learning_realization,
        )
        if expected_adjudication != document["adjudication"]:
            raise ContractError("adjudication 必须由当前兑现检查、冷读和页面探针派生")
    if document.get("schema_version") == "1.3":
        review = _current_blind_review_record(run_dir)
        expected_source = _blind_review_source(run_dir, review)
        if document["blind_review_source"] != expected_source:
            raise ContractError("CUMCM_LAYOUT_AUDIT 未绑定当前独立盲评记录和任务身份")
        for field in (
            "cold_read",
            "structure",
            "argument_findings",
            "question_progression",
            "narrative_risks",
            "review_summary",
        ):
            if document[field] != review[field]:
                raise ContractError(f"CUMCM_LAYOUT_AUDIT.{field} 与独立盲评记录不一致")
        expected_verdict = (
            "pass"
            if review["verdict"] == "pass"
            and review["highest_severity"] not in {"P0", "P1"}
            else "rework"
        )
        if document["paper_review_verdict"] != expected_verdict:
            raise ContractError("CUMCM_LAYOUT_AUDIT 结论与独立盲评结论不一致")
    blockers = _review_blockers(run_dir, document)
    verdict = document["paper_review_verdict"]
    if verdict in {"pass", "conditional_pass"} and blockers:
        raise ContractError("论文评审结论与阻断项冲突: " + "；".join(blockers))
    if verdict == "rework" and not blockers and not document["narrative_risks"]:
        raise ContractError("rework 必须至少有一个具体阻断项或叙事风险")
    return blockers


def write_cumcm_paper_review_audit(run_dir: Path, payload: dict[str, Any]) -> Path:
    """从当前独立盲评派生论证事实，并追加本地呈现与学习检查。"""
    state = _require_cumcm_run(run_dir)
    if state["phase"] != "paper_review":
        raise ContractError("CUMCM 论证审计只能在 paper_review 阶段记录")
    require_cumcm_structure_map(run_dir)
    pdf = run_dir / "paper" / "final.pdf"
    if not pdf.is_file():
        raise ContractError("CUMCM 论证审计缺少 paper/final.pdf")
    schema_version = payload.get("schema_version", "1.3")
    if schema_version != "1.3":
        raise ContractError("新 v3.2 CUMCM 论证审计只能写入 1.3 同源盲评合同")
    forbidden_parallel_inputs = sorted(
        {
            "cold_read",
            "structure",
            "argument_depth",
            "argument_findings",
            "question_progression",
            "narrative_risks",
            "paper_review_verdict",
            "review_summary",
        }
        & set(payload)
    )
    if forbidden_parallel_inputs:
        raise ContractError(
            "CUMCM_LAYOUT_AUDIT 不再接受与独立盲评平行的作者判断: "
            + ", ".join(forbidden_parallel_inputs)
        )
    review = _current_blind_review_record(run_dir)
    paper_review_verdict = (
        "pass"
        if review["verdict"] == "pass" and review["highest_severity"] not in {"P0", "P1"}
        else "rework"
    )
    document = {
        "schema_name": "cumcm_layout_audit",
        "schema_version": schema_version,
        "run_id": run_dir.name,
        "reviewed_pdf_sha256": sha256_file(pdf),
        "blind_review_source": _blind_review_source(run_dir, review),
        "structure": review["structure"],
        "argument_findings": review["argument_findings"],
        "question_progression": review["question_progression"],
        "narrative_risks": review["narrative_risks"],
        "paper_review_verdict": paper_review_verdict,
        "review_summary": review["review_summary"],
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
        "overall_verdict": "rework" if paper_review_verdict == "rework" else "pending",
    }
    if schema_version == "1.3":
        realization = evaluate_presentation_contract(run_dir)
        if realization is None:
            raise ContractError(
                f"CUMCM_LAYOUT_AUDIT {schema_version} 需要 CUMCM_STRUCTURE_MAP 1.1 或 1.2"
            )
        cold_read = review["cold_read"]
        probe = probe_pdf_page_rhythm(pdf)
        document["authoring_realization"] = realization
        document["cold_read"] = cold_read
        document["presentation_probe"] = probe
        learning_realization = build_learning_realization(
            run_dir, payload.get("learning_checks")
        )
        document["learning_realization"] = learning_realization
        document["adjudication"] = _presentation_adjudication(
            state, realization, cold_read, probe, learning_realization
        )
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


def _object_value(value: Any) -> Any:
    """安全解引用 pypdf 的间接对象。"""
    getter = getattr(value, "get_object", None)
    return getter() if callable(getter) else value


def _visual_xobject_count(page: Any) -> int:
    """统计页面 Image/Form XObject，使位图和矢量插图都成为视觉锚点。"""
    try:
        resources = _object_value(page.get("/Resources", {}))
        xobjects = _object_value(resources.get("/XObject", {}))
        values = xobjects.values()
    except (AttributeError, KeyError, TypeError, ValueError):
        return 0
    count = 0
    for value in values:
        try:
            subtype = _object_value(value).get("/Subtype")
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if str(subtype) in {"/Image", "/Form"}:
            count += 1
    return count


def _consecutive_ranges(pages: list[int], *, minimum_length: int) -> list[dict[str, int]]:
    """把页码集合压缩为达到最小长度的连续区间。"""
    if not pages:
        return []
    ranges: list[dict[str, int]] = []
    start = previous = pages[0]
    for page in pages[1:]:
        if page == previous + 1:
            previous = page
            continue
        if previous - start + 1 >= minimum_length:
            ranges.append({"start": start, "end": previous})
        start = previous = page
    if previous - start + 1 >= minimum_length:
        ranges.append({"start": start, "end": previous})
    return ranges


def probe_pdf_page_rhythm(pdf_path: Path) -> dict[str, Any]:
    """生成不参与放行判定的 PDF 页面节奏机械探针。

    Args:
        pdf_path: 待检查的论文 PDF。

    Returns:
        文字密度、视觉锚点、图表集中度和 advisory 警告。
    """
    reader = PdfReader(str(pdf_path))
    metrics: list[dict[str, int]] = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except (KeyError, TypeError, ValueError):
            text = ""
        metrics.append(
            {
                "page": page_number,
                "text_characters": len(_normalized_text(text)),
                "visual_xobjects": _visual_xobject_count(page),
            }
        )
    dense_pages = [
        item["page"]
        for item in metrics
        if item["text_characters"] >= 1600 and item["visual_xobjects"] == 0
    ]
    visual_pages = [item["page"] for item in metrics if item["visual_xobjects"] > 0]
    figure_dense_pages = [
        item["page"] for item in metrics if item["visual_xobjects"] >= 2
    ]
    dense_ranges = _consecutive_ranges(dense_pages, minimum_length=2)
    figure_dense_ranges = _consecutive_ranges(figure_dense_pages, minimum_length=2)
    total_visuals = sum(item["visual_xobjects"] for item in metrics)
    midpoint = len(metrics) / 2
    late_visuals = sum(
        item["visual_xobjects"] for item in metrics if item["page"] > midpoint
    )
    back_loaded = total_visuals >= 3 and late_visuals / total_visuals >= 0.7
    warnings: list[str] = []
    for item in dense_ranges:
        warnings.append(
            f"PRESENTATION-W01 第{item['start']}至{item['end']}页连续高文字密度且无图像或矢量图锚点"
        )
    first_visual = visual_pages[0] if visual_pages else None
    if first_visual is None:
        warnings.append("PRESENTATION-W02 PDF 未检测到 Image/Form 视觉锚点")
    elif first_visual > 5:
        warnings.append(f"PRESENTATION-W02 首个视觉锚点位于第{first_visual}页，建议检查前部数据直觉")
    if back_loaded:
        warnings.append("PRESENTATION-W03 至少 70% 的视觉锚点集中在后半篇，建议检查图表是否后置")
    return {
        "advisory_only": True,
        "pdf_total_pages": len(metrics),
        "page_metrics": metrics,
        "dense_text_page_ranges": dense_ranges,
        "visual_anchor_pages": visual_pages,
        "first_visual_page": first_visual,
        "figure_dense_page_ranges": figure_dense_ranges,
        "back_loaded_visual_concentration": back_loaded,
        "warnings": warnings,
    }


def _presentation_adjudication(
    state: dict[str, Any],
    realization: dict[str, Any],
    cold_read: dict[str, Any],
    probe: dict[str, Any],
    learning_realization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """从本地兑现、PDF 冷读和机械探针派生最小阻断与告警。"""
    blocking = [f"呈现合同未兑现: {item}" for item in realization["blockers"]]
    answers = cold_read.get("direct_answers_found_within_3_minutes", {})
    for question_id in state["required_questions"]:
        if answers.get(question_id) is not True:
            blocking.append(f"三分钟内未找到 {question_id} 的直接答案")
    advisory = [f"呈现合同建议项未兑现: {item}" for item in realization["warnings"]]
    if cold_read.get("cross_question_inheritance_understood") is not True:
        advisory.append("PDF 冷读未能复述跨问题继承关系")
    if cold_read.get("first_five_pages_establish_data_intuition") is not True:
        advisory.append("PDF 前五页尚未建立清楚的数据直觉")
    unidentified = [
        question_id
        for question_id, found in cold_read.get("hero_figures_identified", {}).items()
        if found is not True
    ]
    if unidentified:
        advisory.append("冷读未能识别主图的问题: " + ", ".join(sorted(unidentified)))
    if cold_read.get("report_like_pages"):
        advisory.append("冷读认为部分页面具有工作报告感")
    if learning_realization is not None:
        for item in learning_realization["checks"]:
            if item["pdf_realization"] != "pass":
                advisory.append(
                    "论文卡迁移模式未完全兑现: "
                    f"{item['pattern_id']} ({item['pdf_realization']})"
                )
    advisory.extend(probe["warnings"])
    return {
        "status": "rework" if blocking else "pass",
        "blocking_findings": blocking,
        "advisory_findings": advisory,
    }


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
    record_layout_audit(
        run_dir, render_revision=int(state.get("paper_render_revision", 0))
    )
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
    state = read_simple_state(run_dir)
    render_revision = int(state.get("paper_render_revision", 0))
    if int(state.get("layout_audited_revision", 0)) != render_revision:
        raise ContractError("CUMCM 综合审计未覆盖当前论文渲染修订")
    return document
