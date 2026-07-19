"""覆盖统一实验执行、证据复验和结果准入的公共行为。"""

from __future__ import annotations

import json
import unittest

from tests.runtime_helpers import RuntimeFixture

WRITER_SCRIPT = """from pathlib import Path
import json
import sys
Path(sys.argv[1]).write_text(json.dumps({"value": 1}), encoding="utf-8")
"""


class RuntimeExecutionTests(unittest.TestCase):
    """验证结果只有在真实执行证据完整时才能被接受。"""

    def setUp(self) -> None:
        self.fixture = RuntimeFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def prepare_success(self, execution_id: str, result_id: str) -> dict:
        """执行一次成功实验并返回候选结果。"""
        script_name = f"{execution_id}.py"
        output_name = f"{execution_id}.json"
        self.fixture.write_script(script_name, WRITER_SCRIPT)
        manifest = self.fixture.manifest(execution_id, script_name, output_name)
        completed = self.fixture.run_executor(manifest)
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        return self.fixture.candidate(result_id, execution_id)

    def test_successful_baseline_can_be_accepted(self) -> None:
        """成功执行、完整指标和检查应形成 accepted 基线。"""
        baseline = self.prepare_success("exec_baseline", "q1_baseline")
        self.fixture.set_results([baseline])

        completed = self.fixture.run_acceptor("q1_baseline")

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        registry = json.loads(
            (self.fixture.run_dir / "results/result_registry.json").read_text(encoding="utf-8")
        )
        self.assertEqual("accepted", registry["results"][0]["status"])
        seal = json.loads(
            (self.fixture.run_dir / registry["results"][0]["result_seal_path"]).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("RFC8785", seal["canonicalization"])

    def test_nonzero_exit_cannot_be_accepted(self) -> None:
        """非零退出即使写出文件也不得准入。"""
        self.fixture.write_script(
            "failure.py",
            WRITER_SCRIPT + "raise SystemExit(7)\n",
        )
        manifest = self.fixture.manifest("exec_failure", "failure.py", "failure.json")
        executed = self.fixture.run_executor(manifest)
        candidate = self.fixture.candidate("q1_failure", "exec_failure")
        self.fixture.set_results([candidate])

        accepted = self.fixture.run_acceptor("q1_failure")

        self.assertNotEqual(0, executed.returncode)
        self.assertNotEqual(0, accepted.returncode)

    def test_missing_expected_output_cannot_be_accepted(self) -> None:
        """退出码为零但缺少预期输出时不得准入。"""
        self.fixture.write_script("no_output.py", "print('done')\n")
        manifest = self.fixture.manifest("exec_missing", "no_output.py", "missing.json")
        executed = self.fixture.run_executor(manifest)
        self.fixture.set_results([self.fixture.candidate("q1_missing", "exec_missing")])

        accepted = self.fixture.run_acceptor("q1_missing")

        self.assertNotEqual(0, executed.returncode)
        self.assertNotEqual(0, accepted.returncode)

    def test_preexisting_output_is_not_reused_as_new_evidence(self) -> None:
        """执行前已有输出时必须拒绝，防止旧结果冒充本次产物。"""
        self.fixture.write_script("stale.py", WRITER_SCRIPT)
        (self.fixture.run_dir / "results/stale.json").write_text(
            '{"value": "old"}\n', encoding="utf-8"
        )
        manifest = self.fixture.manifest("exec_stale", "stale.py", "stale.json")

        completed = self.fixture.run_executor(manifest)

        self.assertNotEqual(0, completed.returncode)
        self.assertIn("旧文件", completed.stdout)

    def test_modified_source_invalidates_execution_record(self) -> None:
        """执行后修改源代码必须使哈希复验失败。"""
        candidate = self.prepare_success("exec_source_hash", "q1_source_hash")
        self.fixture.set_results([candidate])
        self.fixture.write_script("exec_source_hash.py", WRITER_SCRIPT + "print('changed')\n")

        accepted = self.fixture.run_acceptor("q1_source_hash")

        self.assertNotEqual(0, accepted.returncode)
        self.assertIn("哈希不一致", accepted.stdout)

    def test_modified_output_invalidates_execution_record(self) -> None:
        """执行后修改输出必须使哈希复验失败。"""
        candidate = self.prepare_success("exec_output_hash", "q1_output_hash")
        self.fixture.set_results([candidate])
        (self.fixture.run_dir / "results/exec_output_hash.json").write_text(
            '{"value": 999}\n', encoding="utf-8"
        )

        accepted = self.fixture.run_acceptor("q1_output_hash")

        self.assertNotEqual(0, accepted.returncode)
        self.assertIn("哈希不一致", accepted.stdout)

    def test_primary_without_accepted_baseline_is_rejected(self) -> None:
        """主结果不能引用不存在或未接受的基线。"""
        primary = self.prepare_success("exec_primary", "q1_primary")
        primary["cycle"] = "primary"
        primary["baseline_result_id"] = "q1_missing_baseline"
        self.fixture.set_results([primary])

        accepted = self.fixture.run_acceptor("q1_primary")

        self.assertNotEqual(0, accepted.returncode)
        self.assertIn("baseline_result_id", accepted.stdout)

    def test_innovation_without_ablation_evidence_is_rejected(self) -> None:
        """创新主张缺少稳健性或消融结果时不得准入。"""
        baseline = self.prepare_success("exec_baseline", "q1_baseline")
        self.fixture.set_results([baseline])
        baseline_accept = self.fixture.run_acceptor("q1_baseline")
        self.assertEqual(0, baseline_accept.returncode, baseline_accept.stdout)
        accepted_baseline = json.loads(
            (self.fixture.run_dir / "results/result_registry.json").read_text(encoding="utf-8")
        )["results"][0]

        primary = self.prepare_success("exec_innovation", "q1_innovation")
        primary["cycle"] = "primary"
        primary["baseline_result_id"] = "q1_baseline"
        primary["innovation_claims"] = [
            {
                "claim_id": "claim_1",
                "claim": "测试创新主张",
                "evidence": [],
                "status": "keep",
            }
        ]
        self.fixture.set_results([accepted_baseline, primary])

        accepted = self.fixture.run_acceptor("q1_innovation")

        self.assertNotEqual(0, accepted.returncode)
        self.assertIn("innovation_claim_id", accepted.stdout)

    def test_cwd_escape_is_rejected(self) -> None:
        """cwd 不得逃出运行目录。"""
        self.fixture.write_script("escape.py", WRITER_SCRIPT)
        manifest = self.fixture.manifest(
            "exec_cwd_escape", "escape.py", "escape.json", cwd="../outside"
        )

        completed = self.fixture.run_executor(manifest)

        self.assertNotEqual(0, completed.returncode)
        self.assertIn("越过运行目录边界", completed.stdout)

    def test_argument_path_traversal_is_rejected(self) -> None:
        """脚本参数中的目录穿越不得进入子进程。"""
        self.fixture.write_script("traversal.py", WRITER_SCRIPT)
        manifest = self.fixture.manifest("exec_traversal", "traversal.py", "safe.json")
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["args"][1] = "../outside.json"
        self.fixture.write_json("executions/manifests/exec_traversal.json", payload)

        completed = self.fixture.run_executor(manifest)

        self.assertNotEqual(0, completed.returncode)
        self.assertIn("越界路径", completed.stdout)

    def test_timeout_is_recorded_and_rejected(self) -> None:
        """超时必须留下记录，但不能成为 accepted 结果。"""
        self.fixture.write_script(
            "timeout.py",
            "import time\ntime.sleep(2)\n" + WRITER_SCRIPT,
        )
        manifest = self.fixture.manifest(
            "exec_timeout", "timeout.py", "timeout.json", timeout_seconds=1
        )
        executed = self.fixture.run_executor(manifest)
        self.fixture.set_results([self.fixture.candidate("q1_timeout", "exec_timeout")])

        accepted = self.fixture.run_acceptor("q1_timeout")
        record = json.loads(
            (self.fixture.run_dir / "executions/exec_timeout/execution_record.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertNotEqual(0, executed.returncode)
        self.assertTrue(record["timed_out"])
        self.assertNotEqual(0, accepted.returncode)


if __name__ == "__main__":
    unittest.main()
