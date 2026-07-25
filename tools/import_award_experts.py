"""导入 CUMCM A/B 获奖论文的结构专家库，并隔离运行时与溯源数据。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

RUNTIME_CARD_FIELDS = (
    "card_id",
    "kind",
    "knowledge_class",
    "applies_to",
    "stages",
    "instruction_zh",
    "checks",
    "rejects",
    "forbidden_material",
)
RUNTIME_EXPERT_FIELDS = (
    "id",
    "name",
    "applies_to",
    "triggers",
    "responsibilities",
    "rejects",
    "card_ids",
    "stages",
)
WRITING_ACTION_CARDS = {
    "writing-round-blueprint": (
        "writing-action-blueprint",
        "先形成研究主线、逐问继承或独立关系、章节合同和证据驱动的篇幅预算。",
    ),
    "writing-round-shared-model": (
        "writing-action-shared-model",
        "集中写共享状态、判定器、评价指标、符号和统一约束，冻结后续章节口径。",
    ),
    "writing-round-question-chapters": (
        "writing-action-question-chapters",
        "逐问展开模型推导、算法选型、求解步骤、结果含义、约束回放和独立验证。",
    ),
    "writing-round-evidence-limitations": (
        "writing-action-evidence-limitations",
        "补写敏感性、消融、误差、局限、推广和图表前后论证，保留失败边界。",
    ),
    "writing-round-abstract-review": (
        "writing-action-strict-revision",
        "在主体证据稳定后写摘要、模型评价和结论，并由严格评阅提出可追踪的返修项。",
    ),
}


def _canonical_hash(value: dict[str, Any]) -> str:
    """计算稳定 JSON 哈希。

    Args:
        value: 需要哈希的 JSON 对象。

    Returns:
        SHA-256 十六进制摘要。
    """
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _as_list(value: object) -> list[str]:
    """将源库的空值、空格分隔字符串或数组统一为文本数组。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [item for item in value.split() if item]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    raise ValueError("源库字段必须是文本或文本数组")


def _runtime_card(raw: dict[str, Any]) -> dict[str, Any]:
    """提取可进入提示词的结构卡，明确删除原始证据索引。"""
    card = {field: raw.get(field) for field in RUNTIME_CARD_FIELDS}
    card["applies_to"] = _as_list(card["applies_to"])
    card["stages"] = _as_list(card["stages"])
    card["structure_only"] = card.pop("knowledge_class") == "structure-only"
    card["prompt_safe"] = True
    action = WRITING_ACTION_CARDS.get(str(raw.get("card_id")))
    if action:
        card["card_id"], card["instruction_zh"] = action
        card["kind"] = "writing-action"
    return card


def _runtime_expert(raw: dict[str, Any]) -> dict[str, Any]:
    """提取角色规则，并把 Word 排版职责改造成 LaTeX 排版职责。"""
    expert = {field: raw.get(field) for field in RUNTIME_EXPERT_FIELDS}
    for field in ("applies_to", "triggers", "responsibilities", "rejects", "card_ids", "stages"):
        expert[field] = _as_list(expert[field])
    expert["card_ids"] = [
        WRITING_ACTION_CARDS.get(card_id, (card_id, ""))[0] for card_id in expert["card_ids"]
    ]
    # 运行时不保留 Word 默认路径，所有版式建议统一服务于 v3.2 的 LaTeX 交付。
    for field in ("name", "triggers", "responsibilities", "rejects"):
        value = expert[field]
        if isinstance(value, str):
            expert[field] = value.replace("Word", "LaTeX")
        else:
            expert[field] = [item.replace("Word", "LaTeX") for item in value]
    if expert["id"] == "word-layout-editor":
        expert["id"] = "latex-layout-editor"
        expert["name"] = "LaTeX 版式与可编译性专家"
        # 版式职责只描述通用交付约束，避免继承任何往届论文的排版内容。
        expert["responsibilities"] = [
            "维护 main.tex 的章节、公式、图表、交叉引用和参考文献结构",
            "检查浮动体、页眉页脚、编译警告、裁切、空白与越界",
            "用最终 PDF 逐页检查版面，不以 LaTeX 模板或固定页数替代证据预算",
        ]
    return expert


def _replace_layout_expert_ids(routes: dict[str, Any]) -> dict[str, Any]:
    """同步替换路由索引中的旧 Word 专家标识。"""
    normalized: dict[str, Any] = {}
    for key, value in routes.items():
        normalized[key] = [
            "latex-layout-editor" if item == "word-layout-editor" else item
            for item in _as_list(value)
        ]
    return normalized


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    """用同目录替换写出 JSON，避免中断产生半个知识资产。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_assets(source_path: Path, output_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """将原始库拆分为运行时安全库和离线追溯资产。

    Args:
        source_path: CUMCM-main 中的完整专家库 JSON。
        output_dir: 本仓库 ``knowledge/award-experts`` 目录。

    Returns:
        依次为运行时 ``library.json`` 与离线 ``provenance.json``。

    Raises:
        ValueError: 源库不是预期的结构专家库。
    """
    raw = json.loads(source_path.read_text(encoding="utf-8"))
    if raw.get("scope", {}).get("usage") != "structure-only":
        raise ValueError("拒绝导入非 structure-only 的专家库")
    cards = [_runtime_card(item) for item in raw.get("cards", []) if isinstance(item, dict)]
    experts = [_runtime_expert(item) for item in raw.get("experts", []) if isinstance(item, dict)]
    if len(cards) != 21 or len(experts) != 15:
        raise ValueError("源库覆盖不完整，预期为 21 张卡和 15 个专家")
    runtime = {
        "schema_version": "1.0",
        "library_id": "cumcm-ab-award-expert-structure",
        "scope": {
            "competition": "全国大学生数学建模竞赛",
            "years": [2012, 2025],
            "questions": ["A", "B"],
            "usage": "structure-only",
            "same_problem_policy": "freeze-baseline-then-answer-filter",
        },
        "coverage": raw.get("coverage"),
        "cards": cards,
        "experts": experts,
        "routing_index": _replace_layout_expert_ids(raw.get("routing", {})),
    }
    runtime["library_hash"] = _canonical_hash(runtime)
    provenance = {
        "schema_version": "1.0",
        "library_id": runtime["library_id"],
        "runtime_library_hash": runtime["library_hash"],
        "source": {
            "file_name": source_path.name,
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "declared_library_hash": raw.get("library_hash"),
            "provenance": raw.get("provenance"),
        },
        "coverage": raw.get("coverage"),
        "card_evidence_refs": {
            str(item.get("card_id")): item.get("evidence_refs", "")
            for item in raw.get("cards", [])
            if isinstance(item, dict)
        },
        "expert_source_locations": [
            {"expert_id": item.get("id"), "evidence": item.get("evidence", [])}
            for item in raw.get("experts", [])
            if isinstance(item, dict)
        ],
        "access_boundary": {
            "runtime_reads_provenance": False,
            "note": "此文件只供离线溯源；运行期路由只读取 library.json。",
        },
    }
    _atomic_json(output_dir / "library.json", runtime)
    _atomic_json(output_dir / "provenance.json", provenance)
    return runtime, provenance


def main() -> None:
    """解析命令行参数并生成两份专家库资产。"""
    parser = argparse.ArgumentParser(description="导入 CUMCM A/B 获奖论文结构专家库")
    parser.add_argument("source", type=Path, help="CUMCM-main 的 award-expert-library.json")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("knowledge/award-experts"),
        help="输出目录，默认 knowledge/award-experts",
    )
    args = parser.parse_args()
    runtime, provenance = build_assets(args.source, args.output_dir)
    print(
        json.dumps(
            {
                "library": str(args.output_dir / "library.json"),
                "library_hash": runtime["library_hash"],
                "cards": len(runtime["cards"]),
                "experts": len(runtime["experts"]),
                "provenance": str(args.output_dir / "provenance.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
