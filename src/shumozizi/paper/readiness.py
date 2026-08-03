"""编译前轻量硬门：确认论证地图、当前结果、当前图表和源码策略真实绑定。

不检查字数、句数、页数、关键词密度——只检查"是否具备最小编译前提"。

此模块是硬门核心，由 ``shumozizi.paper.compiler.compile_paper`` 在启动编译器之前
调用；``scripts/paper/check_paper_readiness.py`` 只是它的薄 CLI 包装。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from shumozizi.core.io import (
    ContractError,
    json_bytes,
    load_json,
    resolve_inside,
    sha256_bytes,
    sha256_file,
)
from shumozizi.core.schema import validate_document
from shumozizi.paper.citations import (
    build_citation_coverage,
    citation_coverage_errors,
    citation_coverage_warnings,
)
from shumozizi.paper.style_audit import audit_report_like_manuscript
from shumozizi.simple.capabilities import ROUTE_PATH
from shumozizi.simple.critical_claims import CRITICAL_CLAIMS_PATH, read_critical_claims
from shumozizi.simple.figures import verify_current_figure_files
from shumozizi.simple.method_profile import METHOD_PROFILE_PATH
from shumozizi.simple.objective_semantics import objective_semantics_digest
from shumozizi.simple.quality import quality_allows_paper
from shumozizi.simple.results import read_result_index
from shumozizi.simple.state import (
    is_competition_first_state,
    is_competition_first_v32_state,
    read_simple_state,
)

_APPENDIX_MODES = {"pdf", "attachment", "both"}
_FIGURE_PLAN_PATH = Path("figures/FIGURE_PLAN.json")
_VISUAL_OPPORTUNITY_POOL_PATH = Path("figures/visual-opportunities.json")


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


def _normalized_latex_path(value: str) -> str:
    """规整 LaTeX 图路径，忽略扩展名和相对目录写法差异。"""
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("../"):
        normalized = normalized[3:]
    suffix = Path(normalized).suffix.lower()
    return normalized[: -len(suffix)] if suffix in {".pdf", ".png", ".jpg", ".jpeg"} else normalized


def validate_required_figure_consumption(run_dir: Path) -> list[str]:
    """复验 FIGURE_PLAN 2.1--2.4 的必需图已生成并在 LaTeX 正文中消费。

    旧 2.0 图表计划继续只服务兼容收据；只有 v3.2 主动写入 2.1 时才启用
    生成、current 来源、插图、交叉引用和解释闭环。
    """
    core_questions: set[str] = set()
    units_path = run_dir / "analysis" / "MODELING_UNITS.json"
    if units_path.is_file():
        try:
            units = load_json(units_path).get("units", [])
            core_questions = {
                item.get("question_id")
                for item in units
                if isinstance(item, dict)
                and item.get("core_question") is True
                and isinstance(item.get("question_id"), str)
            }
        except (OSError, ValueError):
            core_questions = set()
    plan_path = run_dir / _FIGURE_PLAN_PATH
    if not plan_path.is_file():
        # 新 Author Pass 允许先在 Visual Sandbox 探索；只有真正进入正文的 current 图
        # 才需要来源、QA、引用和解释闭环。
        return []
    try:
        plan = load_json(plan_path)
        plan_version = plan.get("schema_version")
        if plan_version not in {"2.1", "2.2", "2.3", "2.4"}:
            return [
                f"核心问题 {question_id} 必须使用 FIGURE_PLAN 2.1--2.4 声明显式视觉决策"
                for question_id in sorted(core_questions)
            ]
        errors = validate_document(plan, "figure_plan")
        if errors:
            return errors
        if plan.get("run_id") != run_dir.name:
            return [f"FIGURE_PLAN {plan_version} 的 run_id 与当前运行不一致"]
        decisions = plan.get("visual_decisions", [])
        decision_map = {
            item.get("scope", item.get("question_id")): item
            for item in decisions
            if isinstance(item, dict)
            and isinstance(item.get("scope", item.get("question_id")), str)
        }
        decision_errors: list[str] = []
        opportunity_pool_mode = plan.get("visual_strategy") == "opportunity_pool"
        opportunity_path = run_dir / "figures/visual-opportunities.json"
        opportunity_questions: set[str] = set()
        if opportunity_pool_mode and opportunity_path.is_file():
            try:
                opportunity_payload = load_json(opportunity_path)
                opportunity_questions = {
                    str(item.get("question_id"))
                    for item in opportunity_payload.get("opportunities", [])
                    if isinstance(item, dict)
                    and isinstance(item.get("question_id"), str)
                    and item.get("status") not in {"drop"}
                }
            except (OSError, ValueError, TypeError):
                opportunity_questions = set()
        for question_id in sorted(core_questions):
            decision = decision_map.get(question_id)
            if decision is None:
                decision_errors.append(
                    f"核心问题 {question_id} 缺少显式视觉决策：必须选择 required 或 waived"
                )
                continue
            evidence_required = (
                decision.get("evidence_need") == "required"
                if plan_version in {"2.3", "2.4"}
                else decision.get("status") == "required"
            )
            if evidence_required:
                main_figures = [
                    item
                    for item in plan.get("figures", [])
                    if item.get("question_id") == question_id
                    and item.get("required") is True
                    and item.get("role") != "stability"
                ]
                if not main_figures and not (
                    opportunity_pool_mode and question_id in opportunity_questions
                ):
                    decision_errors.append(
                        f"核心问题 {question_id} 的视觉决策为 required，"
                        "但没有至少一张 required=true 的正文图或已登记视觉机会"
                    )
        if decision_errors:
            return decision_errors
        verification = verify_current_figure_files(run_dir, figure_stage="current")
        if not verification.get("success"):
            detail = "；".join(
                str(item.get("message", item))
                for item in verification.get("errors", [])
            )
            return [f"FIGURE_PLAN {plan_version} 存在失效 current 图: " + detail]
        index = load_json(run_dir / "figures/index.json")
        current = {
            item.get("figure_id"): item
            for item in index.get("figures", [])
            if isinstance(item, dict) and item.get("status") == "current"
        }
        errors = []
        for item in plan.get("figures", []):
            if item.get("required") is not True:
                continue
            figure_id = item["figure_id"]
            registered = current.get(figure_id)
            if registered is None:
                errors.append(f"必需图 {figure_id} 未登记为 current 图")
                continue
            if registered.get("question_id") != item["question_id"]:
                errors.append(f"必需图 {figure_id} 的 question_id 与计划不一致")
            if registered.get("role") != item["role"]:
                errors.append(f"必需图 {figure_id} 的 role 与计划不一致")
            if set(registered.get("source_result_ids", [])) != set(item["source_result_ids"]):
                errors.append(f"必需图 {figure_id} 未绑定计划声明的 current 结果")
            renderer = registered.get("renderer_script", {})
            if renderer.get("path") != item["script"]:
                errors.append(f"必需图 {figure_id} 的实际绘图脚本与计划不一致")
            output_paths = {record.get("path") for record in registered.get("outputs", [])}
            if item["output"] not in output_paths:
                errors.append(f"必需图 {figure_id} 的计划输出未由登记脚本实际生成")
            section = run_dir / item["paper_section"]
            if not section.is_file() or section.suffix.lower() != ".tex":
                errors.append(f"必需图 {figure_id} 缺少 LaTeX 正文章节: {item['paper_section']}")
                continue
            text = section.read_text(encoding="utf-8")
            includes = [
                _normalized_latex_path(value)
                for value in re.findall(r"\\includegraphics(?:\[[^]]*\])?\{([^}]+)\}", text)
            ]
            expected_output = _normalized_latex_path(item["output"])
            if not any(value.endswith(expected_output) or expected_output.endswith(value) for value in includes):
                errors.append(f"必需图 {figure_id} 未在声明章节中使用 \\includegraphics")
            label = item["latex_label"]
            if f"\\label{{{label}}}" not in text:
                errors.append(f"必需图 {figure_id} 缺少 LaTeX label {label}")
            if f"\\ref{{{label}}}" not in text and f"\\autoref{{{label}}}" not in text:
                errors.append(f"必需图 {figure_id} 正文没有交叉引用 {label}")
            if item["caption"] not in text:
                errors.append(f"必需图 {figure_id} 图注与 FIGURE_PLAN 不一致")
            if item["explanation_anchor"] not in text:
                errors.append(f"必需图 {figure_id} 缺少正文解释锚点")
            if item["role"] == "stability" and "appendix" not in item["paper_section"].casefold():
                errors.append(f"稳定性图 {figure_id} 必须放入附录章节")
        return errors
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return ["FIGURE_PLAN 2.1--2.4 闭环校验失败: " + str(exc)]


def _visual_opportunity_assessment_errors(run_dir: Path) -> list[str]:
    """复验没有 FIGURE_PLAN 时，视觉机会是否已经得到明确处置。

    视觉机会池是 Figure Plan 的轻量替代：它允许评阅者将机会晋级为正式图，
    也允许基于具体原因将机会放弃。这里不要求固定图数，只拒绝尚未评估或
    尚未完成的机会池。
    """
    path = run_dir / _VISUAL_OPPORTUNITY_POOL_PATH
    if not path.is_file():
        return [
            "VISUAL_NOT_ASSESSED：缺少 FIGURE_PLAN，也没有已完成的视觉机会评估；"
            "请记录正式图需求或经评阅的放弃理由。"
        ]
    try:
        from shumozizi.simple.visual_opportunities import read_visual_opportunity_pool

        payload = read_visual_opportunity_pool(run_dir)
    except (ContractError, OSError, TypeError, ValueError) as exc:
        return [f"VISUAL_NOT_ASSESSED：视觉机会评估无法读取或验证：{exc}"]
    if payload.get("status") != "current":
        return ["VISUAL_NOT_ASSESSED：视觉机会池尚未完成正式评估"]
    opportunities = payload.get("opportunities", [])
    if not opportunities:
        return ["VISUAL_NOT_ASSESSED：视觉机会池为空，未记录任何评估结论"]

    errors: list[str] = []
    current_figure_opportunities: set[str] = set()
    index_path = run_dir / "figures" / "index.json"
    if index_path.is_file():
        try:
            index = load_json(index_path)
            current_figure_opportunities = {
                str(item.get("visual_opportunity_id"))
                for item in index.get("figures", [])
                if isinstance(item, dict)
                and item.get("status") == "current"
                and isinstance(item.get("visual_opportunity_id"), str)
            }
        except (OSError, TypeError, ValueError):
            errors.append("VISUAL_NOT_ASSESSED：当前图索引无法读取，无法确认正式图覆盖")

    for item in opportunities:
        if not isinstance(item, dict):
            errors.append("VISUAL_NOT_ASSESSED：视觉机会池含非法条目")
            continue
        opportunity_id = str(item.get("opportunity_id", "<unknown>"))
        status = item.get("status")
        verdict = item.get("critic_verdict")
        critic_path = item.get("critic_path")
        if status not in {"promote", "drop"}:
            errors.append(
                f"VISUAL_NOT_ASSESSED：视觉机会 {opportunity_id} 尚未完成评阅"
            )
            continue
        if not isinstance(critic_path, str) or not critic_path.strip():
            errors.append(
                f"VISUAL_NOT_ASSESSED：视觉机会 {opportunity_id} 缺少评阅记录"
            )
            continue
        try:
            review = resolve_inside(run_dir, critic_path, must_exist=True)
            if not review.is_file() or not review.read_text(encoding="utf-8").strip():
                raise OSError("评阅记录为空")
        except (ContractError, OSError, UnicodeError) as exc:
            errors.append(
                f"VISUAL_NOT_ASSESSED：视觉机会 {opportunity_id} 的评阅记录不可用：{exc}"
            )
            continue
        if status == "drop" and verdict != "DROP":
            errors.append(
                f"VISUAL_NOT_ASSESSED：视觉机会 {opportunity_id} 标记为放弃，但没有 DROP 评阅结论"
            )
        elif status == "promote":
            if verdict != "PROMOTE":
                errors.append(
                    f"VISUAL_NOT_ASSESSED：视觉机会 {opportunity_id} 标记为正式图，但没有 PROMOTE 评阅结论"
                )
            elif opportunity_id not in current_figure_opportunities:
                errors.append(
                    f"VISUAL_NOT_ASSESSED：视觉机会 {opportunity_id} 已获 PROMOTE，但尚未由 current 正式图覆盖"
                )
    return errors


def validate_candidate_visual_assessment(run_dir: Path) -> list[str]:
    """要求 Candidate 已完成视觉评估，但不要求 Author 写作前已有 Figure Plan。

    有 Figure Plan 时沿用其既有 required/waived 合同；没有 Plan 时，允许使用
    已完成的视觉机会池。此函数只由最终 Candidate readiness 调用，绝不能成为
    Author Pass 或 Sandbox 草图阶段的前置门。
    """
    if (run_dir / _FIGURE_PLAN_PATH).is_file():
        errors = validate_required_figure_consumption(run_dir)
        return [f"VISUAL_NOT_ASSESSED：{item}" for item in errors]
    return _visual_opportunity_assessment_errors(run_dir)


def presentation_figure_warnings(run_dir: Path) -> list[str]:
    """对 FIGURE_PLAN 2.3/2.4 的呈现需求给出非阻断性缺口提示。"""
    plan_path = run_dir / _FIGURE_PLAN_PATH
    if not plan_path.is_file():
        return []
    try:
        plan = load_json(plan_path)
        if plan.get("schema_version") not in {"2.3", "2.4"}:
            return []
        if plan.get("visual_strategy") == "opportunity_pool":
            return []
        decisions = plan.get("visual_decisions", [])
        figures = plan.get("figures", [])
        warnings: list[str] = []
        for decision in decisions:
            if decision.get("presentation_need") != "required":
                continue
            scope = decision.get("scope")
            expected_role = "data_portrait" if scope == "whole_paper" else "question_hero"
            matches = [
                figure
                for figure in figures
                if figure.get("presentation_role") == expected_role
                and (
                    scope == "whole_paper"
                    or figure.get("question_id") == scope
                )
            ]
            if not matches:
                warnings.append(
                    f"呈现需求 {scope} 声明为 required，但缺少 {expected_role} 图；"
                    "当前仅提示，不自动要求增加低价值图。"
                )
        return warnings
    except (ContractError, OSError, TypeError, ValueError):
        return ["FIGURE_PLAN 2.3/2.4 呈现需求无法读取，建议人工检查。"]


def validate_presentation_decisions(run_dir: Path) -> list[str]:
    """要求首稿前完成结构性展示图的 required/waived 决策。

    Args:
        run_dir: 当前 Competition-First 运行目录。

    Returns:
        缺失决策、结构性豁免复核或必需图计划的错误列表。
    """
    plan_path = run_dir / _FIGURE_PLAN_PATH
    if not plan_path.is_file():
        return []
    try:
        plan = load_json(plan_path)
        plan_version = plan.get("schema_version")
        if plan_version not in {"2.3", "2.4"}:
            return ["首版草稿前必须用 FIGURE_PLAN 2.3/2.4 记录展示图 required/waived 决策"]
        decisions = {
            item.get("scope"): item
            for item in plan.get("visual_decisions", [])
            if isinstance(item, dict) and isinstance(item.get("scope"), str)
        }
        errors: list[str] = []
        for question_id in _question_ids_from_state(run_dir):
            if question_id not in decisions:
                errors.append(f"{question_id} 缺少首稿前展示图 required/waived 决策")

        units_path = run_dir / "analysis" / "MODELING_UNITS.json"
        units_text = ""
        if units_path.is_file():
            units_text = units_path.read_text(encoding="utf-8")
        structural_signal = bool(
            re.search(
                r"几何|轨迹|空间|光路|相交|并集|交集|覆盖|遮蔽|共享模型|共享参数|"
                r"共享约束|时间区间|事件|多阶段|模型选择|不确定性|"
                r"nominal|robust|名义|稳健|聚合|aggregation",
                units_text,
                re.IGNORECASE,
            )
        )
        if structural_signal and "whole_paper" not in decisions:
            errors.append(
                "共享模型、几何/集合或名义—稳健结构出现时，"
                "whole_paper 缺少首稿前展示图 required/waived 决策"
            )
        figures = plan.get("figures", [])
        opportunity_pool_mode = plan.get("visual_strategy") == "opportunity_pool"
        for scope, decision in decisions.items():
            if (
                plan_version == "2.4"
                and structural_signal
                and decision.get("presentation_need") == "waived"
            ):
                review = decision.get("waiver_review")
                if not isinstance(review, dict) or review.get("reviewed") is not True:
                    errors.append(
                        f"结构性展示需求 {scope}=waived，但缺少独立 waiver_review"
                    )
            if decision.get("presentation_need") != "required":
                continue
            role = "data_portrait" if scope == "whole_paper" else "question_hero"
            if opportunity_pool_mode:
                has_related_figure = any(
                    item.get("question_id") == scope
                    and item.get("role") != "stability"
                    for item in figures
                )
                if not has_related_figure and scope != "whole_paper":
                    errors.append(f"展示图决策 {scope}=required，但机会池尚未选择任何正文图")
                continue
            if not any(
                item.get("presentation_role") == role
                and (scope == "whole_paper" or item.get("question_id") == scope)
                for item in figures
            ):
                errors.append(f"展示图决策 {scope}=required，但计划中缺少 {role}")
        return errors
    except (OSError, TypeError, ValueError) as exc:
        return [f"无法读取首稿展示图决策：{exc}"]


def _reference_count_warnings(run_dir: Path) -> list[str]:
    """兼容旧调用，返回结构化引用覆盖报告中的建议。"""
    return citation_coverage_warnings(build_citation_coverage(run_dir))


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


def _paper_blueprint_path(run_dir: Path) -> Path:
    """返回当前论文结构蓝图；旧运行兼容 ``ARGUMENT_PLAN.md``。"""
    blueprint = run_dir / "paper" / "PAPER_BLUEPRINT.md"
    if blueprint.is_file():
        return blueprint
    return run_dir / "paper" / "ARGUMENT_PLAN.md"


def _argument_coverage_errors(
    run_dir: Path, *, unfinished_questions: set[str] | None = None
) -> list[str]:
    """生成论证覆盖矩阵并返回当前必须完成的问题缺口。"""
    try:
        from shumozizi.paper.blueprint import (
            build_argument_coverage,
            validate_argument_coverage,
        )

        document = build_argument_coverage(run_dir)
        errors = validate_argument_coverage(document)
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return [f"无法生成 paper/generated/argument_coverage.json: {exc}"]
    unfinished = unfinished_questions or set()
    return [
        item
        for item in errors
        if not any(item.startswith(f"{question_id}.") or item.startswith(f"{question_id} ") for question_id in unfinished)
    ]


def _valid_visual_waiver(decision: object) -> bool:
    """判断 FIGURE_PLAN 2.4 的豁免是否有独立复核和替代表达。"""
    if not isinstance(decision, dict) or decision.get("presentation_need") != "waived":
        return False
    review = decision.get("waiver_review")
    return (
        isinstance(review, dict)
        and review.get("reviewed") is True
        and review.get("verdict") == "waived"
        and review.get("replacement_medium")
        in {"equation", "table", "equation+table", "text"}
    )


def _visual_contract_text(unit: dict[str, Any]) -> str:
    """提取用于视觉义务推导的结构化合同文本。"""
    fields = (
        "visual_outputs",
        "data_contract",
        "simulation_contract",
        "capability_decision",
        "mathematical_structure",
        "primary_method",
        "answer_contract",
        "question_delta",
        "evaluation",
        "oracle",
    )
    return json.dumps(
        {key: unit[key] for key in fields if key in unit},
        ensure_ascii=False,
        sort_keys=True,
    )


def derive_required_visual_obligations(
    unit: dict[str, Any],
    blueprint_question: dict[str, Any] | None = None,
) -> set[str]:
    """从建模合同推导该问题真正需要的视觉论证义务。

    优先读取 ``visual_outputs``、题型合同和显式布尔决策；旧运行缺少这些
    字段时，才用数学结构与蓝图文本作兼容判断。函数只推导信息角色，不
    规定图数，因此一张合理的多面板图可以同时承担多项义务。

    Args:
        unit: ``MODELING_UNITS`` 中的单个问题单元。
        blueprint_question: 可选的逐问蓝图结构化记录。

    Returns:
        该问题需要由非稳定性正文图覆盖的义务集合。
    """
    obligations: set[str] = set()
    contract_text = _visual_contract_text(unit)
    fallback_text = json.dumps(
        {"unit": unit, "blueprint": blueprint_question or {}},
        ensure_ascii=False,
        sort_keys=True,
    )

    object_pattern = re.compile(
        r"几何|轨迹|空间|光路|并集|交集|覆盖|共享模型|共享参数|共享约束|"
        r"时间区间|事件|多阶段|聚合|aggregation",
        re.IGNORECASE,
    )
    decision_pattern = re.compile(
        r"模型选择|判别|不确定性|名义|稳健|nominal|robust|优化|权衡|活跃约束",
        re.IGNORECASE,
    )
    if unit.get("core_question") is True or object_pattern.search(fallback_text):
        obligations.add("model_structure")
    if unit.get("core_question") is True or decision_pattern.search(fallback_text):
        obligations.add("mechanism")

    data_pattern = re.compile(
        r"missing|outlier|censor|imbalance|class_balance|distribution|group(?:ing)?|"
        r"observational_unit|sampling_unit|cluster|spatial_density|temporal_density|"
        r"缺失|异常|删失|不平衡|分布|统计单位|观测单位|分组|聚集|密度",
        re.IGNORECASE,
    )
    if data_pattern.search(contract_text):
        obligations.add("data_intuition")

    uncertainty_pattern = re.compile(
        r"bootstrap|confidence_interval|prediction_interval|quantile|stochastic|"
        r"random_seed|scenario_distribution|parameter_distribution|fan_band|"
        r"nominal|robust|ranking_flip|rank_flip|置信区间|预测区间|分位数|"
        r"随机仿真|场景分布|参数分布|名义|稳健|排序翻转",
        re.IGNORECASE,
    )
    explicit_uncertainty = any(
        unit.get(key) is True
        for key in ("robustness_required", "uncertainty_required")
    )
    if explicit_uncertainty or uncertainty_pattern.search(contract_text):
        obligations.add("uncertainty")

    boundary_pattern = re.compile(
        r"feasible_(?:mask|region|set)|infeasible|active_constraint|constraint_slack|"
        r"threshold|critical_event|switch_point|safety_(?:boundary|region)|"
        r"可行域|不可行区|活跃约束|约束余量|阈值|临界事件|切换点|安全边界",
        re.IGNORECASE,
    )
    if boundary_pattern.search(contract_text):
        obligations.add("boundary")

    visual_result_pattern = re.compile(
        r"trajectory|curve|surface|field|pareto|candidate_points|alternative_points|"
        r"solution_set|spatial_(?:map|distribution)|interval_set|multi_solution|"
        r"轨迹|曲线|曲面|空间场|候选点|备选方案|解集|多方案|帕累托",
        re.IGNORECASE,
    )
    if visual_result_pattern.search(contract_text):
        obligations.add("result")
    return obligations


def _waived_visual_obligations(decision: object) -> set[str]:
    """读取现有 waiver_review 中按义务声明的替代表达。"""
    if not isinstance(decision, dict):
        return set()
    review = decision.get("waiver_review")
    if not isinstance(review, dict) or review.get("reviewed") is not True:
        return set()
    values = review.get("waived_obligation_types", [])
    if not isinstance(values, list):
        return set()
    return {str(value) for value in values if isinstance(value, str)}


def validate_figure_argument_obligations(run_dir: Path) -> list[str]:
    """要求结构性和核心问题的图真正承担模型理解与机制义务。

    Args:
        run_dir: 当前 Competition-First 运行目录。

    Returns:
        逐问及全文图表论证覆盖缺口。
    """
    plan_path = run_dir / _FIGURE_PLAN_PATH
    modeling_path = run_dir / "analysis" / "MODELING_UNITS.json"
    if not plan_path.is_file() or not modeling_path.is_file():
        return []
    try:
        plan = load_json(plan_path)
        modeling = load_json(modeling_path)
    except (OSError, TypeError, ValueError) as exc:
        return [f"无法复验图表论证义务: {exc}"]
    if plan.get("schema_version") != "2.4":
        return []
    decisions = {
        item.get("scope"): item
        for item in plan.get("visual_decisions", [])
        if isinstance(item, dict) and isinstance(item.get("scope"), str)
    }
    figures = [
        item
        for item in plan.get("figures", [])
        if isinstance(item, dict)
        and item.get("required") is True
        and item.get("role") != "stability"
    ]
    by_question: dict[str, set[str]] = {}
    for figure in figures:
        question_id = figure.get("question_id")
        if isinstance(question_id, str):
            by_question.setdefault(question_id, set()).update(
                str(item) for item in figure.get("obligation_types", [])
            )

    errors: list[str] = []
    for unit in modeling.get("units", []):
        if not isinstance(unit, dict) or not isinstance(unit.get("question_id"), str):
            continue
        question_id = unit["question_id"]
        decision = decisions.get(question_id)
        if _valid_visual_waiver(decision):
            continue
        required = derive_required_visual_obligations(unit)
        required -= _waived_visual_obligations(decision)
        covered = by_question.get(question_id, set())
        if "model_structure" in required and not covered.intersection(
            {"mathematical_object", "model_structure"}
        ):
            errors.append(
                f"{question_id} 缺少 mathematical_object/model_structure 图表义务覆盖"
            )
        if "mechanism" in required and not covered.intersection(
            {"mechanism", "comparison", "decision"}
        ):
            errors.append(f"{question_id} 缺少 mechanism/comparison/decision 图表义务覆盖")
        for obligation in sorted(
            required - {"model_structure", "mechanism"}
        ):
            if obligation not in covered:
                errors.append(f"{question_id} 缺少 {obligation} 图表义务覆盖")

    modeling_text = json.dumps(modeling, ensure_ascii=False)
    shared_signal = bool(re.search(r"共享模型|共享参数|跨问题|问题递进", modeling_text))
    all_obligations = {
        str(value)
        for figure in figures
        for value in figure.get("obligation_types", [])
    }
    if (
        shared_signal
        and not all_obligations.intersection({"mathematical_object", "model_structure"})
        and not _valid_visual_waiver(decisions.get("whole_paper"))
    ):
        errors.append("whole_paper 缺少共享数学对象或跨问模型结构表达")
    return errors


def _paper_review_closure_errors(run_dir: Path) -> list[str]:
    """复验批量返修 finding 与全部文风 warning 已明确处置。"""
    try:
        from shumozizi.paper.paper_review import load_paper_review, paper_review_errors

        document = load_paper_review(run_dir)
        errors = paper_review_errors(document, run_dir=run_dir)
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        return [f"PAPER_REVIEW 批量返修闭环无效: {exc}"]
    dispositions = {"accepted", "repaired", "false_positive", "deferred_with_reason"}
    findings = document.get("findings", [])
    try:
        style = audit_report_like_manuscript(run_dir)
    except (OSError, UnicodeError, KeyError, TypeError, ValueError) as exc:
        return errors + [f"无法把文风 warning 与 PAPER_REVIEW 对账: {exc}"]
    for warning in style.get("warnings", []):
        code = str(warning.get("code", ""))
        matched = next(
            (
                item
                for item in findings
                if isinstance(item, dict)
                and code
                and code.casefold()
                in json.dumps(item, ensure_ascii=False).casefold()
            ),
            None,
        )
        if matched is None or matched.get("status") not in dispositions:
            errors.append(f"文风 warning [{code}] 尚未在 PAPER_REVIEW 中处置")
        elif not matched.get("evidence_of_closure"):
            errors.append(f"文风 warning [{code}] 的处置缺少 closure 证据")
    return errors


def _argument_plan_warnings(run_dir: Path) -> list[str]:
    """检查核心问题是否在论文蓝图中有对应论证单元。

    轻量 warning（不阻断）：核心问题存在但论文蓝图缺少或
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

    plan_path = _paper_blueprint_path(run_dir)
    if not plan_path.is_file():
        core_ids = sorted(available)
        return [
            f"核心问题 {', '.join(core_ids)} 已提炼规律，但缺少 paper/PAPER_BLUEPRINT.md；"
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
        f"核心问题 {', '.join(missing)} 已提炼规律，但 paper/PAPER_BLUEPRINT.md "
        "中没有对应论证单元；写论文前请补充这些问题的论证单元规划。"
    ]


def _markdown_question_section(text: str, question_id: str) -> str | None:
    """提取 Markdown 中以问题编号命名的章节正文。"""
    heading = re.compile(
        rf"^(?P<marks>#{{1,4}})[^\n]*\b{re.escape(question_id)}\b[^\n]*$",
        re.MULTILINE | re.IGNORECASE,
    )
    match = heading.search(text)
    if match is None:
        return None
    level = len(match.group("marks"))
    following = re.compile(rf"^#{{1,{level}}}\s+", re.MULTILINE).search(text, match.end())
    end = following.start() if following is not None else len(text)
    return text[match.end() : end].strip()


def _substantive_markdown(path: Path, *, label: str, minimum_chars: int) -> tuple[str, list[str]]:
    """读取非占位 Markdown，并返回正文和就绪错误。"""
    if not path.is_file():
        return "", [f"可审阅草稿缺少 {label}"]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return "", [f"无法读取 {label}: {exc}"]
    body = re.sub(r"^#{1,6}\s+.*$", "", text, flags=re.MULTILINE).strip()
    meaningful = re.sub(r"\s+", "", body)
    if len(meaningful) < minimum_chars:
        return text, [f"{label} 内容过短，尚不足以形成可审阅论证"]
    placeholders = len(re.findall(r"待填写|待补充|TODO|TBD", text, flags=re.IGNORECASE))
    if placeholders and placeholders * 20 >= len(meaningful):
        return text, [f"{label} 仍以占位内容为主"]
    question_cards = re.findall(
        r"^##\s+(?:Q[1-9]\d*|问题[一二三四五六七八九十]+).*?(?=^##\s+|\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    if question_cards and all(
        re.search(r"待填写|待补充|TODO|TBD", card, flags=re.IGNORECASE)
        for card in question_cards
    ):
        return text, [f"{label} 的逐问完整性卡仍以占位内容为主"]
    return text, []


def require_reviewable_draft_argument_readiness(
    run_dir: Path, *, unfinished_questions: list[str]
) -> None:
    """要求首版草稿已经形成最小论文论证，而不要求所有问题完成。

    Args:
        run_dir: 当前 Competition-First v3.2 运行目录。
        unfinished_questions: 草稿披露页明确列出的未完成问题。

    Raises:
        ContractError: 论文蓝图或已完成核心问题仍是占位内容。
    """
    state = read_simple_state(run_dir)
    if not is_competition_first_v32_state(state):
        return
    blueprint_path = _paper_blueprint_path(run_dir)
    plan, errors = _substantive_markdown(
        blueprint_path,
        label="paper/PAPER_BLUEPRINT.md",
        minimum_chars=120,
    )
    from shumozizi.knowledge.retrieval import (
        evaluate_paper_knowledge_consumption,
        require_paper_knowledge_application,
    )

    try:
        require_paper_knowledge_application(run_dir)
        # 知识迁移只提供写作启发，不再拥有首稿放行权。
        evaluate_paper_knowledge_consumption(run_dir)
    except ContractError as exc:
        # 文件缺失或未填只影响建议质量；当前题证据仍由 answer-map 和真实结果控制。
        _ = exc
    if plan and not re.search(r"总体判断|中心判断|核心判断", plan):
        errors.append("PAPER_BLUEPRINT.md 缺少全篇总体判断")
    if plan and not re.search(r"论证链|章节作用|各问递进", plan):
        errors.append("PAPER_BLUEPRINT.md 缺少跨问题论证链")
    errors.extend(validate_presentation_decisions(run_dir))
    figure_plan_path = run_dir / _FIGURE_PLAN_PATH
    if figure_plan_path.is_file():
        try:
            if load_json(figure_plan_path).get("schema_version") == "2.4":
                errors.extend(
                    _argument_coverage_errors(
                        run_dir, unfinished_questions=set(unfinished_questions)
                    )
                )
                from shumozizi.paper.checkpoints import (
                    validate_paper_blueprint_review_checkpoint,
                )

                errors.extend(validate_paper_blueprint_review_checkpoint(run_dir))
        except (ContractError, OSError, TypeError, ValueError) as exc:
            errors.append(f"写作前蓝图审核 checkpoint 无法复验: {exc}")

    unfinished = set(unfinished_questions)
    core_questions: set[str] = set()
    modeling_path = run_dir / "analysis" / "MODELING_UNITS.json"
    if modeling_path.is_file():
        try:
            modeling = load_json(modeling_path)
            core_questions = {
                str(unit.get("question_id"))
                for unit in modeling.get("units", [])
                if isinstance(unit, dict) and unit.get("core_question") is True
            }
        except (OSError, ValueError):
            errors.append("analysis/MODELING_UNITS.json 无法读取，不能识别核心问题")

    required_markers = {
        "判断": r"关键判断|判断|命题|结论",
        "证据": r"证据|结果|计算|验证|实验",
        "竞争解释": r"竞争解释|替代解释|模型比较|路线比较|对照",
        "边界": r"边界|限制|适用|外推",
    }
    for question_id in state["required_questions"]:
        if question_id in unfinished:
            continue
        section = _markdown_question_section(plan, question_id) if plan else None
        if section is None or len(re.sub(r"\s+", "", section)) < 60:
            errors.append(f"已完成问题 {question_id} 在 PAPER_BLUEPRINT.md 中缺少实质完整性卡")
            continue
        if question_id not in core_questions:
            continue
        for label, pattern in required_markers.items():
            if not re.search(pattern, section):
                errors.append(f"已完成核心问题 {question_id} 的论证单元缺少{label}")
    if errors:
        raise ContractError("可审阅草稿尚未达到最小论证就绪条件: " + "；".join(errors))


def _validate_competition_readiness(run_dir: Path) -> tuple[list[str], list[str]]:
    """执行 Competition-First 最小论文硬门和可选写作警告。"""
    errors: list[str] = []
    warnings: list[str] = []
    if is_competition_first_v32_state(read_simple_state(run_dir)):
        from shumozizi.knowledge.retrieval import (
            evaluate_paper_knowledge_consumption,
        )
        from shumozizi.paper.cumcm_adapter import (
            evaluate_presentation_contract,
            require_cumcm_structure_map,
        )

        try:
            knowledge = evaluate_paper_knowledge_consumption(run_dir)
            warnings.extend(
                "知识迁移建议未兑现：" + message for message in knowledge["errors"]
            )
        except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
            warnings.append(f"知识迁移建议不可用：{exc}")
        try:
            from shumozizi.knowledge.usage import (
                build_knowledge_usage_report,
                build_paper_knowledge_context,
                knowledge_usage_errors,
                knowledge_usage_warnings,
            )

            usage = build_knowledge_usage_report(run_dir, stage="paper")
            usage_errors = knowledge_usage_errors(usage)
            warnings.extend("知识使用建议：" + item for item in usage_errors)
            warnings.extend("知识使用建议：" + item for item in knowledge_usage_warnings(usage))
            if not usage_errors:
                build_paper_knowledge_context(run_dir)
        except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
            warnings.append(f"知识使用报告不可用：{exc}")
        try:
            require_cumcm_structure_map(run_dir)
            realization = evaluate_presentation_contract(run_dir)
            if realization is not None:
                for item in realization["checks"]:
                    if item["status"] == "present":
                        continue
                    message = (
                        f"呈现合同 {item['check_id']} 为 {item['status']}"
                        f"（{item['location']}）：{item['issue']}"
                    )
                    warnings.append(message)
        except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
            errors.append(str(exc))
    answers = _competition_answer_map(run_dir)
    if answers is None:
        errors.append("缺少 paper/answer-map.json 或 analysis/answer_map.json")
        return errors, warnings
    required = _question_ids_from_state(run_dir)
    results = _current_production_results(run_dir)
    from shumozizi.simple.modeling_units import final_answer_selections

    selections = final_answer_selections(run_dir)
    for question_id in required:
        selection = selections.get(question_id)
        if is_competition_first_v32_state(read_simple_state(run_dir)) and selection is None:
            errors.append(f"必答问题 {question_id} 尚未形成系统派生的答案资格")
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
        if selection is not None:
            if selection["status"] == "redesign_required":
                errors.append(
                    f"必答问题 {question_id} 仍为 redesign_required，不能生成论文主答案"
                )
                continue
            primary_result_id = item.get("primary_result_id")
            if primary_result_id != selection["result_id"]:
                errors.append(
                    f"必答问题 {question_id} 的 primary_result_id 必须使用题面 "
                    f"objective_answer {selection['result_id']}"
                )
            elif isinstance(result_ids, list) and primary_result_id not in result_ids:
                errors.append(f"必答问题 {question_id} 的 primary_result_id 未列入 result_ids")
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
    if not _paper_blueprint_path(run_dir).is_file():
        warnings.append("缺少 paper/PAPER_BLUEPRINT.md；建议先明确主线、各问递进与核心图表。")
    if not (run_dir / "paper" / "CONTRIBUTION_BRIEF.md").is_file():
        warnings.append("缺少 paper/CONTRIBUTION_BRIEF.md；这不阻断普通问题的正确回答。")
    warnings.extend(_insight_figure_warnings(run_dir))
    warnings.extend(_argument_plan_warnings(run_dir))
    warnings.extend(presentation_figure_warnings(run_dir))
    try:
        citation_coverage = build_citation_coverage(run_dir)
        errors.extend(citation_coverage_errors(citation_coverage))
        warnings.extend(citation_coverage_warnings(citation_coverage))
    except (OSError, UnicodeError, KeyError, TypeError, ValueError) as exc:
        # 旧运行可能含非标准文献源；报告失败先显式告警，不能伪装成引用已闭环。
        warnings.append(f"引用覆盖报告不可用：{exc}")
    try:
        style_audit = audit_report_like_manuscript(run_dir)
        errors.extend(
            f"论文提交完整性[{item['code']}]：{item['message']}"
            for item in style_audit.get("errors", [])
        )
        warnings.extend(
            f"报告式写作告警[{item['code']}]：{item['message']}"
            for item in style_audit["warnings"]
        )
    except (OSError, UnicodeError, KeyError, TypeError, ValueError) as exc:
        # 文风检测是启发式辅助，读取失败不能夺取正式答案与论文编译的控制权。
        warnings.append(f"报告式写作检测不可用：{exc}")
    errors.extend(_code_appendix_errors(run_dir))
    warnings.extend(_core_insight_usage_errors(run_dir, answers))
    if is_competition_first_v32_state(read_simple_state(run_dir)):
        # Figure Plan 是可选的创作资产，但 Competition Candidate 不能因为它缺失
        # 就跳过视觉判断；机会池提供不强制固定图数的替代评估路径。
        errors.extend(validate_candidate_visual_assessment(run_dir))
        errors.extend(validate_required_figure_consumption(run_dir))
        plan_path = run_dir / _FIGURE_PLAN_PATH
        if plan_path.is_file():
            try:
                if load_json(plan_path).get("schema_version") == "2.4":
                    warnings.extend(_argument_coverage_errors(run_dir))
                    warnings.extend(validate_presentation_decisions(run_dir))
                    warnings.extend(validate_figure_argument_obligations(run_dir))
                    from shumozizi.paper.checkpoints import paper_checkpoint_errors

                    warnings.extend(paper_checkpoint_errors(run_dir, candidate=True))
                    warnings.extend(_paper_review_closure_errors(run_dir))
                    from shumozizi.simple.modeling_units import (
                        validate_visual_output_sources,
                    )

                    errors.extend(validate_visual_output_sources(run_dir))
            except (ContractError, OSError, TypeError, ValueError) as exc:
                errors.append(f"FIGURE_PLAN 2.4 竞争力合同无法复验: {exc}")
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
    state = read_simple_state(run_dir)
    competition = str(state.get("competition", "")).strip().casefold()
    if competition == "cumcm" or "全国大学生数学建模竞赛" in competition:
        if appendix.get("mode") != "pdf":
            return ["CUMCM 2026 要求完整源码进入论文附录，source_code_appendix.mode 必须为 pdf"]
        if not appendix.get("included_roles"):
            return ["CUMCM 2026 完整源码附录必须声明 included_roles"]
        # CUMCM Profile 已提供赛事依据，不再要求每个运行重复手写豁免字段。
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
    """返回兼容旧协议的编译就绪结果，并补充论文层级状态。

    ``ready`` 仍表示旧的严格候选稿硬门；新增的 ``scientific_ready``、
    ``narrative_ready`` 和 ``competition_paper_ready`` 用于 v3.4 的长篇首稿与
    编辑裁剪流程，避免把“有科学答案”误报成“已完成竞赛论文”。
    """
    run_dir = run_dir.resolve()
    errors = _validate_readiness(run_dir)
    warnings: list[str] = []
    if is_competition_first_state(read_simple_state(run_dir)):
        _, warnings = _validate_competition_readiness(run_dir)
    layers = classify_paper_readiness(run_dir)
    return {
        "ready": not errors,
        "errors": errors,
        "warnings": warnings,
        "scientific_ready": layers["scientific_ready"],
        "narrative_ready": layers["narrative_ready"],
        "competition_paper_ready": layers["competition_paper_ready"],
        "layer_errors": layers["scientific_errors"],
        "narrative_findings": layers["narrative_findings"],
        "run_dir": str(run_dir),
    }


def _manuscript_text_for_layers(run_dir: Path) -> str:
    """读取论文正文源文件的可见文本，避开控制文档和生成目录。"""
    paper_dir = run_dir / "paper"
    if not paper_dir.is_dir():
        return ""
    excluded = {"generated", "submission", "source_appendix", "archive", "work"}
    chunks: list[str] = []
    for path in sorted(paper_dir.rglob("*")):
        if (
            not path.is_file()
            or path.suffix.casefold() not in {".tex", ".typ", ".md"}
            or any(part.casefold() in excluded for part in path.parts)
            or path.name.startswith("PAPER_")
            or path.name in {
                "ARGUMENT_PLAN.md",
                "STORYBOARD.md",
                "RESEARCH_STORYBOARD.md",
                "CITATION_PLAN.md",
            }
        ):
            continue
        try:
            chunks.append(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            continue
    return "\n".join(chunks)


def classify_paper_readiness(run_dir: Path) -> dict[str, Any]:
    """区分科学证据层、论叙层与竞赛候选稿层的就绪状态。

    科学层只要求可定位的直接答案、公式/判据和至少一种结果或图示证据；
    机制、结构观察、推导展开和边界属于叙事层，缺失时只能阻断竞赛稿，不
    会把已有科学答案抹掉。这正是“答案预览可先出现但不能提前收尾”的实现。
    """
    root = run_dir.resolve()
    text = _manuscript_text_for_layers(root)
    style = audit_report_like_manuscript(root)
    compact = re.sub(r"\s+", "", text)
    has_answer = bool(re.search(r"直接答案|答案|结论|最优|可行解|判定为", text, re.IGNORECASE))
    has_formula = bool(re.search(r"\\begin\{(?:equation|align)|\\\[|\$\$|公式|判据", text, re.IGNORECASE))
    has_evidence = bool(
        re.search(r"\\begin\{figure|\\includegraphics|!\[[^]]*\]\(|结果|实验|验证|表明", text, re.IGNORECASE)
    )
    scientific_errors: list[str] = []
    if not compact:
        scientific_errors.append("尚无可读取的论文正文")
    if not has_answer:
        scientific_errors.append("正文尚无可定位的直接答案或结论")
    if not has_formula:
        scientific_errors.append("正文尚无公式、判据或数学对象表达")
    if not has_evidence:
        scientific_errors.append("正文尚无结果、验证或图示证据")

    narrative_findings: list[dict[str, Any]] = []
    warning_codes = {
        "PAPER_SECTION_UNDERDEVELOPED",
        "REPORT_STYLE_PATTERN",
        "FIGURE_WITHOUT_INTERPRETATION",
        "FORMULA_WITHOUT_EXPLANATION",
        "NARRATIVE_SCARCITY_REVIEW",
        "VISUAL_SCARCITY_REVIEW",
    }
    for finding in style.get("warnings", []):
        if finding.get("code") in warning_codes:
            narrative_findings.append(finding)
    # 没有正文层可验证的机制、结构和边界时，科学答案仍然可以先进入长篇首稿，
    # 但候选稿必须显式提醒编辑补全，而不是依靠篇幅数字自动放行。
    required_roles = (
        ("结构观察", r"观察|结构|规律|拐点|集中|分层"),
        ("机制解释", r"机制|原因|活跃约束|瓶颈|边际收益|权衡"),
        ("边界说明", r"边界|限制|适用|敏感性|不能外推"),
    )
    for label, pattern in required_roles:
        if not re.search(pattern, text, re.IGNORECASE):
            narrative_findings.append(
                {
                    "code": "PAPER_SECTION_UNDERDEVELOPED",
                    "message": f"正文尚未展开{label}，答案预览不能替代该论证角色。",
                    "missing_role": label,
                }
            )
    narrative_ready = not narrative_findings
    strict_ready = check_paper_readiness_strict(root)
    return {
        "scientific_ready": not scientific_errors,
        "scientific_errors": scientific_errors,
        "narrative_ready": narrative_ready,
        "narrative_findings": narrative_findings,
        "competition_paper_ready": not scientific_errors and strict_ready,
        "metrics": {
            "has_answer": has_answer,
            "has_formula": has_formula,
            "has_evidence": has_evidence,
            "characters": len(compact),
        },
    }


def check_paper_readiness_strict(run_dir: Path) -> bool:
    """执行旧的严格论文硬门而不递归调用分层检查。"""
    try:
        return not _validate_readiness(run_dir)
    except (ContractError, OSError, KeyError, TypeError, ValueError):
        return False


def require_scientific_readiness(run_dir: Path) -> None:
    """要求论文已有最小科学答案层，但不要求竞赛叙事完整。"""
    status = classify_paper_readiness(run_dir)
    if not status["scientific_ready"]:
        raise ContractError(
            "长篇科学首稿缺少最小科学证据层:\n- "
            + "\n- ".join(status["scientific_errors"])
        )


def require_competition_paper_readiness(run_dir: Path) -> None:
    """要求候选竞赛稿同时通过科学、叙事与旧协议硬门。"""
    status = check_paper_readiness(run_dir)
    if not status["competition_paper_ready"]:
        reasons = [*status["layer_errors"]]
        reasons.extend(
            str(item.get("message", item)) for item in status["narrative_findings"]
        )
        reasons.extend(status["errors"])
        raise ContractError("竞赛论文尚未完成:\n- " + "\n- ".join(dict.fromkeys(reasons)))


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
