"""编译前轻量硬门：确认论证地图、当前结果、当前图表和源码策略真实绑定。

不检查字数、句数、页数、关键词密度——只检查"是否具备最小编译前提"。

此模块是硬门核心，由 ``shumozizi.paper.compiler.compile_paper`` 在启动编译器之前
调用；``scripts/paper/check_paper_readiness.py`` 只是它的薄 CLI 包装。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from shumozizi.core.io import (
    ContractError,
    json_bytes,
    load_json,
    sha256_bytes,
    sha256_file,
)
from shumozizi.core.schema import validate_document
from shumozizi.simple.capabilities import ROUTE_PATH
from shumozizi.simple.critical_claims import CRITICAL_CLAIMS_PATH, read_critical_claims
from shumozizi.simple.figures import verify_current_figure_files
from shumozizi.simple.method_profile import METHOD_PROFILE_PATH
from shumozizi.simple.objective_semantics import objective_semantics_digest
from shumozizi.simple.quality import quality_allows_paper
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import is_competition_first_state, read_simple_state

_APPENDIX_MODES = {"pdf", "attachment", "both"}


def _argument_map_path(run_dir: Path) -> Path:
    """返回生产模式论证地图路径（只认结构化 argument_map.json）。"""
    return run_dir / "paper" / "argument_map.json"


def _load_argument_map(run_dir: Path) -> dict[str, Any] | None:
    """读取论证地图；不存在或不可解析返回 None。"""
    path = _argument_map_path(run_dir)
    if not path.is_file() or path.stat().st_size == 0:
        return None
    try:
        return load_json(path)
    except (OSError, ValueError):
        return None


def _question_ids_from_state(run_dir: Path) -> list[str]:
    """读取必答问题列表。"""
    state = read_simple_state(run_dir)
    return list(state["required_questions"])


def _current_production_results(run_dir: Path) -> dict[str, dict[str, Any]]:
    """返回所有可作为论文事实的 current production 结果。"""
    index = read_result_index(run_dir)
    allowed: dict[str, dict[str, Any]] = {}
    competition_first = is_competition_first_state(read_simple_state(run_dir))
    for result in index["results"]:
        if result.get("status") != "current":
            continue
        if result.get("execution_mode") != "production":
            continue
        if competition_first and result.get("execution_valid") is not True:
            continue
        if not competition_first and not quality_allows_paper(run_dir, result["result_id"]):
            continue
        allowed[result["result_id"]] = result
    return allowed


def _tree_digest(root: Path, *, exclude_names: set[str] | None = None) -> str:
    """计算目录内路径集合和文件内容的稳定摘要。"""
    digest = hashlib.sha256()
    if root.is_dir():
        excluded = exclude_names or set()
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            if path.name in excluded:
                continue
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def argument_map_bindings(run_dir: Path) -> dict[str, str]:
    """重新计算当前论证地图必须绑定的全部运行事实。"""
    results = _current_production_results(run_dir)
    accepted = [results[key] for key in sorted(results)]
    return {
        "capability_route_sha256": sha256_file(run_dir / ROUTE_PATH),
        "method_profile_sha256": sha256_file(run_dir / METHOD_PROFILE_PATH),
        "critical_claims_sha256": sha256_file(run_dir / CRITICAL_CLAIMS_PATH),
        "objective_semantics_digest": objective_semantics_digest(run_dir),
        "accepted_results_digest": sha256_bytes(json_bytes(accepted)),
        "claim_evidence_digest": _tree_digest(
            run_dir / "claims", exclude_names={"ARGUMENT_MAP.json"}
        ),
        "figure_index_sha256": sha256_file(run_dir / "figures" / "index.json"),
    }


def _source_appendix_strategy_clear(run_dir: Path) -> bool:
    """确认 content_blueprint.json 已记录非空源码附录策略。

    仅有 source_code_appendix 键但值为 null/空不算有策略；必须给出 mode 与
    included_roles，说明哪些源码进入论文附录。
    """
    blueprint_path = run_dir / "paper" / "content_blueprint.json"
    if not blueprint_path.is_file():
        return False
    try:
        blueprint = load_json(blueprint_path)
    except (OSError, ValueError):
        return False
    appendix = blueprint.get("source_code_appendix")
    if isinstance(appendix, list):
        return bool(appendix) and all(
            isinstance(item, dict)
            and isinstance(item.get("source_path"), str)
            and isinstance(item.get("sha256"), str)
            for item in appendix
        )
    if not isinstance(appendix, dict):
        return False
    if appendix.get("mode") not in _APPENDIX_MODES:
        return False
    roles = appendix.get("included_roles")
    return isinstance(roles, list) and bool(roles)


def _current_figure_ids(run_dir: Path) -> tuple[set[str], str | None]:
    """返回已真实生成、通过校验的当前图 ID 集合。

    只信任 verify_current_figure_files（校验 status=current、源结果 current、
    文件存在与哈希、图 QA）；figure_plan.json 仅表达计划，不计入。
    """
    try:
        verification = verify_current_figure_files(run_dir)
    except (ContractError, OSError, KeyError, ValueError) as exc:
        return set(), f"当前图校验失败: {exc}"
    if not verification["success"]:
        messages = "；".join(
            item.get("message", "") for item in verification.get("errors", [])
        )
        return set(), f"存在无效的当前图，不能作为论文图: {messages}"
    return set(verification.get("checked_figure_ids", [])), None


def _competition_answer_map(run_dir: Path) -> dict[str, Any] | None:
    """读取 Competition-First 的逐问直接答案映射，兼容最终归档路径。"""
    for relative in (Path("paper/answer-map.json"), Path("analysis/answer_map.json")):
        path = run_dir / relative
        if not path.is_file():
            continue
        try:
            payload = load_json(path)
        except (OSError, ValueError):
            return None
        if payload.get("run_id") not in {None, run_dir.name}:
            return None
        answers = payload.get("answers", payload)
        return answers if isinstance(answers, dict) else None
    return None


def build_argument_map_from_current_artifacts(run_dir: Path) -> dict[str, Any]:
    """从当前答案、结果和图表自动生成后台论证映射。

    Args:
        run_dir: 当前 Competition-First 运行目录。

    Returns:
        已写入 ``paper/generated/argument_map.json`` 的映射。

    Raises:
        ContractError: 缺少必答问题的答案映射或引用了非当前结果。
    """
    answers = _competition_answer_map(run_dir)
    if answers is None:
        raise ContractError("缺少 analysis/answer_map.json 或 paper/answer-map.json")
    required = _question_ids_from_state(run_dir)
    results = _current_production_results(run_dir)
    claims: list[dict[str, Any]] = []
    for question_id in required:
        item = answers.get(question_id)
        if not isinstance(item, dict):
            raise ContractError(f"answer_map 缺少 {question_id}")
        result_ids = item.get("result_ids")
        location = item.get("direct_answer_location")
        if not isinstance(result_ids, list) or not result_ids:
            raise ContractError(f"{question_id} 未绑定 result_ids")
        stale = [result_id for result_id in result_ids if result_id not in results]
        if stale:
            raise ContractError(f"{question_id} 引用了非 current production 结果: {', '.join(stale)}")
        if not isinstance(location, str) or not location.strip():
            raise ContractError(f"{question_id} 缺少 direct_answer_location")
        claims.append(
            {
                "question_id": question_id,
                "result_ids": result_ids,
                "direct_answer_location": location,
                "figure_ids": list(item.get("figure_ids", [])),
            }
        )
    document = {
        "schema_version": "3.1",
        "run_id": run_dir.name,
        "status": "current",
        "accepted_results_digest": sha256_bytes(json_bytes([results[key] for key in sorted(results)])),
        "figure_index_sha256": sha256_file(run_dir / "figures" / "index.json"),
        "claims": claims,
    }
    from shumozizi.core.io import atomic_json

    atomic_json(run_dir / "paper" / "generated" / "argument_map.json", document)
    return document


def _argument_plan_warnings(run_dir: Path) -> list[str]:
    """检查核心问题是否在 ARGUMENT_PLAN.md 中有对应论证单元。

    轻量 warning（不阻断）：核心问题存在但 ARGUMENT_PLAN.md 缺少或
    没有该问题的论证单元标题时，提醒写作前填写，避免论文仍然流水账。
    """
    import re

    try:
        from shumozizi.simple.modeling_units import core_question_insights

        available = core_question_insights(run_dir)
    except Exception:  # noqa: BLE001
        return []
    if not available:
        return []

    plan_path = run_dir / "paper" / "ARGUMENT_PLAN.md"
    if not plan_path.is_file():
        core_ids = sorted(available)
        return [
            f"核心问题 {', '.join(core_ids)} 已提炼规律，但缺少 paper/ARGUMENT_PLAN.md；"
            "建议写论文前为每个核心问题规划论证单元（判断→推导→证据→竞争解释→讨论）。"
        ]

    try:
        text = plan_path.read_text(encoding="utf-8")
    except OSError:
        return []

    question_pat = re.compile(r"核心问题\s+(Q\w+)", re.MULTILINE)
    found_in_plan = set(question_pat.findall(text))

    missing = sorted(set(available) - found_in_plan)
    if not missing:
        return []
    return [
        f"核心问题 {', '.join(missing)} 已提炼规律，但 paper/ARGUMENT_PLAN.md "
        "中没有对应论证单元；写论文前请补充这些问题的论证单元规划。"
    ]


def _validate_competition_readiness(run_dir: Path) -> tuple[list[str], list[str]]:
    """执行 Competition-First 最小论文硬门和可选写作警告。"""
    errors: list[str] = []
    warnings: list[str] = []
    answers = _competition_answer_map(run_dir)
    if answers is None:
        return ["缺少 paper/answer-map.json 或 analysis/answer_map.json"], warnings
    required = _question_ids_from_state(run_dir)
    results = _current_production_results(run_dir)
    for question_id in required:
        item = answers.get(question_id)
        if not isinstance(item, dict):
            errors.append(f"必答问题 {question_id} 没有直接答案映射")
            continue
        result_ids = item.get("result_ids")
        location = item.get("direct_answer_location")
        if not isinstance(result_ids, list) or not result_ids:
            errors.append(f"必答问题 {question_id} 没有绑定 current 结果")
        else:
            stale = [result_id for result_id in result_ids if result_id not in results]
            if stale:
                errors.append(f"必答问题 {question_id} 引用了非 current 或不可写入论文的结果: {', '.join(stale)}")
        if not isinstance(location, str) or not location.strip():
            errors.append(f"必答问题 {question_id} 缺少直接答案位置")
        for figure_id in item.get("figure_ids", []):
            if not isinstance(figure_id, str):
                errors.append(f"{question_id} 的 figure_ids 含非法值")
    try:
        generated = build_argument_map_from_current_artifacts(run_dir)
        figure_ids = {
            figure_id
            for claim in generated["claims"]
            for figure_id in claim["figure_ids"]
            if figure_id
        }
        if figure_ids:
            current, figure_error = _current_figure_ids(run_dir)
            if figure_error:
                errors.append(figure_error)
            else:
                missing = sorted(figure_ids - current)
                if missing:
                    errors.append("答案映射引用了不存在或失效图表: " + ", ".join(missing))
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        errors.append(str(exc))
    if not (run_dir / "paper" / "STORYBOARD.md").is_file():
        warnings.append("缺少 paper/STORYBOARD.md；建议先明确最强问题、篇幅与核心图表。")
    if not (run_dir / "paper" / "CONTRIBUTION_BRIEF.md").is_file():
        warnings.append("缺少 paper/CONTRIBUTION_BRIEF.md；这不阻断普通问题的正确回答。")
    warnings.extend(_insight_figure_warnings(run_dir))
    warnings.extend(_argument_plan_warnings(run_dir))
    errors.extend(_code_appendix_errors(run_dir))
    errors.extend(_core_insight_usage_errors(run_dir, answers))
    return errors, warnings


def _core_insight_usage_errors(run_dir: Path, answers: dict[str, Any]) -> list[str]:
    """要求核心问题在论文里真的用上已挖出的规律。

    只生产不消费时，规律挖掘会退化成旁路产物：挖了、论文不写也能过门，于是
    正文继续只讲参数与复核。
    """
    from shumozizi.simple.modeling_units import core_question_insights

    try:
        available = core_question_insights(run_dir)
    except (ContractError, OSError, KeyError, TypeError, ValueError):
        return []
    errors: list[str] = []
    for question_id, insights in sorted(available.items()):
        item = answers.get(question_id)
        if not isinstance(item, dict):
            continue
        used = item.get("insight_ids")
        known = {insight["insight_id"] for insight in insights}
        if not isinstance(used, list) or not used:
            errors.append(
                f"核心问题 {question_id} 已提炼机制或边际收益类规律，"
                f"但 answer map 未引用任何 insight_id（可用: {', '.join(sorted(known))}）；"
                "论文必须真的讲出这些规律"
            )
            continue
        unknown = sorted({value for value in used if value not in known})
        if unknown:
            errors.append(
                f"核心问题 {question_id} 的 answer map 引用了不存在的 insight_id: "
                + ", ".join(unknown)
            )
    return errors


def _insight_figure_warnings(run_dir: Path) -> list[str]:
    """提示正文缺少洞察图：全是证据图会把论文写成技术审计报告。"""
    index_path = run_dir / "figures" / "index.json"
    if not index_path.is_file():
        return []
    try:
        payload = load_json(index_path)
    except (OSError, ValueError):
        return []
    figures = [
        item
        for item in payload.get("figures", [])
        if isinstance(item, dict) and item.get("status") == "current"
    ]
    if not figures:
        return []
    roles = [item.get("role") for item in figures if item.get("role")]
    if not roles:
        return ["当前图未声明 role；建议区分模型理解图、决定性证据图与洞察图。"]
    if not any(role in {"insight", "model_understanding"} for role in roles):
        return [
            "当前图全是证据或稳定性图，没有洞察图；"
            "建议补充回答机制、阈值、边际收益或权衡的主图。"
        ]
    return []


def _code_appendix_errors(run_dir: Path) -> list[str]:
    """限制 PDF 内源码版面：代码的边际价值低于机制解释与权衡分析。

    默认允许最多一页；确有赛事要求时必须显式写出 ``competition_requires_full``
    与理由，否则整篇源码会挤掉结论和洞察。
    """
    blueprint_path = run_dir / "paper" / "content_blueprint.json"
    if not blueprint_path.is_file():
        return []
    try:
        blueprint = load_json(blueprint_path)
    except (OSError, ValueError):
        return []
    appendix = blueprint.get("source_code_appendix")
    if not isinstance(appendix, dict):
        return []
    if appendix.get("mode") == "attachment":
        return []
    if appendix.get("competition_requires_full") is True:
        if not str(appendix.get("full_source_reason", "")).strip():
            return ["source_code_appendix.competition_requires_full 为真时必须写明赛事依据"]
        return []
    budget = appendix.get("pdf_page_budget")
    if budget is None:
        return [
            "source_code_appendix 缺少 pdf_page_budget；"
            "PDF 内源码默认不超过 1 页，完整代码放附件"
        ]
    if not isinstance(budget, (int, float)) or isinstance(budget, bool) or budget > 1:
        return [
            f"source_code_appendix.pdf_page_budget={budget} 超过默认 1 页上限；"
            "请把完整源码移入附件，或显式声明赛事要求"
        ]
    return []


def _validate_readiness(run_dir: Path) -> list[str]:
    """执行所有轻量检查，返回阻断原因列表。"""
    if is_competition_first_state(read_simple_state(run_dir)):
        return _validate_competition_readiness(run_dir)[0]
    errors: list[str] = []

    # 1. 论证大纲：生产模式只接受结构化 argument_map.json，并按 schema 校验
    arg_map = _load_argument_map(run_dir)
    if arg_map is None:
        errors.append(
            "缺少 paper/argument_map.json（生产模式只接受结构化论证地图，"
            "Markdown 提纲不能解锁编译）"
        )
        return errors  # 无论证地图，后续覆盖/图表检查无从谈起

    schema_errors = validate_document(arg_map, "argument_map")
    if schema_errors:
        errors.append("argument_map.json 不符合 schema: " + "；".join(schema_errors))
        return errors
    if arg_map.get("schema_version") != "3.0":
        errors.append("生产论文只接受 argument_map 3.0；2.0 仅供历史只读兼容")
        return errors
    if arg_map.get("status") != "current":
        errors.append(
            "argument_map 已失效（status=superseded），必须根据当前证据重新生成"
        )
        return errors
    if arg_map.get("run_id") != run_dir.name:
        errors.append("argument_map run_id 与当前运行不一致")
    try:
        expected_bindings = argument_map_bindings(run_dir)
    except (ContractError, OSError, KeyError, ValueError) as exc:
        errors.append(f"无法重算 argument_map 绑定: {exc}")
        return errors
    for field, expected in expected_bindings.items():
        if arg_map.get(field) != expected:
            errors.append(f"argument_map 绑定已失效: {field}")

    claims = arg_map.get("claims", [])
    if not claims:
        errors.append("argument_map.json 存在但 claims 为空")
        return errors

    # 2. 必答问题覆盖
    required = _question_ids_from_state(run_dir)
    covered = {
        claim["question_id"]
        for claim in claims
        if isinstance(claim.get("question_id"), str)
    }
    missing_questions = sorted(set(required) - covered)
    if missing_questions:
        errors.append(f"argument_map 缺少必答问题: {', '.join(missing_questions)}")

    # 3. 每个 claim 的 result_ids 必须绑定当前 production 结果
    allowed_results = _current_production_results(run_dir)
    critical_claims = {
        item["claim_id"]: item for item in read_critical_claims(run_dir)["claims"]
    }
    for claim in claims:
        claim_id = claim.get("claim_id", "<未命名>")
        critical = critical_claims.get(claim_id)
        if critical is None or critical.get("question_id") != claim.get("question_id"):
            errors.append(f"论证主张 {claim_id} 未绑定当前同问 critical claim")
        result_ids = claim.get("result_ids", [])
        if not result_ids:
            errors.append(f"主张 {claim_id} 未绑定任何 result_id")
            continue
        stale = [rid for rid in result_ids if rid not in allowed_results]
        if stale:
            errors.append(
                f"主张 {claim_id} 绑定了非当前/不可写入论文的结果: "
                f"{', '.join(stale)}"
            )
        for result_id in result_ids:
            result = allowed_results.get(result_id)
            if result is None:
                continue
            question_id = claim.get("question_id")
            if result.get("question_id") != question_id and not (
                result.get("dependency_scope") in {"shared", "global"}
                and question_id in result.get("affected_question_ids", [])
            ):
                errors.append(f"主张 {claim_id} 不能由其他问题结果 {result_id} 背书")

    # 4. 图表：claim 引用的 figure_ids 必须是已真实生成的当前图
    #    只有当确有主张引用图时才校验当前图，避免无图论文被图索引缺失误伤。
    required_figures: set[str] = set()
    for claim in claims:
        for figure_id in claim.get("figure_ids", []):
            if isinstance(figure_id, str) and figure_id.strip():
                required_figures.add(figure_id)
    if required_figures:
        current_figures, figure_error = _current_figure_ids(run_dir)
        if figure_error:
            errors.append(figure_error)
        else:
            missing_figures = sorted(required_figures - current_figures)
            if missing_figures:
                errors.append(
                    "主张引用了尚未生成的图表（仅 figure_plan 不算已生成）: "
                    + ", ".join(missing_figures)
                )
        figure_index = load_json(run_dir / "figures" / "index.json")
        current_figure_map = {
            item["figure_id"]: item
            for item in figure_index.get("figures", [])
            if item.get("status") == "current"
            and item.get("figure_stage", "publication") == "publication"
        }
        for claim in claims:
            for figure_id in claim.get("figure_ids", []):
                figure = current_figure_map.get(figure_id)
                if figure is not None and figure.get("question_id") not in {
                    None,
                    claim.get("question_id"),
                }:
                    errors.append(
                        f"主张 {claim.get('claim_id')} 不能引用其他问题图 {figure_id}"
                    )

    # 5. 源码附录策略
    if not _source_appendix_strategy_clear(run_dir):
        errors.append(
            "缺少 paper/content_blueprint.json 或 source_code_appendix 策略为空"
            "（需给出 mode 与非空 included_roles）"
        )

    return errors


def check_paper_readiness(run_dir: Path) -> dict[str, Any]:
    """返回就绪检查结果，不抛出异常。"""
    run_dir = run_dir.resolve()
    errors = _validate_readiness(run_dir)
    warnings: list[str] = []
    if is_competition_first_state(read_simple_state(run_dir)):
        _, warnings = _validate_competition_readiness(run_dir)
    return {
        "ready": not errors,
        "errors": errors,
        "warnings": warnings,
        "run_dir": str(run_dir),
    }


def require_paper_readiness(run_dir: Path) -> None:
    """编译前硬门：任一项未满足即阻断。

    Args:
        run_dir: 当前 v3 运行目录。

    Raises:
        ContractError: 最小编译前提未满足。
    """
    status = check_paper_readiness(run_dir)
    if not status["ready"]:
        raise ContractError(
            "论文编译前提未满足，请在编译前修复:\n- " + "\n- ".join(status["errors"])
        )
