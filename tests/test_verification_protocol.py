"""验证三段式 adapter 协议不会接受生成器自证的质量结论。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from shumozizi.core.io import ContractError, load_json
from shumozizi.simple.adapters import run_verification_protocol, validate_adapter_contract
from shumozizi.simple.execution import execute_simple_experiment
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.quality import assess_result_quality, quality_allows_paper
from shumozizi.simple.results import read_result_index
from tests.quality_protocol_helpers import (
    adapter_backed_assessment,
    record_passing_scientific_review,
    run_synthetic_verification_protocol,
)


class VerificationProtocolTests(unittest.TestCase):
    """覆盖候选生成、精确评分和搜索审计的职责隔离。"""

    def test_protocol_rejects_unsafe_result_id_before_writing_receipt_files(self) -> None:
        """协议不得让 result_id 逃出运行目录并提前落盘合同。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = initialize_simple_run(root, "unsafe-result-id")
            escaped = root / "verification-escape.adapter.json"
            variables = ["x", "z"]
            self._write_adapter_scripts(run_dir, variables=variables)

            with self.assertRaisesRegex(ContractError, "result_id"):
                run_verification_protocol(
                    run_dir,
                    result_id="../../../../verification-escape",
                    question_id="Q1",
                    contract=self._adapter_contract(variables=variables),
                )

            self.assertFalse(escaped.exists())

    def test_fresh_execution_rejects_preexisting_output_before_running_command(self) -> None:
        """要求新鲜输出时，执行器不得把旧文件当成本次实验结果。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "fresh-output-rejected")
            output = run_dir / "results" / "raw" / "stale.json"
            marker = run_dir / "results" / "raw" / "command-ran.marker"
            output.write_text(json.dumps({"metrics": {"objective": 1.0}}), encoding="utf-8")
            script = run_dir / "code" / "write-marker.py"
            script.write_text(
                "from pathlib import Path\n"
                "Path('results/raw/command-ran.marker').write_text('ran', encoding='utf-8')\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ContractError, "新鲜|已存在"):
                execute_simple_experiment(
                    run_dir,
                    result_id="stale_output",
                    question_id="Q1",
                    kind="adapter-candidate_generator",
                    command=f'"{sys.executable}" code/write-marker.py',
                    expected_outputs=["results/raw/stale.json"],
                    require_fresh_outputs=True,
                )

            self.assertFalse(marker.exists())

    def test_adapter_contract_rejects_duplicate_stage_outputs(self) -> None:
        """三段输出不得共用路径，避免新执行覆盖先前审计证据。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "duplicate-stage-output")
            variables = ["x", "z"]
            self._write_adapter_scripts(run_dir, variables=variables)
            contract = self._adapter_contract(variables=variables)
            contract["stages"]["search_auditor"]["output_file"] = "results/raw/exact.json"

            with self.assertRaisesRegex(ContractError, "输出.*重复|重复.*输出"):
                validate_adapter_contract(contract, run_dir=run_dir)

    def test_adapter_contract_rejects_implicit_shared_local_dependency(self) -> None:
        """三段入口不能通过未登记的 common.py 复用同一领域逻辑。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "implicit-shared-source")
            self._write_adapter_scripts(run_dir, variables=["x", "z"])
            shared = run_dir / "code" / "common.py"
            shared.write_text("def score(value):\n    return value\n", encoding="utf-8")
            for file_name in ("generate.py", "score.py", "audit.py"):
                path = run_dir / "code" / file_name
                path.write_text(
                    "import common\n" + path.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )

            with self.assertRaisesRegex(ContractError, "source_files|本地依赖|依赖"):
                run_verification_protocol(
                    run_dir,
                    result_id="implicit_shared",
                    question_id="Q1",
                    contract=self._adapter_contract(variables=["x", "z"]),
                )

    def test_adapter_contract_rejects_overlapping_declared_local_dependency(self) -> None:
        """即使显式登记，共享领域源码也不能充当三段独立性证明。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "declared-shared-source")
            self._write_adapter_scripts(run_dir, variables=["x", "z"])
            shared = run_dir / "code" / "common.py"
            shared.write_text("def score(value):\n    return value\n", encoding="utf-8")
            contract = self._adapter_contract(variables=["x", "z"])
            for stage_name in ("candidate_generator", "exact_scorer", "search_auditor"):
                stage = contract["stages"][stage_name]
                stage["source_files"] = [stage["implementation_file"], "code/common.py"]
                stage["input_files"] = [
                    stage["implementation_file"],
                    "code/common.py",
                    *stage["input_files"],
                ]

            with self.assertRaisesRegex(ContractError, "共享|独立"):
                validate_adapter_contract(contract)

    def test_v12_runtime_materializes_source_closure_without_author_fields(self) -> None:
        """作者只写数据输入，运行时仍冻结入口与本地导入源码。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "runtime-source-closure")
            variables = ["x", "z"]
            self._write_adapter_scripts(run_dir, variables=variables)
            contract = self._adapter_contract(variables=variables)
            self.assertNotIn("source_files", contract["stages"]["candidate_generator"])
            protocol = run_verification_protocol(
                run_dir,
                result_id="runtime_closure",
                question_id="Q1",
                contract=contract,
            )

            receipt = load_json(run_dir / protocol["verification"]["protocol_file"])
            frozen = load_json(run_dir / receipt["adapter"]["contract_file"])
            stage = frozen["stages"]["candidate_generator"]
            self.assertEqual(["code/generate.py"], stage["source_files"])
            self.assertIn("code/generate.py", stage["input_files"])

    def test_protocol_refuses_reused_stage_outputs_before_second_execution(self) -> None:
        """第二次协议不得复用第一轮已冻结的 raw 阶段输出。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "reused-stage-output")
            variables = ["x", "z"]
            self._write_adapter_scripts(run_dir, variables=variables)
            contract = self._adapter_contract(variables=variables)
            run_verification_protocol(
                run_dir,
                result_id="first_exact",
                question_id="Q1",
                contract=contract,
            )
            before = read_result_index(run_dir)

            with self.assertRaisesRegex(ContractError, "新鲜|已存在"):
                run_verification_protocol(
                    run_dir,
                    result_id="second_exact",
                    question_id="Q1",
                    contract=contract,
                )

            after = read_result_index(run_dir)
            self.assertEqual(
                [item["result_id"] for item in after["results"]],
                [item["result_id"] for item in before["results"]],
            )

    def test_provisional_stages_do_not_supersede_verified_incumbent(self) -> None:
        """审计尚未成功时，新 exact 阶段不得抢占已验证的 current 结果。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "provisional-stage")
            incumbent_protocol = run_synthetic_verification_protocol(
                run_dir,
                result_id="incumbent",
                question_id="Q1",
                objective=10.0,
            )
            accepted = assess_result_quality(
                run_dir,
                result_id="incumbent",
                assessment=adapter_backed_assessment(incumbent_protocol),
            )
            self.assertTrue(accepted["paper_allowed"])
            self.assertFalse(quality_allows_paper(run_dir, "incumbent"))

            with self.assertRaisesRegex(ContractError, "calibration"):
                run_synthetic_verification_protocol(
                    run_dir,
                    result_id="failed_candidate",
                    question_id="Q1",
                    objective=11.0,
                    calibration_status="invalid",
                )

            results = {
                item["result_id"]: item for item in read_result_index(run_dir)["results"]
            }
            self.assertEqual("current", results["incumbent"]["status"])
            record_passing_scientific_review(run_dir)
            self.assertTrue(quality_allows_paper(run_dir, "incumbent"))
            self.assertEqual("diagnostic", results["failed_candidate"]["status"])

    @staticmethod
    def _selection_contract(*, variables: list[str]) -> dict[str, object]:
        """构造声明原生联合覆盖的最小选择合同。

        Args:
            variables: 原始候选坐标名称。

        Returns:
            供合成 adapter 使用的选择合同。
        """
        return {
            "objective": {
                "metric": "objective",
                "direction": "maximize",
                "objective_version": "synthetic-v1",
                "scorer_version": "synthetic-exact-v1",
                "constraint_version": "synthetic-constraints-v1",
                "semantics": "additive",
                "fine_tolerance": 0.0,
            },
            "coverage": {
                "candidate_variables": variables,
                "groups": [
                    {
                        "id": "joint",
                        "variables": variables,
                        "minimum_joint_coverage": 0.25,
                        "metric": "occupied_bins",
                        "bins_per_variable": 2,
                        "bounds": {name: [0.0, 1.0] for name in variables},
                    }
                ],
            },
        }

    def _write_adapter_scripts(self, run_dir: Path, *, variables: list[str], projected: bool = False) -> None:
        """写入完全合成的非光滑稀疏目标 adapter 实现。

        Args:
            run_dir: 临时 v3 运行目录。
            variables: 合同声明的原始坐标。
            projected: 为真时故意遗漏高维原始坐标，模拟投影伪造。
        """
        generator = run_dir / "code" / "generate.py"
        scorer = run_dir / "code" / "score.py"
        auditor = run_dir / "code" / "audit.py"
        candidate_variables = variables[:4] if projected else variables
        candidates = [
            {
                "id": "baseline",
                "coordinates": {name: 0.0 for name in candidate_variables},
                "parameters": {name: 0.0 for name in candidate_variables},
                "proxy_value": 0.0,
                "role": "baseline",
            },
            {
                "id": "island",
                "coordinates": {name: 1.0 for name in candidate_variables},
                "parameters": {name: 1.0 for name in candidate_variables},
                "proxy_value": 0.8,
                "role": "search",
            },
        ]
        generation = {
            "schema_name": "candidate_generation",
            "adapter_id": "synthetic-sparse",
            "adapter_version": "1.0",
            "candidate_variables": candidate_variables,
            "candidates": candidates,
            "search_trace": [
                {"step": 0, "candidate_id": "baseline", "event": "warm_start"},
                {"step": 1, "candidate_id": "island", "event": "independent_search"},
            ],
        }
        generator.write_text(
            "import json\n"
            "import sys\n"
            "from pathlib import Path\n"
            f"payload = {generation!r}\n"
            "Path(sys.argv[1]).write_text(json.dumps(payload), encoding='utf-8')\n",
            encoding="utf-8",
        )
        scorer.write_text(
            "import json\n"
            "import sys\n"
            "from pathlib import Path\n"
            "pool = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
            "scores = []\n"
            "for candidate in pool['candidates']:\n"
            "    score = 1.0 if candidate['id'] == 'island' else 0.0\n"
            "    scores.append({'candidate_id': candidate['id'], 'feasible': True, "
            "'objective': score, 'constraint_violations': []})\n"
            "payload = {\n"
            "    'schema_name': 'exact_scores',\n"
            "    'adapter_id': 'synthetic-sparse',\n"
            "    'adapter_version': '1.0',\n"
            "    'candidate_scores': scores,\n"
            "    'selected_candidate_id': 'island',\n"
            "    'metrics': {'objective': 1.0},\n"
            "}\n"
            "Path(sys.argv[2]).write_text(json.dumps(payload), encoding='utf-8')\n",
            encoding="utf-8",
        )
        auditor.write_text(
            "import json\n"
            "import sys\n"
            "from pathlib import Path\n"
            "pool = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
            "exact = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))\n"
            f"coverage = {{'group_reports': [{{'id': 'joint', 'variables': {variables!r}, "
            f"'metric': 'occupied_bins', 'occupied_cells': 2, "
            f"'possible_cells': {2 ** len(variables)}, 'joint_coverage': {2 / (2 ** len(variables))}}}]}}\n"
            "payload = {\n"
            "    'schema_name': 'search_audit',\n"
            "    'adapter_id': 'synthetic-sparse',\n"
            "    'adapter_version': '1.0',\n"
            "    'candidate_count': len(pool['candidates']),\n"
            "    'exact_candidate_count': len(exact['candidate_scores']),\n"
            "    'coverage': coverage,\n"
            "    'calibration': {\n"
            "        'status': 'passed',\n"
            "        'decision_metrics': {\n"
            "            'top_k_recall': 1.0,\n"
            "            'improvement_sign_agreement': 1.0,\n"
            "            'boundary_high_value_error': 0.0,\n"
            "            'filtering_false_negative_rate': 0.0,\n"
            "        },\n"
            "        'catastrophic_errors': [],\n"
            "    },\n"
            "    'challenge': {'outcome': 'not_requested'},\n"
            "}\n"
            "Path(sys.argv[3]).write_text(json.dumps(payload), encoding='utf-8')\n",
            encoding="utf-8",
        )

    def _adapter_contract(self, *, variables: list[str]) -> dict[str, object]:
        """返回受控 Python adapter 的三段式合同。

        Args:
            variables: 候选坐标名称。

        Returns:
            可由通用运行时执行的 adapter 合同。
        """
        return {
            "schema_version": "1.2",
            "adapter_id": "synthetic-sparse",
            "adapter_version": "1.0",
            "selection_contract": self._selection_contract(variables=variables),
            "stages": {
                "candidate_generator": {
                    "implementation_file": "code/generate.py",
                    "arguments": ["results/raw/candidates.json"],
                    "input_files": [],
                    "output_file": "results/raw/candidates.json",
                },
                "exact_scorer": {
                    "implementation_file": "code/score.py",
                    "arguments": ["results/raw/candidates.json", "results/raw/exact.json"],
                    "input_files": ["results/raw/candidates.json"],
                    "output_file": "results/raw/exact.json",
                },
                "search_auditor": {
                    "implementation_file": "code/audit.py",
                    "arguments": [
                        "results/raw/candidates.json",
                        "results/raw/exact.json",
                        "results/raw/audit.json",
                    ],
                    "input_files": ["results/raw/candidates.json", "results/raw/exact.json"],
                    "output_file": "results/raw/audit.json",
                },
            },
        }

    def test_generator_self_report_cannot_release_without_adapter_artifacts(self) -> None:
        """生成器写入通过布尔值，但没有独立 scorer/auditor 时必须被拒绝。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "self-report-rejected")
            output = "results/raw/generator.json"
            script = run_dir / "code" / "generator.py"
            script.write_text(
                "import json\n"
                "from pathlib import Path\n"
                "Path('results/raw/generator.json').write_text(json.dumps({\n"
                "    'metrics': {'objective': 99.0},\n"
                "    'quality': {\n"
                "        'feasible': True, 'exact_recomputed': True,\n"
                "        'search_adequacy': 'passed',\n"
                "        'problem_effectiveness': 'progressed',\n"
                "    },\n"
                "}), encoding='utf-8')\n",
                encoding="utf-8",
            )
            executed = execute_simple_experiment(
                run_dir,
                result_id="self_report",
                question_id="Q1",
                kind="search",
                command=f'"{sys.executable}" code/generator.py',
                expected_outputs=[output],
                metrics_from=output,
            )
            self.assertTrue(executed["success"], executed["error"])

            with self.assertRaisesRegex(ContractError, "adapter|独立"):
                assess_result_quality(
                    run_dir,
                    result_id="self_report",
                    assessment={
                        "result_role": "accepted",
                        "selection_contract": self._selection_contract(variables=["x"]),
                        "evidence": {
                            "feasibility": {
                                "result_id": "self_report",
                                "file": output,
                                "json_path": "quality.feasible",
                                "expected": True,
                            }
                        },
                        "reasons": ["generator_self_report"],
                    },
                )
            self.assertFalse(quality_allows_paper(run_dir, "self_report"))

    def test_synthetic_sparse_adapter_e2e_binds_three_independent_stages(self) -> None:
        """非光滑稀疏目标必须由三段独立实现生成、精算和审计后才可放行。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "synthetic-adapter")
            variables = ["x", "z"]
            self._write_adapter_scripts(run_dir, variables=variables)
            protocol = run_verification_protocol(
                run_dir,
                result_id="synthetic_exact",
                question_id="Q1",
                contract=self._adapter_contract(variables=variables),
            )

            assessment = assess_result_quality(
                run_dir,
                result_id="synthetic_exact",
                assessment={
                    "result_role": "accepted",
                    "selection_contract": self._selection_contract(variables=variables),
                    "verification": protocol["verification"],
                    "reasons": ["synthetic_sparse_e2e"],
                },
            )

            self.assertTrue(protocol["success"], protocol.get("error"))
            self.assertTrue(assessment["paper_allowed"])
            record_passing_scientific_review(run_dir)
            self.assertTrue(quality_allows_paper(run_dir, "synthetic_exact"))

    def test_candidate_pool_hash_drift_revokes_adapter_acceptance(self) -> None:
        """候选池或轨迹在审计后变化时，旧 accepted 记录不能继续放行。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "adapter-drift")
            variables = ["x", "z"]
            self._write_adapter_scripts(run_dir, variables=variables)
            protocol = run_verification_protocol(
                run_dir,
                result_id="drift_exact",
                question_id="Q1",
                contract=self._adapter_contract(variables=variables),
            )
            assess_result_quality(
                run_dir,
                result_id="drift_exact",
                assessment={
                    "result_role": "accepted",
                    "selection_contract": self._selection_contract(variables=variables),
                    "verification": protocol["verification"],
                    "reasons": ["adapter_drift"],
                },
            )
            candidate_path = run_dir / "results" / "raw" / "candidates.json"
            candidate_path.write_text(json.dumps({"tampered": True}), encoding="utf-8")

            self.assertFalse(quality_allows_paper(run_dir, "drift_exact"))

    def test_exact_sidecar_is_bound_and_nonexact_stages_cannot_declare_one(self) -> None:
        """精确评分 sidecar 必须受哈希约束，其他阶段不得登记它。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "adapter-sidecar")
            protocol = run_synthetic_verification_protocol(
                run_dir,
                result_id="sidecar_exact",
                question_id="Q1",
                objective=1.0,
                artifact_payloads={
                    "figure": {"figure_data": {"values": [[1.0, 2.0], [3.0, 4.0]]}}
                },
            )
            assessment = assess_result_quality(
                run_dir,
                result_id="sidecar_exact",
                assessment=adapter_backed_assessment(protocol),
            )

            self.assertTrue(assessment["paper_allowed"])
            sidecar = run_dir / str(protocol["paths"]["artifacts"]["figure"])
            sidecar.write_text(json.dumps({"tampered": True}), encoding="utf-8")
            self.assertFalse(quality_allows_paper(run_dir, "sidecar_exact"))

            for stage_name in ("candidate_generator", "search_auditor"):
                self._write_adapter_scripts(run_dir, variables=["x"])
                contract = self._adapter_contract(variables=["x"])
                contract["stages"][stage_name]["artifact_files"] = [
                    "results/raw/not-allowed.json"
                ]
                with self.assertRaisesRegex(ContractError, "exact_scorer"):
                    run_verification_protocol(
                        run_dir,
                        result_id=f"forbidden_{stage_name}",
                        question_id="Q1",
                        contract=contract,
                    )

    def test_eight_dimensional_projection_cannot_claim_four_dimensional_coverage(self) -> None:
        """原始 8D 合同缺少四个坐标时，不能以平均或首元素伪造联合覆盖。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "eight-dimension-rejected")
            variables = [f"x{index}" for index in range(8)]
            self._write_adapter_scripts(run_dir, variables=variables, projected=True)

            with self.assertRaisesRegex(ContractError, "坐标|变量|coverage"):
                run_verification_protocol(
                    run_dir,
                    result_id="projected_exact",
                    question_id="Q1",
                    contract=self._adapter_contract(variables=variables),
                )


if __name__ == "__main__":
    unittest.main()
