"""证据链一致性审计：论文每个图/数字必须能回溯到 production 结果。

``import_audit`` 只检查图是否存在于图目录、数字是否与 answer-map 一致；它不检查
**图的渲染脚本是否真的从 production 结果生成**。图 26/27 是典型故障：图存在且被
引用，但生成代码是写作工具自写的全数据 refit（``_fit_q4``/``_feasible_week``），
画出来的结果与正文正式答案冲突。

本模块补上这一环：遍历论文引用的每张图，要求它在 ``figures/index.json`` 中登记、
标记 ``paper_allowed``、且绑定至少一个 ``source_result_ids``（来源 production 结果）
或 ``input_result``。未绑定或未登记的图标记 ``EVIDENCE_CHAIN_BROKEN``，并提示
写作工具必须从 production 结果投影，而不是自己重算。

同时核对正文方法名与交接包 ``estimator_contract`` 的正式方法名：正文出现的方法
名若与正式 estimator 不一致，标记 ``METHOD_NAME_DRIFT``。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, load_json

INCLUDEGRAPHICS_PATTERN = re.compile(
    r"\\includegraphics(?:\s*\[[^\]]*\])?\{([^}]+)\}"
)
_METHOD_NAME_TERMS = ("GEE", "Bootstrap", "Logistic", "Elastic-Net", "OLS", "AFT")


def _figure_index(run_dir: Path) -> dict[str, Any]:
    """读取图索引；缺失时返回空。"""
    path = run_dir / "figures/index.json"
    if not path.is_file():
        return {}
    try:
        return load_json(path)
    except (ContractError, OSError, ValueError):
        return {}


def _figure_lookup(index: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """建立 figure_id / 文件名 到图条目的映射；current 条目优先于 superseded。"""
    lookup: dict[str, dict[str, Any]] = {}
    # 先登记 superseded/历史，最后写 current，保证 current 覆盖旧版本。
    ordered = sorted(
        (figure for figure in index.get("figures", []) if isinstance(figure, dict)),
        key=lambda item: 1 if item.get("status") == "current" else 0,
    )
    for figure in ordered:
        figure_id = str(figure.get("figure_id", "")).strip()
        if figure_id:
            lookup[figure_id] = figure
        for out in figure.get("outputs", []):
            if isinstance(out, dict):
                name = Path(str(out.get("path", ""))).name
                if name:
                    lookup[name] = figure
    return lookup


def _figure_is_bound(figure: dict[str, Any]) -> bool:
    """图是否绑定至少一个 production 结果来源。"""
    if figure.get("status") != "current" or figure.get("paper_allowed") is False:
        return False
    if isinstance(figure.get("input_result"), dict) and figure["input_result"].get(
        "path"
    ):
        return True
    sources = figure.get("source_result_ids")
    if isinstance(sources, list) and sources:
        return True
    source_files = figure.get("source_files")
    if isinstance(source_files, list) and source_files:
        return any(
            isinstance(item, dict) and item.get("path") for item in source_files
        )
    return False


def audit_evidence_chain(run_dir: Path) -> dict[str, Any]:
    """审计论文图/方法名与 production 结果的证据链一致性。

    Args:
        run_dir: 当前运行目录。

    Returns:
        含 ``findings`` 的审计结果。``EVIDENCE_CHAIN_BROKEN`` 属于客观失败，
        ``METHOD_NAME_DRIFT`` 属于需人工核对的方法名漂移告警。
    """
    root = run_dir.resolve()
    findings: list[dict[str, Any]] = []
    # 兼容两种论文结构：v3.4 的 paper/*.tex 与 mma-paper 的 texfile/*.tex。
    tex_dirs = (root / "paper", root / "texfile")
    tex_sources: list[Path] = []
    for directory in tex_dirs:
        if directory.is_dir():
            tex_sources.extend(sorted(directory.glob("*.tex")))
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in tex_sources
        if path.is_file()
    )
    index = _figure_index(root)
    lookup = _figure_lookup(index)

    used_figures: set[str] = set()
    for match in INCLUDEGRAPHICS_PATTERN.finditer(combined):
        value = match.group(1).strip()
        if not value:
            continue
        # 排除 LaTeX 宏定义里的参数占位符（如 \\includegraphics[width=#1]{#2}）。
        if "#" in value:
            continue
        used_figures.add(value)

    for raw in sorted(used_figures):
        if not raw:
            continue
        name = Path(raw).stem
        figure = (
            lookup.get(raw)
            or lookup.get(name)
            or lookup.get(Path(raw).name)
        )
        if figure is None:
            # 图目录里完全没有这个图 → 写作工具自由生成，未走正式登记。
            findings.append(
                {
                    "finding_id": f"EC-FIG-{len(findings) + 1:02d}",
                    "class": "EVIDENCE_CHAIN_BROKEN",
                    "location": f"图 {raw}",
                    "observation": (
                        f"论文引用的图 {raw} 未登记在 figures/index.json；"
                        "图必须由 production 结果经正式 renderer 生成并登记。"
                    ),
                    "verdict": "objective_failure",
                    "can_continue_without_it": False,
                    "evidence": "figure not in figures/index.json",
                }
            )
            continue
        if not _figure_is_bound(figure):
            findings.append(
                {
                    "finding_id": f"EC-FIG-{len(findings) + 1:02d}",
                    "class": "EVIDENCE_CHAIN_BROKEN",
                    "location": f"图 {raw}",
                    "observation": (
                        f"图 {figure.get('figure_id', raw)} 未绑定 production 结果"
                        "（无 source_result_ids / input_result / source_files）；"
                        "图的科学对象可能是写作工具自写 refit 的结果，与正式答案"
                        "不一致。必须改为从 production 结果确定性投影。"
                    ),
                    "verdict": "objective_failure",
                    "can_continue_without_it": False,
                    "evidence": (
                        f"figure_id={figure.get('figure_id')} "
                        f"source_result_ids={figure.get('source_result_ids')}"
                    ),
                }
            )

    # 方法名漂移：交接包 estimator_contract 声明了正式方法名，正文不得改用别称。
    estimator_contracts = _estimator_contracts_from_handoff(root)
    for question_id, contract in estimator_contracts.items():
        formal = str(contract.get("formal_method", ""))
        if not formal:
            continue
        # 在含该问标题的正文段内，检查是否出现与正式方法冲突的替代命名。
        section = _question_section(combined, question_id)
        for term in _METHOD_NAME_TERMS:
            if term not in formal and term in section and _term_means_different_method(
                section, term, formal
            ):
                findings.append(
                    {
                        "finding_id": f"EC-METHOD-{len(findings) + 1:02d}",
                        "class": "METHOD_NAME_DRIFT",
                        "location": f"{question_id} 方法描述",
                        "observation": (
                            f"{question_id} 正文出现 '{term}'，但正式 estimator 是"
                            f" '{formal}'；请核对方法名是否与实现一致，避免把"
                            "聚类稳健 OLS+Ridge 样条写成 GEE 样条这类改名。"
                        ),
                        "verdict": "needs_confirmation",
                        "can_continue_without_it": True,
                        "evidence": f"formal={formal}; seen={term}",
                    }
                )

    return {
        "success": True,
        "advisory_only": False,
        "source_files": [path.name for path in tex_sources if path.is_file()],
        "findings": findings,
        "metrics": {
            "figures_referenced": len(used_figures),
            "figures_bound": sum(
                1
                for raw in used_figures
                if (figure := lookup.get(raw) or lookup.get(Path(raw).stem))
                and _figure_is_bound(figure)
            ),
            "estimator_contracts": len(estimator_contracts),
        },
        "limitations": (
            "证据链审计只检查图的登记与结果绑定、方法名与 estimator_contract 一致；"
            "不评价图本身的美观或科学正确性。"
        ),
    }


def _estimator_contracts_from_handoff(root: Path) -> dict[str, dict[str, str]]:
    """从交接包的 answer-and-claims 读每问 estimator_contract。"""
    path = root / "paper/writer-handoff/answer-and-claims.json"
    if not path.is_file():
        return {}
    try:
        document = load_json(path)
    except (ContractError, OSError, ValueError):
        return {}
    contracts: dict[str, dict[str, str]] = {}
    for question in document.get("questions", []):
        if not isinstance(question, dict):
            continue
        question_id = str(question.get("question_id", ""))
        contract = question.get("estimator_contract")
        if isinstance(contract, dict) and question_id:
            contracts[question_id] = {
                str(k): str(v) for k, v in contract.items() if isinstance(v, str)
            }
    return contracts


def _question_section(text: str, question_id: str) -> str:
    """截取含该问题标题的正文段（近似，只用于方法名核对）。"""
    number = question_id[-1] if question_id and question_id[-1].isdigit() else ""
    pattern = re.compile(rf"\b{re.escape(question_id)}\b|第\s*{number}\s*问|问题\s*{number}")
    positions = [match.start() for match in pattern.finditer(text)]
    if not positions:
        return text
    start = positions[-1]
    rest = text[start:]
    next_heading = re.search(r"\n\s*(?:问题|第\s*\d+\s*问)\s", rest)
    end = next_heading.start() if next_heading else len(rest)
    return rest[:end]


def _term_means_different_method(section: str, term: str, formal: str) -> bool:
    """术语出现在正文且与正式方法不同；出现在同义上下文（如'GEE'本身就是正式名）不算。"""
    return term.casefold() not in formal.casefold()
