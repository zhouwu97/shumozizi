"""视觉数据可画性解析器：把“论文最需要什么图”与“production 结果实际能画什么图”接通。

给定数学对象与候选 archetype，读取对应 production 结果工件，按该 archetype 真正
需要的语义组检查字段是否可用，输出 ``available_fields / missing_fields / can_render``，
并据此给出 ``direct_render`` 或 ``data_missing`` 的确定性路由决策。

同源原则（防止 resolver、实验合同与 renderer 各持一套字段名而漂移）：

- 语义组别名来自 :data:`shumozizi.simple.visual_requirements._OBJECT_GROUPS`，
  与实验阶段对象级最低字段检查共享同一张表；
- 本模块只补充生产持久化的常见字段名（如 ``p_estimate``、``n_conductive``），
  不反向放宽实验阶段的对象校验；
- “哪些 archetype 是正式 renderer”以
  :data:`shumozizi.figures.renderers.DETERMINISTIC_RENDERER_ARCHETYPES` 为唯一权威，
  避免“路由说可用、renderer 实际未接入”的伪可用。

禁止 silent fallback：数据缺失时返回 ``data_missing`` 并列出缺失字段，上层必须
暴露缺口，不得用通用示意图假装“该视觉需求已解决”。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shumozizi.core.io import ContractError, load_json
from shumozizi.simple.visual_requirements import _OBJECT_GROUPS

# archetype ID -> 数学对象。与 paper.visual_requirements._OBJECT_ROUTE 语义一致，
# 但避免 paper -> simple 反向导入造成的循环依赖，因此在本模块保留一份只读映射。
_ARCHETYPE_OBJECTS: dict[str, str] = {
    "periodic_spatial_scene": "periodic_spatial_geometry",
    "spatial_scene_cross_section": "spatial_geometry",
    "spatial_contact_backbone_triptych": "periodic_contact_network",
    "contact_network_backbone": "contact_network",
    "oracle_comparison_zoom": "geometric_oracle_comparison",
    "probability_threshold_curve": "probability_transition",
    "uncertainty_margin_ribbon": "uncertainty_threshold",
    "integer_feasible_region": "integer_feasible_region",
    "cost_reliability_frontier": "pareto_cost_reliability",
    "convergence_envelope": "search_stability",
    "implementation_agreement": "implementation_agreement",
    "shared_model_pipeline": "shared_model_pipeline",
}

# 语义组别名总表：以对象级最低字段组为基底，合并生产持久化的常见字段名。
# 组名即“合同字段名”，resolver 输出的 available_fields/missing_fields 使用组名。
_ALIASES: dict[str, set[str]] = {}
for _groups in _OBJECT_GROUPS.values():
    for _name, _aliases in _groups:
        _ALIASES.setdefault(_name, set()).update(_aliases)

# 生产持久化常见别名（observing 实际 results/raw 工件命名）。
_ALIASES["probability"] = {
    "probability", "p_estimate", "prob_estimate", "prob", "p_hat",
    "point_estimate", "estimate",
}
_ALIASES["successes"] |= {"n_conductive", "conductive_count", "conductive"}
_ALIASES["trials"] |= {"n_samples", "sample_count"}
_ALIASES["interval"] |= {"ci_lower", "ci_upper", "ci_low", "ci_hi"}
_ALIASES["x_values"] |= {"n_media", "f_pct"}
_ALIASES["lattice_points"] |= {"grid_points"}
_ALIASES["candidate_points"] |= {"frontier_points", "solutions"}
_ALIASES["seeds"] |= {"seed", "seed_base"}

# 每个确定性 renderer 真正需要的语义组（与 figures/renderers.py 的读取一致）。
# 可选组（renderer 提供默认值或只增强表现，如 threshold=0.90、interval 回落点估计）
# 不写入此处，避免因“渲染可容忍缺失”的字段阻断 can_render。
_ARCHETYPE_REQUIRED_GROUPS: dict[str, tuple[str, ...]] = {
    "periodic_spatial_scene": ("object_coordinates",),
    "spatial_scene_cross_section": ("object_coordinates",),
    "spatial_contact_backbone_triptych": ("object_coordinates",),
    "contact_network_backbone": ("nodes", "edges"),
    "oracle_comparison_zoom": ("candidate_pairs", "exact_distance", "capsule_distance"),
    "probability_threshold_curve": ("x_values", "probability"),
    "uncertainty_margin_ribbon": ("x_values", "interval_low"),
    "integer_feasible_region": ("lattice_points", "feasible_mask", "costs"),
    "cost_reliability_frontier": ("candidate_points", "costs", "probability"),
    "convergence_envelope": ("seeds", "budget_or_samples", "quantile_bands"),
    "implementation_agreement": ("classifications", "differences"),
    "shared_model_pipeline": ("stages", "relations"),
}

_DATA_MISSING = "data_missing"
_DIRECT_RENDER = "direct_render"


def _artifact_documents(
    run_dir: Path,
    source_result_ids: list[str],
    source_artifact_paths: list[str] = (),
) -> list[dict[str, Any]]:
    """解析 source_result_ids 与 source_artifact_paths 到 results/raw 工件并加载 JSON。

    优先从 results/index.json 的 output_files 解析 result_id；visual_outputs 声明的
    ``output_path`` 绘图原语工件按相对路径直接加载。缺失或损坏的工件被跳过，不抛错，
    保证 resolver 在结果未冻结时仍能给出诚实的 data_missing。
    """
    root = run_dir.resolve()
    wanted = {str(item) for item in source_result_ids if str(item).strip()}
    relatives: list[str] = [str(item) for item in source_artifact_paths if str(item).strip()]
    index_path = root / "results/index.json"
    if index_path.is_file():
        try:
            index = load_json(index_path)
            for result in index.get("results", []):
                if not isinstance(result, dict) or result.get("result_id") not in wanted:
                    continue
                for rel in result.get("output_files", []):
                    if isinstance(rel, str) and rel.endswith(".json"):
                        relatives.append(rel)
        except (ContractError, OSError, ValueError):
            relatives = []
    for result_id in sorted(wanted):
        relatives.append(f"results/raw/{result_id}.json")
    bases = (
        root,
        root / "results/raw",
        root / "results",
    )
    documents: list[dict[str, Any]] = []
    seen: set[str] = set()
    for relative in relatives:
        candidates = [base / relative for base in bases] + [root / f"results/raw/{relative}"]
        candidate = next((path for path in candidates if path.is_file()), None)
        if candidate is None:
            continue
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        try:
            document = load_json(candidate)
        except (ContractError, OSError, ValueError, TypeError):
            continue
        if isinstance(document, dict):
            documents.append(document)
    return documents


def _reachable_keys(value: Any, depth: int = 0) -> set[str]:
    """递归收集工件中出现的所有键（含列表内对象的嵌套键）。

    深度上限防止病态嵌套数据拖慢解析；对“字段是否出现”的判断足够。
    """
    keys: set[str] = set()
    if depth > 5:
        return keys
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key))
            keys.update(_reachable_keys(child, depth + 1))
    elif isinstance(value, list):
        for item in value:
            keys.update(_reachable_keys(item, depth + 1))
    return keys


_PROBABILITY_VALUE_KEYS = frozenset(
    {
        "p_estimate", "prob_estimate", "probability", "prob", "point_estimate",
        "ci_lower", "wilson_low", "interval_low", "ci_low",
        "ci_upper", "wilson_high", "interval_high", "ci_hi",
    }
)


def _probability_values(documents: list[dict[str, Any]]) -> list[float]:
    """从工件递归收集概率/区间值，用于转变区覆盖检查。"""
    values: list[float] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in _PROBABILITY_VALUE_KEYS and isinstance(child, (int, float)):
                    values.append(float(child))
                else:
                    collect(child)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    for document in documents:
        collect(document)
    return values


def _saturation_warning(archetype: str, documents: list[dict[str, Any]]) -> str | None:
    """对概率类 archetype 检查采样是否覆盖转变区，全饱和时给出明确警告。

    数据字段存在 ≠ 数据能支撑转变曲线。若所有点估计/区间都接近 0 或 1、跨度不足，
    连续转变曲线会被误画成假 sigmoid；此时必须暴露缺口，提示自适应补采样，而不是
    为高级感伪造转变。
    """
    if archetype not in {
        "probability_threshold_curve",
        "uncertainty_margin_ribbon",
        "cost_reliability_frontier",
    }:
        return None
    values = [value for value in _probability_values(documents) if 0.0 <= value <= 1.0]
    if not values:
        return None
    span = max(values) - min(values)
    all_high = all(value >= 0.999 for value in values)
    all_low = all(value <= 0.001 for value in values)
    if all_high or all_low or span < 0.01:
        return (
            "probability_transition_saturated: 当前 production 采样未覆盖转变区"
            "（点估计接近 0 或 1、跨度不足）；不支持连续转变曲线，不得伪造 sigmoid。"
        )
    return None


def resolve_visual_data_availability(
    run_dir: Path,
    question_id: str,
    source_result_ids: list[str],
    preferred_archetype: str,
    *,
    mathematical_object: str | None = None,
    source_artifact_paths: list[str] = (),
) -> dict[str, Any]:
    """判断指定 archetype 能否由当前 production 结果直接渲染。

    Args:
        run_dir: 运行目录。
        question_id: 问题 ID；当 source_result_ids 为空时用于回退定位该问当前结果。
        source_result_ids: 需求绑定的结果 ID 列表。
        preferred_archetype: 候选 archetype ID。
        mathematical_object: 数学对象；省略时按 archetype 反查。

    Returns:
        包含 ``archetype / mathematical_object / required_fields /
        available_fields / missing_fields / can_render / decision /
        source_artifacts`` 的判定结果。
    """
    archetype = str(preferred_archetype or "").strip()
    if not archetype:
        return {
            "archetype": "",
            "mathematical_object": str(mathematical_object or ""),
            "required_fields": [],
            "available_fields": [],
            "missing_fields": [],
            "can_render": False,
            "decision": _DATA_MISSING,
            "note": "未提供候选 archetype",
            "source_artifacts": [],
        }
    object_name = (
        str(mathematical_object or "").strip()
        or _ARCHETYPE_OBJECTS.get(archetype, "")
    )
    required = list(_ARCHETYPE_REQUIRED_GROUPS.get(archetype, ()))
    if not required:
        # 未登记 renderer 契约的 archetype 无法确认可画性，诚实返回 data_missing。
        return {
            "archetype": archetype,
            "mathematical_object": object_name,
            "required_fields": [],
            "available_fields": [],
            "missing_fields": [],
            "can_render": False,
            "decision": _DATA_MISSING,
            "note": f"未登记确定性 renderer archetype: {archetype}",
            "source_artifacts": [],
        }
    documents = _artifact_documents(run_dir, source_result_ids, list(source_artifact_paths))
    reachable: set[str] = set()
    for document in documents:
        reachable.update(_reachable_keys(document))
    available: list[str] = []
    missing: list[str] = []
    for group in required:
        aliases = _ALIASES.get(group)
        if aliases is None:
            missing.append(group)
            continue
        if reachable & aliases:
            available.append(group)
        else:
            missing.append(group)
    can_render = not missing
    return {
        "archetype": archetype,
        "mathematical_object": object_name,
        "required_fields": required,
        "available_fields": available,
        "missing_fields": missing,
        "can_render": can_render,
        "decision": _DIRECT_RENDER if can_render else _DATA_MISSING,
        "warnings": [
            warning
            for warning in [_saturation_warning(archetype, documents)]
            if warning
        ],
        "source_artifacts": sorted(
            {str(document.get("result_id", "")).strip() for document in documents if document.get("result_id")}
        ),
        "note": "" if can_render else "当前 production 结果缺少该 renderer 必需的语义字段；不得用示意图冒充正式证据图。",
    }


def availability_for_requirement(
    run_dir: Path, requirement: dict[str, Any]
) -> dict[str, Any] | None:
    """给定视觉需求，选第一个确定性 renderer archetype 解析数据可画性。

    无确定性 renderer archetype 时返回 None（该需求走解释型图/Sandbox，不进入
    production 证据 renderer 决策）。只有已接入 ``figures.renderers`` 的 archetype
    才会被解析，避免默认 ``mathematical_object_schematic`` 造成伪可用。
    """
    archetypes = [
        str(item.get("id", "")).strip()
        for item in requirement.get("preferred_archetypes", [])
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    ]
    if not archetypes:
        return None
    from shumozizi.figures.renderers import deterministic_renderer_archetypes

    chosen = next((item for item in archetypes if item in deterministic_renderer_archetypes()), None)
    if chosen is None:
        return None
    return resolve_visual_data_availability(
        run_dir,
        str(requirement.get("question_id", "")),
        list(requirement.get("source_result_ids", [])),
        chosen,
        mathematical_object=str(requirement.get("mathematical_object", "")).strip() or None,
        source_artifact_paths=list(requirement.get("source_artifact_paths", [])),
    )


__all__ = [
    "resolve_visual_data_availability",
    "availability_for_requirement",
    "_DIRECT_RENDER",
    "_DATA_MISSING",
]
