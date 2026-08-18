"""准备长篇论文 Author Pass，并把创作输入与科学证据隔离。"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.paper.policy import formal_result_digest
from shumozizi.paper.templates import require_materialized_template
from shumozizi.simple.modeling_units import _SUBSTANTIVE_INSIGHT_KINDS
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
    "model rationale": 1,
    "structural observation": 2,
    "structural insight": 2,
    "mechanism": 2,
    "intermediate result": 3,
    "baseline/contrast": 3,
    "illustrative case": 3,
    "boundary/robustness": 4,
    "validation": 4,
    "negative finding": 5,
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
        and item.get("scientific_status", "valid") != "invalidated"
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
    """选择高价值论证素材并按科学功能去重，不进行机械数量截断。"""
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
    for question_id, items in selected.items():
        # 语义功能去重：同类别且文本高度重复的内容去重，保留差异化推导、机制与反例
        deduped: list[dict[str, Any]] = []
        seen_signatures: set[tuple[str, str]] = set()
        for item in items:
            cat = str(item.get("category", "")).strip().casefold()
            content = str(item.get("content", "")).strip()
            norm_content = re.sub(r"\s+", "", content)
            sig = (cat, hashlib.sha256(norm_content.encode("utf-8")).hexdigest())
            if sig in seen_signatures:
                continue
            seen_signatures.add(sig)
            deduped.append(item)
        deduped.sort(
            key=lambda item: (
                _AUTHOR_MATERIAL_PRIORITIES[
                    str(item.get("category", "")).strip().casefold()
                ],
                str(item.get("title", "")),
            )
        )
        selected[question_id] = deduped
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


# 机制类 insight 才是"为什么答案是这个结构"的论证来源；与
# shumozizi.simple.modeling_units 的核心问题实质规律要求保持一致。
# （_SUBSTANTIVE_INSIGHT_KINDS 从 modeling_units 导入，保持单一事实来源）


def _warrant_sources(unit: dict[str, Any]) -> list[str]:
    """从建模单元的结构化 insight 提取 warrant 候选（机制类优先）。

    warrant = 为什么这些 evidence 能推出这个 claim。核心问题在进入论文前
    已被 modeling_units 校验强制拥有机制/边际收益/活跃约束/权衡类 insight，
    其 mechanism 字段正是论证桥梁的现成种子；这里只做提取与排序，让 Author
    判断与改写，而不是从零写。

    Args:
        unit: 单个建模单元（含 ``actual.insights``）。

    Returns:
        去重后的 mechanism 文本列表，机制类优先；无 insight 时为空列表。
    """
    actual = unit.get("actual")
    if not isinstance(actual, dict):
        return []
    insights = actual.get("insights")
    if not isinstance(insights, list):
        return []
    substantive: list[str] = []
    others: list[str] = []
    for insight in insights:
        if not isinstance(insight, dict):
            continue
        mechanism = str(insight.get("mechanism", "")).strip()
        if not mechanism:
            continue
        if str(insight.get("kind", "")) in _SUBSTANTIVE_INSIGHT_KINDS:
            substantive.append(mechanism)
        else:
            others.append(mechanism)
    return list(dict.fromkeys([*substantive, *others]))


def _support_strength(answer: dict[str, Any]) -> str:
    """把 objective_answer 的 claim_level 翻译成 Author 可读的支持强度。

    Args:
        answer: 逐问答案映射（含 ``objective_answer.claim_level``）。

    Returns:
        支持强度一句话；缺少 claim_level（如旧运行）时返回空串。
    """
    objective = answer.get("objective_answer")
    if not isinstance(objective, dict):
        return ""
    level = str(objective.get("claim_level", "")).strip()
    if not level:
        return ""
    label = {
        "optimal": "已确认全局最优证书（optimal）。",
        "best_found": "当前最优（best_found，无全局证书，不得写成全局最优）。",
        "feasible": "当前可行解（feasible，相对 baseline 改善不足）。",
    }.get(level)
    return label or level


def _decision_advice(unit: dict[str, Any]) -> dict[str, str] | None:
    """提取决策单元的不可行域决策合同。

    决策题（优化/协同）问的是"怎么办"：严格结果之外还必须给出备用决策、
    可达可靠度、复检策略与可靠性敏感性，否则等于把决策责任甩回给评委。
    只有声明了 ``infeasible_policy`` 的单元才渲染决策建议，避免普通问套模板。

    Args:
        unit: 单个建模单元（含 ``answer_contract.infeasible_policy``）。

    Returns:
        非空决策字段字典；非决策单元返回 ``None``。
    """
    contract = unit.get("answer_contract")
    if not isinstance(contract, dict):
        return None
    policy = contract.get("infeasible_policy")
    if not isinstance(policy, dict) or not policy:
        return None
    advice = {
        key: str(policy.get(key, "")).strip()
        for key in (
            "strict_result",
            "fallback_decision",
            "fallback_attained_reliability",
            "retest_strategy",
            "reliability_sensitivity",
        )
    }
    return advice if any(advice.values()) else None


def _decision_advice_lines(advice: dict[str, str]) -> list[str]:
    """把决策合同渲染成逐行决策建议。"""
    lines = ["- 决策建议（该问为决策题）：", ""]
    strict = advice.get("strict_result")
    fallback = advice.get("fallback_decision")
    attained = advice.get("fallback_attained_reliability")
    retest = advice.get("retest_strategy")
    sensitivity = advice.get("reliability_sensitivity")
    if strict:
        lines.append(f"  - 严格答案：{strict}")
    if fallback:
        suffix = f"（可达可靠度：{attained}）" if attained else ""
        lines.append(f"  - 严格目标不可行时的备用决策：{fallback}{suffix}")
    if retest:
        lines.append(f"  - 复检策略：{retest}")
    if sensitivity:
        lines.append(f"  - 敏感性边界（何时不适用当前推荐）：{sensitivity}")
    lines.append("")
    return lines


def _argument_chain_lines(
    question_id: str,
    unit: dict[str, Any],
    answer: dict[str, Any],
) -> list[str]:
    """渲染单问论证链：warrant + 支持强度 + 决策建议。

    主要主张已经在"逐问正式答案"中给出，这里不重复主张文本，只补上
    "为什么证据支持结论"与"推荐什么"，避免上下文膨胀。
    """
    warrants = _warrant_sources(unit)
    support = _support_strength(answer)
    decision = _decision_advice(unit)
    if not warrants and not support and not decision:
        return []
    lines = [f"### {question_id}", ""]
    if warrants:
        lines.append(f"- 论证理由（为什么这些证据支持上述正式答案）：{warrants[0]}")
        for extra in warrants[1:]:
            lines.append(f"  - {extra}")
    if support:
        lines.append(f"- 支持强度：{support}")
    if decision:
        lines.extend(_decision_advice_lines(decision))
    lines.append("")
    return lines


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
    """把已就绪的 current 正式图压缩为 Author 必须引用的资产清单。

    与旧版的关键区别：不再把视觉状态写成"需求需要视觉评估"（会误导 Author
    以为图还没生成），而是列出 figures/index.json 中 status=current 的正式图、
    它们在正文可直接引用的 ``\\includegraphics`` 相对路径（从 paper/ 出发），
    并给出要求：正文必须引用其中的关键图，每张配图号与图注，并在正文中完成
    '观察 → 机制 → 结论' 的完整三步论证。
    """
    lines = ["## 已就绪正式图（必须引用，并在正文完成观察—机制—结论）", ""]
    figures = _optional_json(root, "figures/index.json").get("figures", [])
    current = [
        item
        for item in figures
        if isinstance(item, dict) and item.get("status") == "current"
    ] if isinstance(figures, list) else []
    if not current:
        lines.extend(
            [
                "- 当前没有已就绪的 current 正式图；若论证需要图，提出返工请求补充，不得用装饰图替代。",
                "",
            ]
        )
        return lines
    referenced = 0
    for item in current:
        figure_id = str(item.get("figure_id", ""))
        question_id = str(item.get("question_id", ""))
        # 取 current 输出中的 pdf 作为正文引用路径。
        include = ""
        for output in item.get("outputs", []):
            if isinstance(output, dict) and str(output.get("path", "")).startswith("figures/current/") and str(output.get("path")).endswith(".pdf"):
                include = "../" + str(output["path"])
                break
        if not include:
            # 回退：用 figure_id 构造约定路径。
            include = f"../figures/current/{figure_id}.pdf"
        takeaway = str(item.get("takeaway", item.get("question", ""))).strip()
        q_label = f"Q{str(question_id).lstrip('Q')}" if question_id else ""
        lines.append(
            f"- {q_label} 图 {figure_id}：`\\includegraphics[width=0.9\\textwidth]{{{include}}}`"
            + (f" —— {takeaway}" if takeaway else "")
        )
        referenced += 1
    lines.extend(
        [
            "",
            f"以上 {referenced} 张正式图已由 current production 数据确定性生成，正文必须引用其中的关键图，"
            "每张配图号、图注，并在正文中完成'观察（图显示了什么）→ 机制（为什么呈现该形态）→ 结论（对答案意味着什么）'。"
            "不要因为图注复杂就省略图，也不要仅用一句话掠过。",
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
    progression_map: dict[str, dict[str, Any]] = {}
    for item in story.get("question_progression", []):
        if isinstance(item, dict) and item.get("question_id"):
            progression_map[str(item["question_id"])] = item

    lines = [
        "# RESEARCH PACKAGE",
        "",
        "本文件只包含可用于写作的当前研究事实。运行状态、哈希、回执、工具探测和完整搜索轨迹不进入作者上下文。"
        "论证结构、章节组织、图文方案与叙事焦点由你自由形成，但不得创造不存在的证据、"
        "不得超出主张边界，也不得用结果报账替代论证。",
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
        progression = progression_map.get(question_id, {})
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
        if progression:
            why_insufficient = progression.get("why_previous_insufficient")
            new_diff = progression.get("new_difficulty")
            if why_insufficient:
                lines.append(f"- 为什么不能沿用上一问方法：{why_insufficient}")
            if new_diff:
                lines.append(f"- 本问核心数学困难：{new_diff}")
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
        objective = answer.get("objective_answer")
        boundary = (
            objective.get("claim_boundary")
            if isinstance(objective, dict)
            else None
        )
        if isinstance(boundary, dict):
            label = str(boundary.get("label", "")).strip()
            statement = str(boundary.get("statement", "")).strip()
            if label and statement:
                lines.append(f"主张边界（{label}）：{statement}")
                assumptions = boundary.get("assumptions", [])
                if isinstance(assumptions, list) and assumptions:
                    lines.append("必要假设：" + "；".join(map(str, assumptions)))
                range_ids = boundary.get("range_result_ids", [])
                if isinstance(range_ids, list) and range_ids:
                    lines.append("范围证据结果：" + "、".join(map(str, range_ids)))
                lines.append("")
        metrics = result.get("metrics", {})
        if isinstance(metrics, dict) and metrics:
            visible = [
                f"{key}={value}"
                for key, value in metrics.items()
                if key not in {"runtime_seconds", "seed"}
            ]
            if visible:
                lines.extend(["核心数字：" + "；".join(visible[:8]), ""])

    # 逐问论证链与决策建议：把 insight.mechanism 投影为 warrant（为什么证据
    # 支持结论），把决策单元合同投影为决策建议（推荐什么、何时不推荐）。
    chain_lines: list[str] = []
    for question_id in state.get("required_questions", []):
        chain_lines.extend(
            _argument_chain_lines(
                question_id,
                units.get(question_id, {}),
                answers[question_id],
            )
        )
    if chain_lines:
        lines.extend(["## 逐问论证链与决策建议", ""])
        lines.extend(chain_lines)

    lines.extend(["## 关键推导、机制与边界", ""])
    substantive = False
    for question_id in state.get("required_questions", []):
        materials = [
            item
            for item in selected_materials.get(question_id, [])
            if str(item.get("category", "")).strip().casefold() != "direct answer"
        ]
        unit = units.get(question_id, {})
        cap = unit.get("capability_decision", {})
        delta = unit.get("question_delta", {})
        contract = unit.get("answer_contract", {})
        has_unit_context = bool(cap or delta or contract)
        if not materials and not has_unit_context:
            continue
        substantive = True
        lines.extend([f"### {question_id}", ""])
        if isinstance(cap, dict) and cap.get("reason"):
            lines.extend([f"- 模型/算法选择依据：{cap.get('reason')}", ""])
        if isinstance(contract, dict):
            baseline = contract.get("natural_baseline")
            if baseline:
                lines.extend([f"- 自然基准（Baseline）：{baseline}", ""])
            counterexample = contract.get("semantic_counterexample")
            if isinstance(counterexample, dict) and counterexample.get("expected_preference"):
                lines.extend([f"- 临界/反例校验设计：{counterexample.get('expected_preference')}", ""])
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
        "论文必须按国奖级完整竞赛论文的论证标准自检，篇幅只由真实论证任务决定：每个问题都要能找到直接答案、"
        "模型建立、求解、结果解读以及必要证据；不得用空泛压缩或堆砌页数、图数规避论证。"
        "附录可含核心代码与稳定性图。",
        "",
        "正式答案、数字、题意语义和主张边界不可擅自修改。若无法解释结果或缺少必要对照、机制、图或证据，应提出返工请求。"
        "每个主要结论都必须能回答'为什么这些证据支持这个结论'；"
        "Research Package 的'逐问论证链与决策建议'已给出机制级论证候选，"
        "你的工作是判断、改写与补全，而不是照抄。"
        "决策类问题必须给出推荐，或明确说明严格目标不可行时的备用决策与适用条件，"
        "不能把'无可行时点'写成推荐一个不满足可靠性的时点。",
        "",
        "前五页优先建立答案与证据链：摘要应给出关键数值与条件边界；读者应尽早找到逐问直接答案、"
        "共享数学对象、原始数据直觉和至少一张决定性 Hero 图及其机制解释。具体页码与段落顺序由中心主线决定，"
        "不要等到后半篇才首次展示主要结论。",
        "",
        "采用可识别的国赛外壳（问题重述与分析、必要假设和符号、共享模型、问题链、检验与结论、"
        "参考文献及附录），但正文必须服从共享数学对象和中心主线。允许合并相邻问题、集中共享推导，"
        "并让核心问题获得更多篇幅；每个必答问题只需在自然叙事中可定位地给出直接答案，"
        "不要为所有问题复制相同的“建模—参数—结果—答案”小节序列。",
        "",
        "文风必须是学术论文而非技术报告："
        "采用自然、正式、克制的数学建模学术语言，允许使用'本文建立'、'本文定义'、'由式(x)可得'、'这说明'、'其原因在于'等自然表达；"
        "禁止口语化、自我吹捧和工作汇报式报账，正文禁止使用'我们/大家'等第一人称；"
        "每段第一句通常是主题句，后续围绕它展开；"
        "正文的核心是模型建立、数学推导、求解方法与结果机制分析（建议篇幅占比 50–60%）：必须解释为什么选择该模型（与更简单 baseline 对比）、变量与参数定量依据、关键推导展开、约束物理意义以及为什么结果呈现当前结构；"
        "每个数值结果后必须解读其物理/工程意义和产生机理（'这表明……'、'其原因在于……'）；"
        "正文叙述中尽量用文字描述结合符号（如'介质 A 的最优体积分数为 1.24%'而非只有 $f_A^*=1.24\\%$）；"
        "正文的主要论证必须使用连续学术段落，列表仅适合必要模型假设、符号说明、极少量算法步骤或优缺点摘要，推导与机制分析严禁使用列表堆砌。",
        "",
        "按 claim-first 的 Visual Brief 写图：先回答每张图要证明什么，再说明读者应看到的观察、"
        "其机制或边界，以及对应的 current 数据来源；之后才选择 Hero 或 supporting 图型。图必须分别承担"
        "数据直觉、模型机制、决定性证据、权衡/边界或验证中的真实论证角色，不能按问题编号凑图，"
        "也不能靠拆图、换色或重复插图补数量。优先选择最能说明命题的图型；普通折线/柱状图在确实"
        "最清楚时同样可用。所有正式图均从 current 数据或正式结构 renderer 生成，保持统一字体、"
        "坐标轴/单位/图例，并在正文中完成'观察 → 机制 → 结论'三步论证。候选稿的图消费合同由后台按题数"
        "和未覆盖论证角色复核，Author 不应把总图数当成写作目标。",
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
