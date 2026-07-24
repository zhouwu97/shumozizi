"""验证独立科学红队和 PDF 盲审是 v3 的实际状态机门，而非文本约定。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shumozizi.core.io import ContractError, load_json
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.review import (
    build_review_packet,
    completion_status,
    final_audit_status,
    import_final_audit,
    import_objective_semantics_review,
    import_paper_blind_review,
    import_scientific_review,
    paper_blind_review_status,
    run_red_team_evidence,
    scientific_review_status,
    verify_review_packet,
)
from shumozizi.simple.state import update_simple_state
from tests.capability_flow_helpers import (
    prepare_cumcm_template,
    prepare_minimal_capability_route,
    prepare_minimal_visualization,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_PACKET = REPO_ROOT / "scripts" / "review" / "build_review_packet.py"
IMPORT_REVIEW = REPO_ROOT / "scripts" / "review" / "import_review.py"


class IndependentReviewWorkflowTests(unittest.TestCase):
    """覆盖审查隔离包、阶段门和终态的最小生产链。"""

    @staticmethod
    def _manifest_relative(packet: dict[str, object]) -> str:
        """返回构建结果对应的运行内 manifest 路径。"""
        return f"review/packet/{packet['packet_kind']}/{packet['packet_id']}/manifest.json"

    @staticmethod
    def _write_report(run_dir: Path, name: str) -> Path:
        """写入满足导入要求的最小自由审查报告。"""
        report = run_dir / "review" / name
        evidence_reference = ""
        if name == "SCIENTIFIC_RED_TEAM.md":
            artifact_root = run_dir / "review" / "red_team_artifacts"
            manifests = sorted((run_dir / "review" / "packet" / "scientific").glob("*/manifest.json"))
            if not manifests:
                raise AssertionError("测试红队缺少 scientific packet")
            manifest = manifests[-1].relative_to(run_dir).as_posix()
            recompute = artifact_root / "minimal_recompute.py"
            recompute.write_text(
                "import json\n"
                "import sys\n"
                "from pathlib import Path\n"
                "packet, outputs = (Path(value) for value in sys.argv[1:3])\n"
                "assert (packet / 'problem').is_dir()\n"
                "(outputs / 'recompute.json').write_text(json.dumps({\n"
                "    'claim_id': 'Q1-objective',\n"
                "    'method': 'independent_quadratic_oracle',\n"
                "    'cases': 12,\n"
                "    'production_value': 3.348287,\n"
                "    'independent_value': 3.347912,\n"
                "    'absolute_difference': 0.000375,\n"
                "    'verdict': 'consistent',\n"
                "}), encoding='utf-8')\n",
                encoding="utf-8",
            )
            property_test = artifact_root / "minimal_property.py"
            property_test.write_text(
                "import json\n"
                "import sys\n"
                "from pathlib import Path\n"
                "packet, outputs = (Path(value) for value in sys.argv[1:3])\n"
                "assert (packet / 'source_snapshot').is_dir()\n"
                "(outputs / 'property.json').write_text(json.dumps({\n"
                "    'claim_id': 'segment-intersection',\n"
                "    'property': 'finite_segment_endpoint_cases',\n"
                "    'cases': 12,\n"
                "    'failures': 0,\n"
                "    'verdict': 'pass',\n"
                "}), encoding='utf-8')\n",
                encoding="utf-8",
            )
            run_red_team_evidence(
                run_dir,
                evidence_id="minimal-recompute",
                kind="independent-recompute",
                packet_manifest=manifest,
                script_path="review/red_team_artifacts/minimal_recompute.py",
                output_paths=["recompute.json"],
            )
            receipt = run_red_team_evidence(
                run_dir,
                evidence_id="minimal-property",
                kind="property-test",
                packet_manifest=manifest,
                script_path="review/red_team_artifacts/minimal_property.py",
                output_paths=["property.json"],
            )
            evidence_reference = "证据：`" + receipt["outputs"][0]["path"] + "`。\n"
        report.write_text(
            "# 独立审查\n\n已从题面重建问题，并记录了可复现实验与反例检查。\n"
            + evidence_reference,
            encoding="utf-8",
        )
        return report

    @staticmethod
    def _prepare_scientific_phase(run_dir: Path) -> None:
        """写入审查所需的最小可读输入并进入科学审查阶段。"""
        (run_dir / "problem" / "statement.md").write_text("最小题面", encoding="utf-8")
        (run_dir / "code" / "solver.py").write_text("print('solver')\n", encoding="utf-8")
        (run_dir / "results" / "raw" / "candidate.json").write_text(
            json.dumps({"objective": 1.0}), encoding="utf-8"
        )
        prepare_minimal_capability_route(run_dir)
        update_simple_state(run_dir, phase="scientific_review")

    def _pass_scientific_review(self, run_dir: Path) -> dict[str, object]:
        """构建科学包并导入一个合格的隔离审查结论。"""
        packet = build_review_packet(run_dir, kind="scientific")
        report = self._write_report(run_dir, "SCIENTIFIC_RED_TEAM.md")
        import_scientific_review(
            run_dir,
            manifest_file=self._manifest_relative(packet),
            verdict="pass",
            highest_severity="none",
            competition_strength="qualified",
            full_rerun_required=False,
            affected_questions=[],
            reviewer_thread_id="fresh-scientific-thread",
            report_file=report.relative_to(run_dir),
        )
        return packet

    def _pass_paper_blind_review(self, run_dir: Path) -> dict[str, object]:
        """构建盲审包并导入一个合格的隔离 PDF 审查结论。"""
        packet = build_review_packet(run_dir, kind="paper-blind")
        report = self._write_report(run_dir, "PAPER_BLIND_REVIEW.md")
        import_paper_blind_review(
            run_dir,
            manifest_file=self._manifest_relative(packet),
            verdict="pass",
            highest_severity="none",
            reviewer_thread_id="fresh-paper-thread",
            argumentation_complete=True,
            readability_passed=True,
            report_file=report.relative_to(run_dir),
        )
        return packet

    def _pass_final_audit(self, run_dir: Path) -> dict[str, object]:
        """构建最终交付包并导入第三个独立对话的通过结论。"""
        packet = build_review_packet(run_dir, kind="final-audit")
        report = self._write_report(run_dir, "FINAL_SUBMISSION_REVIEW.md")
        import_final_audit(
            run_dir,
            manifest_file=self._manifest_relative(packet),
            verdict="pass",
            highest_severity="none",
            reviewer_thread_id="fresh-final-thread",
            report_file=report.relative_to(run_dir),
        )
        return packet

    @staticmethod
    def _write_passing_mechanical_qa(run_dir: Path) -> None:
        """写入绑定当前 PDF 的最小机械 QA 收据。"""
        pdf = run_dir / "paper" / "final.pdf"
        (run_dir / "qa" / "mechanical-qa.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "run_id": run_dir.name,
                    "workflow": "capability-first-v3",
                    "status": "pass",
                    "final_pdf": "paper/final.pdf",
                    "final_pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                    "checks": [{"id": "synthetic", "passed": True}],
                }
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _enter_paper(run_dir: Path) -> None:
        """在通过科学红队后完成最小可视化门并进入论文阶段。"""
        prepare_minimal_visualization(run_dir)
        prepare_cumcm_template(run_dir)
        update_simple_state(run_dir, phase="paper")

    @staticmethod
    def _enter_paper_review(run_dir: Path) -> None:
        """在已实例化完整模板的论文完成后进入 PDF 盲审阶段。"""
        update_simple_state(run_dir, phase="paper_review")

    @staticmethod
    def _run_review_cli(*arguments: str) -> dict[str, object]:
        """运行审查脚本入口并返回其 JSON 输出。"""
        completed = subprocess.run(
            [sys.executable, *arguments],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr)
        return json.loads(completed.stdout)

    def test_paper_requires_current_scientific_review_and_packet_is_sanitized(self) -> None:
        """本地证据链不能绕过新对话审查，且科学包不泄露旧质量结论。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "scientific-gate")
            self._prepare_scientific_phase(run_dir)
            packet = build_review_packet(run_dir, kind="scientific")
            manifest = load_json(run_dir / self._manifest_relative(packet))
            copied = {item["source"] for item in manifest["files"]}

            self.assertNotIn("results/quality.json", copied)
            self.assertFalse(any(path.startswith("state/") for path in copied))
            self.assertFalse(any(path.startswith("qa/") for path in copied))
            # 回归：results/raw 下含 quality 标签的文件也应被排除
            quality_labeled = {path for path in copied if "quality" in path}
            self.assertFalse(quality_labeled, f"quality-labeled files leaked: {quality_labeled}")
            with self.assertRaisesRegex(ContractError, "独立科学红队"):
                update_simple_state(run_dir, phase="visualization")

            report = self._write_report(run_dir, "SCIENTIFIC_RED_TEAM.md")
            import_scientific_review(
                run_dir,
                manifest_file=self._manifest_relative(packet),
                verdict="pass",
                highest_severity="none",
                competition_strength="qualified",
                full_rerun_required=False,
                affected_questions=[],
                reviewer_thread_id="fresh-scientific-thread",
                report_file=report.relative_to(run_dir),
            )
            self._enter_paper(run_dir)

            self.assertTrue(scientific_review_status(run_dir)["allowed"])

    def test_red_team_rejects_executed_but_scientifically_empty_output(self) -> None:
        """真实运行但只写计数的脚本不能成为科学红队证据。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "empty-red-team-output")
            self._prepare_scientific_phase(run_dir)
            packet = build_review_packet(run_dir, kind="scientific")
            script = run_dir / "review" / "red_team_artifacts" / "empty.py"
            script.write_text(
                "import json\n"
                "import sys\n"
                "from pathlib import Path\n"
                "_, outputs = (Path(value) for value in sys.argv[1:3])\n"
                "(outputs / 'empty.json').write_text(json.dumps({'cases': 1}), encoding='utf-8')\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ContractError, "语义输出"):
                run_red_team_evidence(
                    run_dir,
                    evidence_id="empty",
                    kind="independent-recompute",
                    packet_manifest=self._manifest_relative(packet),
                    script_path="review/red_team_artifacts/empty.py",
                    output_paths=["empty.json"],
                )

    def test_scientific_review_drift_or_p0_cannot_release_paper(self) -> None:
        """代码变化和 P0 都必须撤销论文放行，而不是只保留旧摘要。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "scientific-revocation")
            self._prepare_scientific_phase(run_dir)
            self._pass_scientific_review(run_dir)
            (run_dir / "code" / "solver.py").write_text("print('changed')\n", encoding="utf-8")

            self.assertFalse(scientific_review_status(run_dir)["allowed"])
            with self.assertRaisesRegex(ContractError, "独立科学红队"):
                self._enter_paper(run_dir)

        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "scientific-p0")
            self._prepare_scientific_phase(run_dir)
            packet = build_review_packet(run_dir, kind="scientific")
            report = self._write_report(run_dir, "SCIENTIFIC_RED_TEAM.md")

            with self.assertRaisesRegex(ContractError, "P0/P1"):
                import_scientific_review(
                    run_dir,
                    manifest_file=self._manifest_relative(packet),
                    verdict="pass",
                    highest_severity="P0",
                    competition_strength="weak",
                    full_rerun_required=True,
                    affected_questions=["Q1"],
                    reviewer_thread_id="fresh-scientific-thread",
                    report_file=report.relative_to(run_dir),
                )

    def test_objective_semantics_reimport_revokes_all_downstream_reviews(self) -> None:
        """目标语义重审必须撤销基于旧目标的科学审核和论文审核。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            statement = root / "statement.md"
            statement.write_text("问题 Q5：求总有效作用时长。", encoding="utf-8")
            run_dir = initialize_simple_run(
                root,
                "objective-reimport",
                problem_path=statement,
                required_questions=["Q5"],
            )
            self._prepare_scientific_phase(run_dir)
            self._pass_scientific_review(run_dir)
            semantics_manifest = next(
                (run_dir / "review" / "packet" / "objective-semantics").glob(
                    "*/manifest.json"
                )
            )

            import_objective_semantics_review(
                run_dir,
                manifest_file=semantics_manifest.relative_to(run_dir).as_posix(),
                verdict="pass",
                highest_severity="none",
                reviewer_thread_id="semantic-recheck-thread",
            )

            summary = load_json(run_dir / "review" / "summary.json")
            self.assertEqual("revoked", summary["scientific_review"]["verdict"])
            self.assertIsNone(summary["paper_blind_review"])
            self.assertIsNone(summary["final_audit"])
            self.assertFalse(scientific_review_status(run_dir)["allowed"])

    def test_manifest_paths_and_import_phases_cannot_be_swapped(self) -> None:
        """手写 manifest 越界或在错误阶段导入结论都不能改变流程放行。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "packet-integrity")
            self._prepare_scientific_phase(run_dir)
            packet = build_review_packet(run_dir, kind="scientific")
            manifest_path = run_dir / self._manifest_relative(packet)
            manifest = load_json(manifest_path)
            manifest["source_roots"][0]["packet"] = "../../results/quality.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            verified = verify_review_packet(run_dir, self._manifest_relative(packet))
            self.assertFalse(verified["success"])
            self.assertIn("路径", "；".join(verified["errors"]))

            report = run_dir / "review" / "SCIENTIFIC_RED_TEAM.md"
            report.write_text("# 失效包测试\n\n该报告不会绕过已损坏的审查包。\n", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "审查包|路径"):
                import_scientific_review(
                    run_dir,
                    manifest_file=self._manifest_relative(packet),
                    verdict="pass",
                    highest_severity="none",
                    competition_strength="qualified",
                    full_rerun_required=False,
                    affected_questions=[],
                    reviewer_thread_id="fresh-scientific-thread",
                    report_file=report.relative_to(run_dir),
                )

    def test_three_reviews_and_current_mechanical_qa_are_required_for_completion(self) -> None:
        """三轮审核和机械 QA 必须依次绑定同一套当前交付物。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "paper-blind-gate")
            self._prepare_scientific_phase(run_dir)
            self._pass_scientific_review(run_dir)
            self._enter_paper(run_dir)
            (run_dir / "paper" / "final.pdf").write_bytes(b"%PDF-1.4\nminimal")
            self._enter_paper_review(run_dir)
            packet = build_review_packet(run_dir, kind="paper-blind")
            manifest = load_json(run_dir / self._manifest_relative(packet))
            copied = {item["source"] for item in manifest["files"]}

            self.assertFalse(any(path.startswith("code/") for path in copied))
            self.assertFalse(any(path.startswith("qa/") for path in copied))
            with self.assertRaisesRegex(ContractError, "独立 PDF 盲审"):
                update_simple_state(run_dir, phase="verify")

            self._pass_paper_blind_review(run_dir)
            (run_dir / "paper" / "final.pdf").write_bytes(b"%PDF-1.4\nchanged")
            self.assertFalse(paper_blind_review_status(run_dir)["allowed"])
            with self.assertRaisesRegex(ContractError, "独立 PDF 盲审"):
                update_simple_state(run_dir, phase="verify")

        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "complete-gate")
            self._prepare_scientific_phase(run_dir)
            self._pass_scientific_review(run_dir)
            self._enter_paper(run_dir)
            pdf = run_dir / "paper" / "final.pdf"
            pdf.write_bytes(b"%PDF-1.4\nminimal")
            self._enter_paper_review(run_dir)
            self._pass_paper_blind_review(run_dir)
            update_simple_state(run_dir, phase="verify")

            with self.assertRaisesRegex(ContractError, "不允许从 verify 直接进入 complete"):
                update_simple_state(run_dir, phase="complete")

            self._write_passing_mechanical_qa(run_dir)
            update_simple_state(run_dir, phase="final_review")
            with self.assertRaisesRegex(ContractError, "最终交付审核"):
                update_simple_state(run_dir, phase="complete")

            packet = self._pass_final_audit(run_dir)
            manifest = load_json(run_dir / self._manifest_relative(packet))
            copied = {item["source"] for item in manifest["files"]}
            self.assertIn("paper/final.pdf", copied)
            self.assertFalse(any(path.startswith("qa/") for path in copied))
            self.assertFalse(any(path.startswith("results/") for path in copied))
            self.assertFalse(any(path.startswith("review/") for path in copied))
            self.assertTrue(completion_status(run_dir)["allowed"])
            update_simple_state(run_dir, phase="complete")

    def test_final_audit_requires_third_thread_and_invalidates_on_delivery_drift(self) -> None:
        """终审不得复用旧对话，且最终交付树变化后必须重新审核。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "final-audit-drift")
            self._prepare_scientific_phase(run_dir)
            self._pass_scientific_review(run_dir)
            self._enter_paper(run_dir)
            (run_dir / "paper" / "final.pdf").write_bytes(b"%PDF-1.4\nminimal")
            self._enter_paper_review(run_dir)
            self._pass_paper_blind_review(run_dir)
            update_simple_state(run_dir, phase="verify")
            self._write_passing_mechanical_qa(run_dir)
            update_simple_state(run_dir, phase="final_review")
            packet = build_review_packet(run_dir, kind="final-audit")
            report = self._write_report(run_dir, "FINAL_SUBMISSION_REVIEW.md")

            with self.assertRaisesRegex(ContractError, "第三个新对话"):
                import_final_audit(
                    run_dir,
                    manifest_file=self._manifest_relative(packet),
                    verdict="pass",
                    highest_severity="none",
                    reviewer_thread_id="fresh-paper-thread",
                    report_file=report.relative_to(run_dir),
                )

            import_final_audit(
                run_dir,
                manifest_file=self._manifest_relative(packet),
                verdict="pass",
                highest_severity="none",
                reviewer_thread_id="fresh-final-thread",
                report_file=report.relative_to(run_dir),
            )
            self.assertTrue(final_audit_status(run_dir)["allowed"])
            (run_dir / "paper" / "submission" / "final.pdf").write_bytes(
                b"%PDF-1.4\ntampered"
            )
            self.assertFalse(final_audit_status(run_dir)["allowed"])
            self.assertFalse(completion_status(run_dir)["allowed"])

    def test_blind_packet_contains_completed_task_attachments(self) -> None:
        """盲审提交包必须使用已填写产物，而不是题面中的空白模板。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "completed-attachments")
            self._prepare_scientific_phase(run_dir)
            self._pass_scientific_review(run_dir)
            self._enter_paper(run_dir)
            (run_dir / "paper" / "final.pdf").write_bytes(b"%PDF-1.4\nminimal")
            template = run_dir / "problem" / "attachments" / "result1.xlsx"
            template.parent.mkdir(parents=True, exist_ok=True)
            template.write_bytes(b"")
            completed = run_dir / "artifacts" / "result1.xlsx"
            completed.parent.mkdir(parents=True, exist_ok=True)
            completed.write_bytes(b"filled-result")
            self._enter_paper_review(run_dir)

            packet = build_review_packet(run_dir, kind="paper-blind")
            packet_dir = (
                run_dir
                / "review"
                / "packet"
                / "paper-blind"
                / str(packet["packet_id"])
            )
            submitted = packet_dir / "submission" / "attachments" / "result1.xlsx"
            submission_manifest = load_json(packet_dir / "submission" / "manifest.json")

            self.assertEqual(b"filled-result", submitted.read_bytes())
            self.assertTrue(
                any(
                    item["role"] == "completed_problem_attachment"
                    and item["source"] == "artifacts/result1.xlsx"
                    for item in submission_manifest["files"]
                )
            )

    def test_paper_blind_review_cannot_reuse_the_scientific_review_thread(self) -> None:
        """两次独立审查必须绑定不同的新对话标识。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "separate-review-threads")
            self._prepare_scientific_phase(run_dir)
            self._pass_scientific_review(run_dir)
            self._enter_paper(run_dir)
            (run_dir / "paper" / "final.pdf").write_bytes(b"%PDF-1.4\nminimal")
            self._enter_paper_review(run_dir)
            packet = build_review_packet(run_dir, kind="paper-blind")
            report = self._write_report(run_dir, "PAPER_BLIND_REVIEW.md")

            with self.assertRaisesRegex(ContractError, "不同于科学红队"):
                import_paper_blind_review(
                    run_dir,
                    manifest_file=self._manifest_relative(packet),
                    verdict="pass",
                    highest_severity="none",
                    reviewer_thread_id="fresh-scientific-thread",
                    argumentation_complete=True,
                    readability_passed=True,
                    report_file=report.relative_to(run_dir),
                )

    def test_review_cli_crosses_all_independent_boundaries(self) -> None:
        """脚本入口必须执行三次隔离审查的实际阶段迁移。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "review-cli-e2e")
            self._prepare_scientific_phase(run_dir)
            scientific_packet = self._run_review_cli(
                str(BUILD_PACKET), str(run_dir), "--kind", "scientific"
            )
            scientific_manifest = self._manifest_relative(scientific_packet)
            scientific_report = self._write_report(run_dir, "SCIENTIFIC_RED_TEAM.md")
            self._run_review_cli(
                str(IMPORT_REVIEW),
                str(run_dir),
                "--kind",
                "scientific",
                "--manifest",
                scientific_manifest,
                "--verdict",
                "pass",
                "--severity",
                "none",
                "--competition-strength",
                "qualified",
                "--thread-id",
                "cli-scientific-thread",
                "--report",
                scientific_report.relative_to(run_dir).as_posix(),
            )
            self._enter_paper(run_dir)
            (run_dir / "paper" / "final.pdf").write_bytes(b"%PDF-1.4\nminimal")
            self._enter_paper_review(run_dir)
            blind_packet = self._run_review_cli(
                str(BUILD_PACKET), str(run_dir), "--kind", "paper-blind"
            )
            blind_manifest = self._manifest_relative(blind_packet)
            blind_report = self._write_report(run_dir, "PAPER_BLIND_REVIEW.md")
            self._run_review_cli(
                str(IMPORT_REVIEW),
                str(run_dir),
                "--kind",
                "paper-blind",
                "--manifest",
                blind_manifest,
                "--verdict",
                "pass",
                "--severity",
                "none",
                "--thread-id",
                "cli-paper-thread",
                "--argumentation-complete",
                "--readability-passed",
                "--report",
                blind_report.relative_to(run_dir).as_posix(),
            )
            update_simple_state(run_dir, phase="verify")
            self._write_passing_mechanical_qa(run_dir)
            update_simple_state(run_dir, phase="final_review")
            final_packet = self._run_review_cli(
                str(BUILD_PACKET), str(run_dir), "--kind", "final-audit"
            )
            final_manifest = self._manifest_relative(final_packet)
            final_report = self._write_report(run_dir, "FINAL_SUBMISSION_REVIEW.md")
            self._run_review_cli(
                str(IMPORT_REVIEW),
                str(run_dir),
                "--kind",
                "final-audit",
                "--manifest",
                final_manifest,
                "--verdict",
                "pass",
                "--severity",
                "none",
                "--thread-id",
                "cli-final-thread",
                "--report",
                final_report.relative_to(run_dir).as_posix(),
            )

            self.assertTrue(scientific_review_status(run_dir)["allowed"])
            self.assertTrue(paper_blind_review_status(run_dir)["allowed"])
            self.assertTrue(final_audit_status(run_dir)["allowed"])


if __name__ == "__main__":
    unittest.main()
