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
    if errors:
        raise ContractError("Author Pass 科学输入未就绪: " + "；".join(errors))


def _render_research_package(
    root: Path,
    state: dict[str, Any],
    answers: dict[str, Any],
    results: dict[str, dict[str, Any]],
) -> str:
    """把后台证据投影成不含哈希和控制台账的作者材料。"""
    lines = [
        "# RESEARCH PACKAGE",
        "",
        "本文件只包含可用于写作的当前研究事实。运行状态、哈希、回执、工具探测和完整搜索轨迹不进入作者上下文。",
        "",
        "## 逐问正式答案",
        "",
    ]
    for question_id in state.get("required_questions", []):
        answer = answers[question_id]
        result = results[str(answer["primary_result_id"])]
        lines.extend([f"### {question_id}", ""])
        metrics = result.get("metrics", {})
        if isinstance(metrics, dict) and metrics:
            for key, value in metrics.items():
                lines.append(f"- {key}: {value}")
        else:
            lines.append("- 当前正式结果未暴露可直接呈现的标量指标；正文应使用已登记答案文本。")
        location = answer.get("direct_answer_location")
        if isinstance(location, str) and location.strip():
            lines.append(f"- 当前答案位置建议: {location.strip()}")
        lines.append("")

    pool = _optional_json(root, "paper/generated/material_pool.json")
    lines.extend(["## 可用研究素材", ""])
    items = pool.get("items", [])
    if isinstance(items, list) and items:
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", item.get("category", "研究素材")))
            content = str(item.get("content", "")).strip()
            if content:
                lines.extend([f"### {title}", "", content, ""])
    else:
        lines.extend(["当前没有结构化素材池；Author 应只展开上述正式答案和已有论文源中的可验证推导。", ""])

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
    lines.extend([
        "",
        "## 作者返工权",
        "",
        "若材料只能形成结果报账，Author 应在 AUTHOR_GAPS.md 指出缺少的推导、机制、反事实、视觉或科学证据；不得自行创造结果。",
        "",
    ])
    return "\n".join(lines)


def _render_author_brief(state: dict[str, Any], inspiration: dict[str, Any]) -> str:
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
        answers.update(answer_overrides)
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
    _validate_scientific_inputs(state, answers, results)
    package_path = root / RESEARCH_PACKAGE_PATH
    brief_path = root / AUTHOR_BRIEF_PATH
    from shumozizi.knowledge.inspiration import build_inspiration_context

    inspiration = build_inspiration_context(root)
    _atomic_text(package_path, _render_research_package(root, state, answers, results))
    _atomic_text(brief_path, _render_author_brief(state, inspiration))
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
        "formal_result_digest": formal_result_digest(root),
        "prepared_at": utc_now(),
    }
    atomic_json(root / AUTHOR_PASS_MANIFEST_PATH, payload)
    return payload


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
