"""验证 Capability-First v3 的独立运行时和机械 QA。"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.qa.check_numeric_consistency import check_numeric_consistency
from scripts.qa.check_placeholders import check_placeholders
from scripts.qa.check_result_references import check_result_references
from scripts.qa.run_final_checks import run_final_checks
from shumozizi.core.io import atomic_json
from shumozizi.simple.execution import execute_simple_experiment
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.results import read_result_index, verify_current_result_files
from shumozizi.simple.state import read_simple_state, update_simple_state
from tools.qa.figqa import find_overlaps
from tools.qa.make_contact_sheet import make_contact_sheet
from tools.qa.pdf_qa import FIGURE_CAPTION_PATTERN, audit_pdf

REPO_ROOT = Path(__file__).resolve().parents[1]
INITIALIZER = REPO_ROOT / "scripts" / "codex" / "init_run.py"


class CapabilityFirstV3Tests(unittest.TestCase):
    """覆盖 v3 与 legacy-v2 隔离的关键用户路径。"""

    def setUp(self) -> None:
        """创建带题面和附件的临时仓库根。"""
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.problem = self.root / "source-problem"
        self.problem.mkdir()
        (self.problem / "statement.md").write_text("请回答 Q1。\n", encoding="utf-8")
        (self.problem / "data.csv").write_text("x,y\n1,2\n", encoding="utf-8")

    def tearDown(self) -> None:
        """清理临时运行目录。"""
        self.temporary.cleanup()

    def test_initializes_minimal_state_and_problem_copy(self) -> None:
        """初始化应创建计划定义的目录，而不写入 v2 状态。"""
        run_dir = initialize_simple_run(
            self.root,
            "v3-test",
            problem_path=self.problem,
            competition="cumcm",
            required_questions=["Q1"],
            total_hours=72,
            token_soft_cap=200_000,
        )

        state = read_simple_state(run_dir)

        self.assertEqual("capability-first-v3", state["workflow"])
        self.assertEqual("analysis", state["phase"])
        self.assertTrue((run_dir / "problem" / "statement.md").is_file())
        self.assertTrue((run_dir / "problem" / "attachments" / "data.csv").is_file())
        self.assertTrue((run_dir / "state" / "DECISIONS.md").is_file())
        self.assertFalse((run_dir / "state.json").exists())
        updated = update_simple_state(run_dir, phase="experiment", selected_route="route-a")
        self.assertEqual(1, updated["revision"])
        self.assertEqual("route-a", updated["selected_route"])

    def test_experiment_records_hashes_and_supersedes_prior_current_result(self) -> None:
        """同问同类的新真实执行应替代旧 current 结果，而不是删除历史。"""
        run_dir = initialize_simple_run(self.root, "v3-experiment")
        script = run_dir / "code" / "q1.py"
        script.write_text(
            "from pathlib import Path\n"
            "import json\n"
            "Path('results/raw/q1.json').write_text(json.dumps({'metrics': {'objective': 2.0}}), encoding='utf-8')\n",
            encoding="utf-8",
        )
        command = f'"{sys.executable}" code/q1.py'
        first = execute_simple_experiment(
            run_dir,
            result_id="q1_primary_a",
            question_id="Q1",
            kind="primary",
            command=command,
            expected_outputs=["results/raw/q1.json"],
            metrics_from="results/raw/q1.json",
        )
        second = execute_simple_experiment(
            run_dir,
            result_id="q1_primary_b",
            question_id="Q1",
            kind="primary",
            command=command,
            expected_outputs=["results/raw/q1.json"],
            metrics_from="results/raw/q1.json",
        )

        index = read_result_index(run_dir)

        self.assertTrue(first["success"], first["error"])
        self.assertTrue(second["success"], second["error"])
        self.assertEqual(["superseded", "current"], [item["status"] for item in index["results"]])
        self.assertTrue(index["results"][0]["execution_valid"])
        self.assertTrue(index["results"][1]["execution_valid"])
        self.assertIn("code/q1.py", index["results"][1]["input_hashes"])
        self.assertIn("results/raw/q1.json", index["results"][1]["output_hashes"])
        self.assertEqual(
            {
                "file": "results/raw/q1.json",
                "json_path": "metrics.objective",
                "file_sha256": index["results"][1]["output_hashes"]["results/raw/q1.json"],
            },
            index["results"][1]["metric_sources"]["objective"],
        )
        (run_dir / "paper" / "sections" / "q1.typ").write_text(
            "// @result q1_primary_b\n// @metric q1_primary_b.objective 2.0\n",
            encoding="utf-8",
        )
        self.assertTrue(check_result_references(run_dir)["success"])
        self.assertTrue(check_numeric_consistency(run_dir)["success"])
        self.assertTrue(verify_current_result_files(run_dir)["success"])

        (run_dir / "paper" / "sections" / "q1.typ").write_text(
            "// @metric q1_primary_a.objective 2.0\n", encoding="utf-8"
        )
        stale_metric = check_numeric_consistency(run_dir)
        self.assertFalse(stale_metric["success"])
        self.assertEqual(
            "指标引用的结果不是 current 且 execution_valid=true",
            stale_metric["inconsistent"][0]["reason"],
        )

        index["results"][1]["execution_valid"] = False
        atomic_json(run_dir / "results" / "index.json", index)
        invalid_current = verify_current_result_files(run_dir)
        self.assertFalse(invalid_current["success"])
        self.assertEqual(
            "current 结果未标记为 execution_valid",
            invalid_current["errors"][0]["message"],
        )

    def test_failed_rerun_that_overwrites_output_invalidates_current_result(self) -> None:
        """失败运行覆盖 current 输出后，终检必须发现旧哈希不再可信。"""
        run_dir = initialize_simple_run(self.root, "v3-stale-output")
        (run_dir / "code" / "success.py").write_text(
            "from pathlib import Path\n"
            "import json\n"
            "Path('results/raw/q1.json').write_text(json.dumps({'metrics': {'objective': 1.0}}), encoding='utf-8')\n",
            encoding="utf-8",
        )
        (run_dir / "code" / "failure.py").write_text(
            "from pathlib import Path\n"
            "import json\n"
            "Path('results/raw/q1.json').write_text(json.dumps({'metrics': {'objective': 999.0}}), encoding='utf-8')\n"
            "raise SystemExit(7)\n",
            encoding="utf-8",
        )
        success_command = f'"{sys.executable}" code/success.py'
        failure_command = f'"{sys.executable}" code/failure.py'
        first = execute_simple_experiment(
            run_dir,
            result_id="q1_current",
            question_id="Q1",
            kind="primary",
            command=success_command,
            expected_outputs=["results/raw/q1.json"],
            metrics_from="results/raw/q1.json",
        )
        failed = execute_simple_experiment(
            run_dir,
            result_id="q1_failed_rerun",
            question_id="Q1",
            kind="primary",
            command=failure_command,
            expected_outputs=["results/raw/q1.json"],
            metrics_from="results/raw/q1.json",
        )

        verification = verify_current_result_files(run_dir)
        final_report = run_final_checks(run_dir)

        self.assertTrue(first["success"], first["error"])
        self.assertFalse(failed["success"])
        self.assertFalse(verification["success"])
        self.assertTrue(
            any(item["result_id"] == "q1_current" for item in verification["errors"])
        )
        current_check = next(
            item for item in final_report["checks"] if item["id"] == "current-result-files"
        )
        self.assertFalse(current_check["passed"])

    def test_legacy_rendered_marker_is_blocked_but_comment_marker_is_accepted(self) -> None:
        """追溯信息必须写在注释中，避免污染最终 PDF。"""
        run_dir = initialize_simple_run(self.root, "v3-markers")
        source = run_dir / "paper" / "sections" / "q1.typ"
        source.write_text("// @result q1_primary\n", encoding="utf-8")
        self.assertTrue(check_placeholders(run_dir / "paper")["success"])

        source.write_text("[[result:q1_primary]]\n", encoding="utf-8")
        report = check_placeholders(run_dir / "paper")

        self.assertFalse(report["success"])
        self.assertIn("遗留可渲染追溯标记", report["matches"]["sections/q1.typ"])

    def test_v3_init_run_cli_accepts_workflow_without_problem_path(self) -> None:
        """兼容入口应能显式创建未附题面的 v3 运行。"""
        completed = subprocess.run(
            [
                sys.executable,
                str(INITIALIZER),
                "--workflow",
                "capability-first-v3",
                "--run-id",
                "cli-v3",
                "--repo-root",
                str(self.root),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual("3.0", payload["run_schema_version"])
        self.assertTrue((self.root / "runs" / "cli-v3" / "state" / "run.json").is_file())

    def test_final_checks_report_missing_pdf_without_legacy_imports(self) -> None:
        """机械终检应在 PDF 缺失时产生可定位报告，而不是调用旧 QA。"""
        run_dir = initialize_simple_run(self.root, "v3-qa")

        report = run_final_checks(run_dir)

        self.assertEqual("blocked", report["status"])
        self.assertIn("pdf", report["hard_failures"])
        self.assertTrue((run_dir / "qa" / "mechanical-qa.json").is_file())
        self.assertTrue((run_dir / "reports" / "VERIFY_REPORT.md").is_file())

    def test_figqa_detects_exported_text_box_overlap(self) -> None:
        """导出的文字边界相交时应报告确定性重叠。"""
        overlaps = find_overlaps(
            [
                {"id": "title", "x0": 0, "y0": 0, "x1": 10, "y1": 5},
                {"id": "legend", "x0": 8, "y0": 4, "x1": 12, "y1": 9},
            ]
        )

        self.assertEqual([{"first": "title", "second": "legend"}], overlaps)

    def test_contact_sheet_is_generated_from_a_real_pdf(self) -> None:
        """联系表应能在 Windows 上使用仓内 PDF 产物生成 PNG。"""
        source_pdf = REPO_ROOT / "benchmarks" / "huashubei-2023-c1" / "paper_a" / "paper_a.pdf"
        target = self.root / "contact-sheet.png"

        output = make_contact_sheet(source_pdf, target)

        self.assertEqual(target, output)
        self.assertGreater(target.stat().st_size, 0)

    def test_anonymous_mode_blocks_configured_identity_term(self) -> None:
        """启用匿名模式时，调用方指定的身份词必须成为硬错误。"""
        source_pdf = (
            REPO_ROOT / "benchmarks" / "huashubei-2023-c1" / "paper_a" / "paper_a.pdf"
        )

        report = audit_pdf(
            source_pdf,
            anonymous_required=True,
            anonymous_terms=("母亲身心指标",),
        )
        anonymous_check = next(
            item for item in report["checks"] if item["id"] == "anonymous"
        )

        self.assertFalse(report["success"])
        self.assertFalse(anonymous_check["passed"])
        self.assertTrue(anonymous_check["blocking"])

    def test_caption_pattern_ignores_normal_figure_references(self) -> None:
        """正文“如图 1 所示”不能被误认为重复图注编号。"""
        text = "如图 1 所示，结果稳定。\n图 1：模型结果\n正文再次引用图 1。\n"

        self.assertEqual(["1"], FIGURE_CAPTION_PATTERN.findall(text))

    def test_active_skills_are_exactly_the_six_v3_capabilities(self) -> None:
        """自动发现目录不得残留 legacy 审核与路线 Skill。"""
        skills = {path.name for path in (REPO_ROOT / ".agents" / "skills").iterdir() if path.is_dir()}

        self.assertEqual(
            {
                "mathmodel-workflow",
                "mathmodel-solve",
                "mathmodel-experiment",
                "mathmodel-paper",
                "mathmodel-final-check",
                "mathmodel-learn-paper",
            },
            skills,
        )

    def test_active_capabilities_route_to_modeling_and_figure_assets(self) -> None:
        """v3 主动 Skill 必须按需接入仓内建模和科研绘图能力。"""
        solve = (REPO_ROOT / ".agents" / "skills" / "mathmodel-solve" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        experiment = (
            REPO_ROOT / ".agents" / "skills" / "mathmodel-experiment" / "SKILL.md"
        ).read_text(encoding="utf-8")

        self.assertIn("skills/2analysis-modeling/SKILL.md", solve)
        self.assertIn("templates/algorithms/", solve)
        self.assertIn("skills/3coding-visual/SKILL.md", experiment)
        self.assertIn("skills/mathmodel-figure-templates", experiment)
        self.assertTrue(
            (
                REPO_ROOT
                / "skills"
                / "mathmodel-figure-templates"
                / "scripts"
                / "render_template.py"
            ).is_file()
        )


if __name__ == "__main__":
    unittest.main()
