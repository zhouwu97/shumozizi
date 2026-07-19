"""验证比赛 Profile、证据审计与机械 QA Adapter。"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from shumozizi.core.io import ContractError, atomic_json
from shumozizi.core.schema import require_valid
from shumozizi.evidence.adapters import audit_paper_evidence
from shumozizi.profiles.lock import create_run_config_lock
from shumozizi.qa.adapters import run_mechanical_qa
from shumozizi.qa.aggregator import run_submission_qa
from shumozizi.workflow.initialization import initialize_run

REPO_ROOT = Path(__file__).resolve().parents[1]


class ProfileTests(unittest.TestCase):
    """所有内置 Profile 必须有明确规则状态和机械检查配置。"""

    def test_builtin_profiles_validate(self) -> None:
        """Profile JSON 应显式声明规则来源或确认警告。"""
        for path in sorted((REPO_ROOT / "profiles").glob("*.json")):
            with self.subTest(profile=path.name):
                profile = json.loads(path.read_text(encoding="utf-8"))
                require_valid(profile, "competition_profile")
                self.assertEqual(path.stem, profile["profile_id"])
                if profile["rules_status"] == "official-confirmation-required":
                    self.assertTrue(profile["warnings"])

    def test_config_lock_rejects_profile_tampering(self) -> None:
        """锁定后改动 Profile 必须让统一配置复验失败。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(REPO_ROOT / "profiles", root / "profiles")
            (root / ".shumozizi-root").touch()
            (root / ".git").mkdir()
            problem = root / "problem.md"
            problem.write_text("固定题面\n", encoding="utf-8")
            run_dir = root / "runs" / "profile-test"
            (run_dir / "config").mkdir(parents=True)
            create_run_config_lock(root, run_dir, problem)
            profile = root / "profiles" / "generic.json"
            payload = json.loads(profile.read_text(encoding="utf-8"))
            payload["warnings"].append("tampered")
            profile.write_text(json.dumps(payload), encoding="utf-8")

            from shumozizi.profiles.lock import verify_run_config_lock

            with self.assertRaisesRegex(ContractError, "哈希已变化"):
                verify_run_config_lock(root, run_dir)


class AdapterTests(unittest.TestCase):
    """验证 C1/C2 Adapter 的硬失败项汇入统一 QA。"""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "repo"
        shutil.copytree(REPO_ROOT / "profiles", self.root / "profiles")
        shutil.copytree(REPO_ROOT / "schemas", self.root / "schemas")
        (self.root / ".shumozizi-root").touch()
        (self.root / ".git").mkdir()
        problem = self.root / "problem.md"
        problem.write_text("固定题面\n", encoding="utf-8")
        self.run_dir = initialize_run(self.root, problem, "adapter-test", mode="audit")
        paper = self.run_dir / "paper"
        paper.mkdir(exist_ok=True)
        (paper / "main.typ").write_text(
            '#import "generated/evidence_values.typ": evidence\n#evidence("C1")\n',
            encoding="utf-8",
        )
        atomic_json(
            paper / "evidence_map.json",
            {
                "schema_name": "evidence_map",
                "schema_version": "2.0",
                "run_id": self.run_dir.name,
                "claims": [
                    {
                        "claim_id": "C1",
                        "inputs": [{"name": "a", "result_id": "missing", "metric_spec_id": "m"}],
                        "expression": None,
                        "display": {"decimals": 2, "unit": "kg"},
                        "core": True,
                    }
                ],
            },
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_evidence_adapter_rejects_missing_result(self) -> None:
        """证据输入不存在时必须阻断，而不是信任手写展示值。"""
        report = audit_paper_evidence(self.run_dir, self.run_dir / "paper/final.pdf")

        self.assertEqual("blocked", report["status"])
        self.assertTrue(any("输入无效" in error for error in report["errors"]))

    def test_mechanical_adapter_detects_duplicate_caption_and_anonymity(self) -> None:
        """Profile 规则命中的重复 caption 与身份字段必须硬失败。"""
        pdf = self.run_dir / "paper/final.pdf"
        source = self.run_dir / "paper/source.typ"
        source.write_text(
            '#set document(author: "Alice")\nFigure 1: one\nFigure 1: duplicate\n',
            encoding="utf-8",
        )
        subprocess.run(
            ["typst", "compile", str(source), str(pdf)],
            cwd=source.parent,
            check=True,
            capture_output=True,
            text=True,
        )

        report = run_mechanical_qa(self.run_dir.name, pdf)

        self.assertEqual("blocked", report["status"])
        self.assertTrue(any("重复 caption" in error for error in report["errors"]))

    def test_aggregator_contains_adapter_checks(self) -> None:
        """统一 QA 报告必须包含两个 Adapter 的结果。"""
        report = run_submission_qa(self.run_dir.name, self.run_dir / "paper/final.pdf")
        check_ids = {item["check_id"] for item in report["checks"]}

        self.assertIn("paper-evidence-adapter", check_ids)
        self.assertIn("mechanical-qa-adapter", check_ids)
        self.assertEqual("blocked", report["status"])


if __name__ == "__main__":
    unittest.main()
