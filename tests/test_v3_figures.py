"""验证 v3 真实数据图表适配器的输入、追溯与失效行为。"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.figures.use_template import generate_from_result
from shumozizi.simple.execution import execute_simple_experiment
from shumozizi.simple.figures import read_figure_index, verify_current_figure_files
from shumozizi.simple.initialization import initialize_simple_run


@unittest.skipUnless(
    importlib.util.find_spec("matplotlib") and importlib.util.find_spec("numpy"),
    "真实绘图测试需要 .[figures] 可选依赖",
)
class V3FigureTests(unittest.TestCase):
    """覆盖四类已接入模板的真实 JSON 入口。"""

    def setUp(self) -> None:
        """建立带可追溯 JSON 输出的临时 v3 运行。"""
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.run_dir = initialize_simple_run(self.root, "figure-test")
        script = self.run_dir / "code" / "make_data.py"
        payloads = {
            "roc": {
                "metrics": {"objective": 0.8},
                "figure_data": {
                    "models": [
                        {
                            "name": "基线模型",
                            "folds": [
                                {"fpr": [0, 0.25, 1], "tpr": [0, 0.66, 1]},
                                {"fpr": [0, 0.35, 1], "tpr": [0, 0.73, 1]},
                            ],
                        }
                    ]
                },
            },
            "prediction": {
                "metrics": {"objective": 0.81},
                "figure_data": {
                    "series": [
                        {
                            "name": "Validation",
                            "actual": [1, 2, 3, 4, 5],
                            "predicted": [1.1, 1.9, 2.8, 4.2, 5.1],
                        }
                    ]
                },
            },
            "paired": {
                "metrics": {"objective": 0.82},
                "figure_data": {
                    "groups": [
                        {"name": "处理组", "before": [2, 3, 4, 5], "after": [3, 3.5, 5, 6]}
                    ]
                },
            },
            "correlation": {
                "metrics": {"objective": 0.83},
                "figure_data": {
                    "columns": ["x1", "x2", "target"],
                    "values": [[1, 2, 3], [2, 4, 5], [3, 5, 7], [4, 7, 8], [5, 8, 10]],
                },
            },
        }
        script.write_text(
            "import json\n"
            "from pathlib import Path\n"
            f"payloads = {payloads!r}\n"
            "for name, payload in payloads.items():\n"
            "    Path(f'results/raw/{name}.json').write_text(json.dumps(payload), encoding='utf-8')\n",
            encoding="utf-8",
        )
        execution = execute_simple_experiment(
            self.run_dir,
            result_id="q1_visual",
            question_id="Q1",
            kind="primary",
            command=f'"{sys.executable}" code/make_data.py',
            expected_outputs=[f"results/raw/{item}.json" for item in payloads],
            metrics_from="results/raw/roc.json",
        )
        self.assertTrue(execution["success"], execution["error"])

    def tearDown(self) -> None:
        """清理临时运行目录。"""
        self.temporary.cleanup()

    def test_real_json_templates_generate_traceable_outputs(self) -> None:
        """四类模板应读取真实结果、输出三种格式并进入图表索引。"""
        template_inputs = {
            "cv-roc-ci": "results/raw/roc.json",
            "prediction-marginal-grid": "results/raw/prediction.json",
            "paired-raincloud": "results/raw/paired.json",
            "correlation-pairgrid": "results/raw/correlation.json",
        }
        for template_id, input_result in template_inputs.items():
            generated = generate_from_result(
                self.run_dir,
                template_id=template_id,
                result_id="q1_visual",
                input_result=input_result,
                output_prefix=f"figures/{template_id}",
            )
            self.assertTrue(generated["success"])
            for output in generated["outputs"]:
                self.assertGreater((self.run_dir / output).stat().st_size, 0)
        index = read_figure_index(self.run_dir)
        self.assertEqual(4, len(index["figures"]))
        self.assertTrue(all(not item["demo"] and item["paper_allowed"] for item in index["figures"]))
        verification = verify_current_figure_files(self.run_dir)
        self.assertTrue(verification["success"], verification["errors"])

    def test_source_result_supersession_requires_figure_regeneration(self) -> None:
        """源结果被同问同类的新执行替代后，旧图必须阻断最终检查。"""
        generate_from_result(
            self.run_dir,
            template_id="cv-roc-ci",
            result_id="q1_visual",
            input_result="results/raw/roc.json",
            output_prefix="figures/q1_roc",
        )
        replacement = self.run_dir / "code" / "replace.py"
        replacement.write_text(
            "from pathlib import Path\n"
            "import json\n"
            "Path('results/raw/replacement.json').write_text(json.dumps({'metrics': {'objective': 0.9}}), encoding='utf-8')\n",
            encoding="utf-8",
        )
        rerun = execute_simple_experiment(
            self.run_dir,
            result_id="q1_visual_replacement",
            question_id="Q1",
            kind="primary",
            command=f'"{sys.executable}" code/replace.py',
            expected_outputs=["results/raw/replacement.json"],
            metrics_from="results/raw/replacement.json",
        )
        self.assertTrue(rerun["success"], rerun["error"])
        verification = verify_current_figure_files(self.run_dir)
        self.assertFalse(verification["success"])
        self.assertIn("源结果已被替代", verification["errors"][0]["message"])

    def test_demo_cannot_be_registered_as_paper_figure(self) -> None:
        """索引 Schema 必须拒绝把演示图伪装成可引用真实图。"""
        generated = generate_from_result(
            self.run_dir,
            template_id="cv-roc-ci",
            result_id="q1_visual",
            input_result="results/raw/roc.json",
            output_prefix="figures/q1_roc",
        )
        figure = generated["figure"]
        figure["demo"] = True
        index = read_figure_index(self.run_dir)
        index["figures"] = [figure]
        (self.run_dir / "figures" / "index.json").write_text(
            json.dumps(index), encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "demo"):
            read_figure_index(self.run_dir)


if __name__ == "__main__":
    unittest.main()
