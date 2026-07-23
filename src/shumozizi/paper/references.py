"""登记仅用于表达组织的离线论文卡，不把历史论文带入事实证据链。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, relative_inside, sha256_file
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.core.schema import require_valid
from shumozizi.knowledge.papers import read_paper_card
from shumozizi.simple.quality import quality_allows_paper
from shumozizi.simple.state import read_simple_state, utc_now

PAPER_REFERENCE_RECEIPT_SCHEMA = "paper_reference_receipt"
PAPER_REFERENCE_RECEIPT_VERSION = "2.0"
PAPER_REFERENCE_PATH = Path("paper/paper_references.json")
CONTROLLED_PAPER_INDEX_PATH = Path("knowledge/indexes/papers.json")
CONTROLLED_PAPER_CARDS_PATH = Path("knowledge/cards/papers")
ALLOWED_REFERENCE_USES = (
    "section_organization",
    "model_explanation",
    "validation_narrative",
    "figure_contract",
)
PROHIBITED_REFERENCE_USES = (
    "rendering",
    "citation",
    "evidence",
    "claim_evidence",
    "result_reference",
    "fact_source",
)
FROZEN_PAPER_PHASES = {"paper", "paper_review", "verify", "final_review", "complete"}


def _default_index_path() -> Path:
    """返回仓库内离线论文卡索引。"""
    return resolve_repo_root(Path(__file__)) / CONTROLLED_PAPER_INDEX_PATH


def _index_root(index_path: Path) -> Path:
    """推断论文索引所属的仓库根或测试根。"""
    parent = index_path.resolve().parent
    if parent.name == "indexes" and parent.parent.name == "knowledge":
        return parent.parent.parent
    return parent


def _controlled_index_path(index_path: Path | None) -> Path:
    """解析唯一受控的论文卡索引，拒绝调用方注入其他目录。

    Args:
        index_path: 兼容性参数；提供时必须与仓库固定索引完全一致。

    Returns:
        受控 ``knowledge/indexes/papers.json`` 的规范绝对路径。

    Raises:
        ContractError: 索引路径不在受控仓库位置，或调用方尝试替换索引。
    """
    expected = _default_index_path().resolve()
    root = _index_root(expected)
    if expected != (root / CONTROLLED_PAPER_INDEX_PATH).resolve():
        raise ContractError("论文卡索引必须位于受控 knowledge/indexes/papers.json")
    if index_path is not None and Path(index_path).resolve() != expected:
        raise ContractError("论文卡索引只能使用受控 knowledge/indexes/papers.json")
    return expected


def _resolve_index_card(index_root: Path, value: object) -> Path:
    """解析受索引登记的卡路径，拒绝绝对路径和目录穿越。"""
    if not isinstance(value, str) or not value.strip():
        raise ContractError("论文卡索引 card_path 必须是非空相对路径")
    supplied = Path(value)
    if supplied.is_absolute():
        raise ContractError("论文卡索引不得登记绝对 card_path")
    candidate = (index_root / supplied).resolve()
    try:
        candidate.relative_to(index_root.resolve())
    except ValueError as exc:
        raise ContractError(f"论文卡路径越过索引根目录: {value}") from exc
    controlled_cards = (index_root / CONTROLLED_PAPER_CARDS_PATH).resolve()
    try:
        candidate.relative_to(controlled_cards)
    except ValueError as exc:
        raise ContractError(
            f"论文卡必须位于受控 knowledge/cards/papers 目录: {value}"
        ) from exc
    if not candidate.is_file():
        raise ContractError(f"已登记论文卡不存在: {value}")
    return candidate


def _relative_to_index_root(index_root: Path, path: Path) -> str:
    """返回不泄露机器绝对路径的索引根相对路径。"""
    try:
        return path.resolve().relative_to(index_root.resolve()).as_posix()
    except ValueError as exc:
        raise ContractError(f"路径越过论文索引根目录: {path}") from exc


def _require_frozen_production(
    run_dir: Path, production_result_ids: list[str]
) -> dict[str, Any]:
    """验证离线参考前的生产冻结条件。"""
    state = read_simple_state(run_dir)
    if state.get("execution_mode") != "production":
        raise ContractError("离线论文卡只允许在 production 模式登记")
    if state["phase"] not in FROZEN_PAPER_PHASES:
        raise ContractError("离线论文卡必须在 production 结果冻结后登记")
    if not production_result_ids:
        raise ContractError("离线论文卡需要至少一个有效的 production 结果")
    invalid = [
        result_id
        for result_id in production_result_ids
        if not isinstance(result_id, str) or not quality_allows_paper(run_dir, result_id)
    ]
    if invalid:
        raise ContractError(
            "缺少有效且 current 的 production 结果: " + ", ".join(map(str, invalid))
        )
    return state


def _registered_cards(
    index_document: Mapping[str, Any],
    *,
    index_root: Path,
    card_ids: list[str],
) -> list[dict[str, Any]]:
    """从索引解析并哈希有限数量的离线卡，不读取或复制卡正文。"""
    papers = index_document.get("papers")
    if not isinstance(papers, list):
        raise ContractError("论文卡索引缺少 papers 数组")
    by_id = {
        item.get("paper_id"): item
        for item in papers
        if isinstance(item, dict) and isinstance(item.get("paper_id"), str)
    }
    records: list[dict[str, Any]] = []
    for card_id in card_ids:
        item = by_id.get(card_id)
        if item is None:
            raise ContractError(f"论文卡索引中不存在 paper_id: {card_id}")
        source_sha256 = item.get("source_sha256")
        if not isinstance(source_sha256, str) or len(source_sha256) != 64:
            raise ContractError(f"论文卡 source_sha256 无效: {card_id}")
        card_path = _resolve_index_card(index_root, item.get("card_path"))
        card_metadata = read_paper_card(card_path)["metadata"]
        if str(card_metadata["paper_id"]) != card_id:
            raise ContractError(f"论文卡 paper_id 与索引不一致: {card_id}")
        if str(card_metadata["source_sha256"]) != source_sha256:
            raise ContractError(f"论文卡 source_sha256 与索引不一致: {card_id}")
        records.append(
            {
                "paper_id": card_id,
                "card_path": _relative_to_index_root(index_root, card_path),
                "card_sha256": sha256_file(card_path),
                "source_sha256": source_sha256,
                "allowed_uses": list(ALLOWED_REFERENCE_USES),
            }
        )
    return records


def _receipt_output_path(run_dir: Path, output_path: Path | None) -> Path:
    """解析运行目录内的论文参考收据输出位置。"""
    candidate = run_dir / PAPER_REFERENCE_PATH if output_path is None else output_path
    if not candidate.is_absolute():
        candidate = run_dir / candidate
    try:
        relative_inside(run_dir, candidate)
    except ContractError as exc:
        raise ContractError("论文参考收据必须写入当前运行目录") from exc
    return candidate.resolve()


def register_paper_references(
    run_dir: Path,
    *,
    card_ids: list[str],
    production_result_ids: list[str],
    index_path: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """登记 1--2 张离线论文卡作为非渲染式写作参考。

    Args:
        run_dir: 当前 Capability-First v3 运行目录。
        card_ids: 已登记的离线论文卡 ID，数量只能为一或二。
        production_result_ids: 已冻结且仍可写入论文的当前生产结果 ID。
        index_path: 兼容性参数；提供时必须等于受控仓库知识索引。
        output_path: 可选的运行目录内收据路径。

    Returns:
        不含论文正文、引用或事实字段的审计收据。

    Raises:
        ContractError: 生产冻结、卡登记、哈希或输出边界不满足约束。
    """
    root = run_dir.resolve()
    if not isinstance(card_ids, list) or not 1 <= len(card_ids) <= 2:
        raise ContractError("离线论文参考只能登记 1--2 张论文卡")
    if len(set(card_ids)) != len(card_ids) or any(
        not isinstance(card_id, str) or not card_id for card_id in card_ids
    ):
        raise ContractError("离线论文参考 card_ids 必须是唯一非空字符串")
    if not isinstance(production_result_ids, list) or len(set(production_result_ids)) != len(
        production_result_ids
    ):
        raise ContractError("production_result_ids 必须是唯一数组")
    state = _require_frozen_production(root, production_result_ids)
    source_index = _controlled_index_path(index_path)
    if not source_index.is_file():
        raise ContractError(f"论文卡索引不存在: {source_index}")
    index_document = load_json(source_index)
    if index_document.get("schema_name") != "paper_card_index":
        raise ContractError("论文卡索引 schema_name 必须为 paper_card_index")
    index_root = _index_root(source_index)
    receipt = {
        "schema_name": PAPER_REFERENCE_RECEIPT_SCHEMA,
        "schema_version": PAPER_REFERENCE_RECEIPT_VERSION,
        "run_id": state["run_id"],
        "state_revision": state["revision"],
        "execution_mode": "production",
        "frozen_phase": state["phase"],
        "production_result_ids": list(production_result_ids),
        "paper_index": {
            "path": _relative_to_index_root(index_root, source_index),
            "sha256": sha256_file(source_index),
        },
        "reference_role": "offline_writing_reference",
        "prohibited_uses": list(PROHIBITED_REFERENCE_USES),
        "cards": _registered_cards(
            index_document,
            index_root=index_root,
            card_ids=card_ids,
        ),
        "registered_at": utc_now(),
    }
    require_valid(receipt, PAPER_REFERENCE_RECEIPT_SCHEMA)
    atomic_json(_receipt_output_path(root, output_path), receipt)
    return receipt


def verify_paper_references(
    run_dir: Path,
    *,
    receipt_path: Path | None = None,
    index_path: Path | None = None,
) -> dict[str, Any]:
    """复验离线论文卡收据仍满足生产冻结和哈希约束。

    Args:
        run_dir: 当前 Capability-First v3 运行目录。
        receipt_path: 可选的已登记收据路径。
        index_path: 兼容性参数；提供时必须等于受控仓库知识索引。

    Returns:
        含 ``valid`` 和可读错误列表的复验结果。
    """
    root = run_dir.resolve()
    path = _receipt_output_path(root, receipt_path)
    errors: list[str] = []
    try:
        receipt = load_json(path)
        require_valid(receipt, PAPER_REFERENCE_RECEIPT_SCHEMA)
        if receipt["run_id"] != root.name:
            errors.append("论文参考收据 run_id 与运行目录不一致")
        state = _require_frozen_production(root, list(receipt["production_result_ids"]))
        if receipt["state_revision"] > state["revision"]:
            errors.append("论文参考收据来自未来 state revision")
        source_index = _controlled_index_path(index_path)
        index_root = _index_root(source_index)
        if receipt["paper_index"]["path"] != _relative_to_index_root(
            index_root, source_index
        ):
            errors.append("论文卡索引路径已漂移")
        if sha256_file(source_index) != receipt["paper_index"]["sha256"]:
            errors.append("论文卡索引哈希已漂移")
        index_document = load_json(source_index)
        expected = _registered_cards(
            index_document,
            index_root=index_root,
            card_ids=[item["paper_id"] for item in receipt["cards"]],
        )
        if expected != receipt["cards"]:
            errors.append("论文卡路径、来源或哈希已漂移")
    except (ContractError, KeyError, OSError, TypeError, ValueError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors, "receipt_path": str(path)}


def writing_reference_cards(
    run_dir: Path,
    *,
    receipt_path: Path | None = None,
    index_path: Path | None = None,
) -> list[dict[str, str | list[str]]]:
    """返回可按需读取的卡路径和允许用途，不返回任何历史论文内容。

    Args:
        run_dir: 当前 Capability-First v3 运行目录。
        receipt_path: 可选的收据路径。
        index_path: 兼容性参数；提供时必须等于受控仓库知识索引。

    Returns:
        卡 ID、路径和限定用途列表；调用方自行按需读取原卡。

    Raises:
        ContractError: 收据失效或被用作非写作参考。
    """
    verified = verify_paper_references(
        run_dir,
        receipt_path=receipt_path,
        index_path=index_path,
    )
    if not verified["valid"]:
        raise ContractError("论文参考收据不可用: " + "; ".join(verified["errors"]))
    receipt = load_json(_receipt_output_path(run_dir.resolve(), receipt_path))
    return [
        {
            "paper_id": item["paper_id"],
            "card_path": item["card_path"],
            "allowed_uses": list(item["allowed_uses"]),
        }
        for item in receipt["cards"]
    ]
