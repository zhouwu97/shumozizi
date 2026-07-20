"""优秀论文材料清点、论文卡索引与可解释检索。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from shumozizi.core.io import ContractError, atomic_json

SUPPORTED_SOURCE_EXTENSIONS = {
    ".csv",
    ".doc",
    ".docx",
    ".md",
    ".pdf",
    ".txt",
    ".xls",
    ".xlsx",
}
REQUIRED_CARD_FIELDS = {
    "paper_id",
    "title",
    "source_file",
    "source_sha256",
    "problem_type",
    "data_structure",
    "task_types",
}
REQUIRED_CARD_SECTIONS = (
    "核心问题",
    "各问问题链",
    "共享数学对象",
    "模型选择依据",
    "baseline设计",
    "验证设计",
    "论文论证结构",
    "图表承担的作用",
    "可迁移模式",
    "不可迁移内容",
    "论文不足",
    "缺失验证",
    "复现风险",
    "来源页码",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory_sources(source_dirs: list[Path]) -> dict[str, Any]:
    """递归清点支持的论文材料，不复制或修改源文件。"""
    roots: list[dict[str, str]] = []
    files: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for index, source_dir in enumerate(source_dirs, start=1):
        root = source_dir.expanduser().resolve()
        if not root.is_dir():
            raise ContractError(f"论文材料目录不存在: {root}")
        source_id = f"source-{index}"
        # 清点文件可提交到仓库，因此只记录稳定的根目录标签，不泄露本机绝对路径。
        roots.append({"source_id": source_id, "root_name": root.name})
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            if path.suffix.lower() not in SUPPORTED_SOURCE_EXTENSIONS:
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            files.append(
                {
                    "source_id": source_id,
                    "relative_path": path.relative_to(root).as_posix(),
                    "extension": path.suffix.lower(),
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
    extension_counts: dict[str, int] = {}
    for item in files:
        extension = item["extension"]
        extension_counts[extension] = extension_counts.get(extension, 0) + 1
    return {
        "schema_name": "paper_source_inventory",
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "sources": roots,
        "file_count": len(files),
        "extension_counts": dict(sorted(extension_counts.items())),
        "files": files,
    }


def write_source_inventory(source_dirs: list[Path], output_path: Path) -> Path:
    """生成材料清点报告。"""
    atomic_json(output_path, inventory_sources(source_dirs))
    return output_path


def read_paper_card(path: Path) -> dict[str, Any]:
    """使用 YAML 解析器读取 Markdown 论文卡 front matter。"""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ContractError(f"论文卡缺少 YAML front matter: {path}")
    try:
        closing = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise ContractError(f"论文卡 front matter 未闭合: {path}") from exc
    metadata = yaml.safe_load("\n".join(lines[1:closing]))
    if not isinstance(metadata, dict):
        raise ContractError(f"论文卡 front matter 必须是对象: {path}")
    missing = sorted(REQUIRED_CARD_FIELDS - metadata.keys())
    if missing:
        raise ContractError(f"论文卡缺少字段 {', '.join(missing)}: {path}")
    if not isinstance(metadata["task_types"], list) or not metadata["task_types"]:
        raise ContractError(f"论文卡 task_types 必须是非空数组: {path}")
    body = "\n".join(lines[closing + 1 :])
    missing_sections = [section for section in REQUIRED_CARD_SECTIONS if section not in body]
    if missing_sections:
        raise ContractError(f"论文卡缺少正文小节 {', '.join(missing_sections)}: {path}")
    return {"metadata": metadata, "body": body}


def build_paper_index(cards_dir: Path, output_path: Path) -> dict[str, Any]:
    """从论文卡生成不依赖向量数据库的稳定索引。"""
    entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for path in sorted(cards_dir.glob("*.md")):
        card = read_paper_card(path)
        metadata = card["metadata"]
        paper_id = str(metadata["paper_id"])
        if paper_id in seen_ids:
            raise ContractError(f"论文卡 paper_id 重复: {paper_id}")
        seen_ids.add(paper_id)
        entries.append(
            {
                "paper_id": paper_id,
                "title": str(metadata["title"]),
                "problem_type": str(metadata["problem_type"]),
                "data_structure": str(metadata["data_structure"]),
                "task_types": [str(item) for item in metadata["task_types"]],
                "domain_terms": [str(item) for item in metadata.get("domain_terms", [])],
                "structural_tags": [
                    str(item) for item in metadata.get("structural_tags", [])
                ],
                "source_sha256": str(metadata["source_sha256"]),
                "card_path": path.as_posix(),
            }
        )
    document = {
        "schema_name": "paper_card_index",
        "schema_version": "1.0",
        "paper_count": len(entries),
        "papers": entries,
    }
    atomic_json(output_path, document)
    return document


def load_paper_index(path: Path) -> dict[str, Any]:
    """读取最小论文索引并检查基础结构。"""
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_name") != "paper_card_index" or not isinstance(
        document.get("papers"), list
    ):
        raise ContractError(f"无效论文索引: {path}")
    return document


def retrieve_papers(
    index_path: Path,
    *,
    problem_type: str,
    data_structure: str,
    task_types: list[str],
    keywords: list[str],
    structural_tags: list[str] | None = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    """分别计算结构与领域相似度，避免通用研究原则冒充高相关命中。"""
    normalized_tasks = {item.casefold() for item in task_types}
    normalized_keywords = {item.casefold() for item in keywords}
    normalized_structures = {item.casefold() for item in structural_tags or []}
    ranked: list[tuple[float, str, dict[str, Any]]] = []
    for entry in load_paper_index(index_path)["papers"]:
        structural_reasons: list[str] = []
        domain_reasons: list[str] = []
        structural_similarity = 0.0
        if entry["problem_type"].casefold() == problem_type.casefold():
            structural_similarity += 0.35
            structural_reasons.append("problem_type 精确匹配")
        if entry["data_structure"].casefold() == data_structure.casefold():
            structural_similarity += 0.20
            structural_reasons.append("data_structure 精确匹配")
        matched_tasks = normalized_tasks.intersection(
            str(item).casefold() for item in entry["task_types"]
        )
        if matched_tasks:
            task_ratio = len(matched_tasks) / max(len(normalized_tasks), 1)
            structural_similarity += 0.30 * task_ratio
            structural_reasons.append("task_types 匹配: " + ", ".join(sorted(matched_tasks)))
        matched_structures = normalized_structures.intersection(
            str(item).casefold() for item in entry.get("structural_tags", [])
        )
        if matched_structures:
            structure_ratio = len(matched_structures) / max(len(normalized_structures), 1)
            structural_similarity += 0.15 * structure_ratio
            structural_reasons.append(
                "structural_tags 匹配: " + ", ".join(sorted(matched_structures))
            )

        domain_searchable = " ".join(
            [entry["title"], *entry.get("domain_terms", [])]
        ).casefold()
        matched_keywords = sorted(
            keyword for keyword in normalized_keywords if keyword in domain_searchable
        )
        domain_similarity = len(matched_keywords) / max(len(normalized_keywords), 1)
        if matched_keywords:
            domain_reasons.append("领域关键词匹配: " + ", ".join(matched_keywords))

        structural_similarity = round(min(structural_similarity, 1.0), 4)
        domain_similarity = round(min(domain_similarity, 1.0), 4)
        score = round(10.0 * (0.7 * structural_similarity + 0.3 * domain_similarity), 1)
        if structural_similarity >= 0.60 and domain_similarity >= 0.50:
            overall_confidence = "high"
        elif structural_similarity >= 0.50 or domain_similarity >= 0.50:
            overall_confidence = "medium"
        else:
            overall_confidence = "low"
        reasons = structural_reasons + domain_reasons
        if score:
            ranked.append(
                (
                    score,
                    entry["paper_id"],
                    {
                        **entry,
                        "score": score,
                        "structural_similarity": structural_similarity,
                        "domain_similarity": domain_similarity,
                        "overall_confidence": overall_confidence,
                        "match_reasons": reasons,
                        "high_confidence": overall_confidence == "high",
                    },
                )
            )
    return [item[2] for item in sorted(ranked, key=lambda item: (-item[0], item[1]))[:limit]]


def _card_section(body: str, section_name: str) -> str:
    """提取受控论文卡中的单个二级小节。"""
    lines = body.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        if line.startswith("## ") and section_name in line:
            start = index + 1
            break
    if start is None:
        return "未记录"
    content: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        content.append(line)
    return "\n".join(content).strip() or "未记录"


def write_retrieval_artifacts(
    run_dir: Path,
    index_path: Path,
    fingerprint: dict[str, Any],
    *,
    limit: int = 6,
) -> dict[str, Path]:
    """写入路线前知识产物；检索失败不改变运行状态。"""
    required = {"problem_type", "data_structure", "task_types", "keywords"}
    missing = sorted(required - fingerprint.keys())
    if missing:
        raise ContractError("TASK_FINGERPRINT 缺少字段: " + ", ".join(missing))
    normalized = {
        "schema_name": "task_fingerprint",
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "problem_type": str(fingerprint["problem_type"]),
        "data_structure": str(fingerprint["data_structure"]),
        "task_types": [str(item) for item in fingerprint["task_types"]],
        "keywords": [str(item) for item in fingerprint["keywords"]],
        "structural_tags": [str(item) for item in fingerprint.get("structural_tags", [])],
        "question_chain": [str(item) for item in fingerprint.get("question_chain", [])],
        "data_constraints": [str(item) for item in fingerprint.get("data_constraints", [])],
    }
    matches = retrieve_papers(
        index_path,
        problem_type=normalized["problem_type"],
        data_structure=normalized["data_structure"],
        task_types=normalized["task_types"],
        keywords=normalized["keywords"],
        structural_tags=normalized["structural_tags"],
        limit=limit,
    )
    knowledge_dir = run_dir / "knowledge"
    fingerprint_path = knowledge_dir / "TASK_FINGERPRINT.json"
    retrieved_path = knowledge_dir / "RETRIEVED_PATTERNS.md"
    transfer_path = knowledge_dir / "PATTERN_TRANSFER_PLAN.md"
    storyboard_path = run_dir / "brief" / "MODEL_STORYBOARD.md"
    atomic_json(fingerprint_path, normalized)

    confidence = [item for item in matches if item["high_confidence"]]
    retrieved_lines = [
        "# RETRIEVED_PATTERNS",
        "",
        f"- run_id: `{run_dir.name}`",
        f"- paper_index: `{index_path.as_posix()}`",
        f"- retrieved_count: `{len(matches)}`",
        f"- high_confidence_count: `{len(confidence)}`",
        "",
    ]
    if not confidence:
        retrieved_lines.extend(
            [
                "无高置信匹配，当前路线主要依据题面、数据和通用数学建模原则生成。",
                "",
            ]
        )
    for item in matches:
        retrieved_lines.extend(
            [
                f"## {item['title']}",
                "",
                f"- paper_id: `{item['paper_id']}`",
                f"- score: `{item['score']:.1f}`",
                f"- structural_similarity: `{item['structural_similarity']:.4f}`",
                f"- domain_similarity: `{item['domain_similarity']:.4f}`",
                f"- confidence: `{item['overall_confidence']}`",
                "- match_reasons: " + "；".join(item["match_reasons"]),
                f"- card_path: `{item['card_path']}`",
                "",
            ]
        )
    retrieved_path.parent.mkdir(parents=True, exist_ok=True)
    retrieved_path.write_text("\n".join(retrieved_lines), encoding="utf-8", newline="\n")

    repo_root = index_path.resolve().parents[2]
    transfer_lines = [
        "# PATTERN_TRANSFER_PLAN",
        "",
        "本计划只迁移研究结构，不迁移原论文数字、结论、代码或题目特定参数。",
        "",
    ]
    if not confidence:
        transfer_lines.extend(
            [
                "无高置信匹配。候选路线必须主要依据当前题面、数据剖面和通用建模原则生成。",
                "",
            ]
        )
    for item in confidence:
        card = read_paper_card(repo_root / item["card_path"])
        transfer_lines.extend(
            [
                f"## {item['title']}",
                "",
                "### 可迁移模式",
                "",
                _card_section(card["body"], "可迁移模式"),
                "",
                "### 当前题改造要求",
                "",
                "必须重新验证数据支持、参数可辨识性、约束闭合、baseline 公平性和计算预算。",
                "",
                "### 明确不可迁移",
                "",
                _card_section(card["body"], "不可迁移内容"),
                "",
            ]
        )
    transfer_path.write_text("\n".join(transfer_lines), encoding="utf-8", newline="\n")

    questions = normalized["question_chain"] or normalized["task_types"]
    storyboard_lines = [
        "# MODEL_STORYBOARD",
        "",
        f"- 题型：{normalized['problem_type']}",
        f"- 数据结构：{normalized['data_structure']}",
        "- 共享数学对象：各问共同使用的数据索引、变量、约束、目标、评价指标和不确定性来源。",
        "- baseline：每问先定义简单、可靠、可复验的比较对象。",
        "- 主模型：只能采用当前数据足以支持且能完成验证的模型族。",
        "- 论文主线：共享对象建立 -> 各问递进 -> 对照与稳健性 -> 结论边界。",
        "",
        "## 问题链",
        "",
    ]
    storyboard_lines.extend(
        f"- {index}. {question}" for index, question in enumerate(questions, start=1)
    )
    storyboard_lines.extend(
        [
            "",
            "## 路线约束",
            "",
            "每条候选路线必须说明借鉴模式、当前题改造、不可迁移内容、数据支持、验证方案和失败退路。",
            "",
        ]
    )
    storyboard_path.parent.mkdir(parents=True, exist_ok=True)
    storyboard_path.write_text("\n".join(storyboard_lines), encoding="utf-8", newline="\n")
    return {
        "task_fingerprint": fingerprint_path,
        "retrieved_patterns": retrieved_path,
        "pattern_transfer_plan": transfer_path,
        "model_storyboard": storyboard_path,
    }
