"""覆盖 Gate 0 v2 权威链、人工回执与 QA 阻断恢复。"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from shumozizi.core.io import atomic_json, sha256_file
from shumozizi.evidence.validator import generate_paper_evidence
from shumozizi.qa.aggregator import run_submission_qa
from shumozizi.results.metrics import materialize_metric
from shumozizi.results.sealing import admit_candidate
from shumozizi.runtime.execution import execute
from shumozizi.workflow.approval import (
    create_approval_request,
    create_final_approval_request,
    materialize_final_approval,
    materialize_route_approval,
)
from shumozizi.workflow.initialization import initialize_run
from shumozizi.workflow.state_service import (
    Actor,
    ArtifactRef,
    StateService,
    WorkflowEvent,
)


class Gate0EndToEndTests(unittest.TestCase):
    """执行一次含 BLOCKED 修复回路的最小桌面等价工作流。"""

    def test_v2_authority_chains_reach_complete(self) -> None:
        """两份人工回执绑定全部当前事实后才能进入 COMPLETE。"""
        if shutil.which("typst") is None:
            self.skipTest("本机未安装 Typst")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            problem = root / "problems/linear/problem.md"
            problem.parent.mkdir(parents=True)
            problem.write_text("输出一个可复验标量。\n", encoding="utf-8")
            run_dir = initialize_run(root, problem, "e2e-v2", mode="audit")
            service = StateService(root)
            actor = Actor("e2e-test", "system")

            candidates = {
                "schema_name": "route_candidates",
                "schema_version": "2.0",
                "run_id": run_dir.name,
                "run_config_lock_sha256": sha256_file(run_dir / "config/RUN_CONFIG_LOCK.json"),
                "problem_summary": "对固定输入执行确定性计算并输出可复验的结构化标量结果。",
                "ambiguities": [],
                "recommended_route_id": "route_a",
                "recommendation_reason": "直接计算足以验证执行、指标和论文证据闭环。",
                "candidates": [
                    self._candidate("route_a", "直接计算"),
                    self._candidate("route_b", "冗余复算"),
                ],
            }
            candidates_path = run_dir / "brief/route_candidates.json"
            atomic_json(candidates_path, candidates)
            create_approval_request(
                run_dir,
                "route",
                {
                    "run_config_lock": run_dir / "config/RUN_CONFIG_LOCK.json",
                    "route_candidates": candidates_path,
                },
            )
            service.transition(
                run_dir.name,
                WorkflowEvent.ROUTES_PROPOSED,
                actor,
                [self._ref(run_dir, "route_candidates", candidates_path)],
            )
            receipt_path, lock_path = materialize_route_approval(
                run_dir,
                raw_user_response="测试夹具明确批准 route_a",
                selected_route_id="route_a",
                approved_by="human-test-fixture",
            )
            service.transition(
                run_dir.name,
                WorkflowEvent.ROUTE_APPROVED,
                actor,
                [
                    self._ref(run_dir, "route_approval_receipt", receipt_path),
                    self._ref(run_dir, "route_lock", lock_path),
                ],
            )
            model_spec = run_dir / "reports/model_spec.md"
            model_spec.write_text("固定标量计算模型。\n", encoding="utf-8")
            service.transition(
                run_dir.name,
                WorkflowEvent.MODEL_SPEC_COMPLETED,
                actor,
                [self._ref(run_dir, "model_spec", model_spec)],
            )
            service.transition(
                run_dir.name,
                WorkflowEvent.EXPERIMENT_STARTED,
                actor,
                [],
            )

            script = run_dir / "code/model.py"
            script.write_text(
                "from pathlib import Path\n"
                "import json, sys\n"
                "Path(sys.argv[1]).write_text(json.dumps({'metrics': {'value': 1.25}}), encoding='utf-8')\n",
                encoding="utf-8",
            )
            manifest_path = run_dir / "executions/manifests/q1.json"
            atomic_json(
                manifest_path,
                {
                    "schema_name": "execution_manifest",
                    "schema_version": "2.0",
                    "execution_id": "q1-run-001",
                    "program": "python",
                    "args": ["code/model.py", "results/q1.json"],
                    "cwd": ".",
                    "timeout_seconds": 30,
                    "input_files": ["code/model.py"],
                    "expected_outputs": ["results/q1.json"],
                    "random_seed": 42,
                },
            )
            execution = execute(run_dir, manifest_path)
            self.assertTrue(execution["success"])
            output = run_dir / "results/q1.json"
            provenance = materialize_metric(
                run_dir,
                {
                    "metric_spec_id": "q1-value",
                    "execution_record_id": "q1-run-001",
                    "output_artifact": {
                        "path": "results/q1.json",
                        "sha256": sha256_file(output),
                    },
                    "extractor": {"id": "json-pointer", "selector": "/metrics/value"},
                    "raw_unit": "dimensionless",
                    "transform": None,
                    "final_unit": "dimensionless",
                },
            )
            sealed = admit_candidate(
                run_dir,
                {
                    "result_id": "q1-baseline",
                    "question_id": "q1",
                    "cycle": "baseline",
                    "execution_record_id": "q1-run-001",
                    "metrics": [
                        {
                            "name": "value",
                            "metric_spec_id": "q1-value",
                            "value": provenance["final_value"],
                            "unit": provenance["final_unit"],
                        }
                    ],
                    "conclusion": "固定标量已产生。",
                    "constraint_checks": [{"check_id": "finite", "passed": True}],
                    "validation_checks": [{"check_id": "exact", "passed": True}],
                    "baseline_result_id": None,
                    "innovation_claims": [],
                },
                accepted_by="e2e-test",
                paper_allowed=True,
            )
            self.assertEqual("q1-baseline", sealed["result_id"])
            service.transition(
                run_dir.name,
                WorkflowEvent.RESULTS_ADMITTED,
                actor,
                [],
            )

            evidence_map = {
                "schema_name": "evidence_map",
                "schema_version": "2.0",
                "run_id": run_dir.name,
                "claims": [
                    {
                        "claim_id": "Q1-VALUE",
                        "inputs": [
                            {
                                "name": "value",
                                "result_id": "q1-baseline",
                                "metric_spec_id": "q1-value",
                            }
                        ],
                        "expression": None,
                        "display": {
                            "decimals": 2,
                            "unit": "dimensionless",
                        },
                        "core": True,
                    }
                ],
            }
            atomic_json(run_dir / "paper/evidence_map.json", evidence_map)
            generate_paper_evidence(run_dir)
            paper_source = run_dir / "paper/main.typ"
            paper_source.write_text(
                '#import "generated/evidence_values.typ": evidence\n'
                "#set page(width: 120mm, height: 80mm)\n"
                "= Gate 0 E2E\n"
                '核心结果为 #evidence("Q1-VALUE")。\n',
                encoding="utf-8",
            )
            service.transition(
                run_dir.name,
                WorkflowEvent.PAPER_COMPLETED,
                actor,
                [self._ref(run_dir, "paper_source", paper_source)],
            )
            service.transition(run_dir.name, WorkflowEvent.QA_STARTED, actor, [])
            missing_pdf = run_dir / "paper/final.pdf"
            blocked = run_submission_qa(run_dir.name, missing_pdf)
            self.assertEqual("blocked", blocked["status"])
            service.transition(run_dir.name, WorkflowEvent.QA_BLOCKED, actor, [])
            repair = run_dir / "review/targeted_fix.md"
            repair.write_text("编译最终 PDF。\n", encoding="utf-8")
            service.transition(
                run_dir.name,
                WorkflowEvent.FIX_APPLIED,
                actor,
                [self._ref(run_dir, "repair_memo", repair)],
            )
            compiled = subprocess.run(
                ["typst", "compile", str(paper_source), str(missing_pdf)],
                cwd=run_dir / "paper",
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(0, compiled.returncode, compiled.stderr)
            service.transition(run_dir.name, WorkflowEvent.QA_STARTED, actor, [])
            passed = run_submission_qa(run_dir.name, missing_pdf)
            self.assertEqual("pass", passed["status"], passed["hard_failures"])
            service.transition(run_dir.name, WorkflowEvent.QA_PASSED, actor, [])
            create_final_approval_request(run_dir, missing_pdf)
            final_receipt = materialize_final_approval(
                run_dir,
                raw_user_response="测试夹具明确批准最终提交",
                approved_by="human-test-fixture",
            )
            state = service.transition(
                run_dir.name,
                WorkflowEvent.FINAL_APPROVED,
                actor,
                [self._ref(run_dir, "final_approval_receipt", final_receipt)],
            )
            self.assertEqual("COMPLETE", state["status"])

    @staticmethod
    def _candidate(route_id: str, name: str) -> dict[str, object]:
        """生成最小合法路线候选。"""
        return {
            "route_id": route_id,
            "name": name,
            "problem_interpretation": "对固定输入执行可复验的确定性标量计算。",
            "mathematical_nature": "确定性计算",
            "baseline": "直接计算",
            "primary_model": name,
            "innovation": "结构化输出",
            "validation": "精确值复验",
            "computational_cost": "低成本",
            "risks": ["无统计推广性"],
            "fallback": "直接计算",
        }

    @staticmethod
    def _ref(run_dir: Path, role: str, path: Path) -> ArtifactRef:
        """构造带当前哈希的运行内产物引用。"""
        return ArtifactRef(
            role,
            path.relative_to(run_dir).as_posix(),
            sha256_file(path),
        )


if __name__ == "__main__":
    unittest.main()
