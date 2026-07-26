"""管理网页版讨论的本地先行、延迟揭示与实现总结协议。

该协议是可选的研究辅助：它把网页讨论限制为对用户提供材料的假设、反例与
实验建议，不把任何网页内容升级为模型事实、结果证据或最优性证明。没有创建
这些文件的运行保持原有 v3.2 行为，不会因此被阻断。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    load_json,
    resolve_inside,
    sha256_bytes,
    sha256_file,
    sha256_tree,
)
from shumozizi.simple.state import is_competition_first_v32_state, read_simple_state, utc_now

LOCAL_ROUTE_SNAPSHOT_PATH = Path("analysis/LOCAL_ROUTE_SNAPSHOT.json")
EXTERNAL_DISCUSSION_SESSION_PATH = Path("analysis/EXTERNAL_DISCUSSION_SESSION.json")
EXTERNAL_DISCUSSION_COMPARISON_PATH = Path("analysis/EXTERNAL_DISCUSSION_COMPARISON.json")
EXTERNAL_DISCUSSION_SYNTHESIS_PATH = Path("analysis/EXTERNAL_DISCUSSION_SYNTHESIS.json")
WEB_PAPER_AUDIT_PROMPT_PATH = Path("review/WEB_PAPER_AUDIT_PROMPT.json")
WEB_PAPER_AUDIT_PATH = Path("review/WEB_PAPER_AUDIT.json")
WEB_PAPER_REPAIR_PLAN_PATH = Path("review/WEB_PAPER_REPAIR_PLAN.json")
WEB_PAPER_AUDIT_HISTORY_DIR = Path("review/web-paper-audit-history")
WEB_PAPER_AUDIT_FAILURE_PATH = Path("review/WEB_PAPER_AUDIT_FAILURE.json")
WEB_PAPER_AUDIT_MAX_ROUNDS = 3
_RELATIONSHIPS = frozenset({"agrees", "new_hypothesis", "conflicts", "rejected"})
_PAPER_AUDIT_PRIORITIES = frozenset({"P0", "P1", "P2", "P3"})
_REPAIR_DISPOSITIONS = frozenset({"fix", "defer_with_limit", "reject_with_evidence"})


def _require_v32_run(run_dir: Path) -> dict[str, Any]:
    """确认协议只写入 Competition-First v3.2 运行目录。"""
    state = read_simple_state(run_dir)
    if not is_competition_first_v32_state(state):
        raise ContractError("网页讨论协议只服务于 Competition-First v3.2 运行")
    return state


def _text(value: object, label: str) -> str:
    """读取非空文本，拒绝用占位文本伪造已完成的分析。"""
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} 必须是非空文本")
    return value.strip()


def _mapping(value: object, label: str) -> dict[str, Any]:
    """读取对象字段，提供明确的合同错误位置。"""
    if not isinstance(value, dict):
        raise ContractError(f"{label} 必须是对象")
    return value


def _text_list(value: object, label: str, *, minimum: int = 1) -> list[str]:
    """读取去重的非空文本列表。"""
    if not isinstance(value, list) or len(value) < minimum:
        raise ContractError(f"{label} 至少需要 {minimum} 项")
    result = [_text(item, f"{label}[]") for item in value]
    if len(set(result)) != len(result):
        raise ContractError(f"{label} 不得重复")
    return result


def _problem_binding(run_dir: Path) -> dict[str, Any]:
    """绑定当前题面，防止本地路线静默引入外部材料。"""
    problem_dir = run_dir / "problem"
    if not problem_dir.is_dir() or not any(item.is_file() for item in problem_dir.rglob("*")):
        raise ContractError("网页讨论协议需要非空 problem/ 题面输入")
    return {"input_scope": ["problem/"], "problem_tree_sha256": sha256_tree(problem_dir)}


def _validate_routes(value: object, label: str) -> list[dict[str, str]]:
    """验证结构上不同的竞争路线，避免只更换同类求解器。"""
    if not isinstance(value, list) or len(value) < 2:
        raise ContractError(f"{label} 至少需要两条竞争路线")
    routes: list[dict[str, str]] = []
    for index, raw in enumerate(value):
        route = _mapping(raw, f"{label}[{index}]")
        routes.append(
            {
                "route_id": _text(route.get("route_id"), f"{label}[{index}].route_id"),
                "mathematical_structure": _text(
                    route.get("mathematical_structure"), f"{label}[{index}].mathematical_structure"
                ),
                "summary": _text(route.get("summary"), f"{label}[{index}].summary"),
            }
        )
    if len({route["route_id"] for route in routes}) != len(routes):
        raise ContractError(f"{label} 的 route_id 不得重复")
    if len({route["mathematical_structure"] for route in routes}) != len(routes):
        raise ContractError(f"{label} 必须具有不同 mathematical_structure")
    return routes


def _validate_local_snapshot(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """校验本地路线快照确实先于网页回应且仅使用题面。"""
    state = _require_v32_run(run_dir)
    if payload.get("schema_version") != "1.0" or payload.get("run_id") != state["run_id"]:
        raise ContractError("LOCAL_ROUTE_SNAPSHOT 的 schema_version 或 run_id 不匹配")
    question_id = _text(payload.get("question_id"), "question_id")
    if question_id not in state["required_questions"]:
        raise ContractError("LOCAL_ROUTE_SNAPSHOT.question_id 不是必答问题")
    if payload.get("input_bindings") != _problem_binding(run_dir):
        raise ContractError("LOCAL_ROUTE_SNAPSHOT 必须只绑定当前 problem/")
    if payload.get("external_material_read") is not False:
        raise ContractError("本地路线冻结前不得读取网页回应或其它外部建议")
    if payload.get("status") != "frozen":
        raise ContractError("LOCAL_ROUTE_SNAPSHOT.status 必须为 frozen")
    revision = payload.get("revision")
    if not isinstance(revision, int) or revision < 1:
        raise ContractError("LOCAL_ROUTE_SNAPSHOT.revision 必须是从 1 开始的整数")
    _text(payload.get("frozen_at"), "frozen_at")
    route = _mapping(payload.get("local_route"), "local_route")
    baseline = _mapping(route.get("baseline"), "local_route.baseline")
    normalized = {
        "objective": _text(route.get("objective"), "local_route.objective"),
        "baseline": {
            "mathematical_structure": _text(
                baseline.get("mathematical_structure"), "local_route.baseline.mathematical_structure"
            ),
            "summary": _text(baseline.get("summary"), "local_route.baseline.summary"),
        },
        "competitive_routes": _validate_routes(route.get("competitive_routes"), "local_route.competitive_routes"),
        "fallback": _text(route.get("fallback"), "local_route.fallback"),
        "discriminating_probes": _text_list(
            route.get("discriminating_probes"), "local_route.discriminating_probes"
        ),
        "post_first_feasible_rule": _text(
            route.get("post_first_feasible_rule"), "local_route.post_first_feasible_rule"
        ),
    }
    return normalized


def write_local_route_snapshot(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """原子冻结未阅读网页回应的本地路线。

    Args:
        run_dir: 当前 v3.2 运行目录。
        payload: 仅由题面推导的路线、baseline、竞争路线和 probe。

    Returns:
        已写入 ``analysis/LOCAL_ROUTE_SNAPSHOT.json`` 的快照。
    """
    state = _require_v32_run(run_dir)
    question_id = _text(payload.get("question_id"), "question_id")
    route = _mapping(payload.get("local_route"), "local_route")
    path = run_dir / LOCAL_ROUTE_SNAPSHOT_PATH
    revision = 1
    if path.is_file():
        existing = load_json(path)
        _validate_local_snapshot(run_dir, existing)
        revision = int(existing["revision"]) + 1
    document = {
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "question_id": question_id,
        "input_bindings": _problem_binding(run_dir),
        "external_material_read": False,
        "status": "frozen",
        "revision": revision,
        "frozen_at": utc_now(),
        "local_route": route,
    }
    _validate_local_snapshot(run_dir, document)
    atomic_json(path, document)
    return document


def _validate_session(run_dir: Path, payload: dict[str, Any]) -> None:
    """校验网页讨论只接收题面且不会被提前阅读。"""
    state = _require_v32_run(run_dir)
    snapshot_path = run_dir / LOCAL_ROUTE_SNAPSHOT_PATH
    if not snapshot_path.is_file():
        raise ContractError("启动网页讨论前必须先冻结 LOCAL_ROUTE_SNAPSHOT")
    _validate_local_snapshot(run_dir, load_json(snapshot_path))
    if payload.get("schema_version") != "1.0" or payload.get("run_id") != state["run_id"]:
        raise ContractError("EXTERNAL_DISCUSSION_SESSION 的 schema_version 或 run_id 不匹配")
    _text(payload.get("discussion_id"), "discussion_id")
    if payload.get("provider") != "web_gpt":
        raise ContractError("EXTERNAL_DISCUSSION_SESSION.provider 当前必须为 web_gpt")
    if payload.get("input_bindings") != _problem_binding(run_dir):
        raise ContractError("网页讨论只能接收当前 problem/")
    if payload.get("local_route_disclosed") is not False:
        raise ContractError("并行网页讨论不得预先接收本地路线")
    if payload.get("online_answer_search_used") is not False:
        raise ContractError("网页版讨论禁止联网检索题目答案、题解或现成结论")
    if payload.get("response_read") is not False:
        raise ContractError("首次网页讨论收据必须承诺延迟阅读回应")
    if payload.get("local_route_snapshot_sha256") != sha256_file(snapshot_path):
        raise ContractError("网页讨论未绑定当前冻结的本地路线")
    _text(payload.get("started_at"), "started_at")


def record_external_discussion_launch(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """登记可与本地撰写并行发送、但不得提前阅读的网页讨论。"""
    state = _require_v32_run(run_dir)
    snapshot_path = run_dir / LOCAL_ROUTE_SNAPSHOT_PATH
    if not snapshot_path.is_file():
        raise ContractError("启动网页讨论前必须先冻结 LOCAL_ROUTE_SNAPSHOT")
    document = {
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "discussion_id": _text(payload.get("discussion_id"), "discussion_id"),
        "provider": "web_gpt",
        "input_bindings": _problem_binding(run_dir),
        "local_route_disclosed": False,
        "online_answer_search_used": False,
        "response_read": False,
        "local_route_snapshot_sha256": sha256_file(snapshot_path),
        "started_at": utc_now(),
        "purpose": "仅讨论题意、建模假设、反例、验证与论文组织；不提供现成解。",
    }
    _validate_session(run_dir, document)
    atomic_json(run_dir / EXTERNAL_DISCUSSION_SESSION_PATH, document)
    return document


def _validate_comparison(run_dir: Path, payload: dict[str, Any]) -> None:
    """校验读取网页建议发生在本地路线冻结之后，并附带验证动作。"""
    state = _require_v32_run(run_dir)
    session_path = run_dir / EXTERNAL_DISCUSSION_SESSION_PATH
    snapshot_path = run_dir / LOCAL_ROUTE_SNAPSHOT_PATH
    if not session_path.is_file():
        raise ContractError("比较网页建议前必须先登记 EXTERNAL_DISCUSSION_SESSION")
    session = load_json(session_path)
    _validate_session(run_dir, session)
    if payload.get("schema_version") != "1.0" or payload.get("run_id") != state["run_id"]:
        raise ContractError("EXTERNAL_DISCUSSION_COMPARISON 的 schema_version 或 run_id 不匹配")
    if payload.get("discussion_id") != session["discussion_id"]:
        raise ContractError("比较必须绑定同一个网页讨论 ID")
    if payload.get("local_route_snapshot_sha256") != sha256_file(snapshot_path):
        raise ContractError("比较时本地路线已漂移；必须重新发起网页讨论")
    if payload.get("response_read_after_local_freeze") is not True:
        raise ContractError("只有本地路线冻结后才可读取网页回应")
    if payload.get("online_answer_search_used") is not False:
        raise ContractError("比较记录不得将网页答案检索包装成讨论")
    if payload.get("advisory_only") is not True:
        raise ContractError("网页比较必须保持 advisory_only")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ContractError("EXTERNAL_DISCUSSION_COMPARISON 至少需要一项差异比较")
    for index, raw in enumerate(items):
        item = _mapping(raw, f"items[{index}]")
        _text(item.get("local_element"), f"items[{index}].local_element")
        _text(item.get("external_suggestion"), f"items[{index}].external_suggestion")
        if item.get("relationship") not in _RELATIONSHIPS:
            raise ContractError(f"items[{index}].relationship 不合法")
        _text(item.get("local_decision"), f"items[{index}].local_decision")
        _text(item.get("verification"), f"items[{index}].verification")
    _text(payload.get("compared_at"), "compared_at")


def record_external_discussion_comparison(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """记录本地路线与网页建议的差异及其本地验证计划。"""
    state = _require_v32_run(run_dir)
    session = load_json(run_dir / EXTERNAL_DISCUSSION_SESSION_PATH)
    snapshot_path = run_dir / LOCAL_ROUTE_SNAPSHOT_PATH
    document = {
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "discussion_id": session["discussion_id"],
        "local_route_snapshot_sha256": sha256_file(snapshot_path),
        "response_read_after_local_freeze": True,
        "online_answer_search_used": False,
        "advisory_only": True,
        "items": payload.get("items"),
        "compared_at": utc_now(),
    }
    _validate_comparison(run_dir, document)
    atomic_json(run_dir / EXTERNAL_DISCUSSION_COMPARISON_PATH, document)
    return document


def _synthesis_prompt(snapshot: dict[str, Any], comparison: dict[str, Any]) -> str:
    """生成给全新网页对话的受限实现总结提示。"""
    route = snapshot["local_route"]
    lines = [
        "这是一次数学建模实现总结的受限讨论。你是新的独立对话，不得沿用、搜索或引用任何网页题解、往届论文、相近题现成结论或本题答案。",
        "只可根据下列本地路线和已标为 advisory 的差异记录提出可验证的实现建议；不要给出可直接提交的数值策略、Excel 填表结果或无证据的最优性结论。",
        "本地 exact scorer、真实实验和独立复算是唯一能比较候选并寻找最优或最强可行下界的依据。",
        "请输出：1. 优先实现顺序；2. 每条路线的最低成本区分性实验；3. 首解后的异构深化；4. exact scorer 与独立 oracle 的关键测试；5. 何时切换 fallback；6. 论文可写与不可写的边界。",
        "本地冻结路线：",
        f"- 统一目标：{route['objective']}",
        f"- baseline：{route['baseline']['mathematical_structure']}；{route['baseline']['summary']}",
    ]
    for candidate in route["competitive_routes"]:
        lines.append(
            f"- 竞争路线 {candidate['route_id']}：{candidate['mathematical_structure']}；{candidate['summary']}"
        )
    lines.extend(
        [
            f"- fallback：{route['fallback']}",
            f"- 首解后规则：{route['post_first_feasible_rule']}",
            "差异记录（均未验证）：",
        ]
    )
    for item in comparison["items"]:
        lines.append(
            f"- [{item['relationship']}] 本地：{item['local_element']}；建议：{item['external_suggestion']}；"
            f"本地处理：{item['local_decision']}；验证：{item['verification']}"
        )
    return "\n".join(lines) + "\n"


def create_implementation_synthesis(run_dir: Path) -> dict[str, Any]:
    """生成只可交给全新网页对话的实现总结提示，不自动采纳其结论。"""
    state = _require_v32_run(run_dir)
    snapshot_path = run_dir / LOCAL_ROUTE_SNAPSHOT_PATH
    comparison_path = run_dir / EXTERNAL_DISCUSSION_COMPARISON_PATH
    if not comparison_path.is_file():
        raise ContractError("创建实现总结前必须完成 EXTERNAL_DISCUSSION_COMPARISON")
    snapshot = load_json(snapshot_path)
    comparison = load_json(comparison_path)
    _validate_local_snapshot(run_dir, snapshot)
    _validate_comparison(run_dir, comparison)
    document = {
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "fresh_thread_required": True,
        "resume_existing_forbidden": True,
        "online_answer_search_prohibited": True,
        "advisory_only": True,
        "local_route_snapshot_sha256": sha256_file(snapshot_path),
        "comparison_sha256": sha256_file(comparison_path),
        "created_at": utc_now(),
        "prompt": _synthesis_prompt(snapshot, comparison),
    }
    atomic_json(run_dir / EXTERNAL_DISCUSSION_SYNTHESIS_PATH, document)
    return document


def validate_external_discussion_protocol_if_present(run_dir: Path) -> None:
    """在产物存在时校验网页讨论顺序；不存在时保持工作流可选性。"""
    paths = [
        run_dir / LOCAL_ROUTE_SNAPSHOT_PATH,
        run_dir / EXTERNAL_DISCUSSION_SESSION_PATH,
        run_dir / EXTERNAL_DISCUSSION_COMPARISON_PATH,
        run_dir / EXTERNAL_DISCUSSION_SYNTHESIS_PATH,
    ]
    if not any(path.is_file() for path in paths):
        return
    if not paths[0].is_file():
        raise ContractError("网页讨论协议缺少 LOCAL_ROUTE_SNAPSHOT")
    snapshot = load_json(paths[0])
    _validate_local_snapshot(run_dir, snapshot)
    if paths[1].is_file():
        _validate_session(run_dir, load_json(paths[1]))
    elif paths[2].is_file() or paths[3].is_file():
        raise ContractError("网页讨论协议缺少 EXTERNAL_DISCUSSION_SESSION")
    if paths[2].is_file():
        _validate_comparison(run_dir, load_json(paths[2]))
    elif paths[3].is_file():
        raise ContractError("网页讨论协议缺少 EXTERNAL_DISCUSSION_COMPARISON")
    if paths[3].is_file():
        synthesis = load_json(paths[3])
        if (
            synthesis.get("schema_version") != "1.0"
            or synthesis.get("run_id") != snapshot["run_id"]
            or synthesis.get("fresh_thread_required") is not True
            or synthesis.get("resume_existing_forbidden") is not True
            or synthesis.get("online_answer_search_prohibited") is not True
            or synthesis.get("advisory_only") is not True
            or synthesis.get("local_route_snapshot_sha256") != sha256_file(paths[0])
            or synthesis.get("comparison_sha256") != sha256_file(paths[2])
        ):
            raise ContractError("EXTERNAL_DISCUSSION_SYNTHESIS 未保持新对话和本地验证边界")
        _text(synthesis.get("prompt"), "EXTERNAL_DISCUSSION_SYNTHESIS.prompt")


def _paper_audit_prompt() -> str:
    # 编辑审核提示词：只允许依据冻结 PDF 作答。
    # 用于模型和结果已稳定后的可选编辑审查，聚焦写作质量，
    # 不重复 PDF 盲评已做的竞争力定位。
    return (
        "这是一次数学建模论文的编辑审核。你只收到一份冻结 PDF；"
        "不要联网搜索、引用或复用任何外部资料。"
        "必须只根据 PDF 内部的数学定义、推导、数值、表格、图和版式进行核查。\n\n"
        "请按以下顺序作答：\n\n"
        "一、写作风格问题（优先检查）\n"
        "逐一检查以下 AI 生成文本的典型特征，发现后给出页码/位置和原文片段：\n"
        "1. 分点堆砌：大量首先-其次-最后或(1)(2)(3)编号，分点多但每点内容薄，"
        "删掉后正文反而更清晰。\n"
        "2. 固定句式：多段以「针对问题X，本文采用……方法，得到……结果，表明……」"
        "相同结构反复出现，换掉数字后内容几乎没有差别。\n"
        "3. 空话总结：模型具有较强鲁棒性、方法行之有效、理论基础扎实——"
        "这类句子没有任何证据支撑，删掉不损失信息。\n"
        "4. 结论重复正文：结论节只是把各问数字再列一遍，"
        "没有解释为什么结果呈现这个形态。\n"
        "5. 讨论缺位：某些章节给出了数值却没有说明原因，"
        "读者不知道最优解呈现这个结构的原因。\n\n"
        "二、可读性评估\n"
        "评价普通读者能否顺畅理解建模思路：\n"
        "- 核心建模判断是否用一句话清楚说明（为何选择这个模型而非其他）？\n"
        "- 符号和变量是否在使用前定义？\n"
        "- 图表是否有实质论证功能，还是仅为装饰？\n"
        "- 数值结果是否有解释（不只是说效果良好）？\n"
        "指出最难读懂的两处，说明具体原因。\n\n"
        "三、最高价值修改（不超过 5 条，按预期收益排序）\n"
        "允许建议重写某个章节、替换主图、删除冗余分点、合并重复内容。\n"
        "允许指出需要回到实验增加机制讨论或 Pareto 分析。\n"
        "不要默认优先局部修补：发现根本性问题时直接说明需要重构，"
        "只有不影响模型、结果和论证主线的问题才建议最小修改。\n\n"
        "四、P0/P1（仅限本轮发现的新阻断性问题）\n"
        "只列出前序盲评未发现、且真正可能影响评分的严重问题。"
        "如果没有新发现，直接写：无新增 P0/P1。\n"
        "P2/P3 小问题附在报告末尾，不展开。\n"
    )

def _paper_pdf_binding(run_dir: Path, relative_path: object) -> dict[str, str]:
    """绑定网页审核唯一允许接收的冻结 PDF。"""
    relative = _text(relative_path, "pdf_path")
    path = resolve_inside(run_dir, relative, must_exist=True)
    if path.suffix.lower() != ".pdf":
        raise ContractError("网页版论文审核只能接收 PDF 文件")
    return {"path": path.relative_to(run_dir).as_posix(), "sha256": sha256_file(path)}


def _archive_web_paper_audit_cycle(run_dir: Path, next_pdf: dict[str, str]) -> None:
    """归档被新一轮网页审核替代的报告和修复计划。

    修订 PDF 后旧审核不能继续作为当前论文的证据。保留其完整内容是为了追溯
    已修复问题；随后移除工作路径下的旧文件，避免它们与新 PDF 的哈希混用。
    """
    paths = (
        run_dir / WEB_PAPER_AUDIT_PROMPT_PATH,
        run_dir / WEB_PAPER_AUDIT_PATH,
        run_dir / WEB_PAPER_REPAIR_PLAN_PATH,
    )
    if not any(path.is_file() for path in paths[1:]):
        return
    archived: dict[str, Any] = {
        "schema_version": "1.0",
        "run_id": _require_v32_run(run_dir)["run_id"],
        "archived_at": utc_now(),
        "reason": "开始针对当前 PDF 的新网页审核周期",
        "next_pdf": next_pdf,
        "artifacts": {},
    }
    for path in paths:
        if path.is_file():
            archived["artifacts"][path.name] = load_json(path)
    timestamp = archived["archived_at"].replace(":", "").replace("-", "")
    archive_path = run_dir / WEB_PAPER_AUDIT_HISTORY_DIR / f"{timestamp}-{next_pdf['sha256'][:12]}.json"
    atomic_json(archive_path, archived)
    for path in paths[1:]:
        path.unlink(missing_ok=True)


def _web_paper_audit_round_count(run_dir: Path) -> int:
    """统计已导入的网页审核轮次，不将未发送的提示词计为一轮。"""
    count = 0
    history_dir = run_dir / WEB_PAPER_AUDIT_HISTORY_DIR
    if history_dir.is_dir():
        for path in sorted(history_dir.glob("*.json")):
            archived = load_json(path)
            artifacts = archived.get("artifacts") if isinstance(archived, dict) else None
            audit = artifacts.get(WEB_PAPER_AUDIT_PATH.name) if isinstance(artifacts, dict) else None
            if isinstance(audit, dict) and isinstance(audit.get("web_chat_id"), str):
                count += 1
    current_path = run_dir / WEB_PAPER_AUDIT_PATH
    if current_path.is_file():
        current = load_json(current_path)
        if isinstance(current, dict) and isinstance(current.get("web_chat_id"), str):
            count += 1
    return count


def create_web_paper_audit_prompt(run_dir: Path, pdf_path: str = "paper/final.pdf") -> dict[str, Any]:
    """创建只附 PDF、禁止检索答案的网页版论文审核提示。

    该收据不会替代 Codex fresh-thread PDF 盲评。它仅约束额外的网页审查输入，
    并使后续报告可被当前 PDF 的哈希复验。
    """
    state = _require_v32_run(run_dir)
    pdf = _paper_pdf_binding(run_dir, pdf_path)
    rounds = _web_paper_audit_round_count(run_dir)
    if rounds >= WEB_PAPER_AUDIT_MAX_ROUNDS:
        raise ContractError(
            "网页版论文审核已达到三轮上限；请写入 WEB_PAPER_AUDIT_FAILURE，"
            "说明工作流、建模、证据和论文问题后回到相应阶段修复"
        )
    _archive_web_paper_audit_cycle(run_dir, pdf)
    prompt = _paper_audit_prompt()
    document = {
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "purpose": "网页版 GPT 的补充 PDF 审核，不替代 fresh-thread 盲评或本地复算。",
        "attachment_scope": [pdf],
        "online_answer_search_prohibited": True,
        "fresh_web_chat_required": True,
        "only_pdf_and_prompt": True,
        "round_number": rounds + 1,
        "max_rounds": WEB_PAPER_AUDIT_MAX_ROUNDS,
        "created_at": utc_now(),
        "prompt": prompt,
        "prompt_sha256": sha256_bytes(prompt.encode("utf-8")),
    }
    atomic_json(run_dir / WEB_PAPER_AUDIT_PROMPT_PATH, document)
    return document


def _no_online_references(value: object, label: str) -> None:
    """拒绝把外部检索链接混入只读 PDF 审核报告。"""
    serialized = json.dumps(value, ensure_ascii=False)
    if re.search(r"https?://|www\\.", serialized, flags=re.IGNORECASE):
        raise ContractError(f"{label} 不得包含联网检索或外部引用")


def _validate_web_paper_audit(run_dir: Path, payload: dict[str, Any]) -> list[dict[str, str]]:
    """校验网页审核只绑定当前 PDF、固定提示和基本格式。

    不再强制要求固定字段（competitive_position / argument_and_evidence 等），
    也不强制每条 finding 必须有完整的六项栏目——审核者可以用自由文本说明
    需要重构章节或回到实验，不能被拉回逐项填格子。
    """
    state = _require_v32_run(run_dir)
    prompt_path = run_dir / WEB_PAPER_AUDIT_PROMPT_PATH
    if not prompt_path.is_file():
        raise ContractError("导入网页论文审核前必须先生成 WEB_PAPER_AUDIT_PROMPT")
    prompt = load_json(prompt_path)
    if payload.get("schema_version") != "1.0" or payload.get("run_id") != state["run_id"]:
        raise ContractError("WEB_PAPER_AUDIT 的 schema_version 或 run_id 不匹配")
    if payload.get("fresh_web_chat") is not True:
        raise ContractError("网页版论文审核必须使用全新网页对话")
    if payload.get("online_answer_search_used") is not False:
        raise ContractError("网页版论文审核禁止联网检索题目答案或现成结论")
    if payload.get("advisory_only") is not True:
        raise ContractError("网页版论文审核必须保持 advisory_only")
    if payload.get("attachment_scope") != prompt.get("attachment_scope"):
        raise ContractError("网页版论文审核不得接收 PDF 之外的材料")
    if payload.get("prompt_sha256") != prompt.get("prompt_sha256"):
        raise ContractError("网页版论文审核提示词与冻结版本不一致")
    _text(payload.get("web_chat_id"), "web_chat_id")
    # report 允许自由文本或结构化字典，只要非空即可
    report = payload.get("report")
    if not report:
        raise ContractError("WEB_PAPER_AUDIT.report 不能为空")
    # findings 可以是空列表（审核者认为无新问题时）或包含优先级注释的条目
    findings = payload.get("findings")
    if not isinstance(findings, list):
        raise ContractError("WEB_PAPER_AUDIT.findings 必须是数组（可以为空）")
    normalized: list[dict[str, str]] = []
    ids: set[str] = set()
    for index, raw in enumerate(findings):
        finding = _mapping(raw, f"findings[{index}]")
        identifier = _text(finding.get("finding_id"), f"findings[{index}].finding_id")
        if identifier in ids:
            raise ContractError("WEB_PAPER_AUDIT.finding_id 不得重复")
        ids.add(identifier)
        priority = finding.get("priority")
        if priority not in _PAPER_AUDIT_PRIORITIES:
            raise ContractError(f"findings[{index}].priority 必须为 P0/P1/P2/P3")
        # issue 是唯一必填项，其余字段（location/impact/proposed_fix/verification）可选
        _text(finding.get("issue"), f"findings[{index}].issue")
        normalized.append(
            {
                "finding_id": identifier,
                "priority": priority,
                "issue": finding["issue"],
                "location": finding.get("location", ""),
                "impact": finding.get("impact", ""),
                "proposed_fix": finding.get("proposed_fix", ""),
                "verification": finding.get("verification", ""),
            }
        )
    _no_online_references(payload, "WEB_PAPER_AUDIT")
    _text(payload.get("reviewed_at"), "reviewed_at")
    return normalized


def record_web_paper_audit(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """导入网页版 PDF 审核的结构化报告，但不把它当作论文事实。"""
    state = _require_v32_run(run_dir)
    prompt = load_json(run_dir / WEB_PAPER_AUDIT_PROMPT_PATH)
    document = {
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "web_chat_id": _text(payload.get("web_chat_id"), "web_chat_id"),
        "fresh_web_chat": True,
        "online_answer_search_used": False,
        "advisory_only": True,
        "attachment_scope": prompt["attachment_scope"],
        "prompt_sha256": prompt["prompt_sha256"],
        "report": payload.get("report"),
        "findings": payload.get("findings", []),
        "reviewed_at": utc_now(),
    }
    _validate_web_paper_audit(run_dir, document)
    atomic_json(run_dir / WEB_PAPER_AUDIT_PATH, document)
    return document


def _safe_repair_paths(value: object, label: str) -> list[str]:
    """限制修复文件在运行目录内，避免审核建议引入越界写入。"""
    paths = _text_list(value, label)
    for path in paths:
        candidate = Path(path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ContractError(f"{label} 必须是运行目录内路径")
    return paths


def _validate_web_paper_repair_plan(run_dir: Path, payload: dict[str, Any]) -> None:
    """验证网页修复计划绑定了当前审核报告，以及基本格式正确。

    移除了 targeted_repair_only=True 的强制要求：提示词已明确允许审核者指出
    需要重写章节或回到实验，代码不应再把它拉回「只能局部修补」。
    P0/P1 仍然要求给出修复动作，但不强制所有 finding 都必须逐项出现在计划里——
    审核者可以选择哪些问题值得跟进，哪些可以忽略。
    """
    state = _require_v32_run(run_dir)
    audit_path = run_dir / WEB_PAPER_AUDIT_PATH
    if not audit_path.is_file():
        raise ContractError("制定网页论文修复计划前必须导入 WEB_PAPER_AUDIT")
    audit = load_json(audit_path)
    findings = _validate_web_paper_audit(run_dir, audit)
    if payload.get("schema_version") != "1.0" or payload.get("run_id") != state["run_id"]:
        raise ContractError("WEB_PAPER_REPAIR_PLAN 的 schema_version 或 run_id 不匹配")
    if payload.get("audit_sha256") != sha256_file(audit_path):
        raise ContractError("WEB_PAPER_REPAIR_PLAN 未绑定当前网页审核报告")
    # full_rewrite 允许为 True（允许重构），但需要写明理由
    if payload.get("full_rewrite") is True:
        _text(payload.get("rewrite_justification"), "rewrite_justification")
    repairs = payload.get("repairs")
    if not isinstance(repairs, list):
        raise ContractError("WEB_PAPER_REPAIR_PLAN.repairs 必须是数组（可以为空）")
    p0p1_ids = {f["finding_id"] for f in findings if f["priority"] in {"P0", "P1"}}
    repair_ids: set[str] = set()
    audit_ids = {f["finding_id"] for f in findings}
    for index, raw in enumerate(repairs):
        repair = _mapping(raw, f"repairs[{index}]")
        identifier = _text(repair.get("finding_id"), f"repairs[{index}].finding_id")
        if identifier not in audit_ids or identifier in repair_ids:
            raise ContractError("WEB_PAPER_REPAIR_PLAN 不能引用不存在的 finding_id 或重复闭合")
        repair_ids.add(identifier)
        disposition = repair.get("disposition")
        if disposition not in _REPAIR_DISPOSITIONS:
            raise ContractError(f"repairs[{index}].disposition 不合法")
        _text(repair.get("action"), f"repairs[{index}].action")
    # P0/P1 必须出现在修复计划里（但可以 disposition=defer 并写明原因）
    missing_critical = p0p1_ids - repair_ids
    if missing_critical:
        raise ContractError(
            "P0/P1 网页审核发现必须在修复计划中出现: " + ", ".join(sorted(missing_critical))
        )
    if payload.get("competition_rank_guarantee") is not False:
        raise ContractError("网页审核不能作为竞赛名次或省一保证")
    _text(payload.get("planned_at"), "planned_at")


def write_web_paper_repair_plan(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """把网页审核发现转为修复计划。允许重构章节，不强制全部局部修补。"""
    state = _require_v32_run(run_dir)
    audit_path = run_dir / WEB_PAPER_AUDIT_PATH
    document = {
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "audit_sha256": sha256_file(audit_path),
        "full_rewrite": payload.get("full_rewrite", False),
        "rewrite_justification": payload.get("rewrite_justification"),
        "repairs": payload.get("repairs"),
        "competition_rank_guarantee": False,
        "planned_at": utc_now(),
    }
    _validate_web_paper_repair_plan(run_dir, document)
    atomic_json(run_dir / WEB_PAPER_REPAIR_PLAN_PATH, document)
    return document


def validate_web_paper_audit_if_present(run_dir: Path) -> None:
    """复验已有网页 PDF 审核和修复计划；未使用时不形成阶段门。"""
    prompt_path = run_dir / WEB_PAPER_AUDIT_PROMPT_PATH
    audit_path = run_dir / WEB_PAPER_AUDIT_PATH
    plan_path = run_dir / WEB_PAPER_REPAIR_PLAN_PATH
    if not any(path.is_file() for path in (prompt_path, audit_path, plan_path)):
        return
    if not prompt_path.is_file():
        raise ContractError("网页版论文审核缺少 WEB_PAPER_AUDIT_PROMPT")
    prompt = load_json(prompt_path)
    prompt_text = prompt.get("prompt")
    _text(prompt_text, "prompt")
    if (
        prompt.get("online_answer_search_prohibited") is not True
        or prompt.get("fresh_web_chat_required") is not True
        or prompt.get("only_pdf_and_prompt") is not True
        or not isinstance(prompt_text, str)
        or prompt.get("prompt_sha256") != sha256_bytes(prompt_text.encode("utf-8"))
    ):
        raise ContractError("WEB_PAPER_AUDIT_PROMPT 未保持仅 PDF、禁止检索和新对话边界")
    scope = prompt.get("attachment_scope")
    if not isinstance(scope, list) or len(scope) != 1:
        raise ContractError("WEB_PAPER_AUDIT_PROMPT 必须且只能绑定一个 PDF")
    current_pdf = _paper_pdf_binding(run_dir, scope[0].get("path") if isinstance(scope[0], dict) else None)
    if scope != [current_pdf]:
        raise ContractError("网页论文审核 PDF 已发生变化，必须生成新提示并重新审核")
    if audit_path.is_file():
        _validate_web_paper_audit(run_dir, load_json(audit_path))
    elif plan_path.is_file():
        raise ContractError("网页版论文审核缺少 WEB_PAPER_AUDIT")
    if plan_path.is_file():
        _validate_web_paper_repair_plan(run_dir, load_json(plan_path))
    failure_path = run_dir / WEB_PAPER_AUDIT_FAILURE_PATH
    if failure_path.is_file():
        _validate_web_paper_audit_failure(run_dir, load_json(failure_path))


def _validate_web_paper_audit_failure(run_dir: Path, payload: dict[str, Any]) -> None:
    """校验三轮网页审核失败后的复盘确实定位到可修复环节。"""
    state = _require_v32_run(run_dir)
    audit_path = run_dir / WEB_PAPER_AUDIT_PATH
    prompt_path = run_dir / WEB_PAPER_AUDIT_PROMPT_PATH
    if payload.get("schema_version") != "1.0" or payload.get("run_id") != state["run_id"]:
        raise ContractError("WEB_PAPER_AUDIT_FAILURE 的 schema_version 或 run_id 不匹配")
    if payload.get("status") != "not_submission_ready":
        raise ContractError("WEB_PAPER_AUDIT_FAILURE.status 必须为 not_submission_ready")
    if payload.get("round_count") != WEB_PAPER_AUDIT_MAX_ROUNDS:
        raise ContractError("WEB_PAPER_AUDIT_FAILURE 只能在第三轮失败后写入")
    if not audit_path.is_file() or not prompt_path.is_file():
        raise ContractError("WEB_PAPER_AUDIT_FAILURE 缺少当前审核或提示词")
    if payload.get("current_audit_sha256") != sha256_file(audit_path):
        raise ContractError("WEB_PAPER_AUDIT_FAILURE 未绑定当前审核报告")
    prompt = load_json(prompt_path)
    if payload.get("attachment_scope") != prompt.get("attachment_scope"):
        raise ContractError("WEB_PAPER_AUDIT_FAILURE 未绑定当前 PDF")
    findings = _validate_web_paper_audit(run_dir, load_json(audit_path))
    blocking = sorted(
        finding["finding_id"] for finding in findings if finding["priority"] in {"P0", "P1"}
    )
    if payload.get("blocking_findings") != blocking or not blocking:
        raise ContractError("WEB_PAPER_AUDIT_FAILURE 必须记录当前 P0/P1")
    _text(payload.get("summary"), "summary")
    _text_list(payload.get("workflow_issues"), "workflow_issues")
    _text_list(payload.get("modeling_issues"), "modeling_issues")
    _text_list(payload.get("evidence_issues"), "evidence_issues")
    _text_list(payload.get("paper_issues"), "paper_issues")
    _text_list(payload.get("next_actions"), "next_actions")
    if payload.get("competition_rank_guarantee") is not False:
        raise ContractError("失败复盘不得声称竞赛名次或奖项结果")
    _text(payload.get("recorded_at"), "recorded_at")


def write_web_paper_audit_failure(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """记录第三轮仍未通过时的失败原因，阻止无限审核循环。"""
    state = _require_v32_run(run_dir)
    if _web_paper_audit_round_count(run_dir) != WEB_PAPER_AUDIT_MAX_ROUNDS:
        raise ContractError("只有恰好完成三轮网页审核后才可写失败复盘")
    prompt = load_json(run_dir / WEB_PAPER_AUDIT_PROMPT_PATH)
    audit_path = run_dir / WEB_PAPER_AUDIT_PATH
    findings = _validate_web_paper_audit(run_dir, load_json(audit_path))
    document = {
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "status": "not_submission_ready",
        "round_count": WEB_PAPER_AUDIT_MAX_ROUNDS,
        "current_audit_sha256": sha256_file(audit_path),
        "attachment_scope": prompt["attachment_scope"],
        "blocking_findings": sorted(
            finding["finding_id"] for finding in findings if finding["priority"] in {"P0", "P1"}
        ),
        "summary": _text(payload.get("summary"), "summary"),
        "workflow_issues": payload.get("workflow_issues"),
        "modeling_issues": payload.get("modeling_issues"),
        "evidence_issues": payload.get("evidence_issues"),
        "paper_issues": payload.get("paper_issues"),
        "next_actions": payload.get("next_actions"),
        "competition_rank_guarantee": False,
        "recorded_at": utc_now(),
    }
    _validate_web_paper_audit_failure(run_dir, document)
    atomic_json(run_dir / WEB_PAPER_AUDIT_FAILURE_PATH, document)
    return document


def web_paper_audit_status(run_dir: Path) -> dict[str, Any]:
    """判断当前 PDF 是否已完成网页审核与必要的局部处置。

    该状态只说明审核意见已被处理到可继续终检的程度，不表示模型正确、
    竞争力充分或任何奖项结果。
    """
    root = run_dir.resolve()
    try:
        _require_v32_run(root)
        prompt_path = root / WEB_PAPER_AUDIT_PROMPT_PATH
        audit_path = root / WEB_PAPER_AUDIT_PATH
        plan_path = root / WEB_PAPER_REPAIR_PLAN_PATH
        if not prompt_path.is_file() or not audit_path.is_file():
            return {"allowed": False, "reason": "当前 PDF 缺少网页版 GPT 审核报告"}
        validate_web_paper_audit_if_present(root)
        findings = _validate_web_paper_audit(root, load_json(audit_path))
        rounds = _web_paper_audit_round_count(root)
        blocking = [
            finding["finding_id"]
            for finding in findings
            if finding["priority"] in {"P0", "P1"}
        ]
        if blocking:
            if rounds >= WEB_PAPER_AUDIT_MAX_ROUNDS:
                failure_path = root / WEB_PAPER_AUDIT_FAILURE_PATH
                suffix = "已写入失败复盘" if failure_path.is_file() else "必须写入失败复盘"
                reason = "网页版 GPT 审核三轮后仍有 P0/P1，" + suffix
            else:
                reason = "网页版 GPT 审核仍有 P0/P1：" + ", ".join(blocking)
            return {
                "allowed": False,
                "reason": reason,
                "blocking_findings": blocking,
                "round_count": rounds,
            }
        if findings and not plan_path.is_file():
            return {"allowed": False, "reason": "网页版 GPT 审核发现尚未写入局部修复计划"}
        return {
            "allowed": True,
            "reason": "",
            "finding_count": len(findings),
            "round_count": rounds,
            "max_rounds": WEB_PAPER_AUDIT_MAX_ROUNDS,
            "requires_followup_plan": bool(findings),
            "advisory_only": True,
            "competition_rank_guarantee": False,
        }
    except (ContractError, OSError, TypeError, ValueError) as exc:
        return {"allowed": False, "reason": "网页版 GPT 审核无效：" + str(exc)}


def require_web_paper_audit_release(run_dir: Path) -> None:
    """要求当前 PDF 已通过网页审核的放行边界。"""
    status = web_paper_audit_status(run_dir)
    if not status["allowed"]:
        raise ContractError("不能进入终检：" + status["reason"])
