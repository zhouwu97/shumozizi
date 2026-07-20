from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from shumozizi.core.io import ContractError, sha256_file
from shumozizi.knowledge.pack import (
    bind_knowledge_pack,
    check_knowledge_leakage,
    verify_bound_knowledge_pack,
)
from shumozizi.profiles.lock import verify_run_config_lock
from shumozizi.workflow.initialization import initialize_run

REPO_ROOT = Path(__file__).resolve().parents[1]


def sample_pack() -> dict:
    return {
        "schema_name": "excellent_paper_knowledge_pack",
        "schema_version": "0.1.0",
        "pack_id": "cumcm-general-core",
        "pack_version": "0.1.0",
        "source_commit": "1234567",
        "generated_at": "2026-07-20T00:00:00Z",
        "applicable_problem_types": ["optimization"],
        "hard_rules": ["禁止数据泄漏"],
        "advisory_patterns": ["先建立评价函数"],
        "anti_patterns": ["复制同题结果"],
        "source_summary": [{"paper_id": "A092", "title": "示例论文", "verification_status": "verified", "provenance_level": "source_verified", "sha256": "a" * 64, "problem_types": ["optimization"]}],
        "leakage_exclusions": [{"paper_id": "A092", "forbidden_tokens": ["A092"]}],
        "cards": [{"card_id": "paper-a092", "title": "示例论文", "paper_id": "A092", "provenance_level": "source_verified", "problem_types": ["optimization"], "core_problem": "示例", "main_value": "示例", "model_route": [], "models": [], "reusable_experience": ["先建立评价函数"], "source_sha256": "a" * 64}],
    }


class KnowledgePackTests(unittest.TestCase):
    def test_checked_in_pack_is_valid(self) -> None:
        pack = json.loads((REPO_ROOT / "knowledge/packs/cumcm-general-core.json").read_text(encoding="utf-8"))
        self.assertEqual("cumcm-general-core", pack["pack_id"])

    def test_bind_and_verify_pack_in_run_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            shutil.copytree(REPO_ROOT / "profiles", root / "profiles")
            shutil.copytree(REPO_ROOT / "schemas", root / "schemas")
            problem = root / "problems" / "sample.md"
            problem.parent.mkdir(parents=True)
            problem.write_text("一个陌生优化题\n", encoding="utf-8")
            pack = root / "pack.json"
            pack.write_text(json.dumps(sample_pack(), ensure_ascii=False), encoding="utf-8")
            run_dir = initialize_run(root, problem, "pack-test", mode="training")
            lock = bind_knowledge_pack(root, run_dir, pack, problem_source=problem)
            self.assertEqual("cumcm-general-core", lock["knowledge_pack"]["pack_id"])
            self.assertEqual(sha256_file(root / "knowledge/packs/cumcm-general-core.json"), lock["knowledge_pack"]["sha256"])
            self.assertEqual("cumcm-general-core", verify_bound_knowledge_pack(root, lock)["pack_id"])
            self.assertEqual("cumcm-general-core", verify_run_config_lock(root, run_dir)["knowledge_pack"]["pack_id"])
            self.assertTrue((run_dir / "config/RUN_CONFIG_LOCK.json").is_file())
            installed = root / "knowledge/packs/cumcm-general-core.json"
            installed.write_bytes(installed.read_bytes() + b"\n")
            with self.assertRaisesRegex(ContractError, "知识包哈希已变化"):
                verify_bound_knowledge_pack(root, lock)

    def test_same_problem_leakage_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            problem = Path(temporary) / "A092_problem.md"
            problem.write_text("官方题面", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "同题资产泄漏"):
                check_knowledge_leakage(sample_pack(), problem)

    def test_same_problem_content_hash_is_rejected_after_rename(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            problem = Path(temporary) / "renamed-attachment.dat"
            problem.write_text("copied source asset", encoding="utf-8")
            pack = sample_pack()
            pack["source_summary"][0]["sha256"] = sha256_file(problem)
            with self.assertRaisesRegex(ContractError, "文件哈希匹配"):
                check_knowledge_leakage(pack, problem)

    def test_problem_directory_rejects_out_of_tree_directory_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            problem = root / "problem"
            problem.mkdir()
            outside = root / "outside"
            outside.mkdir()
            try:
                (problem / "attachments").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"当前平台不允许创建目录 symlink：{exc}")
            with self.assertRaisesRegex(ContractError, "越界符号链接"):
                check_knowledge_leakage(sample_pack(), problem)

if __name__ == "__main__":
    unittest.main()
