"""验证外部来源、知识索引与模板实例化边界。"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from shumozizi.core.io import ContractError, sha256_file
from shumozizi.knowledge.selector import (
    build_knowledge_index,
    select_knowledge_cards,
    verify_knowledge_index,
)
from shumozizi.runtime.templates import instantiate_template, verify_template_receipt
from tests.runtime_helpers import RuntimeFixture

REPO_ROOT = Path(__file__).resolve().parents[1]


class KnowledgeContractTests(unittest.TestCase):
    """验证知识资产只从锁定且许可边界明确的来源进入。"""

    def test_index_is_reproducible_and_selects_ranked_cards(self) -> None:
        """索引重建应稳定，选择器只读取通过哈希复验的卡片。"""
        before = sha256_file(REPO_ROOT / "knowledge" / "INDEX.json")
        rebuilt = build_knowledge_index(REPO_ROOT)
        after = sha256_file(REPO_ROOT / "knowledge" / "INDEX.json")

        self.assertEqual(before, after)
        self.assertEqual(4, len(rebuilt["cards"]))
        self.assertEqual(rebuilt, verify_knowledge_index(REPO_ROOT))
        selected = select_knowledge_cards(REPO_ROOT, {"pdf", "qa", "evidence"})
        self.assertEqual("bounded-mechanical-submission-qa", selected[0]["card_id"])

    def test_unlicensed_source_is_restricted_to_ideas(self) -> None:
        """未声明许可证的 Friendly Mode 来源不得被登记为可复制资产。"""
        registry = json.loads(
            (REPO_ROOT / "knowledge" / "SOURCE_REGISTRY.json").read_text(encoding="utf-8")
        )
        source = next(
            item
            for item in registry["sources"]
            if item["source_id"] == "handsomezr-mathmodel-skill"
        )

        self.assertEqual("not-declared-at-repository-root", source["license_status"])
        self.assertEqual("ideas-only", source["usage_mode"])
        self.assertIn("code-copy", source["forbidden_assets"])


class TemplateIntegrationTests(unittest.TestCase):
    """验证四个模板的来源回执、哈希和实例目录约束。"""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temporary.name) / "repo"
        shutil.copytree(REPO_ROOT / "templates", self.repo_root / "templates")
        shutil.copytree(REPO_ROOT / "knowledge", self.repo_root / "knowledge")
        self.run_dir = self.repo_root / "runs" / "template-test"
        self.run_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_all_representative_templates_have_verifiable_receipts(self) -> None:
        """四类代表模板都必须记录固定来源和实际生成文件哈希。"""
        parameters = {
            "linear-regression-basic": {"x_column": "x", "y_column": "y"},
            "integer-programming-basic": {},
            "monte-carlo-sensitivity": {},
            "network-shortest-path": {},
        }
        for template_id, values in parameters.items():
            with self.subTest(template_id=template_id):
                instance = instantiate_template(
                    self.repo_root,
                    self.run_dir,
                    template_id,
                    "q1",
                    template_id,
                    values,
                )
                verification = verify_template_receipt(instance)
                self.assertTrue(verification["valid"], verification["errors"])
                self.assertEqual(
                    "856816bda312ca9c02082f1d026d1416ebbaa861",
                    verification["receipt"]["source_commit"],
                )

    def test_modified_instance_invalidates_receipt(self) -> None:
        """实例化后修改代码必须由回执复验发现。"""
        instance = instantiate_template(
            self.repo_root,
            self.run_dir,
            "linear-regression-basic",
            "q1",
            "modified",
            {"x_column": "x", "y_column": "y"},
        )
        (instance / "model.py").write_text("print('tampered')\n", encoding="utf-8")

        verification = verify_template_receipt(instance)

        self.assertFalse(verification["valid"])
        self.assertIn("生成文件哈希不一致", "; ".join(verification["errors"]))

    def test_destination_outside_runs_is_rejected(self) -> None:
        """实例化器不得向仓库其他目录写模板代码。"""
        with self.assertRaisesRegex(ContractError, "runs/<run_id>"):
            instantiate_template(
                self.repo_root,
                self.repo_root / "scratch",
                "network-shortest-path",
                "q1",
                "outside",
                {},
            )


class ExecutorTemplateBoundaryTests(unittest.TestCase):
    """验证执行器不会直接运行仓库级模板或运行目录其他脚本。"""

    def test_script_outside_code_directory_is_rejected(self) -> None:
        """即使脚本位于 run 内并已声明，也必须在 code/ 下。"""
        fixture = RuntimeFixture()
        try:
            script = fixture.run_dir / "reports" / "outside.py"
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_text(
                "from pathlib import Path\nPath('results/outside.json').write_text('{}')\n",
                encoding="utf-8",
            )
            manifest = fixture.write_json(
                "executions/manifests/outside.json",
                {
                    "schema_name": "execution_manifest",
                    "schema_version": "2.0",
                    "execution_id": "outside",
                    "program": "python",
                    "args": ["reports/outside.py", "results/outside.json"],
                    "cwd": ".",
                    "timeout_seconds": 10,
                    "input_files": ["reports/outside.py"],
                    "expected_outputs": ["results/outside.json"],
                    "random_seed": 42,
                },
            )

            completed = fixture.run_executor(manifest)

            self.assertNotEqual(0, completed.returncode)
            self.assertIn("runs/<run_id>/code/", completed.stdout)
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main()
