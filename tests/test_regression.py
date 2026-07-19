"""验证固定条件回归和结果封存的篡改检测。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shumozizi.regression import run_fixed_regression
from shumozizi.results.sealing import verify_sealed_result
from tests.runtime_helpers import RuntimeFixture

REPO_ROOT = Path(__file__).resolve().parents[1]

WRITER_SCRIPT = """from pathlib import Path
import json
import sys
Path(sys.argv[1]).write_text(json.dumps({"value": 1}), encoding="utf-8")
"""


class FixedRegressionTests(unittest.TestCase):
    """固定输入和算法变化必须产生可识别的回归差异。"""

    def test_fixed_regression_passes(self) -> None:
        """版本化夹具的确定性输出应保持不变。"""
        report = run_fixed_regression(REPO_ROOT)

        self.assertEqual("pass", report["status"])
        self.assertEqual([], report["mismatches"])

    def test_fixed_regression_detects_input_tampering(self) -> None:
        """输入文件变化必须在执行算法前被阻断。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "regression").mkdir()
            (root / "tests/fixtures/e2e_linear_fit").mkdir(parents=True)
            (root / "tests/fixtures/e2e_linear_fit/data.csv").write_text(
                "x,y\n0,3.2\n1,4.8\n", encoding="utf-8"
            )
            baseline = json.loads(
                (REPO_ROOT / "regression/fixed_baseline.json").read_text(encoding="utf-8")
            )
            (root / "regression/fixed_baseline.json").write_text(
                json.dumps(baseline), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "输入数据哈希"):
                run_fixed_regression(root)


class SealedTamperTests(unittest.TestCase):
    """封存后修改事实不能被误认为仍可用于论文。"""

    def prepare_success(self, execution_id: str, result_id: str) -> dict:
        """执行一次成功实验并返回候选结果。"""
        script_name = f"{execution_id}.py"
        output_name = f"{execution_id}.json"
        self.fixture.write_script(script_name, WRITER_SCRIPT)
        manifest = self.fixture.manifest(execution_id, script_name, output_name)
        completed = self.fixture.run_executor(manifest)
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        return self.fixture.candidate(result_id, execution_id)

    def setUp(self) -> None:
        self.fixture = RuntimeFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_modified_sealed_result_is_invalid(self) -> None:
        """RFC 8785 seal 应发现任何 accepted 事实改写。"""
        candidate = self.prepare_success("exec_sealed_tamper", "q1_sealed_tamper")
        self.fixture.set_results([candidate])
        accepted = self.fixture.run_acceptor("q1_sealed_tamper")
        self.assertEqual(0, accepted.returncode, accepted.stdout)
        result_path = self.fixture.run_dir / "results/sealed/q1_sealed_tamper.result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["conclusion"] = "tampered"
        result_path.write_text(json.dumps(result), encoding="utf-8")

        report = verify_sealed_result(self.fixture.run_dir, "q1_sealed_tamper")

        self.assertFalse(report["valid"])
        self.assertTrue(any("事实已被修改" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
