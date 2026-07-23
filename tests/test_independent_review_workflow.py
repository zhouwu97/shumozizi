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
    import_paper_blind_review,
    import_scientific_review,
    paper_blind_review_status,
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
        report.write_text(
            "# 独立审查\n\n已从题面重建问题，并记录了可复现实验与反例检查。\n",
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
            report_file=report.relative_to(run_dir),
        )
        return packet

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

            report = self._write_report(run_dir, "SCIENTIFIC_RED_TEAM.md")
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

    def test_blind_review_and_current_mechanical_qa_are_required_for_completion(self) -> None:
        """PDF 盲审只审 PDF 包，且 complete 绑定同一份已检查 PDF。"""
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

            with self.assertRaisesRegex(ContractError, "机械 QA"):
                update_simple_state(run_dir, phase="complete")

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
            self.assertTrue(completion_status(run_dir)["allowed"])
            update_simple_state(run_dir, phase="complete")

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
                    report_file=report.relative_to(run_dir),
                )

    def test_review_cli_crosses_both_independent_boundaries(self) -> None:
        """脚本入口必须执行两次隔离审查的实际阶段迁移。"""
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
                "--report",
                blind_report.relative_to(run_dir).as_posix(),
            )
            update_simple_state(run_dir, phase="verify")

            self.assertTrue(scientific_review_status(run_dir)["allowed"])
            self.assertTrue(paper_blind_review_status(run_dir)["allowed"])


if __name__ == "__main__":
    unittest.main()
