"""构建并复验 v3.4 External Author Handoff 交接包。

本模块负责四个职责：

- ``writer_handoff_readiness``：科学事实与提交边界是硬门，素材、故事板和图表
  缺口只作为 Author 可回流的编辑信号。
- ``build_writer_handoff``：把已冻结研究材料投影成两个人读文件，后台继续保留
  answer-and-claims JSON 与 provenance manifest。
- ``mark_waiting_external_author``：进入正常暂停状态，并记录 checkpoint。
- ``verify_handoff_freshness``：确认外部稿件仍是针对当前材料版本写作的。

Writer 只读 ``RESEARCH_PACKAGE.md`` 与 ``AUTHOR_BRIEF.md``；机器 JSON 与 manifest
是 Import Audit 做数字 / 主张绑定的机器事实来源，不要求 Author 阅读。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file, sha256_tree
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.core.schema import require_valid
from shumozizi.paper.citations import citation_coverage_errors
from shumozizi.paper.materials import (
    material_pool_quality_report,
    read_material_pool,
    validate_material_pool_freshness,
)
from shumozizi.paper.policy import formal_result_digest, policy_fingerprint
from shumozizi.paper.readiness import validate_required_figure_consumption
from shumozizi.paper.storyboard import (
    storyboard_quality_report,
    validate_storyboard_freshness,
)
from shumozizi.simple import review as simple_review
from shumozizi.simple.authoring import (
    mark_authoring_status,
    read_authoring,
    record_handoff_revision,
)
from shumozizi.simple.modeling_units import question_outcome_selections
from shumozizi.simple.state import read_simple_state, utc_now

HANDOFF_DIR = Path("paper/writer-handoff")
INTERNAL_HANDOFF_DIR = HANDOFF_DIR / "internal"
HANDOFF_MANIFEST_PATH = HANDOFF_DIR / "manifest.json"
HANDOFF_READY_CHECKPOINT_PATH = Path("review/writer-handoff-ready.json")

# Author 默认阅读的人读文件；answer-and-claims.json 是机器绑定源。
WRITER_MARKDOWN_FILES = (
    "RESEARCH_PACKAGE.md",
    "AUTHOR_BRIEF.md",
)
ANSWER_AND_CLAIMS_JSON = "answer-and-claims.json"
PACKAGE_FILES = (*WRITER_MARKDOWN_FILES, ANSWER_AND_CLAIMS_JSON)

_LEGACY_ROOT_MARKDOWN_FILES = (
    "WRITER_BRIEF.md",
    "PAPER_BLUEPRINT.md",
    "ANSWER_AND_CLAIMS.md",
    "MATERIAL_POOL.md",
    "FIGURE_CATALOG.md",
    "CITATION_PACKET.md",
)


def _backend_handoff_path(root: Path, filename: str) -> Path:
    """读取后台投影的新 internal 位置，并兼容旧根目录交接包。"""
    internal = root / INTERNAL_HANDOFF_DIR / filename
    if internal.is_file():
        return internal
    return root / HANDOFF_DIR / filename

MINIMUM_BLUEPRINT_CHARACTERS = 400
MINIMUM_MUST_ANSWER_CHARACTERS = 8


def _atomic_text(path: Path, value: str) -> None:
    """原子写入交接文本，避免外部 Author 读取到半成品。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _repo_root() -> Path:
    """返回仓库根目录，用于计算论文政策指纹。"""
    return resolve_repo_root(Path(__file__))


# ---------------------------------------------------------------------------
# WRITER_HANDOFF_READY 实质条件
# ---------------------------------------------------------------------------


def writer_handoff_readiness(run_dir: Path) -> dict[str, Any]:
    """检查研究材料是否满足 Writer Handoff 交接条件。

    该检查只看研究输入侧（正式答案、素材池、故事板、图表、主张边界、文献），
    不要求存在任何手写正文——正文正是外部 Author 接下来要写的东西。

    Args:
        run_dir: 当前运行目录。

    Returns:
        含 ``ready``、``layers`` 与 ``reasons`` 的就绪报告；reasons 只收集
        阻断项，不抛出异常。
    """
    root = run_dir.resolve()
    layers: dict[str, Any] = {}
    reasons: list[str] = []
    signals: list[str] = []

    # Scientific：正式答案 + 关键科学挑战已关闭。
    try:
        simple_review.require_paper_generation_allowed(root)
        layers["scientific"] = "ok"
    except ContractError as exc:
        reasons.append(f"scientific: {exc}")
        layers["scientific"] = "blocked"
    if not (root / "review/scientific-challenge-evidence.json").is_file():
        reasons.append("scientific: 缺少科学挑战证据，关键科学挑战尚未关闭")
        layers["scientific"] = "blocked"

    # Material：素材池充分且绑定当前结果。
    try:
        pool_report = material_pool_quality_report(root)
        if not pool_report.get("substantive"):
            messages = pool_report.get("errors") or ["素材池缺少实质内容"]
            signals.append("material: " + "; ".join(str(item) for item in messages[:3]))
            layers["material"] = "advisory"
        else:
            layers["material"] = "ok"
        freshness = validate_material_pool_freshness(root)
        if not freshness.get("current"):
            stale = freshness.get("stale_fields") or []
            signals.append("material: 素材池未绑定当前结果: " + ", ".join(map(str, stale)))
            layers["material"] = "advisory"
    except ContractError as exc:
        signals.append(f"material: {exc}")
        layers["material"] = "advisory"

    # Storyboard / narrative：故事板充分且绑定当前素材。
    try:
        sb_report = storyboard_quality_report(root)
        if not sb_report.get("substantive"):
            messages = sb_report.get("errors") or ["故事板缺少实质内容"]
            signals.append("storyboard: " + "; ".join(str(item) for item in messages[:3]))
            layers["storyboard"] = "advisory"
        else:
            layers["storyboard"] = "ok"
        sb_fresh = validate_storyboard_freshness(root)
        if not sb_fresh.get("current"):
            signals.append("storyboard: 故事板未绑定当前素材")
            layers["storyboard"] = "advisory"
    except ContractError as exc:
        signals.append(f"storyboard: {exc}")
        layers["storyboard"] = "advisory"

    # Visual：每问 required 图已在 current 或经复核的 waiver。
    try:
        figure_errors = validate_required_figure_consumption(root)
        if figure_errors:
            signals.append("visual: " + "; ".join(str(item) for item in figure_errors[:5]))
            layers["visual"] = "advisory"
        else:
            layers["visual"] = "ok"
    except ContractError as exc:
        signals.append(f"visual: {exc}")
        layers["visual"] = "advisory"

    # Blueprint：PAPER_BLUEPRINT.md 必须存在且非空壳。
    blueprint = root / "paper/PAPER_BLUEPRINT.md"
    if not blueprint.is_file():
        signals.append("blueprint: 缺少 paper/PAPER_BLUEPRINT.md")
        layers["blueprint"] = "advisory"
    elif len(blueprint.read_text(encoding="utf-8").strip()) < MINIMUM_BLUEPRINT_CHARACTERS:
        signals.append("blueprint: PAPER_BLUEPRINT.md 过短，建议由 Author 自主重建叙事")
        layers["blueprint"] = "advisory"
    else:
        layers["blueprint"] = "ok"

    # Claims：核心答案必须有 claim boundary。
    claim_gate = root / "paper/claim_gate.json"
    if not claim_gate.is_file():
        reasons.append("claims: 缺少 paper/claim_gate.json，核心答案无主张边界")
        layers["claims"] = "blocked"
    else:
        try:
            gate = load_json(claim_gate)
            if gate.get("stale") is True:
                reasons.append("claims: claim evidence 已 stale")
                layers["claims"] = "blocked"
            elif not gate.get("claims"):
                reasons.append("claims: claim_gate 未登记任何主张边界")
                layers["claims"] = "blocked"
            else:
                layers["claims"] = "ok"
        except ContractError as exc:
            reasons.append(f"claims: {exc}")
            layers["claims"] = "blocked"

    # Citation：有文献计划时必须无未定义引用键；无计划视为无需外部引用。
    coverage_path = root / "paper/generated/citation_coverage.json"
    if coverage_path.is_file():
        try:
            coverage_errors = citation_coverage_errors(load_json(coverage_path))
            if coverage_errors:
                reasons.append("citation: " + "; ".join(str(item) for item in coverage_errors[:3]))
                layers["citation"] = "blocked"
            else:
                layers["citation"] = "ok"
        except ContractError as exc:
            reasons.append(f"citation: {exc}")
            layers["citation"] = "blocked"
    else:
        # 未声明文献计划：允许"明确无需外部引用"的交接。
        layers["citation"] = "no_plan"

    return {
        "ready": not reasons,
        "layers": layers,
        "reasons": reasons,
        "editorial_signals": signals,
        "run_id": read_simple_state(root)["run_id"],
    }


# ---------------------------------------------------------------------------
# Writer Handoff Package 构建
# ---------------------------------------------------------------------------


def _package_digests(
    root: Path, answers_path: Path, catalog_path: Path, packet_path: Path
) -> dict[str, str | None]:
    """计算 manifest 需要的全部摘要。"""
    pool = root / "paper/generated/material_pool.json"
    storyboard = root / "paper/generated/research_storyboard.json"
    return {
        "paper_policy_fingerprint": policy_fingerprint(_repo_root(), "paper"),
        "formal_result_digest": formal_result_digest(root),
        "material_pool_digest": sha256_tree(pool) if pool.is_file() else None,
        "storyboard_digest": sha256_tree(storyboard) if storyboard.is_file() else None,
        "claim_boundary_digest": sha256_tree(answers_path) if answers_path.is_file() else None,
        "figure_catalog_digest": sha256_tree(catalog_path) if catalog_path.is_file() else None,
        "citation_packet_digest": sha256_tree(packet_path) if packet_path.is_file() else None,
    }


def _write_writer_brief(root: Path, handoff_dir: Path) -> Path:
    """从模板写入对外部 Author 的系统说明。"""
    template = _repo_root() / "templates/paper/writer-brief.md"
    if not template.is_file():
        raise ContractError("缺少 WRITER_BRIEF 模板 templates/paper/writer-brief.md")
    state = read_simple_state(root)
    authoring = read_authoring(root)
    text = (
        template.read_text(encoding="utf-8")
        .replace("{{RUN_ID}}", state["run_id"])
        .replace("{{PROBLEM_ID}}", str(state.get("problem_id", "")))
        .replace(
            "{{REQUIRED_QUESTIONS}}",
            "、".join(state.get("required_questions", [])),
        )
        .replace("{{HANDOFF_REVISION}}", str(authoring["handoff_revision"]))
    )
    path = handoff_dir / "WRITER_BRIEF.md"
    _atomic_text(path, text)
    return path


def _write_blueprint_projection(root: Path, handoff_dir: Path) -> Path:
    """投影现有 PAPER_BLUEPRINT.md 供 Author 阅读。"""
    source = root / "paper/PAPER_BLUEPRINT.md"
    if not source.is_file():
        raise ContractError("缺少 paper/PAPER_BLUEPRINT.md")
    text = source.read_text(encoding="utf-8")
    path = handoff_dir / "PAPER_BLUEPRINT.md"
    _atomic_text(
        path,
        "<!-- 由 shumozizi 投影 paper/PAPER_BLUEPRINT.md 生成。这是推荐的论证主线，"
        "允许为提升可读性调整局部章节、段落和图表顺序，但不得改变答案、模型语义、"
        "证据边界与跨问逻辑依赖。 -->\n\n" + text,
    )
    return path


def _current_result_answers(root: Path) -> dict[str, str]:
    """当建模单元缺失时，从 current production 结果回退生成直接答案文本。

    这层只在没有 ``MODELING_UNITS`` 的轻量运行中兜底，保证交接包永远能给出
    逐问可引用的正式答案，而不是让外部 Author 面对空白的"必须回答"。这里直接
    读 ``results/index.json`` 而不是 ``read_result_index``，因为结果登记可能在
    任意阶段被写入，容错读取不应因为登记信息不完整而让交接构建失败。
    """
    answers: dict[str, str] = {}
    try:
        index = load_json(root / "results/index.json")
    except ContractError:
        return answers
    for item in index.get("results", []):
        question_id = item.get("question_id")
        if (
            question_id
            and question_id not in answers
            and item.get("status") == "current"
            and item.get("execution_mode") == "production"
            and item.get("execution_valid") is True
        ):
            metrics = item.get("metrics") or {}
            if metrics:
                key = next(iter(metrics))
                answers[question_id] = f"{item.get('result_id')}: {metrics[key]}"
    return answers


def _answer_from_result(root: Path, result_id: str) -> str:
    """从指定正式结果读取首个标量指标，避免把路线字典当成答案文本。"""
    try:
        index = load_json(root / "results/index.json")
    except ContractError:
        return ""
    for item in index.get("results", []):
        if (
            isinstance(item, dict)
            and item.get("result_id") == result_id
            and item.get("status") == "current"
            and item.get("execution_mode") == "production"
            and item.get("execution_valid") is True
        ):
            for metric, value in (item.get("metrics") or {}).items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return f"{metric} = {value}"
    return ""


def _current_result_essential_numbers(root: Path) -> dict[str, list[int | float]]:
    """从中央指标账本或正式 current 结果提取正文必现数字。

    中央指标账本已经表达了“哪些数是核心答案”；没有账本的兼容运行只取每问
    首个标量指标，避免把数组、逐日序列和求解日志整体变成正文出现义务。
    """
    try:
        index = load_json(root / "results/index.json")
    except ContractError:
        return {}
    current = {
        str(item.get("result_id")): item
        for item in index.get("results", [])
        if isinstance(item, dict)
        and item.get("status") == "current"
        and item.get("execution_mode") == "production"
        and item.get("execution_valid") is True
    }
    numbers: dict[str, list[int | float]] = {}
    ledger_path = root / "paper/generated/metric_ledger.json"
    if ledger_path.is_file():
        try:
            ledger = load_json(ledger_path)
        except ContractError:
            ledger = {}
        for metric in ledger.get("metrics", []):
            if not isinstance(metric, dict) or metric.get("central") is not True:
                continue
            result = current.get(str(metric.get("source_result_id", "")))
            if result is None:
                continue
            value = (result.get("metrics") or {}).get(metric.get("source_metric"))
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            question_id = str(result.get("question_id", ""))
            numbers.setdefault(question_id, []).append(value)
    if numbers:
        return {
            question_id: list(dict.fromkeys(values))
            for question_id, values in numbers.items()
        }

    for result in current.values():
        question_id = str(result.get("question_id", ""))
        for value in (result.get("metrics") or {}).values():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                numbers[question_id] = [value]
                break
    return numbers


def _estimator_contracts(root: Path) -> dict[str, dict[str, str]]:
    """从 MODELING_UNITS 提取每问"正式方法名 + 数学结构 + 形式化转换"。

    这是论文与代码一致性的 ground truth：正文用什么方法名、代码实际拟合什么
    模型、形式化如何转换，都必须与这里声明的正式 estimator 对齐。写作工具
    若把"聚类稳健 OLS + Ridge 样条"改写成"GEE 样条"，或把 LCB 换成
    mean-1.645SE，就构成对该契约的违反。
    """
    payload_path = root / "analysis/MODELING_UNITS.json"
    if not payload_path.is_file():
        return {}
    try:
        payload = load_json(payload_path)
    except ContractError:
        return {}
    contracts: dict[str, dict[str, str]] = {}
    for unit in payload.get("units", []):
        if not isinstance(unit, dict):
            continue
        question_id = str(unit.get("question_id", ""))
        if not question_id:
            continue
        method = unit.get("primary_method")
        if not isinstance(method, dict):
            continue
        method_id = str(method.get("method_id", "")).strip()
        structure = str(method.get("mathematical_structure", "")).strip()
        if not method_id and not structure:
            continue
        formalization = unit.get("formalization_diff")
        transformation = ""
        if isinstance(formalization, dict):
            transformation = str(formalization.get("transformation", "")).strip()
        contracts[question_id] = {
            "formal_method": method_id,
            "mathematical_structure": structure,
            "formalization_transformation": transformation,
        }
    return contracts


def _build_answer_and_claims(root: Path) -> dict[str, Any]:
    """从正式结果与主张门禁生成逐问答案与边界文档。"""
    state = read_simple_state(root)
    try:
        outcomes = question_outcome_selections(root)
    except ContractError:
        # 结果登记可能不完整；此时退回结果索引兜底，不让交接构建失败。
        outcomes = {}
    estimator_contracts = _estimator_contracts(root)
    result_answers = _current_result_answers(root)
    essential_numbers = _current_result_essential_numbers(root)
    gate: dict[str, Any] = {}
    gate_path = root / "paper/claim_gate.json"
    if gate_path.is_file():
        try:
            gate = load_json(gate_path)
        except ContractError:
            gate = {}
    claims_by_question: dict[str, list[dict[str, Any]]] = {}
    for claim in gate.get("claims", []):
        claims_by_question.setdefault(claim.get("question_id", ""), []).append(claim)
    questions: list[dict[str, Any]] = []
    for question_id in state.get("required_questions", []):
        outcome = outcomes.get(question_id) or {}
        objective = outcome.get("objective_answer")
        must_answer = ""
        if isinstance(objective, dict):
            must_answer = str(objective.get("answer") or objective.get("value") or "").strip()
            result_id = objective.get("result_id")
            if len(must_answer) < MINIMUM_MUST_ANSWER_CHARACTERS and isinstance(
                result_id, str
            ):
                must_answer = _answer_from_result(root, result_id)
        if len(must_answer) < MINIMUM_MUST_ANSWER_CHARACTERS:
            must_answer = result_answers.get(question_id, "")
        if len(must_answer) < MINIMUM_MUST_ANSWER_CHARACTERS:
            must_answer = str(outcome.get("recommended_plan") or objective or "").strip()
        safe_claims: list[str] = []
        forbidden_upgrades: list[str] = []
        key_boundaries: list[str] = []
        claim_ids: list[str] = []
        for claim in claims_by_question.get(question_id, []):
            claim_ids.append(str(claim.get("claim_id", "")))
            status = claim.get("status")
            if status in {"supported", "partially_supported"}:
                safe_claims.append(f"{claim.get('claim_id', '')}: {claim.get('reason', '')}")
            elif status in {"rejected", "inconclusive"}:
                forbidden_upgrades.append(f"{claim.get('claim_id', '')}: {claim.get('reason', '')}")
        grade = outcome.get("evidence_grade")
        if isinstance(grade, dict):
            certificate = grade.get("certificate")
            if not certificate:
                forbidden_upgrades.append("无全局最优性证书：不得写'全局最优'、'必然'等升级表达")
            key_boundaries.append(f"证据等级: {grade.get('grade', '')}")
        source_result_ids = outcome.get("result_ids", [])
        if not source_result_ids and isinstance(objective, dict):
            candidate = objective.get("result_id")
            if isinstance(candidate, str):
                source_result_ids = [candidate]
        questions.append(
            {
                "question_id": question_id,
                "must_answer": must_answer,
                "essential_numbers": essential_numbers.get(question_id, []),
                "safe_claims": safe_claims,
                "forbidden_upgrades": forbidden_upgrades,
                "key_boundaries": key_boundaries,
                "source_result_ids": list(dict.fromkeys(source_result_ids)),
                "claim_ids": list(dict.fromkeys(filter(None, claim_ids))),
                "estimator_contract": estimator_contracts.get(question_id, {}),
            }
        )
    return {
        "schema_name": "answer_and_claims",
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "questions": questions,
        "generated_at": utc_now(),
    }


def _render_answer_and_claims_markdown(document: dict[str, Any]) -> str:
    """把机器可绑定的 answer-and-claims JSON 渲染成 Author 可读 Markdown。"""
    lines = [
        "# 逐问正式答案与主张边界",
        "",
        "这份文件是外部 Author 最重要的事实边界。正文任何数字、比较、强度词都"
        "只能落在这份文件声明的范围内。",
        "",
    ]
    for question in document["questions"]:
        lines.append(f"## {question['question_id']}")
        lines.append("")
        lines.append("### 必须回答")
        lines.append("")
        lines.append(question["must_answer"] or "（当前缺少可引用的正式答案文本）")
        lines.append("")
        lines.append("### 可以安全表达")
        lines.append("")
        if question["safe_claims"]:
            for item in question["safe_claims"]:
                lines.append(f"- {item}")
        else:
            lines.append("- 无已验证的确定性创新主张")
        lines.append("")
        lines.append("### 禁止升级")
        lines.append("")
        if question["forbidden_upgrades"]:
            for item in question["forbidden_upgrades"]:
                lines.append(f"- {item}")
        else:
            lines.append("- 无")
        lines.append("")
        lines.append("### 关键边界")
        lines.append("")
        if question["key_boundaries"]:
            for item in question["key_boundaries"]:
                lines.append(f"- {item}")
        else:
            lines.append("- 无")
        lines.append("")
        estimator = question.get("estimator_contract") or {}
        lines.append("### 正式方法与实现契约")
        lines.append("")
        if estimator:
            lines.append(f"- 正式方法名：{estimator.get('formal_method', '未声明')}")
            lines.append(f"- 数学结构：{estimator.get('mathematical_structure', '未声明')}")
            transformation = estimator.get("formalization_transformation", "")
            lines.append(f"- 形式化转换：{transformation or '未声明'}")
            lines.append(
                "- 约束：正文方法名、代码实际拟合的模型、公式推导必须与上面"
                "正式 estimator 一致；不得用其它名字重命名方法（如把聚类稳健"
                "OLS+Ridge 样条写成 GEE 样条），不得用不同公式重算正式数字"
                "（如把 Bootstrap 下界换成 mean-1.645*SE）。"
            )
        else:
            lines.append("- （该问未声明正式方法契约，写作时禁止凭空指定方法名）")
        lines.append("")
    return "\n".join(lines)


def _write_answer_and_claims(
    root: Path, handoff_dir: Path, *, markdown_dir: Path | None = None
) -> tuple[Path, Path]:
    """写入逐问答案与主张边界的人读与机器绑定双形态。"""
    document = _build_answer_and_claims(root)
    require_valid(document, "answer_and_claims")
    json_path = handoff_dir / ANSWER_AND_CLAIMS_JSON
    atomic_json(json_path, document)
    md_path = (markdown_dir or handoff_dir) / "ANSWER_AND_CLAIMS.md"
    _atomic_text(md_path, _render_answer_and_claims_markdown(document))
    return md_path, json_path


def _write_material_pool_projection(root: Path, handoff_dir: Path) -> Path:
    """把素材池投影成 Writer 可读列表，过滤控制层字段。"""
    pool = read_material_pool(root)
    lines = [
        "# 研究素材池",
        "",
        "素材按类别列出，来源是当前生产结果、分析材料与当前图表。每项给出"
        "内容、所属问题与包含建议，但不暴露内部登记号、哈希或执行回执。",
        "",
    ]
    items = pool.get("items", [])
    if not items:
        lines.append("（素材池为空）")
    else:
        by_category: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            category = str(item.get("category", "其他"))
            by_category.setdefault(category, []).append(item)
        for category in sorted(by_category):
            lines.append(f"## {category}")
            lines.append("")
            for item in by_category[category]:
                lines.append(f"### {item.get('title', item.get('material_id', ''))}")
                lines.append("")
                lines.append(f"- 问题: {item.get('question_id', '')}")
                lines.append(f"- 包含建议: {item.get('inclusion', '')}")
                lines.append("")
                lines.append(item.get("content", ""))
                lines.append("")
    path = handoff_dir / "MATERIAL_POOL.md"
    _atomic_text(path, "\n".join(lines))
    return path


def _write_figure_catalog(root: Path, handoff_dir: Path) -> Path:
    """从 FIGURE_PLAN 与当前图表生成 Author 可读图目录。"""
    plan_path = root / "figures/FIGURE_PLAN.json"
    current_dir = root / "figures/current"
    figures: list[dict[str, Any]] = []
    if plan_path.is_file():
        try:
            figures = load_json(plan_path).get("figures", [])
        except ContractError:
            figures = []
    lines = [
        "# 图目录",
        "",
        "每张图都声明用途、核心观察、机制、边界与建议位置。Author 负责在图"
        "的叙事位置组织它们，不负责重新判断图是否可信。",
        "",
    ]
    for figure in figures:
        if not isinstance(figure, dict):
            continue
        figure_id = figure.get("figure_id", "")
        if not figure_id:
            continue
        rendered = "否"
        if current_dir.is_dir():
            candidates = [
                path
                for path in current_dir.rglob("*")
                if path.is_file() and path.name.startswith(figure_id)
            ]
            rendered = "是" if candidates else "否"
        lines.append(f"## {figure_id}")
        lines.append("")
        lines.append(f"- 用途: {figure.get('visual_question', figure.get('claim', ''))}")
        lines.append(f"- 核心观察: {figure.get('expected_observation', '')}")
        lines.append(f"- 机制: {figure.get('mechanism_annotation', '')}")
        lines.append(f"- 决策后果: {figure.get('decision_consequence', '')}")
        lines.append(f"- 所属问题: {figure.get('question_id', '')}")
        lines.append(f"- 建议位置: {figure.get('paper_section', '')}")
        lines.append(f"- 是否已有 current 渲染: {rendered}")
        lines.append("- 不能证明: 该图本身不能替代正式答案与 claim boundary。")
        lines.append("")
    path = handoff_dir / "FIGURE_CATALOG.md"
    _atomic_text(path, "\n".join(lines))
    return path


def _write_citation_packet(root: Path, handoff_dir: Path) -> Path:
    """从文献覆盖生成 Author 可读引用包。"""
    coverage_path = root / "paper/generated/citation_coverage.json"
    lines = [
        "# 引用包",
        "",
        "只提供可用于正文的文献及其用途边界。Author 不得把某篇文献扩展开来支持计划之外的结论。",
        "",
    ]
    if coverage_path.is_file():
        try:
            coverage = load_json(coverage_path)
        except ContractError:
            coverage = {}
        defined = coverage.get("bibliography_keys") or []
        if not defined:
            lines.append("（当前无已登记文献；本稿可不使用外部引用。）")
        else:
            lines.append("| key | 可用于 |")
            lines.append("|---|---|")
            for key in sorted(defined):
                lines.append(f"| {key} | 用于解释其方法或指标的基本思想 |")
    else:
        lines.append("（未声明文献计划：本稿不引入外部引用。）")
    lines.append("")
    lines.append("不能用于：证明当前题的结果优于其他方案，除非有当前生产结果支持。")
    path = handoff_dir / "CITATION_PACKET.md"
    _atomic_text(path, "\n".join(lines))
    return path


def build_writer_handoff(run_dir: Path) -> dict[str, Any]:
    """构建 Writer Handoff Package 并写入 manifest。

    Args:
        run_dir: 当前运行目录。

    Returns:
        含各文件路径、digest 与 manifest 的构建回执。

    Raises:
        ContractError: 交接材料未就绪，或输出不满足协议。
    """
    root = run_dir.resolve()
    readiness = writer_handoff_readiness(root)
    if not readiness["ready"]:
        raise ContractError("Writer Handoff 未就绪: " + "；".join(readiness["reasons"]))
    # 每次构建生成一个新版本交接包；首次构建即 revision=1。
    current_revision = int(read_authoring(root)["handoff_revision"])
    record_handoff_revision(root, current_revision + 1)
    handoff_dir = root / HANDOFF_DIR
    handoff_dir.mkdir(parents=True, exist_ok=True)
    internal_dir = root / INTERNAL_HANDOFF_DIR
    internal_dir.mkdir(parents=True, exist_ok=True)
    _answers_md, answers_json = _write_answer_and_claims(
        root,
        handoff_dir,
        markdown_dir=internal_dir,
    )
    answer_document = load_json(answers_json)
    answer_overrides: dict[str, Any] = {}
    for question in answer_document["questions"]:
        result_ids = question.get("source_result_ids", [])
        if len(result_ids) == 1:
            answer_overrides[question["question_id"]] = {
                "primary_result_id": result_ids[0],
                "result_ids": result_ids,
                "objective_answer": {
                    "result_id": result_ids[0],
                    "answer": str(question.get("must_answer", "")).strip(),
                },
            }
    from shumozizi.paper.author_pass import (
        AUTHOR_BRIEF_PATH,
        RESEARCH_PACKAGE_PATH,
        prepare_longform_author,
    )

    prepare_longform_author(
        root,
        require_template=False,
        allow_unmapped_singletons=True,
        answer_overrides=answer_overrides,
    )
    research = handoff_dir / "RESEARCH_PACKAGE.md"
    _atomic_text(research, (root / RESEARCH_PACKAGE_PATH).read_text(encoding="utf-8"))
    author_brief = handoff_dir / "AUTHOR_BRIEF.md"
    _atomic_text(author_brief, (root / AUTHOR_BRIEF_PATH).read_text(encoding="utf-8"))
    # 旧投影只供后台兼容与审计，物理隔离到 internal，避免整目录交接时污染 Author。
    _write_writer_brief(root, internal_dir)
    _write_blueprint_projection(root, internal_dir)
    _write_material_pool_projection(root, internal_dir)
    catalog = _write_figure_catalog(root, internal_dir)
    packet = _write_citation_packet(root, internal_dir)
    for filename in _LEGACY_ROOT_MARKDOWN_FILES:
        (handoff_dir / filename).unlink(missing_ok=True)
    digests = _package_digests(root, answers_json, catalog, packet)
    writer_files: dict[str, str] = {}
    for path in (research, author_brief):
        relative = path.relative_to(root).as_posix()
        writer_files[relative] = sha256_file(path)
    authoring = read_authoring(root)
    manifest = {
        "schema_name": "writer_handoff_manifest",
        "schema_version": "1.0",
        "run_id": root.name,
        "handoff_revision": authoring["handoff_revision"],
        "paper_policy_fingerprint": digests["paper_policy_fingerprint"],
        "formal_result_digest": digests["formal_result_digest"],
        "material_pool_digest": digests["material_pool_digest"],
        "storyboard_digest": digests["storyboard_digest"],
        "claim_boundary_digest": digests["claim_boundary_digest"],
        "figure_catalog_digest": digests["figure_catalog_digest"],
        "citation_packet_digest": digests["citation_packet_digest"],
        "writer_files": writer_files,
        "generated_at": utc_now(),
    }
    require_valid(manifest, "writer_handoff_manifest")
    manifest_path = handoff_dir / "manifest.json"
    atomic_json(manifest_path, manifest)
    return {
        "status": "WRITER_HANDOFF_READY",
        "manifest_path": HANDOFF_MANIFEST_PATH.as_posix(),
        "writer_files": sorted(writer_files),
        "digests": digests,
    }


# ---------------------------------------------------------------------------
# 暂停、新鲜度与状态
# ---------------------------------------------------------------------------


def mark_waiting_external_author(run_dir: Path) -> dict[str, Any]:
    """从 ``handoff_ready`` 进入正常暂停 ``waiting_external_author``。

    该状态不是 blocked：主 Agent 停止自动撰写正文，等待用户把 Package 交给
    外部写作模型。执行前必须已构建过 Writer Handoff。
    """
    root = run_dir.resolve()
    if not (root / HANDOFF_DIR / "manifest.json").is_file():
        raise ContractError("尚未构建 Writer Handoff，无法进入等待外部 Author")
    mark_authoring_status(root, "waiting_external_author")
    manifest_path = root / HANDOFF_MANIFEST_PATH
    manifest = load_json(manifest_path)
    checkpoint = {
        "schema_name": "writer_handoff_ready_checkpoint",
        "schema_version": "1.0",
        "run_id": root.name,
        "kind": "writer_handoff_ready",
        "handoff_revision": int(manifest["handoff_revision"]),
        "authoring_status": "waiting_external_author",
        "manifest": {
            "path": HANDOFF_MANIFEST_PATH.as_posix(),
            "sha256": sha256_file(manifest_path),
        },
        "digests": {
            "paper_policy_fingerprint": manifest["paper_policy_fingerprint"],
            "formal_result_digest": manifest["formal_result_digest"],
            "material_pool_digest": manifest["material_pool_digest"],
            "storyboard_digest": manifest["storyboard_digest"],
            "claim_boundary_digest": manifest["claim_boundary_digest"],
            "figure_catalog_digest": manifest["figure_catalog_digest"],
            "citation_packet_digest": manifest["citation_packet_digest"],
        },
        "recorded_at": utc_now(),
    }
    require_valid(checkpoint, "writer_handoff_ready_checkpoint")
    atomic_json(root / HANDOFF_READY_CHECKPOINT_PATH, checkpoint)
    return checkpoint


def verify_handoff_freshness(run_dir: Path) -> dict[str, Any]:
    """确认当前 Writer Handoff 仍针对最新材料版本。

    任意上游变化（正式结果、素材池、故事板、图表、主张边界、文献或论文
    政策）都会让 handoff 变 stale；外部草稿保留，但必须重新 audit。
    """
    root = run_dir.resolve()
    manifest_path = root / HANDOFF_MANIFEST_PATH
    if not manifest_path.is_file():
        return {"fresh": False, "reasons": ["缺少 Writer Handoff manifest"]}
    manifest = load_json(manifest_path)
    stale_reasons: list[str] = []
    answers_path = root / HANDOFF_DIR / ANSWER_AND_CLAIMS_JSON
    catalog_path = _backend_handoff_path(root, "FIGURE_CATALOG.md")
    packet_path = _backend_handoff_path(root, "CITATION_PACKET.md")
    current = _package_digests(root, answers_path, catalog_path, packet_path)
    for field, value in current.items():
        recorded = manifest.get(field)
        if recorded != value:
            stale_reasons.append(f"{field} 已变化")
    for relative, recorded_hash in (manifest.get("writer_files") or {}).items():
        try:
            current_hash = sha256_file(root / relative)
        except ContractError:
            current_hash = None
        if current_hash != recorded_hash:
            stale_reasons.append(f"writer 文件已变化: {relative}")
    return {
        "fresh": not stale_reasons,
        "reasons": stale_reasons,
        "handoff_revision": int(manifest.get("handoff_revision", 0)),
    }


def handoff_status(run_dir: Path) -> dict[str, Any]:
    """汇总 authoring 状态、就绪情况与新鲜度，供 CLI 与上层消费。"""
    root = run_dir.resolve()
    authoring = read_authoring(root)
    readiness = writer_handoff_readiness(root)
    freshness = verify_handoff_freshness(root)
    return {
        "authoring_mode": authoring["authoring_mode"],
        "authoring_status": authoring["authoring_status"],
        "handoff_revision": authoring["handoff_revision"],
        "external_draft_present": authoring["external_draft_present"],
        "ready": readiness["ready"],
        "reasons": readiness["reasons"],
        "handoff_fresh": freshness["fresh"],
        "stale_reasons": freshness["reasons"],
    }
