"""把科学解释字段登记到已存在的 production 结果上（事后回填）。

结果登记（``run_simple_experiment``）只记录机器指标；论文素材池的
``_result_materials`` 按白名单从结果提取 ``conclusion / mechanism /
derivation / boundary`` 作为 Direct Answer 与 Mechanism 素材。本命令为
已执行的结果补录这些字段，按 ``result_id`` 精确挂载，不重跑实验命令、
不改变 metrics、output_hashes 等执行事实，只扩展 index 条目的解释字段。

用法::

    python scripts/runtime/record_explanations.py <run_dir> --from-json explanations.json

``explanations.json`` 形如::

    {
      "q1_final": {
        "conclusion": "固定策略遮蔽时长 1.3958s（完整遮挡判据）",
        "mechanism": "云团球体与导弹-目标视线线段相交…",
        "derivation": "余量公式 R_c - R_t·(d_c/d_t)…",
        "boundary": "云团固定半径球体，未建模浓度衰减…"
      }
    }

字段均可省略；已存在的同名字段会被覆盖并输出变更提示。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from shumozizi.core.io import ContractError, atomic_json, load_json  # noqa: E402
from shumozizi.simple.results import INDEX_PATH, require_result_index  # noqa: E402

EXPLANATION_FIELDS = ("conclusion", "mechanism", "derivation", "boundary")
_SCHEMA_NAME = "simple_result_index"


def _load_explanations(path: Path) -> dict[str, dict[str, str]]:
    """读取并验证解释字段 JSON。"""
    try:
        payload = load_json(path)
    except (ContractError, OSError, ValueError, TypeError) as exc:
        raise ContractError(f"无法读取解释文件 {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractError("解释文件必须是按 result_id 键的对象")
    normalized: dict[str, dict[str, str]] = {}
    for result_id, fields in payload.items():
        if not isinstance(fields, dict):
            raise ContractError(f"{result_id} 的解释字段必须是对象")
        clean: dict[str, str] = {}
        for field, value in fields.items():
            if field not in EXPLANATION_FIELDS:
                raise ContractError(
                    f"{result_id} 含未知解释字段 {field!r}；允许 {EXPLANATION_FIELDS}"
                )
            if value is None:
                continue
            if not isinstance(value, str):
                raise ContractError(f"{result_id}.{field} 必须为字符串")
            if not value.strip():
                continue
            clean[field] = value.strip()
        if clean:
            normalized[result_id] = clean
    return normalized


def _refresh_challenge_evidence(
    root: Path, changed_result_ids: list[str]
) -> dict[str, Any]:
    """结果条目哈希变化后重建科学挑战证据，避免交接门因哈希漂移阻断。

    ``verify_scientific_challenge_evidence`` 校验结果索引条目的 JSON 哈希，
    挂载解释字段会改变条目，因此必须用正式登记路径
    ``record_scientific_challenge_evidence`` 重新绑定当前结果；原有攻击描述、
    发现与阶段 A 语义评估原样保留（``_normalize_scientific_findings`` 幂等）。

    Args:
        root: 运行目录。
        changed_result_ids: 条目哈希发生变化的 result_id 列表。

    Returns:
        证据重建状态；证据文件缺失时返回未刷新原因（不阻断挂载本身）。
    """
    if not changed_result_ids:
        return {"refreshed": False, "reason": "no_changes"}
    path = root / "review/scientific-challenge-evidence.json"
    if not path.is_file():
        return {"refreshed": False, "reason": "no_evidence_file"}
    try:
        payload = load_json(path)
    except (ContractError, OSError, ValueError, TypeError) as exc:
        return {"refreshed": False, "reason": f"evidence 不可读: {exc}"}
    from shumozizi.simple.review_focus import record_scientific_challenge_evidence

    current_ids = [
        str(item.get("result_id"))
        for item in payload.get("results", [])
        if isinstance(item, dict) and item.get("evidence_role") == "current"
    ]
    comparison_ids = [
        str(item.get("result_id"))
        for item in payload.get("results", [])
        if isinstance(item, dict) and item.get("evidence_role") == "comparison"
    ]
    record_scientific_challenge_evidence(
        root,
        result_ids=current_ids,
        attack_description=str(payload.get("attack_description", "")),
        comparison_result_ids=comparison_ids or None,
        findings=payload.get("findings"),
        stage_a_semantic_assessment=payload.get("stage_a_semantic_assessment"),
    )
    return {
        "refreshed": True,
        "reason": "result_entries_changed",
        "result_ids": current_ids,
    }


def record_explanations(
    run_dir: Path, explanations: dict[str, dict[str, str]]
) -> dict[str, Any]:
    """按 result_id 把解释字段写入结果索引条目。

    Args:
        run_dir: v3 运行目录。
        explanations: result_id → {field: text} 映射。

    Returns:
        变更摘要：每项含 result_id、变更字段与是否新建；含证据重建状态。

    Raises:
        ContractError: 目标结果不存在、非 production/current，或索引校验失败。
    """
    root = run_dir.resolve()
    index = load_json(root / INDEX_PATH)
    by_id = {str(item.get("result_id")): item for item in index.get("results", [])}
    summary: list[dict[str, Any]] = []
    changed_ids: list[str] = []
    for result_id, fields in explanations.items():
        entry = by_id.get(result_id)
        if entry is None:
            raise ContractError(f"结果 {result_id} 不在索引中")
        if entry.get("execution_mode") != "production":
            raise ContractError(f"结果 {result_id} 不是 production 结果，拒绝挂载解释")
        if entry.get("status") != "current":
            raise ContractError(
                f"结果 {result_id} 状态为 {entry.get('status')}，"
                "只允许给 current 结果挂载解释"
            )
        changed = [field for field in fields if entry.get(field) != fields[field]]
        if changed:
            entry.update(fields)
            changed_ids.append(result_id)
            summary.append(
                {"result_id": result_id, "fields": changed, "overwritten": True}
            )
        else:
            summary.append({"result_id": result_id, "fields": [], "overwritten": False})
    if changed_ids:
        require_result_index(index)
        atomic_json(root / INDEX_PATH, index)
    evidence = _refresh_challenge_evidence(root, changed_ids)
    return {"recorded": len(summary), "changes": summary, "evidence_refresh": evidence}


def main() -> int:
    """回填解释字段并输出变更摘要。"""
    parser = argparse.ArgumentParser(description="为 production 结果补录科学解释字段")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "--from-json",
        type=Path,
        required=True,
        help="解释字段 JSON 路径：{result_id: {conclusion/mechanism/derivation/boundary: 文本}}",
    )
    args = parser.parse_args()
    try:
        explanations = _load_explanations(args.from_json)
        if not explanations:
            raise ContractError("解释文件没有可挂载的非空字段")
        result = record_explanations(args.run_dir, explanations)
    except ContractError as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"success": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
