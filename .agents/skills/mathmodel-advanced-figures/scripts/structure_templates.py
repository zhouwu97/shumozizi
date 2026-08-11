"""结构图 TikZ 模板：structure spec -> 确定性 TikZ 布局（AI 决定语义，程序决定几何）。

三个高频模板，不发展成模板动物园：

- shared_model_map：中央共享模型/核心状态，左输入右输出、上下状态/约束。
- problem_progression：多问继承，水平递进 Q1 -> Q2 -> ...，边标注"上一问如何进入下一问"。
- mechanism_decision：输入 -> 状态更新 -> 条件/阈值 -> 输出，可带反馈回环。

布局由节点的语义角色决定（center/input/output/state/top/bottom），不是坐标。
模板只固定版式语法（坐标、间距、线型、强调），LLM 只填数学对象、关系与强调层级。

边界：TikZ 只负责解释性结构图，不进入 evidence layer。
spec 的 argument_role 若为 decisive_evidence，renderer 拒绝（必须走数据 renderer）。
"""
from __future__ import annotations

from typing import Any

# 模板仅允许这些 argument_role（解释性）；证据类被 render_structure 拒绝。
ALLOWED_STRUCTURE_ROLES = frozenset(
    {"model_understanding", "mechanism", "boundary", "insight", "tradeoff", "stability"}
)
BLOCKED_EVIDENCE_ROLES = frozenset({"decisive_evidence"})

# 语义角色 -> 节点风格
_STYLES = {
    "center": "draw=teal!70!black, very thick, rounded corners, align=center",
    "center_math": "draw=none, align=center",  # 数学对象无边框，避免流程图味
    "input": "draw, rounded corners, align=center",
    "output": "draw, rounded corners, align=center",
    "state": "draw=gray, dashed, rounded corners, align=center",
    "top": "draw=gray, rounded corners, align=center",
    "bottom": "draw=gray, rounded corners, align=center",
    "default": "draw, rounded corners, align=center",
}
_EMPHASIS = "fill=teal!8!white"
_FEED = "->, >=stealth, line width=0.8pt"
_INHERIT = "->, >=stealth, dashed, line width=0.7pt"
_FEEDBACK = "->, >=stealth, bend left=25, line width=0.7pt, color=gray!70!black"
_CONDITION = "->, >=stealth, line width=0.8pt, color=gray!70!black"


def _esc(text: str) -> str:
    """把普通标签转义成 LaTeX 安全文本（保留已转义的输入）。"""
    return str(text).replace("%", "\\%").replace("_", "\\_").replace("#", "\\#")


def _node_tex(node: dict[str, Any], x: float, y: float, emph: bool) -> str:
    """单个节点 -> TikZ \\node。有 math 字段用公式排版，否则用 label 文本。"""
    nid = str(node.get("id", "n")).replace(" ", "")
    role = str(node.get("role", "default"))
    has_math = bool(node.get("math"))
    style = _STYLES.get("center_math" if (has_math and role == "center") else role, _STYLES["default"])
    if emph and not has_math:
        style = style + ", " + _EMPHASIS
    content = f"${str(node['math'])}$" if has_math else _esc(node.get("label", nid))
    return f"\\node[{style}] ({nid}) at ({x},{y}) {{{content}}};"


def _edge(from_id: str, to_id: str, kind: str, label: str = "") -> str:
    """一条边 -> TikZ \\draw；kind 决定线型（feed/inherit/feedback/condition）。"""
    arrow = {"feed": _FEED, "inherit": _INHERIT, "feedback": _FEEDBACK, "condition": _CONDITION}.get(
        str(kind), _FEED
    )
    label_tex = f" node[midway, fill=white, font=\\scriptsize] {{{_esc(label)}}}" if label else ""
    return f"\\draw[{arrow}] ({from_id}) {label_tex} -- ({to_id});"


def _nodes_by_role(spec: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_role: dict[str, list[dict[str, Any]]] = {}
    for node in spec.get("nodes", []):
        if isinstance(node, dict):
            by_role.setdefault(str(node.get("role", "default")), []).append(node)
    return by_role


def _ids(spec: dict[str, Any]) -> set[str]:
    return {str(n.get("id", "")).replace(" ", "") for n in spec.get("nodes", []) if isinstance(n, dict)}


def _emphasis_ids(spec: dict[str, Any]) -> set[str]:
    """emphasis 是节点 id 的字符串列表（不是 dict 列表）。"""
    value = spec.get("emphasis", [])
    if isinstance(value, list):
        return {str(item).replace(" ", "") for item in value if str(item).strip()}
    return {str(value).replace(" ", "")} if str(value).strip() else set()


def render_shared_model_map(spec: dict[str, Any]) -> str:
    """中央共享模型/核心状态，左输入右输出、上下状态/约束。"""
    by_role = _nodes_by_role(spec)
    centers = by_role.get("center") or by_role.get("default", [])
    center = centers[0] if centers else {"id": "core", "label": spec.get("title", "共享模型")}
    inputs = by_role.get("input", [])
    outputs = by_role.get("output", [])
    states = by_role.get("state", []) + by_role.get("top", []) + by_role.get("bottom", [])
    emph = _emphasis_ids(spec)
    lines = [_node_tex(center, 0.0, 0.0, str(center.get("id", "")) in emph)]
    cid = str(center.get("id", "core")).replace(" ", "")
    n_in, n_out = len(inputs), len(outputs)
    for i, node in enumerate(inputs):
        y = (n_in - 1) * 0.8 / 2 - i * 0.8 if n_in else 0.0
        nid = str(node.get("id", f"in{i}")).replace(" ", "")
        lines.append(_node_tex(node, -4.2, y, nid in emph))
        lines.append(_edge(nid, cid, "feed"))
    for j, node in enumerate(outputs):
        y = (n_out - 1) * 0.8 / 2 - j * 0.8 if n_out else 0.0
        nid = str(node.get("id", f"out{j}")).replace(" ", "")
        lines.append(_node_tex(node, 4.2, y, nid in emph))
        lines.append(_edge(cid, nid, "inherit"))
    for k, node in enumerate(states):
        nid = str(node.get("id", f"st{k}")).replace(" ", "")
        y = 1.8 + k * 1.0
        lines.append(_node_tex(node, 0.0, y, nid in emph))
        lines.append(_edge(nid, cid, "condition"))
    # 反馈边：任一节点 kind=feedback 的连接画回环。
    for edge in spec.get("edges", []):
        if isinstance(edge, dict) and edge.get("kind") == "feedback":
            lines.append(_edge(str(edge["from"]), str(edge["to"]), "feedback", str(edge.get("label", ""))))
    return "\n".join(lines)


def render_problem_progression(spec: dict[str, Any]) -> str:
    """多问继承：水平递进 Q1 -> Q2 -> ...，边标注上一问结果如何进入下一问。"""
    nodes = [n for n in spec.get("nodes", []) if isinstance(n, dict)]
    emph = _emphasis_ids(spec)
    if not nodes:
        return "% empty problem_progression"
    spacing = max(3.2, 10.0 / max(len(nodes), 1))
    start = -(spacing * (len(nodes) - 1)) / 2
    lines = []
    placed: dict[str, str] = {}
    for i, node in enumerate(nodes):
        nid = str(node.get("id", f"q{i}")).replace(" ", "")
        placed[node.get("id", nid)] = nid
        x = start + i * spacing
        lines.append(_node_tex(node, x, 0.0, nid in emph))
    edges = spec.get("edges", [])
    if not edges:
        # 默认按节点顺序连链。
        for i in range(len(nodes) - 1):
            lines.append(_edge(placed[str(nodes[i].get("id", ""))], placed[str(nodes[i + 1].get("id", ""))], "inherit"))
    else:
        for edge in edges:
            if isinstance(edge, dict):
                f = placed.get(str(edge.get("from", "")))
                t = placed.get(str(edge.get("to", "")))
                if f and t:
                    lines.append(_edge(f, t, str(edge.get("kind", "inherit")), str(edge.get("label", ""))))
    return "\n".join(lines)


def render_mechanism_decision(spec: dict[str, Any]) -> str:
    """输入 -> 状态更新 -> 条件/阈值 -> 输出，可带回环。先放节点再画边。"""
    by_role = _nodes_by_role(spec)
    emph = _emphasis_ids(spec)
    inputs = by_role.get("input", [])
    states = by_role.get("state", []) + by_role.get("center", [])
    condition = by_role.get("condition", by_role.get("top", []))
    outputs = by_role.get("output", [])
    if not inputs:
        inputs = [{"id": "in", "label": "输入"}]
    if not states:
        states = [{"id": "st", "label": "状态更新"}]
    if not condition:
        condition = [{"id": "cond", "label": "条件/阈值？"}]
    if not outputs:
        outputs = [{"id": "out", "label": "输出"}]
    placed: dict[str, str] = {}
    lines: list[str] = []
    y = 0.0
    for node in inputs:
        nid = str(node.get("id", "in")).replace(" ", "")
        placed[str(node.get("id", "in"))] = nid
        lines.append(_node_tex(node, 0.0, y, nid in emph))
    y -= 1.4
    st_id = str(states[0].get("id", "st")).replace(" ", "")
    lines.append(_node_tex(states[0], 0.0, y, st_id in emph))
    placed[str(states[0].get("id", "st"))] = st_id
    y -= 1.4
    cond_id = str(condition[0].get("id", "cond")).replace(" ", "")
    lines.append(_node_tex(condition[0], 0.0, y, cond_id in emph))
    placed[str(condition[0].get("id", "cond"))] = cond_id
    y -= 1.4
    out_ids: list[str] = []
    for i, node in enumerate(outputs):
        nid = str(node.get("id", f"out{i}")).replace(" ", "")
        x = -1.6 if i == 0 and len(outputs) > 1 else 1.6 if i == 1 else 0.0
        lines.append(_node_tex(node, x, y, nid in emph))
        placed[str(node.get("id", f"out{i}"))] = nid
        out_ids.append(nid)
    # 主链边
    in_id = placed[str(inputs[0].get("id", "in"))]
    lines.append(_edge(in_id, st_id, "feed"))
    lines.append(_edge(st_id, cond_id, "condition"))
    for i, out_id in enumerate(out_ids):
        kind = "feed" if i == 0 else "condition"
        lines.append(_edge(cond_id, out_id, kind))
    # 反馈回环
    for edge in spec.get("edges", []):
        if isinstance(edge, dict) and edge.get("kind") == "feedback":
            f = placed.get(str(edge.get("from", "")))
            t = placed.get(str(edge.get("to", "")))
            if f and t:
                lines.append(_edge(f, t, "feedback", str(edge.get("label", ""))))
    return "\n".join(lines)


TEMPLATES = {
    "shared_model_map": render_shared_model_map,
    "problem_progression": render_problem_progression,
    "mechanism_decision": render_mechanism_decision,
}
