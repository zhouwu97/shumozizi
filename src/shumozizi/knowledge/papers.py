"""优秀论文材料清点、论文卡索引与可解释检索。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from shumozizi.core.io import (
    ContractError,
    atomic_json,
    load_json,
    resolve_inside,
    sha256_file,
)
from shumozizi.knowledge.snapshot import RETRIEVAL_POLICY, write_retrieval_snapshot

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
REVIEW_STATUSES = {
    "legacy_provisional",
    "provisional",
    "revision_required",
    "rejected",
    "verified",
    "superseded",
}
PROVISIONAL_STATUSES = {"legacy_provisional", "provisional", "revision_required"}
DEFAULT_REVIEW_STATUS = "legacy_provisional"
REQUIRED_VERIFIED_IDENTITY_FIELDS = {
    "card_version",
    "competition_id",
    "competition_year",
    "problem_code",
    "canonical_problem_id",
    "problem_asset_sha256",
    "paper_asset_sha256",
}


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


def load_paper_card_review_registry(path: Path) -> dict[str, Any]:
    """读取论文卡独立审核注册表；历史卡统一按 provisional 处理。"""
    registry = load_json(path)
    if registry.get("schema_name") != "paper_card_review_registry":
        raise ContractError(f"无效论文卡审核注册表: {path}")
    if registry.get("schema_version") != "1.0":
        raise ContractError(f"不支持的论文卡审核注册表版本: {path}")
    if registry.get("default_status") != DEFAULT_REVIEW_STATUS:
        raise ContractError("论文卡审核注册表 default_status 必须是 legacy_provisional")
    cards = registry.get("cards")
    if not isinstance(cards, dict):
        raise ContractError("论文卡审核注册表 cards 必须是对象")
    for paper_id, record in cards.items():
        if not isinstance(paper_id, str) or not paper_id or not isinstance(record, dict):
            raise ContractError("论文卡审核注册表包含无效记录")
        status = record.get("review_status", DEFAULT_REVIEW_STATUS)
        if status not in REVIEW_STATUSES:
            raise ContractError(f"论文卡 {paper_id} 的 review_status 无效: {status}")
        receipt_path = record.get("promotion_receipt")
        receipt_sha256 = record.get("promotion_receipt_sha256")
        if status == "verified" and (not receipt_path or not receipt_sha256):
            raise ContractError(f"论文卡 {paper_id} 缺少 promotion receipt，不能标记 verified")
        if status != "verified" and (receipt_path is not None or receipt_sha256 is not None):
            raise ContractError(f"论文卡 {paper_id} 非 verified 状态不得绑定 promotion receipt")
    return registry


def _review_record(registry: dict[str, Any], paper_id: str) -> dict[str, Any]:
    record = registry["cards"].get(paper_id, {})
    return {
        "review_status": record.get("review_status", registry["default_status"]),
        "promotion_receipt": record.get("promotion_receipt"),
        "promotion_receipt_sha256": record.get("promotion_receipt_sha256"),
    }


def _relative_card_path(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise ContractError(f"论文卡不在知识仓库内: {path}") from exc


def _require_sha256(value: object, field: str, paper_id: str) -> str:
    normalized = str(value or "")
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise ContractError(f"论文卡 {paper_id} 的 {field} 不是有效 SHA-256")
    return normalized


def _require_nonempty_string(value: object, field: str, paper_id: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"论文卡 {paper_id} 的 {field} 必须是非空字符串")
    return value


def _verify_promotion_receipt(
    repo_root: Path,
    card_path: Path,
    metadata: dict[str, Any],
    review: dict[str, Any],
) -> str:
    paper_id = str(metadata["paper_id"])
    missing = sorted(REQUIRED_VERIFIED_IDENTITY_FIELDS - metadata.keys())
    if missing:
        raise ContractError(f"论文卡 {paper_id} 缺少 verified 身份字段: {', '.join(missing)}")
    for field in ("card_version", "competition_id", "problem_code", "canonical_problem_id"):
        _require_nonempty_string(metadata[field], field, paper_id)
    if not isinstance(metadata["competition_year"], int) or isinstance(
        metadata["competition_year"], bool
    ):
        raise ContractError(f"论文卡 {paper_id} 的 competition_year 必须是整数")
    source_sha256 = _require_sha256(metadata["source_sha256"], "source_sha256", paper_id)
    problem_sha256 = _require_sha256(
        metadata["problem_asset_sha256"], "problem_asset_sha256", paper_id
    )
    paper_sha256 = _require_sha256(
        metadata["paper_asset_sha256"], "paper_asset_sha256", paper_id
    )
    if paper_sha256 != source_sha256:
        raise ContractError(f"论文卡 {paper_id} 的 paper_asset_sha256 必须绑定论文源文件")

    receipt_path = resolve_inside(repo_root, str(review["promotion_receipt"]), must_exist=True)
    expected_receipt_sha256 = _require_sha256(
        review["promotion_receipt_sha256"], "promotion_receipt_sha256", paper_id
    )
    if sha256_file(receipt_path) != expected_receipt_sha256:
        raise ContractError(f"论文卡 {paper_id} 的 promotion receipt 哈希不匹配")
    receipt = load_json(receipt_path)
    expected = {
        "schema_name": "paper_card_promotion_receipt",
        "schema_version": "1.0",
        "paper_id": paper_id,
        "card_version": str(metadata["card_version"]),
        "card_sha256": sha256_file(card_path),
        "source_sha256": source_sha256,
        "canonical_problem_id": str(metadata["canonical_problem_id"]),
        "problem_asset_sha256": problem_sha256,
    }
    for field, value in expected.items():
        if receipt.get(field) != value:
            raise ContractError(f"论文卡 {paper_id} 的 promotion receipt 未绑定 {field}")
    if metadata.get("source_id"):
        evidence_map_path = resolve_inside(
            repo_root,
            f"knowledge/reviews/evidence_maps/{paper_id}.json",
            must_exist=True,
        )
        review_report_path = resolve_inside(
            repo_root,
            f"knowledge/reviews/reports/{paper_id}.json",
            must_exist=True,
        )
        v2_expected = {
            "source_id": metadata["source_id"],
            "source_asset_sha256": metadata["source_asset_sha256"],
            "evidence_map_sha256": sha256_file(evidence_map_path),
            "review_report_sha256": sha256_file(review_report_path),
            "promotion_policy_version": "paper-card-promotion-v1",
        }
        for field, value in v2_expected.items():
            if receipt.get(field) != value:
                raise ContractError(f"Paper Card v2 晋级回执未绑定 {field}: {paper_id}")
        for field in (
            "review_session_id",
            "reviewer_identity",
            "reviewer_attestation",
            "promoted_at",
        ):
            if not isinstance(receipt.get(field), str) or not receipt[field].strip():
                raise ContractError(f"Paper Card v2 晋级回执缺少 {field}: {paper_id}")
        if receipt["review_session_id"] == metadata.get("authoring_session_id"):
            raise ContractError(f"Paper Card v2 制作与审核会话未隔离: {paper_id}")
    return expected_receipt_sha256


def _index_entry(
    repo_root: Path,
    path: Path,
    metadata: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    paper_id = str(metadata["paper_id"])
    review_status = str(review["review_status"])
    source_sha256 = _require_sha256(metadata["source_sha256"], "source_sha256", paper_id)
    paper_asset_sha256 = _require_sha256(
        metadata.get("paper_asset_sha256", source_sha256), "paper_asset_sha256", paper_id
    )
    problem_asset_sha256 = metadata.get("problem_asset_sha256")
    if problem_asset_sha256 is not None:
        problem_asset_sha256 = _require_sha256(
            problem_asset_sha256, "problem_asset_sha256", paper_id
        )
    promotion_sha256: str | None = None
    if review_status == "verified":
        promotion_sha256 = _verify_promotion_receipt(repo_root, path, metadata, review)
    return {
        "paper_id": paper_id,
        "card_version": str(metadata.get("card_version", "1.0-legacy")),
        "title": str(metadata["title"]),
        "competition_id": metadata.get("competition_id"),
        "competition_year": metadata.get("competition_year"),
        "problem_code": metadata.get("problem_code"),
        "canonical_problem_id": metadata.get("canonical_problem_id"),
        "problem_asset_sha256": problem_asset_sha256,
        "paper_asset_sha256": paper_asset_sha256,
        "problem_type": str(metadata["problem_type"]),
        "data_structure": str(metadata["data_structure"]),
        "task_types": [str(item) for item in metadata["task_types"]],
        "domain_terms": [str(item) for item in metadata.get("domain_terms", [])],
        "structural_tags": [str(item) for item in metadata.get("structural_tags", [])],
        "source_sha256": source_sha256,
        "card_sha256": sha256_file(path),
        "card_path": _relative_card_path(repo_root, path),
        "review_status": review_status,
        "promotion_receipt": review["promotion_receipt"],
        "promotion_receipt_sha256": promotion_sha256,
    }


def build_paper_indexes(
    cards_dir: Path,
    registry_path: Path,
    provisional_output_path: Path,
    verified_output_path: Path,
) -> dict[str, dict[str, Any]]:
    """按独立审核状态生成完全隔离的 provisional 与 verified 索引。"""
    registry = load_paper_card_review_registry(registry_path)
    repo_root = registry_path.resolve().parents[2]
    entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for path in sorted(cards_dir.glob("*.md")):
        metadata = read_paper_card(path)["metadata"]
        paper_id = str(metadata["paper_id"])
        if paper_id in seen_ids:
            raise ContractError(f"论文卡 paper_id 重复: {paper_id}")
        seen_ids.add(paper_id)
        entries.append(
            _index_entry(repo_root, path, metadata, _review_record(registry, paper_id))
        )

    registry_sha256 = sha256_file(registry_path)
    base = {
        "schema_name": "paper_card_index",
        "schema_version": "2.0",
        "review_registry_path": _relative_card_path(repo_root, registry_path),
        "review_registry_sha256": registry_sha256,
    }
    provisional_entries = [
        entry for entry in entries if entry["review_status"] in PROVISIONAL_STATUSES
    ]
    verified_entries = [entry for entry in entries if entry["review_status"] == "verified"]
    provisional = {
        **base,
        "index_kind": "provisional",
        "paper_count": len(provisional_entries),
        "papers": provisional_entries,
    }
    verified = {
        **base,
        "index_kind": "verified",
        "paper_count": len(verified_entries),
        "papers": verified_entries,
    }
    atomic_json(provisional_output_path, provisional)
    atomic_json(verified_output_path, verified)
    return {"provisional": provisional, "verified": verified}


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


def load_paper_index(path: Path, *, production: bool = False) -> dict[str, Any]:
    """读取论文索引；生产模式只接受可复验的 verified 索引。"""
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_name") != "paper_card_index" or not isinstance(
        document.get("papers"), list
    ):
        raise ContractError(f"无效论文索引: {path}")
    if not production:
        return document
    if document.get("index_kind") != "verified":
        raise ContractError(
            "生产检索只允许使用 verified 索引（默认路径为 papers_verified.json）"
        )
    if document.get("schema_version") != "2.0":
        raise ContractError("生产检索拒绝旧版论文索引")
    if document.get("paper_count") != len(document["papers"]):
        raise ContractError("verified 索引 paper_count 与记录数不一致")
    repo_root = path.resolve().parents[2]
    registry_path = resolve_inside(
        repo_root, str(document.get("review_registry_path", "")), must_exist=True
    )
    if sha256_file(registry_path) != document.get("review_registry_sha256"):
        raise ContractError("verified 索引绑定的审核注册表已变化")
    registry = load_paper_card_review_registry(registry_path)
    for entry in document["papers"]:
        if not isinstance(entry, dict) or entry.get("review_status") != "verified":
            raise ContractError("verified 索引包含未经核验的论文卡")
        paper_id = str(entry.get("paper_id", ""))
        card_path = resolve_inside(repo_root, str(entry.get("card_path", "")), must_exist=True)
        card = read_paper_card(card_path)
        if sha256_file(card_path) != entry.get("card_sha256"):
            raise ContractError(f"verified 论文卡哈希已变化: {paper_id}")
        review = _review_record(registry, paper_id)
        expected_entry = _index_entry(repo_root, card_path, card["metadata"], review)
        if entry != expected_entry:
            raise ContractError(f"verified 索引记录与卡片或晋级回执不一致: {paper_id}")
    return document


def retrieve_papers(
    index_path: Path,
    *,
    problem_type: str,
    data_structure: str,
    task_types: list[str],
    keywords: list[str],
    structural_tags: list[str] | None = None,
    current_canonical_problem_id: str | None = None,
    current_problem_asset_sha256: str | None = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    """从 verified 索引检索，并在评分前硬排除同题论文。"""
    normalized_tasks = {item.casefold() for item in task_types}
    normalized_keywords = {item.casefold() for item in keywords}
    normalized_structures = {item.casefold() for item in structural_tags or []}
    structural_weights = RETRIEVAL_POLICY["structural_weights"]
    score_weights = RETRIEVAL_POLICY["score_weights"]
    if current_problem_asset_sha256 is not None:
        current_problem_asset_sha256 = _require_sha256(
            current_problem_asset_sha256,
            "current_problem_asset_sha256",
            "current problem",
        )
    ranked: list[tuple[float, str, dict[str, Any]]] = []
    for entry in load_paper_index(index_path, production=True)["papers"]:
        if current_canonical_problem_id and (
            entry.get("canonical_problem_id") == current_canonical_problem_id
        ):
            continue
        if current_problem_asset_sha256 and (
            entry.get("problem_asset_sha256") == current_problem_asset_sha256
        ):
            continue
        structural_reasons: list[str] = []
        domain_reasons: list[str] = []
        structural_similarity = 0.0
        if entry["problem_type"].casefold() == problem_type.casefold():
            structural_similarity += structural_weights["problem_type"]
            structural_reasons.append("problem_type 精确匹配")
        if entry["data_structure"].casefold() == data_structure.casefold():
            structural_similarity += structural_weights["data_structure"]
            structural_reasons.append("data_structure 精确匹配")
        matched_tasks = normalized_tasks.intersection(
            str(item).casefold() for item in entry["task_types"]
        )
        if matched_tasks:
            task_ratio = len(matched_tasks) / max(len(normalized_tasks), 1)
            structural_similarity += structural_weights["task_types"] * task_ratio
            structural_reasons.append("task_types 匹配: " + ", ".join(sorted(matched_tasks)))
        matched_structures = normalized_structures.intersection(
            str(item).casefold() for item in entry.get("structural_tags", [])
        )
        if matched_structures:
            structure_ratio = len(matched_structures) / max(len(normalized_structures), 1)
            structural_similarity += structural_weights["structural_tags"] * structure_ratio
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
        score = round(
            10.0
            * (
                score_weights["structural"] * structural_similarity
                + score_weights["domain"] * domain_similarity
            ),
            1,
        )
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
    identity_fields = ("canonical_problem_id", "problem_asset_sha256")
    missing_identity = [
        field
        for field in identity_fields
        if not isinstance(fingerprint.get(field), str) or not fingerprint[field].strip()
    ]
    if missing_identity:
        raise ContractError(
            "TASK_FINGERPRINT 必须提供当前题身份字段: "
            + ", ".join(missing_identity)
        )
    _require_sha256(
        fingerprint["problem_asset_sha256"],
        "problem_asset_sha256",
        "current problem",
    )
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
        "canonical_problem_id": fingerprint.get("canonical_problem_id"),
        "problem_asset_sha256": fingerprint.get("problem_asset_sha256"),
    }
    knowledge_dir = run_dir / "knowledge"
    fingerprint_path = knowledge_dir / "TASK_FINGERPRINT.json"
    retrieved_path = knowledge_dir / "RETRIEVED_PATTERNS.md"
    transfer_path = knowledge_dir / "PATTERN_TRANSFER_PLAN.md"
    storyboard_path = run_dir / "brief" / "MODEL_STORYBOARD.md"
    atomic_json(fingerprint_path, normalized)
    index = load_paper_index(index_path, production=True)
    matches = retrieve_papers(
        index_path,
        problem_type=normalized["problem_type"],
        data_structure=normalized["data_structure"],
        task_types=normalized["task_types"],
        keywords=normalized["keywords"],
        structural_tags=normalized["structural_tags"],
        current_canonical_problem_id=normalized["canonical_problem_id"],
        current_problem_asset_sha256=normalized["problem_asset_sha256"],
        limit=limit,
    )
    snapshot_path = write_retrieval_snapshot(
        run_dir,
        index_path,
        fingerprint_path,
        normalized,
        index,
        matches,
    )

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
    if index["paper_count"] == 0:
        retrieved_lines.extend(
            [
                "本轮没有使用经过验证的论文知识卡。",
                "",
            ]
        )
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
        "retrieval_snapshot": snapshot_path,
    }
