"""验证 v3 执行索引与科学质量层的分离。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.qa.check_result_references import check_result_references
from shumozizi.core.io import ContractError
from shumozizi.simple.execution import execute_simple_experiment
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.quality import (
    assess_result_quality,
    migrate_legacy_result_quality,
    quality_allows_paper,
)
from shumozizi.simple.results import read_result_index
from tests.quality_protocol_helpers import (
    adapter_backed_assessment,
    legacy_self_report_assessment,
    legacy_self_report_document,
    run_synthetic_verification_protocol,
)


class SimpleQualityTests(unittest.TestCase):
    """覆盖高风险优化的最小质量放行边界。"""

    def test_baseline_preserved_does_not_by_itself_allow_paper(self) -> None:
        """基线保持不能替代搜索充分性通过。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = initialize_simple_run(root, "quality-baseline")
            script = run_dir / "code" / "q2.py"
            script.write_text(
                "from pathlib import Path\n"
                "import json\n"
                "Path('results/raw/q2.json').write_text(json.dumps({'metrics': {'objective': 2.0}}), encoding='utf-8')\n",
                encoding="utf-8",
            )
            recorded = execute_simple_experiment(
                run_dir,
                result_id="q2_baseline_only",
                question_id="Q2",
                kind="search",
                command=f'"{sys.executable}" code/q2.py',
                expected_outputs=["results/raw/q2.json"],
                metrics_from="results/raw/q2.json",
            )
            assess_result_quality(
                run_dir,
                result_id="q2_baseline_only",
                feasibility_valid=True,
                baseline_preserved=True,
                search_adequacy="failed",
                result_role="diagnostic",
                reasons=["search_coverage_insufficient"],
            )
            (run_dir / "paper" / "sections" / "q2.typ").write_text(
                "// @result q2_baseline_only\n", encoding="utf-8"
            )

            self.assertTrue(recorded["success"], recorded["error"])
            self.assertFalse(quality_allows_paper(run_dir, "q2_baseline_only"))
            self.assertEqual(
                "结果未通过质量层放行",
                check_result_references(run_dir)["invalid"][0]["reason"],
            )

    def test_migration_removes_legacy_quality_from_execution_index(self) -> None:
        """迁移必须保留执行记录，同时把旧 use_status 留在质量层。"""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = initialize_simple_run(Path(temporary), "quality-migration")
            index_path = run_dir / "results" / "index.json"
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["results"] = [
                {
                    "result_id": "legacy",
                    "question_id": "Q2",
                    "kind": "search",
                    "source_script": None,
                    "command": "python legacy.py",
                    "input_files": [],
                    "input_hashes": {},
                    "output_files": [],
                    "output_hashes": {},
                    "metrics": {},
                    "metric_sources": {},
                    "status": "current",
                    "use_status": "diagnostic_only",
                    "execution_valid": True,
                    "exit_code": 0,
                    "stdout_path": "results/raw/legacy.out",
                    "stderr_path": "results/raw/legacy.err",
                    "started_at": "2026-01-01T00:00:00Z",
                    "finished_at": "2026-01-01T00:00:01Z",
                    "duration_seconds": 1.0,
                    "error": None,
                    "created_at": "2026-01-01T00:00:01Z"
                }
            ]
            index_path.write_text(json.dumps(index), encoding="utf-8")

            migration = migrate_legacy_result_quality(run_dir)

            self.assertEqual(["legacy"], migration["migrated_result_ids"])
            self.assertNotIn("use_status", read_result_index(run_dir)["results"][0])
            self.assertFalse(quality_allows_paper(run_dir, "legacy"))

    def test_failed_search_cannot_be_forced_to_accepted_for_paper(self) -> None:
        """独立审计发现校准失败时，即使申请 accepted 也必须关闭论文权限。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = initialize_simple_run(root, "quality-failed-accepted")
            protocol = run_synthetic_verification_protocol(
                run_dir,
                result_id="q2_low_quality",
                question_id="Q2",
                objective=2.0,
                calibration_status="failed",
            )
            assessment = assess_result_quality(
                run_dir,
                result_id="q2_low_quality",
                assessment=adapter_backed_assessment(protocol),
            )

            self.assertFalse(assessment["paper_allowed"])
            self.assertFalse(quality_allows_paper(run_dir, "q2_low_quality"))

    def test_legacy_generator_self_report_stays_diagnostic_and_unverified(self) -> None:
        """旧输出中的通过布尔值既不能自行 accepted，也不能在迁移时升级。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = initialize_simple_run(root, "legacy-self-report")
            output = "results/raw/q2.json"
            script = run_dir / "code" / "q2.py"
            script.write_text(
                "from pathlib import Path\n"
                "import json\n"
                f"payload = {{'metrics': {{'objective': 2.0}}, 'quality': {legacy_self_report_document(2.0)!r}}}\n"
                f"Path({output!r}).write_text(json.dumps(payload), encoding='utf-8')\n",
                encoding="utf-8",
            )
            executed = execute_simple_experiment(
                run_dir,
                result_id="legacy_self_report",
                question_id="Q2",
                kind="search",
                command=f'"{sys.executable}" code/q2.py',
                expected_outputs=[output],
                metrics_from=output,
            )

            with self.assertRaisesRegex(ContractError, "adapter|verification|独立"):
                assess_result_quality(
                    run_dir,
                    result_id="legacy_self_report",
                    assessment=legacy_self_report_assessment("legacy_self_report", output),
                )
            migrated = assess_result_quality(
                run_dir,
                result_id="legacy_self_report",
                assessment={
                    "result_role": "diagnostic",
                    "reasons": ["legacy_generator_self_report"],
                },
            )

            self.assertTrue(executed["success"], executed["error"])
            self.assertEqual("diagnostic", migrated["result_role"])
            self.assertFalse(migrated["paper_allowed"])
            self.assertIn("legacy_unverified_quality_claim", migrated["reasons"])
            self.assertFalse(quality_allows_paper(run_dir, "legacy_self_report"))


if __name__ == "__main__":
    unittest.main()
