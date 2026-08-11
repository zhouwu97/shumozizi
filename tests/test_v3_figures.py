"""验证 v3 真实数据图表适配器的输入、追溯与失效行为。"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from scripts.figures import use_template
from scripts.figures.use_template import generate_from_result
from shumozizi.simple.figure_templates import load_data, render
from shumozizi.simple.figures import read_figure_index, verify_current_figure_files
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.quality import assess_result_quality
from tests.quality_protocol_helpers import (
    adapter_backed_assessment,
    record_passing_scientific_review,
    run_synthetic_verification_protocol,
)
from tools.qa.figqa import audit_figure


@unittest.skipUnless(
    importlib.util.find_spec("matplotlib") and importlib.util.find_spec("numpy"),
    "真实绘图测试需要 .[figures] 可选依赖",
)
class V3FigureTests(unittest.TestCase):
    """覆盖全部图库模板的真实 JSON 入口。"""

    def setUp(self) -> None:
        """建立带可追溯 JSON 输出的临时 v3 运行。"""
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.run_dir = initialize_simple_run(self.root, "figure-test")
        payloads = {
            "roc": {
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
                    "groups": [{"name": "处理组", "before": [2, 3, 4, 5], "after": [3, 3.5, 5, 6]}]
                },
            },
            "correlation": {
                "metrics": {"objective": 0.83},
                "figure_data": {
                    "columns": ["x1", "x2", "target"],
                    "values": [[1, 2, 3], [2, 4, 5], [3, 5, 7], [4, 7, 8], [5, 8, 10]],
                },
            },
            "rf_tpe": {
                "figure_data": {
                    "x_label": "最大深度",
                    "y_label": "树数量",
                    "metric_label": "RMSE",
                    "direction": "minimize",
                    "trials": [
                        {"x": 3, "y": 80, "metric": 0.42},
                        {"x": 5, "y": 80, "metric": 0.35},
                        {"x": 7, "y": 80, "metric": 0.39},
                        {"x": 3, "y": 160, "metric": 0.34},
                        {"x": 5, "y": 160, "metric": 0.27},
                        {"x": 7, "y": 160, "metric": 0.31},
                    ],
                }
            },
            "taylor": {
                "figure_data": {
                    "reference_std": 1.0,
                    "panels": [
                        {
                            "title": "留出集",
                            "points": [
                                {"name": "基线", "std": 0.82, "corr": 0.76},
                                {"name": "挑战者", "std": 1.08, "corr": 0.91},
                            ],
                        }
                    ],
                }
            },
            "shap": {
                "figure_data": {
                    "features": ["温度", "湿度"],
                    "classes": ["低风险", "高风险"],
                    "mean_abs_shap": [[0.12, 0.28], [0.19, 0.11]],
                    "beeswarm": [
                        {
                            "feature": "温度",
                            "class": "高风险",
                            "shap_values": [-0.2, 0.05, 0.32, 0.4],
                            "feature_values": [12, 19, 27, 31],
                        },
                        {
                            "feature": "湿度",
                            "class": "低风险",
                            "shap_values": [-0.15, -0.04, 0.12, 0.2],
                            "feature_values": [35, 48, 61, 75],
                        },
                    ],
                }
            },
            "grouped_corr": {
                "figure_data": {
                    "features": ["温度", "湿度", "风速"],
                    "groups": [
                        {
                            "name": "训练集",
                            "values": [[12, 40, 1.2], [18, 52, 1.8], [23, 61, 2.3]],
                        },
                        {
                            "name": "留出集",
                            "values": [[14, 43, 1.4], [20, 55, 2.0], [25, 64, 2.5]],
                        },
                    ],
                }
            },
            "circular": {
                "figure_data": {
                    "items": ["方案甲", "方案乙", "方案丙", "方案丁"],
                    "rings": [
                        {"name": "效率", "values": [0.72, 0.81, 0.68, 0.76]},
                        {"name": "稳定性", "values": [0.63, 0.74, 0.88, 0.79]},
                    ],
                }
            },
            "chord": {
                "figure_data": {
                    "nodes": [
                        {"id": "a", "label": "供给端", "group": "供给"},
                        {"id": "b", "label": "中转端", "group": "中转"},
                        {"id": "c", "label": "需求端", "group": "需求"},
                    ],
                    "links": [
                        {"source": "a", "target": "b", "weight": 12},
                        {"source": "b", "target": "c", "weight": 9},
                    ],
                }
            },
            "composition_combo": {
                "figure_data": {
                    "categories": ["区域甲", "区域乙", "区域丙"],
                    "components": [
                        {"name": "绿地", "values": [0.45, 0.38, 0.51]},
                        {"name": "水体", "values": [0.18, 0.24, 0.15]},
                    ],
                    "metrics": [
                        {
                            "name": "降温强度",
                            "groups": [
                                {"name": "小型", "values": [0.8, 1.0, 1.1]},
                                {"name": "大型", "values": [1.5, 1.7, 1.9]},
                            ],
                        }
                    ],
                }
            },
        }
        fixture_root = Path(__file__).parent / "fixtures" / "figures"
        for key, filename in {
            "feasible": "feasible-region-active-constraints.json",
            "timeline": "interval-event-timeline.json",
            "uncertainty": "uncertainty-fan-threshold.json",
            "evidence_chain": "multi-panel-evidence-chain.json",
        }.items():
            payloads[key] = json.loads((fixture_root / filename).read_text(encoding="utf-8"))
        protocol = run_synthetic_verification_protocol(
            self.run_dir,
            result_id="q1_visual",
            question_id="Q1",
            objective=0.83,
            artifact_payloads=payloads,
        )
        assessment = assess_result_quality(
            self.run_dir,
            result_id="q1_visual",
            assessment=adapter_backed_assessment(protocol),
        )
        self.assertTrue(assessment["paper_allowed"])
        record_passing_scientific_review(self.run_dir)
        self.figure_inputs = protocol["paths"]["artifacts"]

    def tearDown(self) -> None:
        """清理临时运行目录。"""
        self.temporary.cleanup()

    def test_real_json_templates_generate_traceable_outputs(self) -> None:
        """十五类模板应读取真实结果、输出三种格式并进入图表索引。"""
        template_inputs = {
            "cv-roc-ci": self.figure_inputs["roc"],
            "prediction-marginal-grid": self.figure_inputs["prediction"],
            "paired-raincloud": self.figure_inputs["paired"],
            "correlation-pairgrid": self.figure_inputs["correlation"],
            "feasible-region-active-constraints": self.figure_inputs["feasible"],
            "interval-event-timeline": self.figure_inputs["timeline"],
            "uncertainty-fan-threshold": self.figure_inputs["uncertainty"],
            "multi-panel-evidence-chain": self.figure_inputs["evidence_chain"],
            "rf-tpe-surface": self.figure_inputs["rf_tpe"],
            "taylor-diagram": self.figure_inputs["taylor"],
            "multiclass-shap-combo": self.figure_inputs["shap"],
            "grouped-corr-split-violin": self.figure_inputs["grouped_corr"],
            "grouped-circular-heatmap": self.figure_inputs["circular"],
            "nature-chord-diagram": self.figure_inputs["chord"],
            "urban-park-cooling-combo": self.figure_inputs["composition_combo"],
        }
        for template_id, input_result in template_inputs.items():
            generated = generate_from_result(
                self.run_dir,
                template_id=template_id,
                result_id="q1_visual",
                input_result=input_result,
                output_prefix=f"figures/current/{template_id}",
            )
            self.assertTrue(generated["success"])
            for output in generated["outputs"]:
                self.assertGreater((self.run_dir / output).stat().st_size, 0)
            self.assertTrue((self.run_dir / generated["visual_manifest"]).is_file())
        index = read_figure_index(self.run_dir)
        self.assertEqual(15, len(index["figures"]))
        self.assertTrue(
            all(not item["demo"] and item["paper_allowed"] for item in index["figures"])
        )
        self.assertTrue(all(item["figure_stage"] == "current" for item in index["figures"]))
        self.assertTrue(
            all(item["visual_archetype"] == item["template_id"] for item in index["figures"])
        )
        verification = verify_current_figure_files(self.run_dir)
        self.assertTrue(verification["success"], verification["errors"])

    def test_production_catalog_is_derived_from_supported_templates(self) -> None:
        """机器目录必须覆盖真实 renderer，并只引用存在的参考脚本和预览。"""
        catalog = use_template.template_catalog_payload()

        self.assertEqual(set(use_template.SUPPORTED_TEMPLATES), {
            item["template_id"] for item in catalog["templates"]
        })
        for item in catalog["templates"]:
            self.assertTrue(item["renderer_available"])
            self.assertTrue((use_template.REPO_ROOT / item["reference_script"]).is_file())
            if item["preview"] is not None:
                self.assertTrue((use_template.REPO_ROOT / item["preview"]).is_file())

    def test_catalog_explains_selection_boundaries_and_preview_fidelity(self) -> None:
        """图库卡片必须说明适用边界、证据角色、宽度和预览保真度。"""
        catalog = use_template.template_catalog_payload()
        required = {
            "use_when",
            "avoid_when",
            "evidence_role",
            "required_data_summary",
            "min_paper_width_cm",
            "preview_fidelity",
            "adaptation_level",
            "grayscale_readability",
        }
        for item in catalog["templates"]:
            self.assertTrue(required.issubset(item))
            self.assertGreater(item["min_paper_width_cm"], 0)
            self.assertTrue(item["use_when"])
            self.assertTrue(item["avoid_when"])
        chord = next(
            item for item in catalog["templates"]
            if item["template_id"] == "nature-chord-diagram"
        )
        self.assertEqual("preview_grade", chord["preview_fidelity"])
        self.assertEqual("conditional", chord["grayscale_readability"])
        prediction = next(
            item for item in catalog["templates"]
            if item["template_id"] == "prediction-marginal-grid"
        )
        self.assertEqual("needs_visual_refinement", prediction["preview_fidelity"])

    def test_model_structure_routes_to_high_value_template_candidates(self) -> None:
        """常见建模结构应路由到可解释的高级图候选，而非固定每问一图。"""
        expected = {
            "optimization": "feasible-region-active-constraints",
            "uncertainty": "uncertainty-fan-threshold",
            "classification": "cv-roc-ci",
            "distribution": "paired-raincloud",
            "network": "nature-chord-diagram",
            "flow": "nature-chord-diagram",
            "temporal": "interval-event-timeline",
        }
        for structure, template_id in expected.items():
            recommendation = use_template.recommend_template_candidates(structure)
            self.assertTrue(recommendation["advisory_only"])
            self.assertIn(template_id, [item["template_id"] for item in recommendation["candidates"]])
            self.assertIn("论文主线", recommendation["selection_rule"])
            self.assertTrue(all(
                item["preview_fidelity"] != "needs_visual_refinement"
                for item in recommendation["candidates"]
            ))
        classification = use_template.recommend_template_candidates("classification")
        self.assertIn(
            "multiclass-shap-combo",
            [item["template_id"] for item in classification["refinement_queue"]],
        )

    def test_structural_fixture_interfaces_render_all_formats(self) -> None:
        """四个结构 renderer 的冻结 JSON fixture 均应通过验证并成图。"""
        fixture_root = Path(__file__).parent / "fixtures" / "figures"
        for template_id in (
            "feasible-region-active-constraints",
            "interval-event-timeline",
            "uncertainty-fan-threshold",
            "multi-panel-evidence-chain",
        ):
            fixture = fixture_root / f"{template_id}.json"
            data = load_data(template_id, fixture)
            stem = self.root / "fixture-renders" / template_id
            boxes = render(template_id, data, stem)
            self.assertTrue(boxes.is_file())
            manifest = json.loads(
                stem.with_suffix(".visual_manifest.json").read_text(encoding="utf-8")
            )
            self.assertTrue(manifest["elements"])
            self.assertEqual(
                {item["label"] for item in manifest["elements"]},
                set(manifest["labels"]),
            )
            for suffix in (".png", ".pdf", ".svg"):
                self.assertGreater(stem.with_suffix(suffix).stat().st_size, 0)

    def test_v34_canonical_archetypes_use_real_renderer_contracts(self) -> None:
        """v3.4 高价值 archetype ID 应直接消费公开数据接口并真实出图。"""
        fixture_root = Path(__file__).parent / "fixtures" / "figures"
        aliases = {
            "active_constraint_map": "feasible-region-active-constraints.json",
            "constraint_margin_timeline": "constraint_margin_timeline.json",
            "uncertainty_threshold_ribbon": "uncertainty-fan-threshold.json",
            "model_evolution_schematic": "model_evolution_schematic.json",
            "argument_evidence_map": "argument_evidence_map.json",
        }
        for template_id, fixture_name in aliases.items():
            data = load_data(template_id, fixture_root / fixture_name)
            stem = self.root / "v34-renders" / template_id
            render(template_id, data, stem)
            self.assertGreater(stem.with_suffix(".png").stat().st_size, 0)
            self.assertTrue(stem.with_suffix(".visual_manifest.json").is_file())

    def test_rf_tpe_surface_uses_registered_trial_data(self) -> None:
        """TPE 曲面必须由真实试验点插值，并标出当前最优试验。"""
        payload = {
            "x_label": "最大深度",
            "y_label": "树数量",
            "metric_label": "RMSE",
            "direction": "minimize",
            "trials": [
                {"x": 3, "y": 80, "metric": 0.42},
                {"x": 5, "y": 80, "metric": 0.35},
                {"x": 7, "y": 80, "metric": 0.39},
                {"x": 3, "y": 160, "metric": 0.34},
                {"x": 5, "y": 160, "metric": 0.27},
                {"x": 7, "y": 160, "metric": 0.31},
                {"x": 3, "y": 240, "metric": 0.38},
                {"x": 5, "y": 240, "metric": 0.30},
                {"x": 7, "y": 240, "metric": 0.36},
            ],
        }
        input_path = self.root / "rf-tpe.json"
        input_path.write_text(json.dumps({"figure_data": payload}), encoding="utf-8")

        data = load_data("rf-tpe-surface", input_path)
        self.assertEqual({"x": 5.0, "y": 160.0, "metric": 0.27}, data["best_trial"])
        stem = self.root / "fixture-renders" / "rf-tpe-surface"
        render("rf-tpe-surface", data, stem)

        for suffix in (".png", ".pdf", ".svg"):
            self.assertGreater(stem.with_suffix(suffix).stat().st_size, 0)
        manifest = json.loads(
            stem.with_suffix(".visual_manifest.json").read_text(encoding="utf-8")
        )
        self.assertIn("当前最优", manifest["labels"])

    def test_taylor_diagram_uses_registered_model_statistics(self) -> None:
        """泰勒图必须使用结果中登记的标准差与相关系数。"""
        input_path = self.root / "taylor.json"
        input_path.write_text(
            json.dumps(
                {
                    "figure_data": {
                        "reference_std": 1.0,
                        "panels": [
                            {
                                "title": "留出集",
                                "points": [
                                    {"name": "基线", "std": 0.82, "corr": 0.76},
                                    {"name": "挑战者", "std": 1.08, "corr": 0.91},
                                ],
                            }
                        ],
                    }
                }
            ),
            encoding="utf-8",
        )

        data = load_data("taylor-diagram", input_path)
        stem = self.root / "fixture-renders" / "taylor-diagram"
        render("taylor-diagram", data, stem)

        manifest = json.loads(
            stem.with_suffix(".visual_manifest.json").read_text(encoding="utf-8")
        )
        self.assertIn("参考", manifest["labels"])
        self.assertIn("挑战者", manifest["labels"])

    def test_multiclass_shap_combo_requires_aggregate_and_sample_evidence(self) -> None:
        """多分类 SHAP 组合图同时消费聚合重要性和逐样本贡献。"""
        payload = {
            "features": ["温度", "湿度"],
            "classes": ["低风险", "高风险"],
            "mean_abs_shap": [[0.12, 0.28], [0.19, 0.11]],
            "beeswarm": [
                {
                    "feature": "温度",
                    "class": "高风险",
                    "shap_values": [-0.2, 0.05, 0.32, 0.4],
                    "feature_values": [12, 19, 27, 31],
                },
                {
                    "feature": "湿度",
                    "class": "低风险",
                    "shap_values": [-0.15, -0.04, 0.12, 0.2],
                    "feature_values": [35, 48, 61, 75],
                },
            ],
        }
        input_path = self.root / "multiclass-shap.json"
        input_path.write_text(json.dumps({"figure_data": payload}), encoding="utf-8")

        data = load_data("multiclass-shap-combo", input_path)
        stem = self.root / "fixture-renders" / "multiclass-shap-combo"
        render("multiclass-shap-combo", data, stem)

        manifest = json.loads(
            stem.with_suffix(".visual_manifest.json").read_text(encoding="utf-8")
        )
        self.assertIn("高风险", manifest["labels"])
        self.assertIn("温度", manifest["labels"])

    def test_grouped_corr_split_violin_computes_from_group_observations(self) -> None:
        """相关矩阵和分组分布必须来自同一组登记观测。"""
        payload = {
            "features": ["温度", "湿度", "风速"],
            "groups": [
                {
                    "name": "训练集",
                    "values": [[12, 40, 1.2], [18, 52, 1.8], [23, 61, 2.3], [28, 68, 2.9]],
                },
                {
                    "name": "留出集",
                    "values": [[14, 43, 1.4], [20, 55, 2.0], [25, 64, 2.5], [30, 72, 3.1]],
                },
            ],
        }
        input_path = self.root / "grouped-corr.json"
        input_path.write_text(json.dumps({"figure_data": payload}), encoding="utf-8")

        data = load_data("grouped-corr-split-violin", input_path)
        stem = self.root / "fixture-renders" / "grouped-corr-split-violin"
        render("grouped-corr-split-violin", data, stem)

        manifest = json.loads(
            stem.with_suffix(".visual_manifest.json").read_text(encoding="utf-8")
        )
        self.assertIn("训练集", manifest["labels"])
        self.assertIn("留出集", manifest["labels"])

    def test_grouped_circular_heatmap_uses_item_by_ring_matrix(self) -> None:
        """环形热图必须消费项目与指标环对齐的真实矩阵。"""
        payload = {
            "items": ["方案甲", "方案乙", "方案丙", "方案丁"],
            "rings": [
                {"name": "效率", "values": [0.72, 0.81, 0.68, 0.76]},
                {"name": "稳定性", "values": [0.63, 0.74, 0.88, 0.79]},
            ],
        }
        input_path = self.root / "circular-heatmap.json"
        input_path.write_text(json.dumps({"figure_data": payload}), encoding="utf-8")

        data = load_data("grouped-circular-heatmap", input_path)
        stem = self.root / "fixture-renders" / "grouped-circular-heatmap"
        render("grouped-circular-heatmap", data, stem)

        manifest = json.loads(
            stem.with_suffix(".visual_manifest.json").read_text(encoding="utf-8")
        )
        self.assertIn("效率", manifest["labels"])
        self.assertIn("稳定性", manifest["labels"])

    def test_chord_diagram_uses_registered_weighted_links(self) -> None:
        """和弦图必须使用已登记节点和正权重关系，不得随机造边。"""
        payload = {
            "nodes": [
                {"id": "a", "label": "供给端", "group": "供给"},
                {"id": "b", "label": "中转端", "group": "中转"},
                {"id": "c", "label": "需求端", "group": "需求"},
            ],
            "links": [
                {"source": "a", "target": "b", "weight": 12},
                {"source": "b", "target": "c", "weight": 9},
                {"source": "a", "target": "c", "weight": 4},
            ],
        }
        input_path = self.root / "chord.json"
        input_path.write_text(json.dumps({"figure_data": payload}), encoding="utf-8")

        data = load_data("nature-chord-diagram", input_path)
        stem = self.root / "fixture-renders" / "nature-chord-diagram"
        render("nature-chord-diagram", data, stem)

        manifest = json.loads(
            stem.with_suffix(".visual_manifest.json").read_text(encoding="utf-8")
        )
        self.assertIn("供给端", manifest["labels"])
        self.assertIn("需求端", manifest["labels"])

    def test_urban_combo_generalizes_to_composition_and_group_distributions(self) -> None:
        """组合图保留数据结构，不把新题强行解释成城市公园。"""
        payload = {
            "categories": ["区域甲", "区域乙", "区域丙"],
            "components": [
                {"name": "绿地", "values": [0.45, 0.38, 0.51]},
                {"name": "水体", "values": [0.18, 0.24, 0.15]},
            ],
            "metrics": [
                {
                    "name": "降温强度",
                    "groups": [
                        {"name": "小型", "values": [0.8, 1.0, 1.1, 1.3]},
                        {"name": "大型", "values": [1.5, 1.7, 1.9, 2.1]},
                    ],
                }
            ],
        }
        input_path = self.root / "composition-combo.json"
        input_path.write_text(json.dumps({"figure_data": payload}), encoding="utf-8")

        data = load_data("urban-park-cooling-combo", input_path)
        stem = self.root / "fixture-renders" / "urban-park-cooling-combo"
        render("urban-park-cooling-combo", data, stem)

        manifest = json.loads(
            stem.with_suffix(".visual_manifest.json").read_text(encoding="utf-8")
        )
        self.assertIn("绿地", manifest["labels"])
        self.assertIn("降温强度", manifest["labels"])

    def test_source_result_supersession_requires_figure_regeneration(self) -> None:
        """源结果被同问同类的新执行替代后，旧图必须阻断最终检查。"""
        generate_from_result(
            self.run_dir,
            template_id="cv-roc-ci",
            result_id="q1_visual",
            input_result=self.figure_inputs["roc"],
            output_prefix="figures/current/q1_roc",
        )
        rerun = run_synthetic_verification_protocol(
            self.run_dir,
            result_id="q1_visual_replacement",
            question_id="Q1",
            objective=0.9,
        )
        self.assertTrue(rerun["success"], rerun.get("error"))
        replacement = assess_result_quality(
            self.run_dir,
            result_id="q1_visual_replacement",
            assessment=adapter_backed_assessment(rerun),
        )
        self.assertTrue(replacement["paper_allowed"])
        verification = verify_current_figure_files(self.run_dir)
        self.assertFalse(verification["success"])
        self.assertIn("源结果已被替代", verification["errors"][0]["message"])

    def test_demo_cannot_be_registered_as_paper_figure(self) -> None:
        """索引 Schema 必须拒绝把演示图伪装成可引用真实图。"""
        generated = generate_from_result(
            self.run_dir,
            template_id="cv-roc-ci",
            result_id="q1_visual",
            input_result=self.figure_inputs["roc"],
            output_prefix="figures/current/q1_roc",
        )
        figure = generated["figure"]
        figure["demo"] = True
        index = read_figure_index(self.run_dir)
        index["figures"] = [figure]
        (self.run_dir / "figures" / "index.json").write_text(json.dumps(index), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "demo"):
            read_figure_index(self.run_dir)

    def test_correlation_pairgrid_wraps_long_field_labels(self) -> None:
        """长字段名应在字段边界换行，避免导出文字框重叠。"""
        output = self.root / "figures" / "long-labels"
        boxes_path = render(
            "correlation-pairgrid",
            {
                "columns": [
                    "uav_index",
                    "bomb_index",
                    "release_time_s",
                    "explosion_time_s",
                    "explosion_altitude_m",
                    "primary_missile_index",
                    "primary_individual_duration_s",
                    "primary_marginal_contribution_s",
                ],
                "values": [
                    [1, 1, 0.1, 2.5, 1771.4, 1, 4.46, 4.46],
                    [1, 2, 1.1, 9.1, 1486.4, 1, 0.0, 0.0],
                    [2, 1, 0.0, 2.0, 1380.4, 1, 0.0, 0.0],
                    [2, 2, 14.8, 22.5, 1113.5, 2, 2.50, 2.50],
                    [3, 3, 17.2, 22.5, 561.3, 3, 2.81, 2.81],
                ],
            },
            output,
        )
        boxes = json.loads(boxes_path.read_text(encoding="utf-8"))["boxes"]
        audit = audit_figure(output.with_suffix(".png"), boxes)

        self.assertFalse(audit["overlaps"], audit["overlaps"])

    def test_frozen_runtime_sources_are_content_addressed(self) -> None:
        """重渲染使用新源码时，不得覆盖此前图表登记的冻结副本。"""
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            template = (
                repository
                / "skills"
                / "mathmodel-figure-templates"
                / "scripts"
                / "templates"
                / "make_correlation_pairgrid.py"
            )
            renderer = repository / "src" / "shumozizi" / "simple" / "figure_templates.py"
            template.parent.mkdir(parents=True)
            renderer.parent.mkdir(parents=True)
            template.write_text("template-v1\n", encoding="utf-8")
            renderer.write_text("renderer-v1\n", encoding="utf-8")

            original_root = use_template.REPO_ROOT
            use_template.REPO_ROOT = repository
            try:
                _, first_renderer = use_template._copy_runtime_sources(
                    self.run_dir, "correlation-pairgrid"
                )
                renderer.write_text("renderer-v2\n", encoding="utf-8")
                _, second_renderer = use_template._copy_runtime_sources(
                    self.run_dir, "correlation-pairgrid"
                )
            finally:
                use_template.REPO_ROOT = original_root

        self.assertNotEqual(first_renderer, second_renderer)
        self.assertEqual(
            "renderer-v1\n", (self.run_dir / first_renderer).read_text(encoding="utf-8")
        )
        self.assertEqual(
            "renderer-v2\n", (self.run_dir / second_renderer).read_text(encoding="utf-8")
        )


if __name__ == "__main__":
    unittest.main()
