"""依据已验证 claim evidence 限制论文中的创新主张表述。

该模块只生成论文使用权限，不修改结果注册表、sealed result 或 claim evidence。
``stale=true`` 时，主张证据完全不可引用；结果数值是否可用仍由结果证据链独立决定。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.core.schema import require_valid

PAPER_CLAIM_GATE_SCHEMA = "paper_claim_gate"
PAPER_CLAIM_GATE_VERSION = "2.0"
PAPER_USES = {
    "contribution",
    "limited_contribution",
    "results",
    "failure_analysis",
    "inconclusive_discussion",
    "limitations",
}


def _usage_for_status(status: str, stale: bool) -> tuple[str, list[str], bool, str]:
    """把 claim status 映射成论文用途和贡献模式。"""
    if stale:
        return "blocked", [], False, "claim evidence 已 stale，禁止引用任何主张证据"
    policies = {
        "supported": (
            "full",
            ["contribution", "results", "limitations"],
            True,
            "已验证的结构化预测全部通过，可写确定性贡献",
        ),
        "partially_supported": (
            "limited",
            ["limited_contribution", "results", "limitations"],
            True,
            "仅部分结构化预测通过，只可写有限贡献并明确限制",
        ),
        "rejected": (
            "none",
            ["results", "failure_analysis", "limitations"],
            True,
            "创新主张被证伪，只可写结果、失败分析和限制",
        ),
        "inconclusive": (
            "none",
            ["results", "inconclusive_discussion", "limitations"],
            True,
            "证据不足，不得写确定性贡献，只可写结果和未决讨论",
        ),
    }
    try:
        return policies[status]
    except KeyError as exc:
        raise ContractError(f"不支持的 claim status: {status}") from exc


def gate_contribution_claims(
    evidence: Mapping[str, Any], *, claim_evidence_sha256: str | None = None
) -> dict[str, Any]:
    """从 claim evidence 生成论文主张使用权限。

    ``evidence`` 只作为输入读取；返回文档不包含自由文本裁决逻辑，所有权限由
    ``status`` 和顶层 ``stale`` 机械映射得到。
    """
    document = dict(evidence)
    require_valid(document, "claim_evidence")
    stale = document["stale"] is True
    claims = []
    for claim in document.get("claims", []):
        status = claim["status"]
        mode, allowed_uses, reference_allowed, reason = _usage_for_status(status, stale)
        claims.append(
            {
                "claim_id": claim["claim_id"],
                "status": status,
                "reference_allowed": reference_allowed,
                "contribution_mode": mode,
                "allowed_uses": allowed_uses,
                "reason": reason,
            }
        )
    gate = {
        "schema_name": PAPER_CLAIM_GATE_SCHEMA,
        "schema_version": PAPER_CLAIM_GATE_VERSION,
        "run_id": document["run_id"],
        "evaluator_version": document["evaluator_version"],
        "stale": stale,
        "claimability": document.get("claimability", "claims"),
        "claims": claims,
    }
    if claim_evidence_sha256 is not None:
        gate["claim_evidence_sha256"] = claim_evidence_sha256
    if stale:
        gate["stale_reason"] = document.get("stale_reason", "claim evidence 已 stale")
    elif document.get("claimability") == "none":
        gate["claimability_reason"] = document.get("claimability_reason") or document.get(
            "reason", "当前运行没有结构化创新主张"
        )
    return gate


def gate_paper_claims(
    run_dir: Path,
    *,
    evidence_path: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """读取 claim evidence 并写入绑定哈希的论文门禁报告。"""
    run_dir = run_dir.resolve()
    source = evidence_path or (run_dir / "claims" / "claim_evidence.json")
    output = output_path or (run_dir / "paper" / "claim_gate.json")
    if not source.is_file():
        raise ContractError(f"缺少 claim evidence: {source}")
    evidence = load_json(source)
    gate = gate_contribution_claims(evidence, claim_evidence_sha256=sha256_file(source))
    require_valid(gate, PAPER_CLAIM_GATE_SCHEMA)
    atomic_json(output, gate)
    return gate


def require_paper_claim_allowed(
    gate: Mapping[str, Any], claim_id: str, *, use: str = "contribution"
) -> dict[str, Any]:
    """要求某个主张可用于指定论文用途，否则抛出协议异常。"""
    if use not in PAPER_USES:
        raise ContractError(f"不支持的论文用途: {use}")
    if gate.get("stale") is True:
        raise ContractError("claim evidence 已 stale，禁止引用任何主张证据")
    claim = next((item for item in gate.get("claims", []) if item.get("claim_id") == claim_id), None)
    if claim is None:
        raise ContractError(f"论文门禁中不存在 claim: {claim_id}")
    if claim.get("reference_allowed") is not True:
        raise ContractError(f"claim {claim_id} 的证据引用权限已关闭")
    if use not in claim.get("allowed_uses", []):
        raise ContractError(
            f"claim {claim_id} 不允许用于 {use}: {claim.get('reason', '论文权限不足')}"
        )
    return dict(claim)
