"""管理 CUMCM A/B 获奖论文的结构专家库。

该模块只加载 ``knowledge/award-experts/library.json``。来源、页码与论文标识
仅存在于同目录的离线 ``provenance.json``，因此不会进入运行时路由或提示词。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.simple.state import is_competition_first_v32_state, read_simple_state, utc_now

BASELINE_FREEZE_PATH = Path("analysis/BASELINE_FREEZE.json")
AWARD_EXPERT_ROUTE_PATH = Path("analysis/AWARD_EXPERT_ROUTE.json")
AWARD_EXPERT_AUDIT_PATH = Path("analysis/AWARD_EXPERT_ROUTE_AUDIT.json")
SUPPORTED_PHASES = frozenset({"analysis", "experiment", "paper", "paper_review", "verify"})
TOPIC_KEYS = {
    "analysis": frozenset({"route_design", "research_story", "validation"}),
    "experiment": frozenset({"mechanism", "comparison", "result_closure"}),
    "paper": frozenset(
        {"blueprint", "shared_model", "question_chapters", "evidence_limits", "revision", "latex"}
    ),
    "paper_review": frozenset({"strict_review", "evidence"}),
    "verify": frozenset({"final_pdf", "evidence"}),
}
DEFAULT_TOPIC_KEYS = {
    "analysis": "route_design",
    "experiment": "comparison",
    "paper": "revision",
    "paper_review": "strict_review",
    "verify": "final_pdf",
}


def _repository_root() -> Path:
    """返回仓库根目录，而非运行目录或来源资料目录。"""
    return Path(__file__).resolve().parents[3]


def _canonical_hash(value: object) -> str:
    """计算稳定 JSON 值的 SHA-256 摘要。"""
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _nonempty_text(value: object, label: str) -> str:
    """读取非空文本字段，避免把占位符冻结为独立分析结论。"""
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} 必须是非空文本")
    return value.strip()


def _runtime_library_path() -> Path:
    """返回唯一允许被运行时读取的专家库文件。"""
    return _repository_root() / "knowledge" / "award-experts" / "library.json"


def load_award_expert_library() -> dict[str, Any]:
    """加载并校验提示安全的专家库。

    Returns:
        仅包含结构规则的运行时库。

    Raises:
        ContractError: 库不存在、被篡改或包含来源泄漏字段。
    """
    path = _runtime_library_path()
    if not path.is_file():
        raise ContractError("缺少 knowledge/award-experts/library.json")
    payload = load_json(path)
    errors = validate_award_expert_library(payload)
    if errors:
        raise ContractError("获奖论文专家库无效: " + "; ".join(errors))
    return payload


def validate_award_expert_library(payload: dict[str, Any]) -> list[str]:
    """校验专家库仅保留结构规则及其完整性。

    Args:
        payload: ``library.json`` 解析结果。

    Returns:
        所有发现的问题；空数组表示库可安全用于路由。
    """
    errors: list[str] = []
    if payload.get("schema_version") != "1.0":
        errors.append("schema_version 必须为 1.0")
    if payload.get("library_id") != "cumcm-ab-award-expert-structure":
        errors.append("library_id 不匹配")
    scope = payload.get("scope")
    if not isinstance(scope, dict):
        errors.append("scope 必须是对象")
    elif (
        scope.get("questions") != ["A", "B"]
        or scope.get("usage") != "structure-only"
        or scope.get("same_problem_policy") != "freeze-baseline-then-answer-filter"
    ):
        errors.append("scope 未保持 A/B structure-only 防泄漏边界")
    supplied_hash = payload.get("library_hash")
    copy = dict(payload)
    copy.pop("library_hash", None)
    if not isinstance(supplied_hash, str) or supplied_hash != _canonical_hash(copy):
        errors.append("library_hash 与运行时结构库不一致")

    serialized = json.dumps(payload, ensure_ascii=False)
    forbidden_patterns = {
        "url": r"https?://",
        "source-field": r'"(?:paper_id|source_url|evidence_refs|pages|page_number|raw_text)"\s*:',
        "raw-material": r'"(?:formula|parameters|results|code)"\s*:',
        "absolute-path": r"(?:[A-Za-z]:[\\/]|(?:^|[\"\s])/[A-Za-z0-9])",
        "word-default": r"\bWord\b",
    }
    errors.extend(
        f"运行时库包含禁止的 {label}" for label, pattern in forbidden_patterns.items() if re.search(pattern, serialized)
    )

    cards = payload.get("cards")
    if not isinstance(cards, list) or len(cards) != 21:
        errors.append("cards 必须恰好包含 21 张结构卡")
        cards = []
    card_ids: set[str] = set()
    for index, card in enumerate(cards, start=1):
        if not isinstance(card, dict):
            errors.append(f"cards[{index}] 必须是对象")
            continue
        card_id = card.get("card_id")
        if not isinstance(card_id, str) or not card_id or card_id in card_ids:
            errors.append(f"cards[{index}] 的 card_id 缺失或重复")
        else:
            card_ids.add(card_id)
        if card.get("structure_only") is not True or card.get("prompt_safe") is not True:
            errors.append(f"{card_id or index} 未声明为提示安全的 structure-only 卡")
        for field in ("kind", "instruction_zh", "checks", "rejects", "applies_to", "stages"):
            if not card.get(field):
                errors.append(f"{card_id or index} 缺少 {field}")

    experts = payload.get("experts")
    if not isinstance(experts, list) or len(experts) != 15:
        errors.append("experts 必须恰好包含 15 个角色")
        experts = []
    expert_ids: set[str] = set()
    for index, expert in enumerate(experts, start=1):
        if not isinstance(expert, dict):
            errors.append(f"experts[{index}] 必须是对象")
            continue
        expert_id = expert.get("id")
        if not isinstance(expert_id, str) or not expert_id or expert_id in expert_ids:
            errors.append(f"experts[{index}] 的 id 缺失或重复")
            continue
        expert_ids.add(expert_id)
        for field in ("name", "applies_to", "responsibilities", "rejects", "card_ids"):
            if not expert.get(field):
                errors.append(f"{expert_id} 缺少 {field}")
        unknown_cards = set(expert.get("card_ids", [])) - card_ids
        if unknown_cards:
            errors.append(f"{expert_id} 引用了未知卡片")
    if "latex-layout-editor" not in expert_ids or "word-layout-editor" in expert_ids:
        errors.append("排版角色必须使用 latex-layout-editor")
    routing_index = payload.get("routing_index")
    if not isinstance(routing_index, dict):
        errors.append("routing_index 必须是对象")
    elif any(
        expert_id not in expert_ids
        for group in routing_index.values()
        if isinstance(group, list)
        for expert_id in group
    ):
        errors.append("routing_index 引用了未知角色")
    return errors


def _require_v32_run(run_dir: Path) -> dict[str, Any]:
    """确认写入目标是 Competition-First v3.2 运行目录。"""
    state = read_simple_state(run_dir)
    if not is_competition_first_v32_state(state):
        raise ContractError("获奖论文结构专家库只服务于 Competition-First v3.2 运行")
    return state


def _current_problem_bindings(run_dir: Path) -> list[dict[str, str]]:
    """绑定当前题面文件，避免 baseline 依赖外部论文资料。"""
    problem_dir = run_dir / "problem"
    if not problem_dir.is_dir():
        raise ContractError("冻结 baseline 前缺少 problem/ 目录")
    bindings = [
        {
            "path": file.relative_to(run_dir).as_posix(),
            "sha256": sha256_file(file),
        }
        for file in sorted(problem_dir.rglob("*"))
        if file.is_file()
    ]
    if not bindings:
        raise ContractError("冻结 baseline 前必须提供至少一个题面文件")
    return bindings


def _baseline_document(
    run_dir: Path, state: dict[str, Any], payload: dict[str, Any], *, frozen_at: str
) -> dict[str, Any]:
    """从独立分析输入构造不可变 baseline 文件。"""
    question_id = _nonempty_text(payload.get("question_id"), "question_id")
    if question_id not in state["required_questions"]:
        raise ContractError("baseline question_id 必须是当前运行的必答问题")
    baseline = payload.get("baseline")
    if not isinstance(baseline, dict):
        raise ContractError("baseline 必须是对象")
    normalized_baseline = {
        "mathematical_structure": _nonempty_text(
            baseline.get("mathematical_structure"), "baseline.mathematical_structure"
        ),
        "objective": _nonempty_text(baseline.get("objective"), "baseline.objective"),
        "rationale": _nonempty_text(baseline.get("rationale"), "baseline.rationale"),
    }
    independent_analysis = payload.get("independent_analysis")
    if not isinstance(independent_analysis, dict):
        raise ContractError("independent_analysis 必须声明独立题面分析边界")
    if (
        independent_analysis.get("allowed_inputs") != ["problem/"]
        or independent_analysis.get("award_expert_library_used") is not False
    ):
        raise ContractError("baseline 必须仅基于 problem/，且冻结前不得使用获奖论文专家库")
    return {
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "question_id": question_id,
        "frozen_at": frozen_at,
        "input_bindings": _current_problem_bindings(run_dir),
        "independent_analysis": {
            "allowed_inputs": ["problem/"],
            "award_expert_library_used": False,
        },
        "baseline": normalized_baseline,
    }


def validate_baseline_freeze(run_dir: Path, payload: dict[str, Any]) -> None:
    """复验 baseline 仍只绑定当前题面，且未被事后改写。

    Args:
        run_dir: 当前 v3.2 运行目录。
        payload: 已保存的 ``BASELINE_FREEZE.json`` 内容。

    Raises:
        ContractError: 运行版本、题面哈希、独立分析声明或冻结内容发生漂移。
    """
    state = _require_v32_run(run_dir)
    if payload.get("schema_version") != "1.0" or payload.get("run_id") != state["run_id"]:
        raise ContractError("BASELINE_FREEZE 的 schema_version 或 run_id 不匹配")
    frozen_at = _nonempty_text(payload.get("frozen_at"), "BASELINE_FREEZE.frozen_at")
    expected = _baseline_document(run_dir, state, payload, frozen_at=frozen_at)
    if payload != expected:
        raise ContractError("BASELINE_FREEZE 与当前题面绑定或独立分析声明不一致")


def write_baseline_freeze(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """原子冻结独立 baseline，拒绝在专家库介入后改写。

    Args:
        run_dir: 当前 v3.2 运行目录。
        payload: ``question_id``、baseline 和独立分析边界声明。

    Returns:
        已冻结的 baseline 文档。

    Raises:
        ContractError: baseline 未只依赖题面，或既有冻结内容被试图改写。
    """
    state = _require_v32_run(run_dir)
    path = run_dir / BASELINE_FREEZE_PATH
    if path.is_file():
        existing = load_json(path)
        validate_baseline_freeze(run_dir, existing)
        expected = _baseline_document(run_dir, state, payload, frozen_at=existing["frozen_at"])
        if existing != expected:
            raise ContractError("BASELINE_FREEZE 已冻结；专家库路由后不得改写 baseline")
        return existing
    document = _baseline_document(run_dir, state, payload, frozen_at=utc_now())
    atomic_json(path, document)
    return document


def read_baseline_freeze(run_dir: Path) -> dict[str, Any]:
    """读取并复验当前运行的独立 baseline 冻结。

    Args:
        run_dir: 当前 v3.2 运行目录。

    Returns:
        当前题面绑定的不可变 baseline 文档。

    Raises:
        ContractError: 冻结文件缺失、不是 v3.2 运行或题面已发生漂移。
    """
    path = run_dir / BASELINE_FREEZE_PATH
    if not path.is_file():
        raise ContractError("路由专家库前必须先冻结 analysis/BASELINE_FREEZE.json")
    payload = load_json(path)
    validate_baseline_freeze(run_dir, payload)
    return payload


def _question_specialist(question: str) -> tuple[str, str, str]:
    """返回 A/B 分类对应的角色和两张核心结构卡。"""
    if question == "A":
        return "a-mechanism-modeler", "a-state-predicate-optimizer", "a-reduction-boundary-proof"
    if question == "B":
        return "b-decision-statistician", "b-stochastic-decision-chain", "b-baseline-uncertainty"
    raise ContractError("获奖论文专家库第一版只支持 CUMCM A 或 B 题")


def _selection(question: str, phase: str, topic_key: str) -> tuple[list[str], list[str]]:
    """按阶段选择 3--6 张结构卡和少量职责互补的角色。"""
    specialist, primary_card, secondary_card = _question_specialist(question)
    if phase == "analysis":
        cards_by_topic = {
            "route_design": ["story-core-thread", primary_card, secondary_card, "innovation-same-budget-ablation", "leakage-structure-only"],
            "research_story": ["story-core-thread", "story-question-progression", primary_card, "innovation-same-budget-ablation", "leakage-structure-only"],
            "validation": [primary_card, secondary_card, "innovation-same-budget-ablation", "evidence-result-closure", "leakage-structure-only"],
        }
        return cards_by_topic[topic_key], ["problem-architect", specialist, "evidence-reviewer", "answer-firewall"]
    if phase == "experiment":
        cards_by_topic = {
            "mechanism": [primary_card, secondary_card, "evidence-result-closure", "innovation-same-budget-ablation", "leakage-structure-only"],
            "comparison": [secondary_card, "evidence-result-closure", "innovation-same-budget-ablation", "figure-argument-task", "leakage-structure-only"],
            "result_closure": [primary_card, "evidence-result-closure", "figure-argument-task", "innovation-same-budget-ablation", "leakage-structure-only"],
        }
        return cards_by_topic[topic_key], [specialist, "evidence-reviewer", "result-interpretation-editor", "figure-editor", "answer-firewall"]
    if phase == "paper":
        cards_by_topic = {
            "blueprint": ["writing-action-blueprint", "story-core-thread", "story-question-progression", "figure-argument-task", "layout-evidence-page-budget"],
            "shared_model": ["writing-action-shared-model", "writing-action-question-chapters", "formula-context-contract", "method-model-before-algorithm", "result-four-link-contract"],
            "question_chapters": ["writing-action-question-chapters", "method-model-before-algorithm", "formula-context-contract", "result-four-link-contract", "story-question-progression"],
            "evidence_limits": ["writing-action-evidence-limitations", "result-four-link-contract", "figure-argument-task", "innovation-same-budget-ablation", "evidence-result-closure"],
            "revision": ["writing-action-strict-revision", "strict-review-return-loop", "result-four-link-contract", "formula-context-contract", "layout-evidence-page-budget"],
            "latex": ["layout-evidence-page-budget", "strict-review-return-loop", "figure-argument-task", "formula-context-contract", "abstract-claim-audit"],
        }
        experts_by_topic = {
            "blueprint": ["research-thread-editor", "paper-narrative-editor", "figure-layout-editor"],
            "shared_model": ["model-derivation-editor", "algorithm-explanation-editor", "research-thread-editor"],
            "question_chapters": ["research-thread-editor", "model-derivation-editor", "algorithm-explanation-editor", "result-interpretation-editor"],
            "evidence_limits": ["evidence-reviewer", "result-interpretation-editor", "figure-editor"],
            "revision": ["strict-paper-reviewer", "abstract-editor", "latex-layout-editor", "result-interpretation-editor"],
            "latex": ["latex-layout-editor", "figure-editor", "strict-paper-reviewer", "abstract-editor"],
        }
        return cards_by_topic[topic_key], experts_by_topic[topic_key]
    if phase == "paper_review":
        cards_by_topic = {
            "strict_review": ["strict-review-return-loop", "writing-action-strict-revision", "formula-context-contract", "result-four-link-contract", "figure-argument-task", "layout-evidence-page-budget"],
            "evidence": ["strict-review-return-loop", "result-four-link-contract", "formula-context-contract", "figure-argument-task", "writing-action-evidence-limitations", "abstract-claim-audit"],
        }
        return cards_by_topic[topic_key], ["strict-paper-reviewer", "evidence-reviewer", "figure-editor", "latex-layout-editor", "abstract-editor"]
    cards_by_topic = {
        "final_pdf": ["strict-review-return-loop", "result-four-link-contract", "figure-argument-task", "layout-evidence-page-budget", "abstract-claim-audit", "leakage-structure-only"],
        "evidence": ["strict-review-return-loop", "result-four-link-contract", "formula-context-contract", "figure-argument-task", "abstract-claim-audit", "leakage-structure-only"],
    }
    return cards_by_topic[topic_key], ["strict-paper-reviewer", "evidence-reviewer", "figure-editor", "latex-layout-editor", "abstract-editor"]


def _public_card(card: dict[str, Any]) -> dict[str, Any]:
    """裁剪卡片为提示所需的结构建议，不暴露离线资产字段。"""
    return {
        "card_id": card["card_id"],
        "kind": card["kind"],
        "instruction_zh": card["instruction_zh"],
        "checks": card["checks"],
        "rejects": card["rejects"],
    }


def _public_expert(expert: dict[str, Any]) -> dict[str, Any]:
    """裁剪角色为跨题职责和拒绝项。"""
    return {
        "expert_id": expert["id"],
        "name": expert["name"],
        "responsibilities": expert["responsibilities"],
        "rejects": expert["rejects"],
    }


def _validate_route_request(question: str, phase: str, topic_key: str) -> tuple[str, str, str]:
    """限制请求参数，防止把题面文本或任意提示串写入路由收据。"""
    normalized_question = question.upper()
    normalized_phase = phase.strip()
    if normalized_phase not in SUPPORTED_PHASES:
        raise ContractError("专家卡路由阶段必须是 v3.2 的 analysis/experiment/paper/paper_review/verify")
    normalized_topic = topic_key.strip() or DEFAULT_TOPIC_KEYS[normalized_phase]
    if normalized_topic not in TOPIC_KEYS[normalized_phase]:
        raise ContractError("topic_key 必须从当前阶段的受限结构主题集合中选择")
    _question_specialist(normalized_question)
    return normalized_question, normalized_phase, normalized_topic


def _route_document(
    run_dir: Path,
    library: dict[str, Any],
    *,
    award_question: str,
    phase: str,
    topic_key: str,
) -> dict[str, Any]:
    """构造不含题面、结果或来源资料的专家路由收据。"""
    baseline = read_baseline_freeze(run_dir)
    card_ids, expert_ids = _selection(award_question, phase, topic_key)
    if not 3 <= len(card_ids) <= 6:
        raise ContractError("专家路由必须只选择 3--6 张结构卡")
    cards_by_id = {card["card_id"]: card for card in library["cards"]}
    experts_by_id = {expert["id"]: expert for expert in library["experts"]}
    if set(card_ids) - set(cards_by_id) or set(expert_ids) - set(experts_by_id):
        raise ContractError("专家库路由索引引用了不存在的卡片或角色")
    selected_cards = [_public_card(cards_by_id[card_id]) for card_id in card_ids]
    if not all(cards_by_id[card["card_id"]].get("structure_only") is True for card in selected_cards):
        raise ContractError("路由只能输出 structure-only 卡")
    return {
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "award_question": award_question,
        "phase": phase,
        "topic_key": topic_key,
        "library_hash": library["library_hash"],
        "baseline_freeze_sha256": sha256_file(run_dir / BASELINE_FREEZE_PATH),
        "usage": "structure-only",
        "same_problem_policy": "freeze-baseline-then-answer-filter",
        "selected_experts": [_public_expert(experts_by_id[expert_id]) for expert_id in expert_ids],
        "selected_cards": selected_cards,
        "allowed_uses": [
            "补充路线竞争、区分性 probe、验证和论文组织的结构检查",
            "提示模型先于算法、同预算比较、结果闭环和失效边界",
        ],
        "prohibited_uses": [
            "不得作为当前题模型、参数、结果、图表、代码、引用或 claim evidence",
            "不得替代 exact 比较、独立审核或当前生产事实",
        ],
        "routed_at": utc_now(),
        "baseline_question_id": baseline["question_id"],
    }


def write_award_expert_route(
    run_dir: Path, *, award_question: str, phase: str, topic_key: str = ""
) -> dict[str, Any]:
    """在 baseline 冻结后写出少量专家卡的可审计路由。

    这是可选辅助产物，不参与状态迁移门禁，也不能成为实验或论文事实来源。

    Args:
        run_dir: 当前 v3.2 运行目录。
        award_question: CUMCM A 或 B 分类。
        phase: 当前 v3.2 阶段。
        topic_key: 受限的结构主题；空值使用阶段默认主题。

    Returns:
        已原子写入的结构专家卡路由。
    """
    _require_v32_run(run_dir)
    normalized_question, normalized_phase, normalized_topic = _validate_route_request(
        award_question, phase, topic_key
    )
    library = load_award_expert_library()
    document = _route_document(
        run_dir,
        library,
        award_question=normalized_question,
        phase=normalized_phase,
        topic_key=normalized_topic,
    )
    atomic_json(run_dir / AWARD_EXPERT_ROUTE_PATH, document)
    return document


def _route_unsafe_fields(route: dict[str, Any]) -> list[str]:
    """检查路由没有夹带来源、页码、原始文件或运行结果。"""
    text = json.dumps(route, ensure_ascii=False)
    forbidden_patterns = {
        "url": r"https?://",
        "file-uri": r"file://",
        "source-field": r'"(?:paper_id|source_url|evidence_refs|pages|page_number|raw_text)"\s*:',
        "raw-material": r'"(?:formula|parameters|results|code)"\s*:',
        "result-reference": r'"(?:result_id|result_ids|evidence)"\s*:',
        "absolute-path": r"(?:[A-Za-z]:[\\/]|(?:^|[\"\s])/[A-Za-z0-9])",
    }
    return [name for name, pattern in forbidden_patterns.items() if re.search(pattern, text)]


def audit_award_expert_route(run_dir: Path, route: dict[str, Any] | None = None) -> dict[str, Any]:
    """审计专家卡路由的隔离边界和篡改情况。

    Args:
        run_dir: 当前 v3.2 运行目录。
        route: 可选的待审计路由；省略时读取当前路由文件。

    Returns:
        ``status`` 为 ``pass`` 或 ``fail`` 的审计结果。失败会被记录而非伪装为通过。
    """
    errors: list[str] = []
    try:
        _require_v32_run(run_dir)
        library = load_award_expert_library()
        candidate = route if route is not None else load_json(run_dir / AWARD_EXPERT_ROUTE_PATH)
        if not isinstance(candidate, dict):
            raise ContractError("AWARD_EXPERT_ROUTE 必须是对象")
        award_question, phase, topic_key = _validate_route_request(
            str(candidate.get("award_question", "")), str(candidate.get("phase", "")), str(candidate.get("topic_key", ""))
        )
        expected = _route_document(
            run_dir,
            library,
            award_question=award_question,
            phase=phase,
            topic_key=topic_key,
        )
        # routed_at 是记录生成时间；不参与内容完整性比较。
        expected.pop("routed_at")
        actual = dict(candidate)
        actual.pop("routed_at", None)
        if actual != expected:
            errors.append("路由内容与受限阶段选择或当前 baseline 冻结不一致")
        unsafe = _route_unsafe_fields(candidate)
        if unsafe:
            errors.append("路由包含禁止内容: " + ", ".join(unsafe))
        if len(candidate.get("selected_cards", [])) not in range(3, 7):
            errors.append("路由未保持 3--6 张卡的范围")
    except (ContractError, FileNotFoundError, TypeError, ValueError) as exc:
        errors.append(str(exc))
        candidate = route if isinstance(route, dict) else {}
    document = {
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "status": "pass" if not errors else "fail",
        "structure_only": not errors,
        "prompt_safe": not errors,
        "raw_sources_returned": 0,
        "access_monitoring": {
            "enabled": False,
            "boundary": "本审计只验证序列化路由；不声明操作系统级文件访问监控。",
        },
        "route_library_hash": candidate.get("library_hash") if isinstance(candidate, dict) else None,
        "errors": errors,
        "audited_at": utc_now(),
    }
    atomic_json(run_dir / AWARD_EXPERT_AUDIT_PATH, document)
    return document
