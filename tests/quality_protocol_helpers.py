"""构造独立 adapter 与遗留质量声明的测试夹具。"""

from __future__ import annotations

import json
from itertools import product
from pathlib import Path
from typing import Any

from shumozizi.simple.adapters import run_verification_protocol


def standard_selection_contract() -> dict[str, Any]:
    """返回可由合成 adapter 重放的最小选择合同。

    Returns:
        含原始坐标和联合覆盖定义的加性目标合同。
    """
    return {
        "objective": {
            "metric": "objective",
            "direction": "maximize",
            "objective_version": "test-objective-v1",
            "scorer_version": "test-scorer-v1",
            "constraint_version": "test-constraint-v1",
            "semantics": "additive",
            "fine_tolerance": 0.0,
        },
        "coverage": {
            "candidate_variables": ["decision"],
            "groups": [
                {
                    "id": "decision",
                    "variables": ["decision"],
                    "minimum_joint_coverage": 1.0,
                    "metric": "occupied_bins",
                    "bins_per_variable": 2,
                    "bounds": {"decision": [0.0, 1.0]},
                }
            ],
        },
        "required_evidence": [],
    }


def _adapter_selection_contract(selection_contract: dict[str, Any]) -> dict[str, Any]:
    """补齐旧测试合同中 adapter 必需的原始坐标覆盖字段。

    Args:
        selection_contract: 测试声明的目标和覆盖合同。

    Returns:
        不修改调用方对象的 adapter 可执行合同副本。
    """
    normalized = json.loads(json.dumps(selection_contract))
    coverage = normalized.setdefault("coverage", {})
    groups = coverage.get("groups", [])
    variables = coverage.get("candidate_variables")
    if not isinstance(variables, list) or not variables:
        variables = []
        for group in groups:
            for variable in group.get("variables", []):
                if variable not in variables:
                    variables.append(variable)
        coverage["candidate_variables"] = variables
    for group in groups:
        group.setdefault("metric", "occupied_bins")
        group.setdefault("bins_per_variable", 2)
        group.setdefault(
            "bounds", {str(variable): [0.0, 1.0] for variable in group["variables"]}
        )
    normalized.setdefault("required_evidence", [])
    return normalized


def _candidate_pool(variables: list[str], objective: float, direction: str) -> list[dict[str, Any]]:
    """生成覆盖所有二元联合单元的原始候选池。

    Args:
        variables: 冻结的原始候选坐标。
        objective: 目标候选的精确目标值。
        direction: 目标优化方向。

    Returns:
        含 baseline、独立搜索候选和同序代理值的候选池。
    """
    rows: list[dict[str, Any]] = []
    combinations = list(product((0.0, 1.0), repeat=len(variables)))
    for index, values in enumerate(combinations):
        is_baseline = not any(values)
        is_target = all(values)
        identifier = "baseline" if is_baseline else "target" if is_target else f"candidate_{index}"
        distance = len(combinations) - index
        value = objective if is_target else objective - distance if direction == "maximize" else objective + distance
        coordinates = dict(zip(variables, values, strict=True))
        rows.append(
            {
                "id": identifier,
                "coordinates": coordinates,
                "parameters": dict(coordinates),
                "proxy_value": value,
                "role": "baseline" if is_baseline else "search",
            }
        )
    return rows


def _write_synthetic_adapter(
    run_dir: Path,
    *,
    result_id: str,
    selection_contract: dict[str, Any],
    objective: float,
    calibration_status: str,
    challenge_outcome: str,
    artifact_payloads: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """写入三段独立、受控且完全合成的 adapter 实现。

    Args:
        run_dir: 临时 v3 运行目录。
        result_id: 精确评分结果 ID。
        selection_contract: 已补齐的 adapter 选择合同。
        objective: 选中候选的精确目标值。
        calibration_status: 审计器的校准结论。
        challenge_outcome: 审计器声明的挑战结果。
        artifact_payloads: 由 exact scorer 写出的受控附属 JSON 数据。

    Returns:
        可直接传给 ``run_verification_protocol`` 的 adapter 合同和产物路径。
    """
    variables = list(selection_contract["coverage"]["candidate_variables"])
    direction = str(selection_contract["objective"]["direction"])
    metric = str(selection_contract["objective"]["metric"])
    candidates = _candidate_pool(variables, objective, direction)
    coverage_reports = [
        {
            "id": group["id"],
            "variables": group["variables"],
            "metric": "occupied_bins",
            "occupied_cells": 2 ** len(group["variables"]),
            "possible_cells": 2 ** len(group["variables"]),
            "joint_coverage": 1.0,
        }
        for group in selection_contract["coverage"]["groups"]
    ]
    prefix = f"synthetic_{result_id}"
    generator_path = f"code/{prefix}_generate.py"
    scorer_path = f"code/{prefix}_score.py"
    auditor_path = f"code/{prefix}_audit.py"
    candidate_output = f"results/raw/{result_id}.candidates.json"
    exact_output = f"results/raw/{result_id}.exact.json"
    audit_output = f"results/raw/{result_id}.audit.json"
    artifact_paths = {
        name: f"results/raw/{result_id}.{name}.json" for name in artifact_payloads
    }
    artifact_documents = [
        (artifact_paths[name], payload) for name, payload in artifact_payloads.items()
    ]
    generation = {
        "schema_name": "candidate_generation",
        "adapter_id": "synthetic-quality-test",
        "adapter_version": "1.0",
        "candidate_variables": variables,
        "candidates": candidates,
        "search_trace": [
            {
                "step": index,
                "candidate_id": candidate["id"],
                "event": "warm_start" if candidate["role"] == "baseline" else "independent_search",
            }
            for index, candidate in enumerate(candidates)
        ],
    }
    (run_dir / generator_path).write_text(
        "import json\n"
        "import sys\n"
        "from pathlib import Path\n"
        f"payload = {generation!r}\n"
        "Path(sys.argv[1]).write_text(json.dumps(payload), encoding='utf-8')\n",
        encoding="utf-8",
    )
    (run_dir / scorer_path).write_text(
        "import json\n"
        "import sys\n"
        "from pathlib import Path\n"
        "pool = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
        f"target_objective = {objective!r}\n"
        f"direction = {direction!r}\n"
        "scores = []\n"
        "for index, candidate in enumerate(pool['candidates']):\n"
        "    value = target_objective if candidate['id'] == 'target' else (target_objective - len(pool['candidates']) + index if direction == 'maximize' else target_objective + len(pool['candidates']) - index)\n"
        "    scores.append({'candidate_id': candidate['id'], 'feasible': True, 'objective': value, 'constraint_violations': []})\n"
        "payload = {\n"
        "    'schema_name': 'exact_scores',\n"
        "    'adapter_id': 'synthetic-quality-test',\n"
        "    'adapter_version': '1.0',\n"
        "    'candidate_scores': scores,\n"
        "    'selected_candidate_id': 'target',\n"
        f"    'metrics': {{{metric!r}: target_objective}},\n"
        "}\n"
        "Path(sys.argv[2]).write_text(json.dumps(payload), encoding='utf-8')\n"
        f"artifact_payloads = {[payload for _, payload in artifact_documents]!r}\n"
        "if len(sys.argv[3:]) != len(artifact_payloads):\n"
        "    raise RuntimeError('artifact output arguments do not match payloads')\n"
        "for path, artifact in zip(sys.argv[3:], artifact_payloads, strict=True):\n"
        "    Path(path).write_text(json.dumps(artifact), encoding='utf-8')\n",
        encoding="utf-8",
    )
    (run_dir / auditor_path).write_text(
        "import json\n"
        "import sys\n"
        "from pathlib import Path\n"
        "pool = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
        "exact = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))\n"
        f"coverage = {{'group_reports': {coverage_reports!r}}}\n"
        "payload = {\n"
        "    'schema_name': 'search_audit',\n"
        "    'adapter_id': 'synthetic-quality-test',\n"
        "    'adapter_version': '1.0',\n"
        "    'candidate_count': len(pool['candidates']),\n"
        "    'exact_candidate_count': len(exact['candidate_scores']),\n"
        "    'coverage': coverage,\n"
        f"    'calibration': {{'status': {calibration_status!r}, 'decision_metrics': {{'top_k': 1, 'top_k_recall': 1.0, 'improvement_sign_agreement': 1.0, 'boundary_high_value_error': 0.0, 'filtering_false_negative_rate': 0.0}}, 'catastrophic_errors': []}},\n"
        f"    'challenge': {{'outcome': {challenge_outcome!r}}},\n"
        "}\n"
        "Path(sys.argv[3]).write_text(json.dumps(payload), encoding='utf-8')\n",
        encoding="utf-8",
    )
    return {
        "schema_version": "1.0",
        "adapter_id": "synthetic-quality-test",
        "adapter_version": "1.0",
        "selection_contract": selection_contract,
        "stages": {
            "candidate_generator": {
                "implementation_file": generator_path,
                "arguments": [candidate_output],
                "input_files": [generator_path],
                "output_file": candidate_output,
            },
            "exact_scorer": {
                "implementation_file": scorer_path,
                "arguments": [candidate_output, exact_output, *artifact_paths.values()],
                "input_files": [scorer_path, candidate_output],
                "output_file": exact_output,
                "artifact_files": list(artifact_paths.values()),
            },
            "search_auditor": {
                "implementation_file": auditor_path,
                "arguments": [candidate_output, exact_output, audit_output],
                "input_files": [auditor_path, candidate_output, exact_output],
                "output_file": audit_output,
            },
        },
        "paths": {
            "candidate": candidate_output,
            "exact": exact_output,
            "audit": audit_output,
            "artifacts": artifact_paths,
        },
    }


def run_synthetic_verification_protocol(
    run_dir: Path,
    *,
    result_id: str,
    question_id: str,
    objective: float,
    selection_contract: dict[str, Any] | None = None,
    calibration_status: str = "passed",
    challenge_outcome: str = "not_requested",
    artifact_payloads: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """运行可接受的合成三段 adapter，并返回冻结收据。

    Args:
        run_dir: 临时 v3 运行目录。
        result_id: 精确评分结果 ID。
        question_id: 当前子问题 ID。
        objective: 选中候选的精确目标。
        selection_contract: 可选的测试选择合同。
        calibration_status: ``passed`` 或 ``failed`` 的审计校准结论。
        challenge_outcome: adapter 审计器的挑战结果。
        artifact_payloads: 可选的 exact scorer 附属 JSON 数据，按名称返回受控路径。

    Returns:
        运行摘要、verification 引用和合成产物路径。
    """
    contract = _write_synthetic_adapter(
        run_dir,
        result_id=result_id,
        selection_contract=_adapter_selection_contract(
            selection_contract or standard_selection_contract()
        ),
        objective=objective,
        calibration_status=calibration_status,
        challenge_outcome=challenge_outcome,
        artifact_payloads=artifact_payloads or {},
    )
    paths = contract.pop("paths")
    protocol = run_verification_protocol(
        run_dir,
        result_id=result_id,
        question_id=question_id,
        contract=contract,
    )
    protocol["paths"] = paths
    return protocol


def adapter_backed_assessment(
    protocol: dict[str, Any], *, reasons: list[str] | None = None
) -> dict[str, Any]:
    """构造唯一可申请 accepted 的 adapter 收据请求。

    Args:
        protocol: ``run_synthetic_verification_protocol`` 的运行摘要。
        reasons: 可选测试说明。

    Returns:
        仅包含独立 verification 收据的质量申请。
    """
    return {
        "result_role": "accepted",
        "verification": protocol["verification"],
        "reasons": reasons or ["synthetic_adapter_evidence"],
    }


def legacy_self_report_document(
    objective: float,
    *,
    search_adequacy: str = "passed",
    problem_effectiveness: str = "progressed",
) -> dict[str, Any]:
    """返回仅用于拒绝路径的旧生成器自报质量字段。

    Args:
        objective: 旧输出中的目标值。
        search_adequacy: 旧输出声称的充分性结论。
        problem_effectiveness: 旧输出声称的问题有效性结论。

    Returns:
        不具备 independent verifier 资格的遗留 JSON 对象。
    """
    return {
        "feasible": True,
        "exact_recomputed": True,
        "search_adequacy": search_adequacy,
        "problem_effectiveness": problem_effectiveness,
        "coverage": {
            "group_reports": [
                {
                    "id": "decision",
                    "variables": ["decision"],
                    "joint_coverage": 1.0,
                }
            ]
        },
        "objective_semantics": {
            "surrogate": "additive_sum",
            "calibration": "additive_sum",
            "exact": "additive_sum",
            "selection": "additive_sum",
            "entity_marginal_gains": [objective],
        },
    }


def legacy_self_report_assessment(
    result_id: str,
    output_file: str,
    *,
    search_adequacy: str = "passed",
    problem_effectiveness: str = "progressed",
) -> dict[str, Any]:
    """构造会被 v3 拒绝的旧 evidence 申请。

    Args:
        result_id: 旧执行结果 ID。
        output_file: 生成器输出 JSON。
        search_adequacy: 旧输出声称的充分性结论。
        problem_effectiveness: 旧输出声称的问题有效性结论。

    Returns:
        缺少 independent verification 的历史 accepted 请求。
    """
    def reference(path: str, expected: object) -> dict[str, object]:
        return {
            "result_id": result_id,
            "file": output_file,
            "json_path": path,
            "expected": expected,
        }

    return {
        "result_role": "accepted",
        "selection_contract": standard_selection_contract(),
        "evidence": {
            "feasibility": reference("quality.feasible", True),
            "exact_recomputed": reference("quality.exact_recomputed", True),
            "search_adequacy": reference("quality.search_adequacy", search_adequacy),
            "problem_effectiveness": reference(
                "quality.problem_effectiveness", problem_effectiveness
            ),
        },
        "reasons": ["legacy_generator_self_report"],
    }
