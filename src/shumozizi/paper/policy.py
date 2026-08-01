"""论文与视觉政策指纹、依赖失效和结果回退判定。

政策变化不改变已经真实执行的正式结果，但会使依赖它的写作或视觉产物需要
重新审阅。把这层单独实现可以避免用工作流元数据反向伪造科学结果的“当前性”。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file, sha256_tree
from shumozizi.core.repo_root import resolve_repo_root
from shumozizi.simple.state import read_simple_state, utc_now

POLICY_STATE_PATH = Path("state/policy-fingerprints.json")
STALE_STATE_PATH = Path("state/staleness.json")


def _policy_files(root: Path, kind: str) -> tuple[Path, ...]:
    """返回某一政策域的可审计输入文件。"""
    common = (
        root / "src/shumozizi/core/schema.py",
        root / "src/shumozizi/simple/state.py",
    )
    if kind == "paper":
        return common + (
            root / ".agents/skills/mathmodel-paper/SKILL.md",
            root / "src/shumozizi/paper/style_audit.py",
            root / "src/shumozizi/paper/templates.py",
            root / "schemas/paper_material_pool.schema.json",
            root / "schemas/research_storyboard.schema.json",
        )
    if kind == "visual":
        return common + (
            root / ".agents/skills/mathmodel-visual/SKILL.md",
            root / "src/shumozizi/simple/figures.py",
            root / "schemas/figure_plan.schema.json",
            root / "schemas/visual_opportunity_pool.schema.json",
        )
    raise ContractError(f"未知政策域: {kind}")


def policy_fingerprint(root: Path, kind: str) -> str:
    """按政策域文件内容生成稳定 SHA-256 指纹。"""
    resolved = root.resolve()
    digest = hashlib.sha256()
    for path in _policy_files(resolved, kind):
        digest.update(path.relative_to(resolved).as_posix().encode("utf-8"))
        digest.update(b"\0")
        if path.is_file():
            digest.update(bytes.fromhex(sha256_file(path)))
        else:
            digest.update(b"missing")
        digest.update(b"\0")
    return digest.hexdigest()


def current_policy_fingerprints(root: Path) -> dict[str, str]:
    """返回论文和视觉两个独立政策指纹。"""
    return {
        "paper": policy_fingerprint(root, "paper"),
        "visual": policy_fingerprint(root, "visual"),
    }


def _optional_digest(path: Path) -> str | None:
    """对可缺失输入返回摘要；缺失本身是可解释状态而不是异常。"""
    return sha256_tree(path) if path.exists() else None


def formal_result_digest(run_dir: Path) -> str | None:
    """摘要当前结果索引及其生产结果证据树。"""
    root = run_dir.resolve()
    index = root / "results/index.json"
    raw = root / "results/raw"
    if not index.is_file():
        return None
    digest = hashlib.sha256()
    digest.update(bytes.fromhex(sha256_file(index)))
    if raw.is_dir():
        digest.update(bytes.fromhex(sha256_tree(raw)))
    return digest.hexdigest()


def source_digest(run_dir: Path, relative: str) -> str | None:
    """计算运行目录内一个文件或目录的摘要。"""
    return _optional_digest(run_dir.resolve() / relative)


def refresh_policy_state(run_dir: Path) -> dict[str, Any]:
    """写入当前政策指纹快照，供后续判定是政策变化还是结果变化。"""
    root = run_dir.resolve()
    state = {
        "schema_version": "1.0",
        "run_id": read_simple_state(root)["run_id"],
        "updated_at": utc_now(),
        "fingerprints": current_policy_fingerprints(resolve_repo_root(Path(__file__))),
        "formal_result_digest": formal_result_digest(root),
    }
    old: dict[str, Any] = {}
    if (root / POLICY_STATE_PATH).is_file():
        try:
            old = load_json(root / POLICY_STATE_PATH)
        except ContractError:
            old = {}
    state["previous"] = {
        "fingerprints": old.get("fingerprints"),
        "formal_result_digest": old.get("formal_result_digest"),
    }
    atomic_json(root / POLICY_STATE_PATH, state)
    return state


def evaluate_staleness(
    run_dir: Path,
    *,
    paper_policy: str | None = None,
    visual_policy: str | None = None,
    results_digest: str | None = None,
) -> dict[str, Any]:
    """计算从正式结果到论文产物的最小失效闭包。

    Args:
        run_dir: 当前运行目录。
        paper_policy: 可选的测试/迁移用论文政策指纹。
        visual_policy: 可选的测试/迁移用视觉政策指纹。
        results_digest: 可选的测试/迁移用正式结果摘要。
    """
    root = run_dir.resolve()
    repo_root = resolve_repo_root(Path(__file__))
    policies = current_policy_fingerprints(repo_root)
    policies["paper"] = paper_policy or policies["paper"]
    policies["visual"] = visual_policy or policies["visual"]
    current_results = results_digest or formal_result_digest(root)
    pool_path = root / "paper/generated/material_pool.json"
    storyboard_path = root / "paper/generated/research_storyboard.json"
    opportunity_path = root / "figures/visual-opportunities.json"
    compile_path = root / "paper/compile-receipt.json"
    pool = load_json(pool_path) if pool_path.is_file() else None
    storyboard = load_json(storyboard_path) if storyboard_path.is_file() else None
    opportunities = load_json(opportunity_path) if opportunity_path.is_file() else None
    compile_receipt = load_json(compile_path) if compile_path.is_file() else None

    result_changed = bool(
        pool is not None
        and pool.get("source_bindings", {}).get("production_results_digest") != current_results
    )
    paper_changed = bool(pool is not None and pool.get("policy_fingerprint") != policies["paper"])
    storyboard_changed = bool(
        storyboard is not None
        and (
            storyboard.get("policy_fingerprint") != policies["paper"]
            or storyboard.get("material_pool_digest") != _optional_digest(pool_path)
        )
    )
    visual_changed = bool(
        opportunities is not None
        and opportunities.get("policy_fingerprint") != policies["visual"]
    )
    paper_compile_changed = bool(
        compile_receipt is not None
        and (
            compile_receipt.get("paper_policy_fingerprint") not in {None, policies["paper"]}
            or compile_receipt.get("visual_policy_fingerprint") not in {None, policies["visual"]}
            or compile_receipt.get("formal_result_digest") not in {None, current_results}
        )
    )
    reasons: list[str] = []
    if result_changed:
        reasons.append("正式生产结果或其证据树已变化")
    if paper_changed:
        reasons.append("论文政策指纹已变化")
    if storyboard_changed:
        reasons.append("研究故事板依赖的素材池或论文政策已变化")
    if visual_changed:
        reasons.append("视觉政策指纹已变化")
    if paper_compile_changed:
        reasons.append("论文编译回执不再绑定当前政策或正式结果")
    status = {
        "schema_version": "1.0",
        "run_id": read_simple_state(root)["run_id"],
        "evaluated_at": utc_now(),
        "current": {
            "formal_results": "current",
            "material_pool": "stale" if result_changed or paper_changed else ("current" if pool else "missing"),
            "research_storyboard": "stale" if result_changed or paper_changed or storyboard_changed else ("current" if storyboard else "missing"),
            "visual_opportunities": "stale" if result_changed or visual_changed else ("current" if opportunities else "missing"),
            "paper": "stale" if result_changed or paper_changed or storyboard_changed or visual_changed or paper_compile_changed else ("current" if compile_receipt else "missing"),
        },
        "changed_domains": {
            "formal_results": result_changed,
            "paper_policy": paper_changed,
            "visual_policy": visual_changed,
        },
        "reasons": reasons,
        "invalidated_artifacts": [
            name
            for name, state in {
                "material_pool": result_changed or paper_changed,
                "research_storyboard": result_changed or paper_changed or storyboard_changed,
                "visual_opportunities": result_changed or visual_changed,
                "paper_compile": result_changed or paper_changed or storyboard_changed or visual_changed or paper_compile_changed,
            }.items()
            if state
        ],
    }
    atomic_json(root / STALE_STATE_PATH, status)
    return status


def mark_policy_change(run_dir: Path, changed_domain: str) -> dict[str, Any]:
    """记录一次明确的政策变化，并返回新的失效状态。"""
    if changed_domain not in {"paper", "visual", "results"}:
        raise ContractError("changed_domain 必须为 paper、visual 或 results")
    return evaluate_staleness(run_dir)
