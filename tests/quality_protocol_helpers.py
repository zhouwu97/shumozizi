"""构造独立 adapter 与遗留质量声明的测试夹具。"""

from __future__ import annotations

import json
import sys
from itertools import product
from pathlib import Path
from typing import Any

from shumozizi.core.io import atomic_json, sha256_file
from shumozizi.simple.adapters import run_verification_protocol
from shumozizi.simple.capabilities import require_capability_route
from shumozizi.simple.critical_claims import CRITICAL_CLAIMS_PATH
from shumozizi.simple.execution import execute_simple_experiment
from shumozizi.simple.method_profile import (
    METHOD_PROFILE_PATH,
    build_method_profile_bindings,
)
from shumozizi.simple.objective_semantics import objective_semantics_digest
from shumozizi.simple.results import read_result_index
from shumozizi.simple.review import (
    build_review_packet,
    generate_required_review_risks,
    import_scientific_review,
    run_red_team_evidence,
)
from shumozizi.simple.review_tasks import create_review_task_receipt
from shumozizi.simple.state import read_simple_state, update_simple_state


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
        "schema_version": "1.2",
        "adapter_id": "synthetic-quality-test",
        "adapter_version": "1.0",
        "selection_contract": selection_contract,
        "stages": {
            "candidate_generator": {
                "implementation_file": generator_path,
                "arguments": [candidate_output],
                "input_files": [],
                "output_file": candidate_output,
            },
            "exact_scorer": {
                "implementation_file": scorer_path,
                "arguments": [candidate_output, exact_output, *artifact_paths.values()],
                "input_files": [candidate_output],
                "output_file": exact_output,
                "artifact_files": list(artifact_paths.values()),
            },
            "search_auditor": {
                "implementation_file": auditor_path,
                "arguments": [candidate_output, exact_output, audit_output],
                "input_files": [candidate_output, exact_output],
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


def _ensure_scientific_review_contracts(run_dir: Path) -> None:
    """为通过路径生成真实实验后的方法画像和高价值主张。"""
    state = read_simple_state(run_dir)
    required_questions = list(state.get("required_questions") or ["Q1"])
    current = {
        item["question_id"]: item
        for item in read_result_index(run_dir)["results"]
        if item.get("status") == "current"
        and item.get("execution_mode") == "production"
        and item.get("execution_valid") is True
        and item.get("kind") != "independent-oracle"
    }
    missing = [question_id for question_id in required_questions if question_id not in current]
    if missing:
        script = run_dir / "code" / "review_fixture_result.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(
            "import json\n"
            "import sys\n"
            "from pathlib import Path\n"
            "question_id, output = sys.argv[1:3]\n"
            "Path(output).parent.mkdir(parents=True, exist_ok=True)\n"
            "Path(output).write_text(json.dumps({'metrics': {'objective': 1.0}, "
            "'question_id': question_id}), encoding='utf-8')\n",
            encoding="utf-8",
        )
        for question_id in missing:
            output = f"results/raw/review-fixture-{question_id}.json"
            execute_simple_experiment(
                run_dir,
                result_id=f"review-fixture-{question_id}",
                question_id=question_id,
                kind="baseline",
                command=(
                    f'"{sys.executable}" code/review_fixture_result.py '
                    f'"{question_id}" "{output}"'
                ),
                expected_outputs=[output],
                metrics_from=output,
            )
        current = {
            item["question_id"]: item
            for item in read_result_index(run_dir)["results"]
            if item.get("status") == "current"
            and item.get("execution_mode") == "production"
            and item.get("execution_valid") is True
            and item.get("kind") != "independent-oracle"
        }

    route = require_capability_route(run_dir)
    atomic_json(
        run_dir / METHOD_PROFILE_PATH,
        {
            "schema_name": "simple_method_profile",
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "bindings": build_method_profile_bindings(run_dir),
            "questions": [
                {
                    "question_id": question_id,
                    "model_families": ["other"],
                    "other_model_family": "synthetic_test_fixture",
                    "production_engine": route["toolchain"]["production_engine"],
                }
                for question_id in required_questions
            ],
            "generated_at": "2026-07-20T00:00:00Z",
        },
    )
    atomic_json(
        run_dir / CRITICAL_CLAIMS_PATH,
        {
            "schema_name": "simple_critical_claims",
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "bindings": {
                "method_profile_sha256": sha256_file(run_dir / METHOD_PROFILE_PATH),
                "objective_semantics_sha256": objective_semantics_digest(run_dir),
                "result_index_sha256": sha256_file(run_dir / "results" / "index.json"),
            },
            "claims": [
                {
                    "claim_id": f"fixture-{index + 1}",
                    "question_id": question_id,
                    "statement": f"{question_id} 的当前生产结果满足测试工作流的主要输出要求。",
                    "claim_type": "model_validity",
                    "importance": "primary",
                    "result_ids": [current[question_id]["result_id"]],
                    "evidence_needed": ["independent_review"],
                    "blocking_if_fails": True,
                }
                for index, question_id in enumerate(required_questions)
            ],
            "generated_at": "2026-07-20T00:00:00Z",
        },
    )


def _write_passing_scientific_coverage(
    run_dir: Path,
    *,
    report_file: str,
    parent_task_id: str,
) -> str:
    """写入覆盖当前动态风险且绑定独立 coverage 任务的声明。"""
    risks = generate_required_review_risks(run_dir, scope="scientific")
    risks_path = run_dir / "review" / "required_risks.json"
    declaration_path = run_dir / "review" / "coverage" / "scientific.json"
    receipt_relative = "review/tasks/scientific-coverage/receipt.json"
    atomic_json(
        declaration_path,
        {
            "schema_name": "red_team_coverage_declaration",
            "schema_version": "3.0",
            "run_id": run_dir.name,
            "review_file": report_file,
            "report_sha256": sha256_file(run_dir / report_file),
            "required_risks_file": "review/required_risks.json",
            "required_risks_sha256": sha256_file(risks_path),
            "coverage_task_receipt": receipt_relative,
            "covered_risks": [
                {
                    "risk_id": risk_id,
                    "conclusion": "sufficient",
                    "evidence_location": f"{report_file}#动态风险覆盖",
                }
                for risk_id in sorted(risks)
            ],
            "follow_ups": [],
            "additional_findings": [],
            "generated_at": "2026-07-20T00:00:00Z",
        },
    )
    coverage_inputs = {
        "report": {"file": report_file, "sha256": sha256_file(run_dir / report_file)},
        "required_risks": {
            "file": "review/required_risks.json",
            "sha256": sha256_file(risks_path),
        },
    }
    return create_review_task_receipt(
        run_dir,
        task_id="scientific-coverage",
        task_type="coverage_extract",
        thread_id="synthetic-coverage-thread",
        model_id="fixture-model",
        prompt_sha256="2" * 64,
        input_bindings=coverage_inputs,
        report_file=declaration_path.relative_to(run_dir).as_posix(),
        parent_task_id=parent_task_id,
    ).relative_to(run_dir).as_posix()


def record_passing_scientific_review(run_dir: Path) -> dict[str, Any]:
    """为运行时协议测试绑定隔离且未漂移的科学红队报告。

    该夹具只模拟已经在新对话完成的报告导入；生产运行仍必须由独立对话实际做清洁室
    复现和反例攻击。
    """
    state = read_simple_state(run_dir)
    if state["phase"] == "analysis":
        from tests.capability_flow_helpers import prepare_minimal_capability_route

        prepare_minimal_capability_route(run_dir)
    if read_simple_state(run_dir)["phase"] == "experiment":
        _ensure_scientific_review_contracts(run_dir)
        update_simple_state(run_dir, phase="scientific_review")
    if read_simple_state(run_dir)["phase"] != "scientific_review":
        raise ValueError("测试科学审查只能从 analysis 或 experiment 开始")
    review_questions = list(read_simple_state(run_dir).get("required_questions") or ["Q1"])
    first_question = review_questions[0]
    packet = build_review_packet(run_dir, kind="scientific")
    artifact_root = run_dir / "review" / "red_team_artifacts"
    recompute = artifact_root / "synthetic_recompute.py"
    recompute.write_text(
        "import json\n"
        "import sys\n"
        "from pathlib import Path\n"
        "packet, outputs = (Path(value) for value in sys.argv[1:3])\n"
        "assert (packet / 'problem').is_dir()\n"
        "(outputs / 'recompute.json').write_text(\n"
        "    json.dumps({\n"
        f"        'question_id': {first_question!r},\n"
        "        'claim_id': 'synthetic-objective',\n"
        "        'method': 'independent_fixture_oracle',\n"
        "        'cases': 2,\n"
        "        'production_value': 1.0,\n"
        "        'independent_value': 1.0,\n"
        "        'absolute_difference': 0.0,\n"
        "        'verdict': 'consistent',\n"
        "    }), encoding='utf-8'\n"
        ")\n",
        encoding="utf-8",
    )
    run_red_team_evidence(
        run_dir,
        evidence_id="synthetic-recompute",
        kind="independent-recompute",
        packet_manifest=f"review/packet/scientific/{packet['packet_id']}/manifest.json",
        script_path="review/red_team_artifacts/synthetic_recompute.py",
        output_paths=["recompute.json"],
    )
    challenge = artifact_root / "synthetic-property.py"
    challenge.write_text(
        "import json\n"
        "import sys\n"
        "from pathlib import Path\n"
        "packet, outputs = (Path(value) for value in sys.argv[1:3])\n"
        "assert (packet / 'candidate_results').is_dir()\n"
        "(outputs / 'property.json').write_text(json.dumps({\n"
        f"    'question_id': {first_question!r},\n"
        "    'claim_id': 'synthetic-invariant',\n"
        "    'property': 'translation_invariance',\n"
        "    'cases': 2,\n"
        "    'failures': 0,\n"
        "    'verdict': 'pass',\n"
        "}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    challenge_receipt = run_red_team_evidence(
        run_dir,
        evidence_id="synthetic-property",
        kind="property-test",
        packet_manifest=f"review/packet/scientific/{packet['packet_id']}/manifest.json",
        script_path="review/red_team_artifacts/synthetic-property.py",
        output_paths=["property.json"],
    )
    for index, question_id in enumerate(review_questions[1:], start=2):
        recompute_extra = artifact_root / f"synthetic-recompute-{index}.py"
        recompute_extra.write_text(
            "import json\n"
            "import sys\n"
            "from pathlib import Path\n"
            "packet, outputs = (Path(value) for value in sys.argv[1:3])\n"
            "assert (packet / 'problem').is_dir()\n"
            f"(outputs / 'recompute-{index}.json').write_text(json.dumps({{\n"
            f"    'question_id': {question_id!r},\n"
            f"    'claim_id': 'synthetic-objective-{index}',\n"
            "    'method': 'independent_fixture_oracle',\n"
            "    'cases': 2,\n"
            "    'production_value': 1.0,\n"
            "    'independent_value': 1.0,\n"
            "    'absolute_difference': 0.0,\n"
            "    'verdict': 'consistent',\n"
            "}), encoding='utf-8')\n",
            encoding="utf-8",
        )
        run_red_team_evidence(
            run_dir,
            evidence_id=f"synthetic-recompute-{index}",
            kind="independent-recompute",
            packet_manifest=f"review/packet/scientific/{packet['packet_id']}/manifest.json",
            script_path=recompute_extra.relative_to(run_dir).as_posix(),
            output_paths=[f"recompute-{index}.json"],
        )
        property_extra = artifact_root / f"synthetic-property-{index}.py"
        property_extra.write_text(
            "import json\n"
            "import sys\n"
            "from pathlib import Path\n"
            "packet, outputs = (Path(value) for value in sys.argv[1:3])\n"
            "assert (packet / 'candidate_results').is_dir()\n"
            f"(outputs / 'property-{index}.json').write_text(json.dumps({{\n"
            f"    'question_id': {question_id!r},\n"
            f"    'claim_id': 'synthetic-invariant-{index}',\n"
            "    'property': 'translation_invariance',\n"
            "    'cases': 2,\n"
            "    'failures': 0,\n"
            "    'verdict': 'pass',\n"
            "}), encoding='utf-8')\n",
            encoding="utf-8",
        )
        challenge_receipt = run_red_team_evidence(
            run_dir,
            evidence_id=f"synthetic-property-{index}",
            kind="property-test",
            packet_manifest=f"review/packet/scientific/{packet['packet_id']}/manifest.json",
            script_path=property_extra.relative_to(run_dir).as_posix(),
            output_paths=[f"property-{index}.json"],
        )
    if "geometry_kinematics" in require_capability_route(run_dir)["problem_families"]:
        geometry = artifact_root / "synthetic-geometry-continuous.py"
        geometry.write_text(
            "import json\n"
            "import sys\n"
            "from pathlib import Path\n"
            "packet, outputs = (Path(value) for value in sys.argv[1:3])\n"
            "assert (packet / 'problem').is_dir()\n"
            "(outputs / 'geometry.json').write_text(json.dumps({\n"
            "    'question_id': 'Q1',\n"
            "    'continuous_quantity': 'minimum_margin_continuous',\n"
            "    'sampled_approximation': 'minimum_margin_grid',\n"
            "    'verification_method': 'root_isolation',\n"
            "    'discretization_error_bound': None,\n"
            "    'critical_cases': {\n"
            "        'left_endpoint': True,\n"
            "        'right_endpoint': True,\n"
            "        'tangent': True,\n"
            "        'degenerate': True,\n"
            "        'outside_segment': True,\n"
            "    },\n"
            "    'verdict': 'pass',\n"
            "}), encoding='utf-8')\n",
            encoding="utf-8",
        )
        run_red_team_evidence(
            run_dir,
            evidence_id="synthetic-geometry-continuous",
            kind="geometry-continuous-validation",
            packet_manifest=f"review/packet/scientific/{packet['packet_id']}/manifest.json",
            script_path="review/red_team_artifacts/synthetic-geometry-continuous.py",
            output_paths=["geometry.json"],
        )
    report = run_dir / "review" / "SCIENTIFIC_RED_TEAM.md"
    report.write_text(
        "# 合成科学红队报告\n\n## 动态风险覆盖\n\n"
        "已绑定独立公式、反例和污染范围。证据：`"
        + challenge_receipt["outputs"][0]["path"]
        + "`。\n",
        encoding="utf-8",
    )
    manifest_file = f"review/packet/scientific/{packet['packet_id']}/manifest.json"
    packet_binding = {
        "manifest_file": manifest_file,
        "manifest_sha256": sha256_file(run_dir / manifest_file),
    }
    open_task = create_review_task_receipt(
        run_dir,
        task_id="scientific-open",
        task_type="scientific_open",
        thread_id="synthetic-fresh-review-thread",
        model_id="fixture-model",
        prompt_sha256="1" * 64,
        input_bindings={"packet": packet_binding},
        report_file=report.relative_to(run_dir).as_posix(),
    )
    _write_passing_scientific_coverage(
        run_dir,
        report_file=report.relative_to(run_dir).as_posix(),
        parent_task_id="scientific-open",
    )
    state = read_simple_state(run_dir)
    return import_scientific_review(
        run_dir,
        manifest_file=manifest_file,
        verdict="pass",
        highest_severity="none",
        competition_strength="qualified",
        full_rerun_required=False,
        affected_questions=[],
        reviewer_thread_id="synthetic-fresh-review-thread",
        task_receipt_file=open_task.relative_to(run_dir).as_posix(),
        question_reviews=(
            [
                {
                    "question_id": question_id,
                    "verdict": "pass",
                    "competition_strength": "qualified",
                }
                for question_id in state.get("required_questions", [])
            ]
            or None
        ),
    )


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
