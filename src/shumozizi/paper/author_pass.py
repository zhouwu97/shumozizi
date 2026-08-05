"""准备长篇论文 Author Pass，并把创作输入与科学证据隔离。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.paper.policy import formal_result_digest
from shumozizi.paper.templates import require_materialized_template
from shumozizi.simple.state import read_simple_state, utc_now

AUTHOR_PASS_DIR = Path("paper/author-pass")
RESEARCH_PACKAGE_PATH = AUTHOR_PASS_DIR / "RESEARCH_PACKAGE.md"
AUTHOR_BRIEF_PATH = AUTHOR_PASS_DIR / "AUTHOR_BRIEF.md"
AUTHOR_PASS_MANIFEST_PATH = AUTHOR_PASS_DIR / "manifest.json"
AUTHOR_GAPS_PATH = Path("paper/AUTHOR_GAPS.md")
INTERNAL_AUTHOR_REQUESTS_PATH = Path("paper/AUTHOR_REQUESTS.json")
NARRATIVE_COMPETITION_PATH = Path("paper/generated/narrative-competition.json")

_BLOCKING_SCIENTIFIC_ACTIONS = frozenset(
    {"MODEL_REPAIR", "OBJECTIVE_REDESIGN", "ANSWER_REJECTION"}
)
_AUTHOR_MATERIAL_PRIORITIES = {
    "direct answer": 0,
    "mathematical derivation": 1,
    "mechanism": 2,
    "structural insight": 2,
    "boundary/robustness": 3,
    "validation": 4,
}


def _atomic_text(path: Path, value: str) -> None:
    """原子写入作者材料，避免半成品被 Author 读取。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _optional_json(root: Path, relative: str) -> dict[str, Any]:
    """读取可选后台材料；缺失时返回空对象。"""
    path = root / relative
    if not path.is_file():
        return {}
    try:
        value = load_json(path)
    except (ContractError, OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _answer_map(root: Path) -> dict[str, Any]:
    """读取正式答案映射，并要求每问绑定 current production 结果。"""
    path = root / "paper/answer-map.json"
    if not path.is_file():
        path = root / "analysis/answer_map.json"
    if not path.is_file():
        raise ContractError("Author Pass 缺少正式 answer-map")
    payload = load_json(path)
    answers = payload.get("answers", payload)
    if not isinstance(answers, dict):
        raise ContractError("answer-map 必须按问题提供答案映射")
    return answers


def _singleton_answer_map(
    state: dict[str, Any], results: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """为旧运行从每问唯一 current production 结果构造兼容答案映射。

    该回退只供 external handoff 使用。存在多个候选时拒绝猜测，避免把
    recommended plan 或任意 current 结果误当作正式答案。
    """
    answers: dict[str, Any] = {}
    for question_id in state.get("required_questions", []):
        candidates = [
            result_id
            for result_id, result in results.items()
            if result.get("question_id") == question_id
        ]
        if len(candidates) != 1:
            raise ContractError(
                f"Author Pass 缺少 {question_id} 的正式 answer-map，且 current production "
                f"候选数为 {len(candidates)}"
            )
        answers[question_id] = {
            "primary_result_id": candidates[0],
            "result_ids": candidates,
        }
    return answers


def _current_results(root: Path) -> dict[str, dict[str, Any]]:
    """只返回可写入论文的 current production 结果。"""
    index = load_json(root / "results/index.json")
    return {
        str(item["result_id"]): item
        for item in index.get("results", [])
        if isinstance(item, dict)
        and isinstance(item.get("result_id"), str)
        and item.get("status") == "current"
        and item.get("execution_mode") == "production"
        and item.get("execution_valid") is True
        and item.get("paper_allowed", True) is not False
    }


def _validate_scientific_inputs(
    state: dict[str, Any], answers: dict[str, Any], results: dict[str, dict[str, Any]]
) -> None:
    """保证作者拿到的是正式答案，而不是推荐层或失效结果。"""
    errors: list[str] = []
    for question_id in state.get("required_questions", []):
        item = answers.get(question_id)
        if not isinstance(item, dict):
            errors.append(f"{question_id} 缺少正式答案映射")
            continue
        primary = item.get("primary_result_id")
        result_ids = item.get("result_ids", [])
        if not isinstance(primary, str) or primary not in results:
            errors.append(f"{question_id} 的 primary_result_id 不是 current production 结果")
        if not isinstance(result_ids, list) or primary not in result_ids:
            errors.append(f"{question_id} 的 primary_result_id 未列入 result_ids")
        objective = item.get("objective_answer")
        if not isinstance(objective, dict):
            errors.append(f"{question_id} 缺少正式 objective_answer")
        elif objective.get("result_id") != primary:
            errors.append(f"{question_id} 的 objective_answer 未绑定 primary_result_id")
    if errors:
        raise ContractError("Author Pass 科学输入未就绪: " + "；".join(errors))


def scientific_authoring_readiness(
    run_dir: Path,
    *,
    state: dict[str, Any] | None = None,
    answers: dict[str, Any] | None = None,
    results: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """检查开始正式写作所需的最小科学事实层。

    该门只复验正式答案、current production 绑定和科学挑战结论。素材池、
    Storyboard、Figure Plan、蓝图、篇幅与叙事选择均不属于此处的阻断条件。

    Args:
        run_dir: 当前运行目录。
        state: 已读取的运行状态，省略时现场读取。
        answers: 已合并的正式答案映射，省略时现场读取。
        results: 已筛选的 current production 结果，省略时现场读取。

    Returns:
        包含 ``ready``、``errors`` 与科学挑战摘要的检查结果。
    """
    root = run_dir.resolve()
    current_state = state or read_simple_state(root)
    current_answers = answers or _answer_map(root)
    current_results = results or _current_results(root)
    errors: list[str] = []
    try:
        _validate_scientific_inputs(current_state, current_answers, current_results)
    except ContractError as exc:
        errors.append(str(exc))

    from shumozizi.simple.review_focus import verify_scientific_challenge_evidence

    challenge = verify_scientific_challenge_evidence(root)
    if not challenge.get("valid"):
        errors.extend(
            f"科学挑战未关闭: {message}" for message in challenge.get("errors", [])
        )
    else:
        findings = challenge.get("evidence", {}).get("findings", [])
        for finding in findings if isinstance(findings, list) else []:
            if not isinstance(finding, dict) or finding.get("status") != "open":
                continue
            severity = str(finding.get("severity", ""))
            action = str(finding.get("action_type", ""))
            if severity in {"P0", "P1"} or action in _BLOCKING_SCIENTIFIC_ACTIONS:
                errors.append(
                    f"科学发现 {finding.get('finding_id', 'unknown')} 尚未关闭"
                    f"（{severity}/{action}）"
                )
    return {
        "ready": not errors,
        "errors": errors,
        "challenge_valid": bool(challenge.get("valid")),
    }


def require_scientific_authoring_ready(
    run_dir: Path,
    *,
    state: dict[str, Any] | None = None,
    answers: dict[str, Any] | None = None,
    results: dict[str, dict[str, Any]] | None = None,
) -> None:
    """要求最小科学事实层就绪，但不检查任何创作控制文件。"""
    status = scientific_authoring_readiness(
        run_dir,
        state=state,
        answers=answers,
        results=results,
    )
    if not status["ready"]:
        raise ContractError("Author 科学输入未就绪: " + "；".join(status["errors"]))


def _modeling_units(root: Path) -> dict[str, Any]:
    """读取建模合同，供作者上下文压缩；缺失时保留轻量兼容。"""
    return _optional_json(root, "analysis/MODELING_UNITS.json")


def _units_by_question(modeling: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """按问题提取建模单元，优先保留带答案合同的单元。"""
    mapped: dict[str, dict[str, Any]] = {}
    for raw in modeling.get("units", []):
        if not isinstance(raw, dict):
            continue
        question_id = raw.get("question_id")
        if not isinstance(question_id, str):
            continue
        if question_id not in mapped or raw.get("answer_contract"):
            mapped[question_id] = raw
    return mapped


def _selected_materials(root: Path) -> dict[str, list[dict[str, Any]]]:
    """只选择直接答案和高价值论证素材，避免把完整素材池重新塞给 Author。"""
    pool = _optional_json(root, "paper/generated/material_pool.json")
    selected: dict[str, list[dict[str, Any]]] = {}
    for raw in pool.get("items", []):
        if not isinstance(raw, dict) or raw.get("status", "current") != "current":
            continue
        category = str(raw.get("category", "")).strip().casefold()
        if category not in _AUTHOR_MATERIAL_PRIORITIES:
            continue
        question_id = str(raw.get("question_id", "global"))
        selected.setdefault(question_id, []).append(raw)
    for items in selected.values():
        items.sort(
            key=lambda item: (
                _AUTHOR_MATERIAL_PRIORITIES[
                    str(item.get("category", "")).strip().casefold()
                ],
                str(item.get("title", "")),
            )
        )
        del items[4:]
    return selected


def _formal_answer_text(
    question_id: str,
    answer: dict[str, Any],
    result: dict[str, Any],
    unit: dict[str, Any],
    materials: list[dict[str, Any]],
) -> str:
    """提取可直接写入正文的自然语言答案，标量指标只作为最后回退。"""
    primary = str(answer["primary_result_id"])
    for item in materials:
        if str(item.get("category", "")).strip().casefold() != "direct answer":
            continue
        source_ids = item.get("source_result_ids", [])
        content = str(item.get("content", "")).strip()
        if content and (not source_ids or primary in source_ids):
            return content
    objective = answer.get("objective_answer", {})
    for source in (objective, answer, result, unit.get("actual", {})):
        if not isinstance(source, dict):
            continue
        for field in ("answer", "direct_answer", "summary", "value"):
            value = source.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
    metrics = result.get("metrics", {})
    if isinstance(metrics, dict) and metrics:
        visible = [
            f"{key}={value}"
            for key, value in metrics.items()
            if key not in {"runtime_seconds", "seed"}
        ]
        if visible:
            return f"在当前题面口径和硬约束下，{question_id} 的正式结果为" + "，".join(
                visible[:6]
            ) + "。"
    return "当前正式结果未提供可直接引用的自然语言答案；Author 必须提出返工请求。"


def _citation_brief(root: Path) -> list[str]:
    """把已核验引用及用途边界压缩为 Research Package 小节。"""
    coverage = _optional_json(root, "paper/generated/citation_coverage.json")
    bindings = coverage.get("plan_bindings", [])
    lines = ["## 可用文献", ""]
    if isinstance(bindings, list) and bindings:
        for item in bindings:
            if not isinstance(item, dict) or not str(item.get("key", "")).strip():
                continue
            source = str(item.get("source", "")).strip()
            claim = str(item.get("claim", "")).strip()
            location = str(item.get("location", "")).strip()
            detail = source or "已在参考文献中登记"
            boundary = claim or "只用于其方法或背景的基本说明"
            suffix = f"；建议位置：{location}" if location else ""
            lines.append(f"- [{item['key']}] {detail}；允许用于：{boundary}{suffix}")
    else:
        keys = coverage.get("bibliography_keys", [])
        if isinstance(keys, list) and keys:
            lines.append("- 已登记引用键：" + "、".join(map(str, keys)))
            lines.append("- 缺少逐条用途边界时不得自行扩展这些文献支持的主张。")
        else:
            lines.append("- 当前没有已登记文献；Author 不得自行补造引用。")
    lines.extend(["", "文献不能替代当前模型、结果、图表或 exact scorer 证据。", ""])
    return lines


def _visual_requirement_brief(root: Path) -> list[str]:
    """把论文驱动视觉需求压缩为 Author 可读提示，不暴露后台台账。"""
    payload = _optional_json(root, "paper/generated/VISUAL_REQUIREMENTS.json")
    requirements = payload.get("requirements", [])
    lines = ["## 论文驱动视觉需求", ""]
    if not isinstance(requirements, list) or not requirements:
        lines.extend(
            [
                "- 当前论证没有识别出必须新增的视觉需求；这不构成固定图数目标。",
                "",
            ]
        )
        return lines
    for item in requirements:
        if not isinstance(item, dict):
            continue
        status = "已有正式图覆盖" if item.get("status") == "covered" else "需要视觉评估"
        tier = "主图候选" if item.get("figure_tier") == "hero_figure" else "论证支持图"
        lines.append(
            f"- {item.get('question_id', '')} / {tier} / {status}："
            f"{item.get('visual_question', '')}"
        )
    lines.extend(
        [
            "",
            "主图只保留最值得记忆的少数视觉；论证支持图按推导、机制、比较和边界的实际需要增加，不设总数上限。",
            "",
        ]
    )
    return lines


def _selected_narrative(root: Path, package_sha256: str) -> dict[str, Any]:
    """返回仍绑定当前 Research Package 的已选叙事候选。"""
    payload = _optional_json(root, NARRATIVE_COMPETITION_PATH.as_posix())
    if (
        payload.get("status") != "reviewed"
        or payload.get("research_package_sha256") != package_sha256
    ):
        return {}
    selected_id = payload.get("selected_candidate_id")
    for candidate in payload.get("candidates", []):
        if isinstance(candidate, dict) and candidate.get("candidate_id") == selected_id:
            return {
                **candidate,
                "selection_reason": payload.get("selection_reason", ""),
                "revision_advice": payload.get("revision_advice", ""),
            }
    return {}


def _render_research_package(
    root: Path,
    state: dict[str, Any],
    answers: dict[str, Any],
    results: dict[str, dict[str, Any]],
) -> str:
    """把后台证据投影成不含哈希和控制台账的作者材料。"""
    modeling = _modeling_units(root)
    units = _units_by_question(modeling)
    selected_materials = _selected_materials(root)
    story = modeling.get("research_story", {})
    lines = [
        "# RESEARCH PACKAGE",
        "",
        "本文件只包含可用于写作的当前研究事实。运行状态、哈希、回执、工具探测和完整搜索轨迹不进入作者上下文。",
        "",
        "## 题面与必答合同",
        "",
    ]
    for question_id in state.get("required_questions", []):
        answer = answers[question_id]
        result = results[str(answer["primary_result_id"])]
        unit = units.get(question_id, {})
        contract = unit.get("answer_contract", {})
        delta = unit.get("question_delta", {})
        lines.extend([f"### {question_id}", ""])
        required_output = str(contract.get("required_output", "")).strip()
        decision_scope = str(contract.get("decision_scope", "")).strip()
        if required_output:
            lines.append(f"- 必须回答：{required_output}")
        else:
            lines.append(f"- 必须回答：给出 {question_id} 的正式结果与可执行输出。")
        if decision_scope:
            lines.append(f"- 决策对象与总体：{decision_scope}")
        inherits = delta.get("inherits_from")
        changed = [
            *delta.get("added_entities", []),
            *delta.get("added_resources", []),
            *delta.get("changed_constraints", []),
        ] if isinstance(delta, dict) else []
        if inherits or changed:
            prefix = f"继承 {inherits}" if inherits else "本问首次建立对象"
            suffix = "；新增 " + "、".join(map(str, changed)) if changed else ""
            lines.append(f"- 相邻问题变化：{prefix}{suffix}")
        location = answer.get("direct_answer_location")
        if isinstance(location, str) and location.strip():
            lines.append(f"- 直接答案建议位置：{location.strip()}")
        lines.append("")

    lines.extend(["## 共享数学对象、符号与必要假设", ""])
    central_tension = str(story.get("central_tension", "")).strip()
    central_object = str(story.get("central_mathematical_object", "")).strip()
    if central_tension:
        lines.append(f"- 中心矛盾：{central_tension}")
    if central_object:
        lines.append(f"- 共享数学对象：{central_object}")
    for question_id in state.get("required_questions", []):
        unit = units.get(question_id, {})
        endpoint = unit.get("answer_contract", {}).get("primary_endpoint", {})
        if not isinstance(endpoint, dict):
            continue
        definition = str(endpoint.get("definition", "")).strip()
        formula = str(endpoint.get("formula", "")).strip()
        if definition or formula:
            lines.append(
                f"- {question_id} 主判据：{definition}"
                + (f"；公式：{formula}" if formula else "")
            )
    if not central_tension and not central_object and not units:
        lines.append("- 当前没有结构化建模合同；Author 必须请求补充题意、符号与必要假设，不能自行猜测。")
    lines.append("")

    lines.extend(["## 逐问正式答案", ""])
    for question_id in state.get("required_questions", []):
        answer = answers[question_id]
        result = results[str(answer["primary_result_id"])]
        materials = selected_materials.get(question_id, [])
        lines.extend(
            [
                f"### {question_id}",
                "",
                _formal_answer_text(
                    question_id,
                    answer,
                    result,
                    units.get(question_id, {}),
                    materials,
                ),
                "",
            ]
        )
        metrics = result.get("metrics", {})
        if isinstance(metrics, dict) and metrics:
            visible = [
                f"{key}={value}"
                for key, value in metrics.items()
                if key not in {"runtime_seconds", "seed"}
            ]
            if visible:
                lines.extend(["核心数字：" + "；".join(visible[:8]), ""])

    lines.extend(["## 关键推导、机制与边界", ""])
    substantive = False
    for question_id in state.get("required_questions", []):
        materials = [
            item
            for item in selected_materials.get(question_id, [])
            if str(item.get("category", "")).strip().casefold() != "direct answer"
        ]
        if not materials:
            continue
        substantive = True
        lines.extend([f"### {question_id}", ""])
        for item in materials:
            title = str(item.get("title", item.get("category", "研究素材"))).strip()
            content = str(item.get("content", "")).strip()
            if content:
                lines.extend([f"**{title}**", "", content, ""])
    if not substantive:
        lines.extend(["当前没有已登记的关键推导或机制材料；Author 应提出返工请求，不得用结果报账替代论证。", ""])

    lines.extend(_visual_requirement_brief(root))

    figures = _optional_json(root, "figures/index.json").get("figures", [])
    lines.extend(["## 可用正式图", ""])
    current_figures = [
        item for item in figures if isinstance(item, dict) and item.get("status") == "current"
    ] if isinstance(figures, list) else []
    if current_figures:
        for item in current_figures:
            outputs = [
                record.get("path")
                for record in item.get("outputs", [])
                if isinstance(record, dict) and isinstance(record.get("path"), str)
            ]
            lines.append(
                f"- {item.get('figure_id', '')}: {item.get('takeaway', item.get('question', ''))}"
                + (f"（{', '.join(outputs)}）" if outputs else "")
            )
    else:
        lines.append("- 当前没有已晋级图；可在 Visual Sandbox 中提出候选，不得在正文引用未晋级草图。")
    lines.append("")

    gate = _optional_json(root, "paper/claim_gate.json")
    lines.extend(["## 主张边界", ""])
    claims = gate.get("claims", [])
    if isinstance(claims, list) and claims:
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            lines.append(
                f"- {claim.get('question_id', '')}: {claim.get('reason', '')}"
                f"；允许用途 {', '.join(map(str, claim.get('allowed_uses', [])))}"
            )
    else:
        lines.append("- 不得使用全局最优、唯一、显著、鲁棒、必然等强度词，除非当前证据明确授权。")
    lines.extend([""])
    lines.extend(_citation_brief(root))
    lines.extend([
        "## 作者返工权",
        "",
        "若材料只能形成结果报账，Author 应在 AUTHOR_GAPS.md 指出缺少的推导、机制、反事实、视觉或科学证据；不得自行创造结果。",
        "",
    ])
    return "\n".join(lines)


def _render_author_brief(
    state: dict[str, Any],
    inspiration: dict[str, Any],
    narrative: dict[str, Any] | None = None,
) -> str:
    """生成不暴露 Reviewer checklist 的自由写作任务。"""
    lines = [
            "# AUTHOR BRIEF",
            "",
            f"为运行 {state['run_id']} 撰写完整数学建模竞赛论文。",
            "",
            "先写完整科学论文，不以当前页数、章节数或图数为目标。可以合并问题、重排章节、展开推导、改变图文节奏和叙事焦点。",
            "",
            "正式答案、数字、题意语义和主张边界不可擅自修改。若无法解释结果或缺少必要对照、机制、图或证据，应提出返工请求。",
            "",
            "不要把审核清单、内部结果编号、回执、哈希、工作流阶段或工具探测写入正文。",
            "",
            "输出 paper/longform-source.tex（或 Typst 对应文件）以及 paper/AUTHOR_GAPS.md。",
            "",
        ]
    if narrative:
        lines.extend(
            [
                "## 本轮选中的叙事方向",
                "",
                f"中心主线：{narrative.get('central_thread', '')}",
                "",
                "推荐阅读顺序：" + " → ".join(map(str, narrative.get("section_flow", []))),
                "",
                f"评委应记住的核心：{narrative.get('memorable_takeaway', '')}",
                "",
                "Reviewer 认为的主要风险："
                + "；".join(map(str, narrative.get("risks", []))),
                "",
                f"选择理由：{narrative.get('selection_reason', '')}",
                "",
                f"修订建议：{narrative.get('revision_advice', '')}",
                "",
                "该方向只提供组织建议。Author 可以局部偏离，但应说明为何新的组织更强。",
                "",
            ]
        )
    cards = inspiration.get("cards", [])
    if cards:
        lines.extend(["## 表达启发", ""])
        for card in cards:
            lines.append(f"### {card['title']}")
            lines.append("")
            for observation in card.get("observations", []):
                lines.append(f"- {observation['lesson']}")
            lines.append("")
        lines.append("这些卡只允许学习表达方法，不得迁移原题事实、数据、公式、引用或结论。")
        lines.append("")
    return "\n".join(lines)


def prepare_longform_author(
    run_dir: Path,
    *,
    require_template: bool = True,
    allow_unmapped_singletons: bool = False,
    answer_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """生成 Author Pass 输入包，不代替 Author 撰写正文。

    Args:
        run_dir: 当前运行目录。
        require_template: 是否要求正式论文模板已物化。内部 longform 写作需要
            确定源文件类型；外部交接只投影科学材料，可以在选模板前准备。
        allow_unmapped_singletons: 是否允许旧运行在每问恰有一个 current
            production 结果时构造兼容答案映射。存在歧义时仍拒绝生成。
        answer_overrides: 外部 handoff 已从正式逐问结果投影得到的答案映射。
            该映射仍会经过 current production 与 primary/result_ids 一致性复验。
    """
    root = run_dir.resolve()
    state = read_simple_state(root)
    if require_template:
        engine = require_materialized_template(root)["engine"]
    else:
        try:
            engine = require_materialized_template(root)["engine"]
        except ContractError:
            # 外部交接包与排版引擎无关；默认值只用于 manifest 的兼容字段。
            engine = "latex"
    results = _current_results(root)
    try:
        answers = _answer_map(root)
    except ContractError:
        if not allow_unmapped_singletons and not answer_overrides:
            raise
        answers = {}
    if answer_overrides:
        for question_id, override in answer_overrides.items():
            merged = dict(answers.get(question_id, {}))
            merged.update(override)
            answers[question_id] = merged
    missing = [
        question_id
        for question_id in state.get("required_questions", [])
        if not isinstance(answers.get(question_id), dict)
    ]
    if missing and allow_unmapped_singletons:
        singleton_answers = _singleton_answer_map(
            {**state, "required_questions": missing}, results
        )
        answers.update(singleton_answers)
    require_scientific_authoring_ready(
        root,
        state=state,
        answers=answers,
        results=results,
    )
    package_path = root / RESEARCH_PACKAGE_PATH
    brief_path = root / AUTHOR_BRIEF_PATH
    from shumozizi.knowledge.inspiration import build_inspiration_context

    inspiration = build_inspiration_context(root)
    from shumozizi.paper.visual_requirements import (
        VISUAL_REQUIREMENTS_PATH,
        build_visual_requirements_from_paper,
    )

    visual_requirements = build_visual_requirements_from_paper(
        root,
        sync_opportunities=False,
    )
    _atomic_text(package_path, _render_research_package(root, state, answers, results))
    narrative = _selected_narrative(root, sha256_file(package_path))
    _atomic_text(brief_path, _render_author_brief(state, inspiration, narrative))
    gaps = root / AUTHOR_GAPS_PATH
    if not gaps.is_file():
        _atomic_text(gaps, "# AUTHOR GAPS\n\n当前未登记写作返工请求。\n")
    payload = {
        "schema_name": "author_pass_manifest",
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "engine": engine,
        "research_package": {
            "path": RESEARCH_PACKAGE_PATH.as_posix(),
            "sha256": sha256_file(package_path),
        },
        "author_brief": {
            "path": AUTHOR_BRIEF_PATH.as_posix(),
            "sha256": sha256_file(brief_path),
        },
        "visual_requirements": {
            "path": VISUAL_REQUIREMENTS_PATH.as_posix(),
            "sha256": sha256_file(root / VISUAL_REQUIREMENTS_PATH),
            "open_count": visual_requirements["summary"]["open"],
        },
        "formal_result_digest": formal_result_digest(root),
        "prepared_at": utc_now(),
    }
    atomic_json(root / AUTHOR_PASS_MANIFEST_PATH, payload)
    return payload


def finalize_author_brief(run_dir: Path) -> dict[str, Any]:
    """把当前 Narrative winner 写回 Author Brief，并刷新 manifest 哈希。"""
    root = run_dir.resolve()
    manifest = require_author_pass(root)
    package_path = root / RESEARCH_PACKAGE_PATH
    narrative = _selected_narrative(root, sha256_file(package_path))
    if not narrative:
        raise ContractError("Narrative Competition 尚未选出绑定当前 Research Package 的候选")
    from shumozizi.knowledge.inspiration import build_inspiration_context

    brief_path = root / AUTHOR_BRIEF_PATH
    _atomic_text(
        brief_path,
        _render_author_brief(
            read_simple_state(root),
            build_inspiration_context(root),
            narrative,
        ),
    )
    manifest["author_brief"]["sha256"] = sha256_file(brief_path)
    manifest["prepared_at"] = utc_now()
    atomic_json(root / AUTHOR_PASS_MANIFEST_PATH, manifest)
    return manifest


def verify_author_pass(run_dir: Path) -> dict[str, Any]:
    """复验 Author Pass 与当前正式结果是否一致。"""
    root = run_dir.resolve()
    errors: list[str] = []
    try:
        payload = load_json(root / AUTHOR_PASS_MANIFEST_PATH)
        for field in ("research_package", "author_brief"):
            record = payload[field]
            path = root / record["path"]
            if not path.is_file() or record.get("sha256") != sha256_file(path):
                errors.append(f"{field} 已变化或缺失")
        visual = payload.get("visual_requirements")
        if isinstance(visual, dict):
            visual_path = root / "paper/generated/VISUAL_REQUIREMENTS.json"
            if not visual_path.is_file() or visual.get("sha256") != sha256_file(visual_path):
                errors.append("visual_requirements 已变化或缺失")
        if payload.get("formal_result_digest") != formal_result_digest(root):
            errors.append("正式结果已变化，Author Pass 必须重建")
    except (ContractError, KeyError, OSError, TypeError, ValueError) as exc:
        payload = None
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors, "manifest": payload}


def require_author_pass(run_dir: Path) -> dict[str, Any]:
    """要求 Author Pass 当前，并返回 manifest。"""
    status = verify_author_pass(run_dir)
    if not status["valid"]:
        raise ContractError("Author Pass 无效: " + "；".join(status["errors"]))
    return dict(status["manifest"])
