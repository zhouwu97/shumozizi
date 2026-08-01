"""把正式结果整理为可供作者使用的研究素材池。

素材池只保存结论、推导、机制、边界和图示机会等“作者输入”，不把日志、任务
回执、源码哈希和调试路径暴露给写作模板；来源绑定仍保留在结构化字段中用于
失效判断和审计。
"""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.core.schema import require_valid
from shumozizi.paper.policy import (
    formal_result_digest,
    policy_fingerprint,
    source_digest,
)
from shumozizi.simple.state import read_simple_state, utc_now

MATERIAL_POOL_MD_PATH = Path("paper/PAPER_MATERIAL_POOL.md")
MATERIAL_POOL_JSON_PATH = Path("paper/generated/material_pool.json")
MATERIAL_CATEGORIES = (
    "Direct Answer",
    "Mathematical Derivation",
    "Structural Observation",
    "Mechanism",
    "Intermediate Result",
    "Baseline/Contrast",
    "Boundary/Robustness",
    "Illustrative Case",
    "Visual Opportunity",
    "Negative Finding",
)


def _text(value: Any) -> str:
    """把结果字段安全地转成一条作者可读的短文本。"""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "；".join(item for item in (_text(part) for part in value) if item)
    if isinstance(value, dict):
        return "；".join(
            f"{key}：{_text(item)}" for key, item in value.items() if _text(item)
        )
    return ""


def _atomic_text(path: Path, value: str) -> None:
    """在同目录原子替换作者可读文本，避免半写入文件被编辑器读取。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _base_item(
    *,
    material_id: str,
    category: str,
    title: str,
    content: str,
    question_id: str | None,
    result_ids: Iterable[str] = (),
    figure_ids: Iterable[str] = (),
    inclusion: str = "candidate",
    evidence_grade: str | None = None,
    media_candidates: Iterable[str] = (),
) -> dict[str, Any]:
    """构造单个素材条目并统一默认字段。"""
    if category not in MATERIAL_CATEGORIES:
        raise ContractError(f"未知素材类别: {category}")
    if not title.strip() or not content.strip():
        raise ContractError("素材标题和内容不能为空")
    if inclusion not in {"body", "appendix", "candidate"}:
        raise ContractError("素材 inclusion 必须为 body、appendix 或 candidate")
    return {
        "material_id": material_id,
        "category": category,
        "title": title.strip(),
        "content": content.strip(),
        "question_id": question_id,
        "source_result_ids": sorted({str(item) for item in result_ids}),
        "source_figure_ids": sorted({str(item) for item in figure_ids}),
        "inclusion": inclusion,
        "evidence_grade": evidence_grade,
        "media_candidates": sorted({str(item) for item in media_candidates}),
        "status": "current",
    }


def _current_results(run_dir: Path) -> list[dict[str, Any]]:
    """只读取当前且执行有效的生产结果，拒绝旧结果污染素材池。"""
    path = run_dir / "results/index.json"
    if not path.is_file():
        return []
    payload = load_json(path)
    return [
        item
        for item in payload.get("results", [])
        if isinstance(item, dict)
        and item.get("status") == "current"
        and item.get("execution_valid") is True
        and item.get("execution_mode", "production") == "production"
    ]


def _result_materials(result: dict[str, Any]) -> list[dict[str, Any]]:
    """从结果显式字段提取作者素材；不把未知结构猜成科学结论。"""
    rid = str(result.get("result_id", ""))
    question_id = result.get("question_id")
    question = str(question_id) if isinstance(question_id, str) else None
    materials: list[dict[str, Any]] = []
    metrics = _text(result.get("metrics"))
    if metrics:
        # 指标是正式结果中的真实中间证据，但它没有自动携带题意解释，
        # 因此只进入 Intermediate Result，不冒充 Direct Answer 或 Mechanism。
        materials.append(
            _base_item(
                material_id=f"intermediate-{rid}",
                category="Intermediate Result",
                title=f"{question or '共享'}正式结果指标",
                content=metrics,
                question_id=question,
                result_ids=[rid],
                inclusion="candidate",
                evidence_grade="formal_result",
            )
        )
    conclusion = _text(result.get("conclusion") or result.get("answer"))
    if conclusion:
        materials.append(
            _base_item(
                material_id=f"answer-{rid}",
                category="Direct Answer",
                title=f"{question or '共享'}直接答案",
                content=conclusion,
                question_id=question,
                result_ids=[rid],
                inclusion="body",
                evidence_grade=_text(result.get("evidence_grade")) or None,
            )
        )
    for index, field in enumerate(("derivation", "key_derivation", "formula_explanation"), 1):
        value = _text(result.get(field))
        if value:
            materials.append(
                _base_item(
                    material_id=f"derivation-{rid}-{index}",
                    category="Mathematical Derivation",
                    title=f"{question or '共享'}关键推导",
                    content=value,
                    question_id=question,
                    result_ids=[rid],
                    inclusion="body",
                )
            )
            break
    for index, field in enumerate(("structural_observation", "insight", "insights"), 1):
        value = _text(result.get(field))
        if value:
            materials.append(
                _base_item(
                    material_id=f"structure-{rid}-{index}",
                    category="Structural Observation",
                    title=f"{question or '共享'}结构观察",
                    content=value,
                    question_id=question,
                    result_ids=[rid],
                    inclusion="body",
                )
            )
    for index, field in enumerate(("mechanism", "mechanism_explanation", "tradeoff"), 1):
        value = _text(result.get(field))
        if value:
            materials.append(
                _base_item(
                    material_id=f"mechanism-{rid}-{index}",
                    category="Mechanism",
                    title=f"{question or '共享'}机制解释",
                    content=value,
                    question_id=question,
                    result_ids=[rid],
                    inclusion="body",
                )
            )
    for index, field in enumerate(("baseline", "contrast", "comparison"), 1):
        value = _text(result.get(field))
        if value:
            materials.append(
                _base_item(
                    material_id=f"contrast-{rid}-{index}",
                    category="Baseline/Contrast",
                    title=f"{question or '共享'}基线对照",
                    content=value,
                    question_id=question,
                    result_ids=[rid],
                    inclusion="body",
                )
            )
    for index, field in enumerate(("boundary", "robustness", "sensitivity", "limitations"), 1):
        value = _text(result.get(field))
        if value:
            materials.append(
                _base_item(
                    material_id=f"boundary-{rid}-{index}",
                    category="Boundary/Robustness",
                    title=f"{question or '共享'}适用边界",
                    content=value,
                    question_id=question,
                    result_ids=[rid],
                    inclusion="body",
                )
            )
    return materials


def build_material_pool(
    run_dir: Path,
    *,
    materials: list[dict[str, Any]] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """构建研究素材池，并可同步生成作者可读 Markdown。"""
    root = run_dir.resolve()
    state = read_simple_state(root)
    items = materials if materials is not None else [
        item for result in _current_results(root) for item in _result_materials(result)
    ]
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict):
            raise ContractError("素材条目必须是对象")
        item = _base_item(
            material_id=str(raw.get("material_id", "")),
            category=str(raw.get("category", "")),
            title=str(raw.get("title", "")),
            content=str(raw.get("content", "")),
            question_id=raw.get("question_id") if isinstance(raw.get("question_id"), str) else None,
            result_ids=raw.get("source_result_ids", []),
            figure_ids=raw.get("source_figure_ids", []),
            inclusion=str(raw.get("inclusion", "candidate")),
            evidence_grade=raw.get("evidence_grade") if isinstance(raw.get("evidence_grade"), str) else None,
            media_candidates=raw.get("media_candidates", []),
        )
        for field in ("source_paths", "editor_note", "claim_function", "status"):
            if field in raw:
                item[field] = raw[field]
        if item["material_id"] in seen:
            raise ContractError(f"素材 ID 重复: {item['material_id']}")
        seen.add(item["material_id"])
        normalized.append(item)
    payload: dict[str, Any] = {
        "schema_name": "paper_material_pool",
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "policy_fingerprint": policy_fingerprint(resolve_repo_root(Path(__file__)), "paper"),
        "generated_at": utc_now(),
        "status": "current" if materials is not None or normalized else "draft",
        "source_bindings": {
            "production_results_digest": formal_result_digest(root),
            "figure_index_digest": source_digest(root, "figures/index.json"),
            "modeling_units_digest": source_digest(root, "analysis/MODELING_UNITS.json"),
        },
        "items": normalized,
    }
    require_valid(payload, "paper_material_pool")
    if write:
        write_material_pool(root, payload)
    return payload


def _markdown(payload: dict[str, Any]) -> str:
    """渲染去除控制字段的作者素材文档。"""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in payload.get("items", []):
        groups[str(item.get("category"))].append(item)
    lines = [
        "# PAPER_MATERIAL_POOL",
        "",
        "这是论文作者的研究素材池。它保留结论、推导、结构观察、机制、边界和视觉机会；"
        "运行日志、任务回执、源码哈希与调试路径不属于写作输入。",
        "",
        f"素材状态：`{payload.get('status', 'draft')}`。素材变化后应重新生成故事板与相关图表。",
        "",
    ]
    for category in MATERIAL_CATEGORIES:
        lines.extend([f"## {category}", ""])
        entries = groups.get(category, [])
        if not entries:
            lines.extend(["暂无可用素材。", ""])
            continue
        for item in entries:
            question = item.get("question_id") or "共享"
            lines.extend(
                [
                    f"### {item['title']}（{question}）",
                    "",
                    item["content"],
                    "",
                    f"- 写作位置建议：`{item.get('inclusion', 'candidate')}`",
                ]
            )
            if item.get("claim_function"):
                lines.append(f"- 证据功能：{item['claim_function']}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_material_pool(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """校验并原子写入素材池 JSON 与 Markdown。"""
    root = run_dir.resolve()
    if payload.get("run_id") != read_simple_state(root)["run_id"]:
        raise ContractError("素材池 run_id 与运行不一致")
    require_valid(payload, "paper_material_pool")
    atomic_json(root / MATERIAL_POOL_JSON_PATH, payload)
    target = root / MATERIAL_POOL_MD_PATH
    _atomic_text(target, _markdown(payload))
    return payload


def read_material_pool(run_dir: Path) -> dict[str, Any]:
    """读取并验证素材池。"""
    payload = load_json(run_dir.resolve() / MATERIAL_POOL_JSON_PATH)
    require_valid(payload, "paper_material_pool")
    return payload


def material_pool_digest(run_dir: Path) -> str | None:
    """返回素材池 JSON 摘要，缺失时返回空值。"""
    path = run_dir.resolve() / MATERIAL_POOL_JSON_PATH
    return sha256_file(path) if path.is_file() else None


def validate_material_pool_freshness(run_dir: Path) -> dict[str, Any]:
    """判断素材池是否仍绑定当前正式结果、图索引和论文政策。"""
    root = run_dir.resolve()
    payload = read_material_pool(root)
    repo_root = resolve_repo_root(Path(__file__))
    current = {
        "production_results_digest": formal_result_digest(root),
        "figure_index_digest": source_digest(root, "figures/index.json"),
        "modeling_units_digest": source_digest(root, "analysis/MODELING_UNITS.json"),
        "policy_fingerprint": policy_fingerprint(repo_root, "paper"),
    }
    stored = {**payload.get("source_bindings", {}), "policy_fingerprint": payload.get("policy_fingerprint")}
    stale_fields = [key for key, value in current.items() if stored.get(key) != value]
    return {"current": not stale_fields, "stale_fields": stale_fields, "run_id": payload["run_id"]}


def require_material_pool(run_dir: Path, *, fresh: bool = True) -> dict[str, Any]:
    """要求素材池存在；默认要求它仍绑定当前科学输入。"""
    payload = read_material_pool(run_dir)
    if fresh:
        freshness = validate_material_pool_freshness(run_dir)
        if not freshness["current"]:
            raise ContractError("研究素材池已失效: " + "、".join(freshness["stale_fields"]))
    return payload
