"""Repair Loop v1：把"路由"从标签升级为具有行为语义的命令。

背景：过去 ``route=experiment / analysis`` 只是记录在裁决台账里，然后把
authoring_status 标成 ``rework_requested``，顶层 phase 从未切回 experiment，
也没有任何真正会被执行的修复任务——这是纸面闭环，不是执行闭环。

本模块引入 RepairDirective 台账：

    finding / author request
        → adjudication
        → open_repair_directive（记录可执行修复动作 + 负责人阶段 + 验收测试）
        → apply_repair_route（真正执行：切 phase / 建 visual opportunity /
          标记 author 返工 / 标记需要重渲染）
        → close_repair_directive（必须提供验收证据，验收不过不能 close）

原则：
- 问题空间 open-world：``finding_class`` 允许 ``unclassified``，新问题能进入系统；
- 动作空间 closed-world：``route`` 只允许 ``author/visual/experiment/analysis/render``，
  不允许 Agent 发明未知执行动作；
- 同一修复指令未关闭时，交接与交付被阻断（``require_no_open_repairs``），
  保证"验收不过不能 close"不是一句空话。
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.core.schema import require_valid
from shumozizi.simple.state import ALLOWED_PHASE_TRANSITIONS, update_simple_state, utc_now

REPAIR_DIRECTIVES_PATH = Path("paper/repair-directives.json")
# 动作空间封闭：修复路由只允许这五种，不允许扩展成未知执行动作。
REPAIR_ROUTES = ("author", "visual", "experiment", "analysis", "render")


def _ledger(run_dir: Path) -> dict[str, Any]:
    """读取修复指令台账；缺失时返回空台账。"""
    path = run_dir / REPAIR_DIRECTIVES_PATH
    if not path.is_file():
        return {
            "schema_name": "repair_directives",
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "directives": [],
        }
    payload = load_json(path)
    require_valid(payload, "repair_directives")
    return payload


def _save(run_dir: Path, payload: dict[str, Any]) -> None:
    """原子落盘台账。"""
    require_valid(payload, "repair_directives")
    atomic_json(run_dir / REPAIR_DIRECTIVES_PATH, payload)


def open_repair_directive(
    run_dir: Path,
    *,
    directive_id: str,
    source: str,
    finding_class: str,
    route: str,
    owner_stage: str,
    repair_action: str,
    acceptance_test: str,
    acceptance_roles: list[str] | None = None,
    affected_questions: list[str] | None = None,
    requires_new_evidence: bool = False,
    waivable: bool = False,
) -> dict[str, Any]:
    """登记一条待执行的修复指令。

    Args:
        run_dir: 当前运行目录。
        directive_id: 唯一指令 ID（通常绑定 finding_id 或 gap_id）。
        source: 来源描述（如 ``reviewer finding F-12`` 或 ``author request gap-3``）。
        finding_class: 问题类别；``unclassified`` 表示现有分类无法覆盖的新问题。
        route: 修复路由，必须属于 ``REPAIR_ROUTES``（动作空间封闭）。
        owner_stage: 负责人阶段（如 ``experiment`` / ``analysis`` / ``author``）。
        repair_action: 可执行的具体修复动作描述。
        acceptance_test: 确定性验收测试；不满足时指令不能 close。
        acceptance_roles: 多部分科学修复必须分别覆盖的证据角色；为空时只要求
            一项合格生产结果，避免为简单修复增加不必要表单。
        affected_questions: 受影响的问题 ID 列表。
        requires_new_evidence: 是否必须产出新的生产证据才能验收。
        waivable: 是否允许评审豁免。

    Returns:
        已写入的指令条目。

    Raises:
        ContractError: 路由非法、指令 ID 重复或字段缺失。
    """
    if route not in REPAIR_ROUTES:
        raise ContractError(f"未知修复路由: {route}（动作空间封闭，只允许 {REPAIR_ROUTES}）")
    payload = _ledger(run_dir)
    if any(item["directive_id"] == directive_id for item in payload["directives"]):
        raise ContractError(f"修复指令已存在: {directive_id}")
    entry = {
        "directive_id": directive_id,
        "source": source,
        "finding_class": finding_class,
        "affected_questions": list(dict.fromkeys(affected_questions or [])),
        "route": route,
        "owner_stage": owner_stage,
        "repair_action": repair_action,
        "requires_new_evidence": requires_new_evidence,
        "acceptance_test": acceptance_test,
        "acceptance_roles": list(dict.fromkeys(acceptance_roles or [])),
        "waivable": waivable,
        "status": "open",
        "opened_at": utc_now(),
        "closed_at": None,
        "render_required": False,
        "closure": None,
    }
    require_valid(
        {
            "schema_name": "repair_directives",
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "directives": [entry],
        },
        "repair_directives",
    )
    payload["directives"].append(entry)
    _save(run_dir, payload)
    return entry


def _phase_path(current: str, target: str) -> list[str] | None:
    """在合法阶段迁移图上找最短路径（BFS）。

    例如 ``paper_review → experiment`` 不直接合法，但可以通过
    ``paper_review → paper → experiment`` 到达；``paper → analysis``
    则经过 ``paper → experiment → analysis``。
    """
    if current == target:
        return [current]
    frontier: deque[tuple[str, list[str]]] = deque([(current, [current])])
    visited = {current}
    while frontier:
        node, path = frontier.popleft()
        # 排序迭代保证 set 顺序不污染路径选择（确定性 BFS）。
        # blocked/complete 只能作为修复目标，不能作为途经阶段：blocked 表示
        # 真实生产失败，绕行它会掩盖失败状态；complete 是死胡同终态。
        for nxt in sorted(ALLOWED_PHASE_TRANSITIONS[node]):
            if nxt in {"blocked", "complete"} and nxt != target:
                continue
            if nxt in visited:
                continue
            visited.add(nxt)
            next_path = [*path, nxt]
            if nxt == target:
                return next_path
            frontier.append((nxt, next_path))
    return None


def _route_phase(run_dir: Path, target: str) -> None:
    """把顶层 phase 沿合法迁移路径真正切到目标阶段。"""
    from shumozizi.simple.state import read_simple_state

    current = read_simple_state(run_dir)["phase"]
    path = _phase_path(current, target)
    if path is None:
        raise ContractError(
            f"修复路由无法从 {current} 到达 {target}（合法迁移图不可达）"
        )
    for hop in path[1:]:
        update_simple_state(run_dir, phase=hop)


def apply_repair_route(run_dir: Path, directive_id: str) -> dict[str, Any]:
    """执行一条修复指令的路由（行为语义，不是标签）。

    Args:
        run_dir: 当前运行目录。
        directive_id: 已登记的修复指令 ID。

    Returns:
        更新后的指令条目。

    Raises:
        ContractError: 指令不存在或已关闭；路由执行失败。
    """
    payload = _ledger(run_dir)
    entry = next(
        (item for item in payload["directives"] if item["directive_id"] == directive_id),
        None,
    )
    if entry is None:
        raise ContractError(f"修复指令不存在: {directive_id}")
    if entry["status"] != "open":
        raise ContractError(f"修复指令已关闭: {directive_id}")

    route = entry["route"]
    if route == "experiment":
        _route_phase(run_dir, "experiment")
    elif route == "analysis":
        _route_phase(run_dir, "analysis")
    elif route == "visual":
        from shumozizi.simple.visual_opportunities import add_visual_opportunity

        add_visual_opportunity(
            run_dir,
            opportunity_id=f"repair-{directive_id}",
            question_id=entry["affected_questions"][0]
            if entry["affected_questions"]
            else None,
            visual_question=entry["repair_action"],
            atomic_claim=entry["acceptance_test"],
            candidate_archetypes=["undecided"],
            origin="repair_directive",
            provenance={"directive_id": directive_id, "source": entry["source"]},
        )
    elif route == "author":
        from shumozizi.simple.authoring import (
            mark_authoring_status,
            read_authoring,
        )

        authoring = read_authoring(run_dir)
        if (
            authoring["authoring_mode"] == "external_handoff"
            and authoring["authoring_status"] == "draft_imported"
        ):
            mark_authoring_status(run_dir, "rework_requested")
    elif route == "render":
        entry["render_required"] = True

    _save(run_dir, payload)
    return entry


def close_repair_directive(
    run_dir: Path,
    directive_id: str,
    *,
    acceptance_evidence: str,
    verified: bool = False,
    acceptance_result_ids: list[str] | None = None,
    acceptance_bindings: dict[str, str] | None = None,
) -> dict[str, Any]:
    """关闭修复指令：必须提供验收证据，验收不过不能 close。

    Args:
        run_dir: 当前运行目录。
        directive_id: 待关闭指令 ID。
        acceptance_evidence: 验收证据（如何满足 acceptance_test 的说明）；
            已通过机械核验时用 ``verified=True`` 补充。
        verified: 是否由确定性机制复核通过（如测试、文件核验）。
        acceptance_result_ids: 验收所绑定的生产结果。需要新证据的分析/实验
            修复必须至少绑定一项在指令打开后产生的 current production 结果。
        acceptance_bindings: “验收角色→结果 ID”的绑定。指令声明多个角色时，
            必须逐项绑定不同结果，防止用一个局部实验关闭整组修复。

    Returns:
        更新后的指令条目。

    Raises:
        ContractError: 证据为空、指令不存在或已关闭。
    """
    if not isinstance(acceptance_evidence, str) or not acceptance_evidence.strip():
        raise ContractError("关闭修复指令必须提供非空验收证据")
    payload = _ledger(run_dir)
    entry = next(
        (item for item in payload["directives"] if item["directive_id"] == directive_id),
        None,
    )
    if entry is None:
        raise ContractError(f"修复指令不存在: {directive_id}")
    if entry["status"] != "open":
        raise ContractError(f"修复指令已关闭: {directive_id}")
    bindings = dict(acceptance_bindings or {})
    required_roles = entry.get("acceptance_roles", [])
    if required_roles:
        if set(bindings) != set(required_roles):
            raise ContractError(
                "修复验收角色未完整覆盖: "
                + ", ".join(sorted(set(required_roles) - set(bindings)))
            )
        if len(set(bindings.values())) != len(bindings):
            raise ContractError("不同验收角色必须绑定不同 production 结果")
    identifiers = list(
        dict.fromkeys([*(acceptance_result_ids or []), *bindings.values()])
    )
    if entry.get("requires_new_evidence"):
        if verified is not True:
            raise ContractError("需要新科学证据的修复必须通过确定性验收（verified=true）")
        if not identifiers:
            raise ContractError("需要新科学证据的修复必须绑定验收 production 结果")
        from shumozizi.simple.results import read_result_index

        results = {
            item["result_id"]: item
            for item in read_result_index(run_dir)["results"]
        }
        for result_id in identifiers:
            result = results.get(result_id)
            if (
                result is None
                or result.get("execution_mode") != "production"
                or result.get("execution_valid") is not True
                or result.get("status") != "current"
                or result.get("scientific_status", "valid") == "invalidated"
            ):
                raise ContractError(
                    f"验收结果 {result_id} 必须是科学有效的 current production"
                )
            if result.get("created_at", "") < entry["opened_at"]:
                raise ContractError(
                    f"验收结果 {result_id} 必须在修复指令打开后产生"
                )
    entry["status"] = "closed"
    entry["closed_at"] = utc_now()
    entry["closure"] = {
        "acceptance_evidence": acceptance_evidence.strip(),
        "verified": bool(verified),
        "acceptance_result_ids": identifiers,
        "acceptance_bindings": bindings,
    }
    _save(run_dir, payload)
    return entry


def open_repair_directives(run_dir: Path) -> list[dict[str, Any]]:
    """返回全部未关闭的修复指令。"""
    return [item for item in _ledger(run_dir)["directives"] if item["status"] == "open"]


def require_no_open_repairs(run_dir: Path) -> None:
    """未关闭的修复指令阻断交接与交付；全部关闭才放行。"""
    open_items = open_repair_directives(run_dir)
    if not open_items:
        return
    details = "、".join(
        f"{item['directive_id']}(route={item['route']})" for item in open_items
    )
    raise ContractError(f"存在未关闭的修复指令（验收不过不能 close）: {details}")
