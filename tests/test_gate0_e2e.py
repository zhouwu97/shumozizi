"""覆盖 Gate 0 v2 权威链、人工回执与 QA 阻断恢复。"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from shumozizi.core.io import atomic_json, load_json, sha256_file
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
from shumozizi.workflow.reviews import (
    create_review_request,
    materialize_review_receipt,
    write_review_report,
)
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
        self.assertIsNotNone(shutil.which("typst"), "E2E 测试需要安装 Typst")
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
            self._record_review(
                service,
                run_dir,
                actor,
                "R1_MODELING",
                {"model_spec": model_spec},
                "ACCEPT",
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
            service.update_question_progress(
                run_dir.name, "q1", "experiment", "accepted", actor
            )
            self._record_review(
                service,
                run_dir,
                actor,
                "R2_EXPERIMENT",
                {
                    "execution_record": run_dir
                    / "executions/q1-run-001/execution_record.json",
                    "sealed_result": run_dir / "results/sealed/q1-baseline.result.json",
                },
                "REPRODUCIBLE",
                question_id="q1",
            )
            service.transition(
                run_dir.name,
                WorkflowEvent.RESULTS_ADMITTED,
                actor,
                [],
            )
            question_section = run_dir / "paper/sections/q1.typ"
            question_section.parent.mkdir(parents=True, exist_ok=True)
            question_section.write_text("= Q1 逐问回答\n固定标量为 1.25。\n", encoding="utf-8")
            checks = {
                name: {"passed": True, "evidence": "Gate 0 fixture 已核验"}
                for name in (
                    "question_requirements", "model_output", "output_mapping", "hard_constraints",
                    "baseline", "accepted_result", "uncertainty", "direct_answer",
                    "upstream_dependencies", "claim_status",
                )
            }
            atomic_json(
                run_dir / "questions/q1/QUESTION_ACCEPTANCE.json",
                {
                    "schema_name": "question_acceptance",
                    "schema_version": "2.0",
                    "run_id": run_dir.name,
                    "question_id": "q1",
                    "status": "accepted",
                    "checks": checks,
                    "accepted_result_ids": ["q1-baseline"],
                    "chapter_paths": ["paper/sections/q1.typ"],
                    "direct_answer": "固定标量为 1.25。",
                    "claim_status": "none",
                    "generated_at": "2026-07-19T00:00:00Z",
                },
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
            final_pdf = run_dir / "paper/final.pdf"
            compiled = subprocess.run(
                ["typst", "compile", str(paper_source), str(final_pdf)],
                cwd=run_dir / "paper",
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(0, compiled.returncode, compiled.stderr)
            # Gate 0 使用最小但完整的论文和图表生产回执。
            for relative in ("skills/mathmodel-paper/SKILL.md", "skills/5writing/SKILL.md", "skills/typst-author/SKILL.md", "skills/3coding-visual/SKILL.md"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("测试 Skill\n", encoding="utf-8")
            claim_gate = run_dir / "paper/claim_gate.json"
            claim_gate.write_text("{}\n", encoding="utf-8")
            paper_plan = {
                "schema_name": "paper_plan",
                "schema_version": "2.0",
                "run_id": run_dir.name,
                "bindings": {
                    "mathmodel_paper": {"path": "skills/mathmodel-paper/SKILL.md", "sha256": sha256_file(root / "skills/mathmodel-paper/SKILL.md")},
                    "writing_skill": {"path": "skills/5writing/SKILL.md", "sha256": sha256_file(root / "skills/5writing/SKILL.md")},
                    "typst_author": {"path": "skills/typst-author/SKILL.md", "sha256": sha256_file(root / "skills/typst-author/SKILL.md")},
                    "competition_template": {"path": "profiles/generic.json", "sha256": sha256_file(root / "profiles/generic.json")},
                    "model_spec": {"path": "reports/model_spec.md", "sha256": sha256_file(run_dir / "reports/model_spec.md")},
                    "result_registry": {"path": "results/result_registry.json", "sha256": sha256_file(run_dir / "results/result_registry.json")},
                    "claim_gate": {"path": "paper/claim_gate.json", "sha256": sha256_file(claim_gate)},
                    "section_files": [
                        {"path": "paper/main.typ", "sha256": sha256_file(paper_source)},
                        {"path": "paper/sections/q1.typ", "sha256": sha256_file(question_section)},
                    ],
                    "figures_used": [],
                },
                "final_pdf_path": "paper/final.pdf",
            }
            atomic_json(run_dir / "paper/paper_plan.json", paper_plan)
            state = load_json(run_dir / "state.json")
            atomic_json(
                run_dir / "paper/PAPER_BUILD_RECEIPT.json",
                {
                    "schema_name": "paper_build_receipt",
                    "schema_version": "2.0",
                    "run_id": run_dir.name,
                    "plan_path": "paper/paper_plan.json",
                    "plan_sha256": sha256_file(run_dir / "paper/paper_plan.json"),
                    "state_revision": state["revision"],
                    "final_pdf_path": "paper/final.pdf",
                    "final_pdf_sha256": sha256_file(final_pdf),
                    "generated_at": "2026-07-19T00:00:00Z",
                },
            )
            atomic_json(
                run_dir / "figures/FIGURE_PLAN.json",
                {"schema_name": "figure_plan", "schema_version": "2.0", "run_id": run_dir.name, "figures": []},
            )
            service.transition(
                run_dir.name,
                WorkflowEvent.PAPER_COMPLETED,
                actor,
                [self._ref(run_dir, "paper_source", paper_source)],
            )
            self._record_review(
                service,
                run_dir,
                actor,
                "R3_PAPER_LOGIC",
                {"paper_source": paper_source, "final_pdf": final_pdf},
                "READY_FOR_COMPREHENSIVE_REVIEW",
            )
            self._record_review(
                service,
                run_dir,
                actor,
                "R4_FORMAT_VISUAL",
                {"paper_source": paper_source, "final_pdf": final_pdf},
                "COMPLIANT",
            )
            service.transition(run_dir.name, WorkflowEvent.QA_STARTED, actor, [])
            missing_pdf = run_dir / "paper/not-the-bound-final.pdf"
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
            service.transition(run_dir.name, WorkflowEvent.QA_STARTED, actor, [])
            passed = run_submission_qa(run_dir.name, final_pdf)
            self.assertEqual("pass", passed["status"], passed["hard_failures"])
            self._record_review(
                service,
                run_dir,
                actor,
                "R5_COMPREHENSIVE",
                {"final_pdf": final_pdf, "qa": run_dir / "review/QA_AGGREGATE.json"},
                "B",
                rating=True,
            )
            self._record_review(
                service,
                run_dir,
                actor,
                "J0_FINAL_BLIND_JUDGE",
                {"final_pdf": final_pdf},
                "PROCEED",
            )
            service.transition(run_dir.name, WorkflowEvent.QA_PASSED, actor, [])
            create_final_approval_request(run_dir, final_pdf)
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
    def _record_review(
        service: StateService,
        run_dir: Path,
        actor: Actor,
        stage: str,
        bindings: dict[str, Path],
        verdict: str,
        *,
        question_id: str | None = None,
        rating: bool = False,
    ) -> None:
        """生成并通过公开审核接口登记一个阶段回执。"""
        request = create_review_request(
            run_dir,
            stage,
            bindings,
            question_id=question_id,
        )
        request_doc = load_json(request)
        report = {
            "schema_name": "review_report",
            "schema_version": "2.0",
            "request_id": request_doc["request_id"],
            "run_id": run_dir.name,
            "stage": stage,
            "review_round_id": request_doc["review_round_id"],
            "verdict": verdict,
            "findings": [],
            "read_only_confirmed": True,
            "generated_at": "2026-07-19T00:00:00Z",
        }
        if rating:
            report["rating"] = {
                "grade": verdict,
                "confidence": "high",
                "basis": ["当前冻结提交包"],
                "downgrade_reasons": [],
                "expert_estimate": True,
            }
        report_path = write_review_report(request, report)
        receipt = materialize_review_receipt(request, report_path)
        gate_id = "R2_EXPERIMENT_" + question_id if question_id else stage
        if stage == "R5_COMPREHENSIVE":
            gate_id = "R5_STANDARD_FINAL"
        service.record_review_gate(run_dir.name, gate_id, receipt, actor)

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
