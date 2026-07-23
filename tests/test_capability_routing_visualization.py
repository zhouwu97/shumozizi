"""验证能力路由、图表合同和完整模板是实际生产门禁。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from shumozizi.core.io import ContractError, atomic_json, load_json
from shumozizi.paper.templates import (
    materialize_selected_template,
    require_materialized_template,
    select_paper_template,
)
from shumozizi.simple.capabilities import (
    require_capability_route,
    require_independent_oracle_execution,
    write_capability_route,
    write_local_tooling,
)
from shumozizi.simple.execution import execute_simple_experiment
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.state import read_simple_state, update_simple_state, utc_now
from shumozizi.simple.visualization import (
    new_visualization_plan,
    require_visualization_complete,
    write_visualization_plan,
)
from tests.quality_protocol_helpers import record_passing_scientific_review


class CapabilityRoutingVisualizationTests(unittest.TestCase):
    """覆盖三条能力链的关键阻断和篡改检测边界。"""

    def setUp(self) -> None:
        """建立独立的最小 v3 运行。"""
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        """删除测试运行目录。"""
        self.temporary.cleanup()

    @staticmethod
    def _route_payload(run_dir: Path, families: list[str]) -> dict[str, object]:
        """构造可执行且不共享源码的最小能力路由。"""
        return {
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "status": "ready",
            "problem_families": families,
            "primary_capability": {
                "id": "geometry-modeling" if "geometry_kinematics" in families else "general-modeling",
                "reason": "测试运行冻结当前题的主要建模与数值风险。",
            },
            "cross_capabilities": [
                {
                    "id": "nonsmooth-optimization",
                    "reason": "搜索诊断需要识别事件边界和代理失真风险。",
                }
            ]
            if "optimization" in families
            else [],
            "verification_capability": {
                "id": "independent-geometry-oracle",
                "reason": "使用独立公式与未共享的领域判定实现复算边界。",
            }
            if "geometry_kinematics" in families
            else None,
            "toolchain": {
                "production_engine": "python",
                "independent_engine": None,
                "independence_strategy": "alternative_formulation"
                if "geometry_kinematics" in families
                else "not_required",
                "reason": "生产与验证路径按冻结能力路由执行，避免虚构不可用工具。",
            },
            "knowledge_assets": [
                {
                    "path": "knowledge/cards/structural-preflight.json",
                    "purpose": "用于在实现前检查输入、单位、退化情形和小规模反例。",
                }
            ],
            "created_at": utc_now(),
        }

    def _enter_experiment(self, run_dir: Path, families: list[str]) -> None:
        """登记受控路由并进入实验阶段。"""
        update_simple_state(run_dir, phase="capability_route")
        write_local_tooling(run_dir)
        write_capability_route(run_dir, self._route_payload(run_dir, families))
        update_simple_state(run_dir, phase="experiment")

    def _enter_visualization(self, run_dir: Path) -> None:
        """通过隔离科学审查后进入可视化阶段。"""
        (run_dir / "problem" / "statement.md").write_text("最小题面", encoding="utf-8")
        (run_dir / "code" / "solver.py").write_text("print('solver')\n", encoding="utf-8")
        (run_dir / "results" / "raw" / "candidate.json").write_text(
            json.dumps({"objective": 1.0}), encoding="utf-8"
        )
        self._record_independent_oracle(run_dir)
        record_passing_scientific_review(run_dir)
        update_simple_state(run_dir, phase="visualization")

    @staticmethod
    def _record_independent_oracle(run_dir: Path) -> None:
        """写入真实执行的独立 oracle 夹具，而非伪造状态字段。"""
        script = run_dir / "code" / "independent_oracle.py"
        script.write_text(
            "import json\n"
            "from pathlib import Path\n"
            "Path('results/raw/independent_oracle.json').write_text(\n"
            "    json.dumps({'metrics': {'oracle_cases_checked': 3}}), encoding='utf-8'\n"
            ")\n",
            encoding="utf-8",
        )
        execute_simple_experiment(
            run_dir,
            result_id="independent-oracle",
            question_id="shared",
            kind="independent-oracle",
            command=f'"{sys.executable}" code/independent_oracle.py',
            expected_outputs=["results/raw/independent_oracle.json"],
            metrics_from="results/raw/independent_oracle.json",
        )

    def _complete_visualization(self, run_dir: Path) -> dict[str, object]:
        """建立几何、优化和路线图的最小冻结 Figure Contract。"""
        source = run_dir / "state" / "DECISIONS.md"
        script = run_dir / "code" / "figures" / "render.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("# 可复现测试图生成器\n", encoding="utf-8")
        roles = [
            "spatial_scene",
            "geometric_boundary",
            "optimization_convergence",
            "optimization_diagnostic",
            "method_roadmap",
        ]
        contracts: list[dict[str, object]] = []
        for role in roles:
            output = run_dir / "figures" / f"{role}.png"
            Image.new("RGB", (320, 240), color=(30, 90, 140)).save(output)
            contracts.append(
                {
                    "figure_id": role,
                    "role": role,
                    "question_id": "shared",
                    "purpose": f"为 {role} 提供模型结构或搜索充分性的可复验视觉证据。",
                    "evidence_scope": "model"
                    if role in {"spatial_scene", "geometric_boundary", "method_roadmap"}
                    else "search_diagnostic",
                    "source_paths": [source.relative_to(run_dir).as_posix()],
                    "rendering_mode": "3d" if role == "spatial_scene" else "2d",
                    "status": "complete",
                    "outputs": [output.relative_to(run_dir).as_posix()],
                    "generator": {
                        "engine": "python",
                        "script_path": script.relative_to(run_dir).as_posix(),
                    },
                    "rationale": "该图直接回答模型边界、搜索过程或多问方法衔接的论证问题。",
                }
            )
        return write_visualization_plan(run_dir, new_visualization_plan(run_dir, contracts))

    def test_geometry_route_requires_independent_oracle(self) -> None:
        """几何题未声明独立验证能力时不能进入实验。"""
        run_dir = initialize_simple_run(self.root, "missing-oracle")
        update_simple_state(run_dir, phase="capability_route")
        write_local_tooling(run_dir)
        payload = self._route_payload(run_dir, ["geometry_kinematics"])
        payload["verification_capability"] = None

        with self.assertRaisesRegex(ContractError, "独立 oracle"):
            write_capability_route(run_dir, payload)

    def test_geometry_route_requires_executed_oracle_before_scientific_review(self) -> None:
        """独立 oracle 不能只在能力路由中声明而未真实执行。"""
        run_dir = initialize_simple_run(self.root, "unexecuted-oracle")
        self._enter_experiment(run_dir, ["geometry_kinematics"])

        with self.assertRaisesRegex(ContractError, "实际运行 independent-oracle"):
            update_simple_state(run_dir, phase="scientific_review")

        self._record_independent_oracle(run_dir)
        self.assertEqual(
            "scientific_review",
            update_simple_state(run_dir, phase="scientific_review")["phase"],
        )

    def test_oracle_cannot_reuse_production_source_script(self) -> None:
        """同一源码换为 oracle 标签不能伪造独立实现。"""
        run_dir = initialize_simple_run(self.root, "shared-oracle-source")
        self._enter_experiment(run_dir, ["geometry_kinematics"])
        self._record_independent_oracle(run_dir)
        execute_simple_experiment(
            run_dir,
            result_id="primary-shared-source",
            question_id="shared",
            kind="primary",
            command=f'"{sys.executable}" code/independent_oracle.py',
            expected_outputs=["results/raw/independent_oracle.json"],
            metrics_from="results/raw/independent_oracle.json",
        )

        with self.assertRaisesRegex(ContractError, "未与生产求解复用"):
            require_independent_oracle_execution(run_dir)

    def test_tooling_and_knowledge_receipts_cannot_drift_after_routing(self) -> None:
        """工具或本地知识变化后，旧能力路由不得继续解锁实验。"""
        run_dir = initialize_simple_run(self.root, "receipt-drift")
        self._enter_experiment(run_dir, ["other"])
        tooling_path = run_dir / "state" / "tooling.json"
        tooling = load_json(tooling_path)
        tooling["engines"][0]["available"] = not tooling["engines"][0]["available"]
        atomic_json(tooling_path, tooling)

        with self.assertRaisesRegex(ContractError, "工具探测记录已漂移"):
            require_capability_route(run_dir)

    def test_visualization_freezes_output_input_and_generator(self) -> None:
        """完成图的输出、输入和生成脚本任一漂移都必须阻断论文。"""
        run_dir = initialize_simple_run(
            self.root,
            "visual-receipts",
            required_questions=["Q1", "Q2"],
        )
        self._enter_experiment(run_dir, ["geometry_kinematics", "optimization"])
        self._enter_visualization(run_dir)
        plan = self._complete_visualization(run_dir)
        require_visualization_complete(run_dir)

        output = run_dir / plan["contracts"][0]["outputs"][0]["path"]
        output.write_bytes(b"tampered-output")
        with self.assertRaisesRegex(ContractError, "输出哈希"):
            require_visualization_complete(run_dir)

        self._complete_visualization(run_dir)
        script = run_dir / "code" / "figures" / "render.py"
        script.write_text("# 被改写的图生成器\n", encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "生成脚本哈希"):
            require_visualization_complete(run_dir)

        self._complete_visualization(run_dir)
        (run_dir / "state" / "DECISIONS.md").write_text("# 被改写的证据\n", encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "输入哈希"):
            require_visualization_complete(run_dir)

    def test_complete_visualization_rejects_non_image_png(self) -> None:
        """文件扩展名不能替代真实图像内容。"""
        run_dir = initialize_simple_run(
            self.root,
            "invalid-visual-output",
            required_questions=["Q1", "Q2"],
        )
        self._enter_experiment(run_dir, ["geometry_kinematics", "optimization"])
        self._enter_visualization(run_dir)
        plan = self._complete_visualization(run_dir)
        output = run_dir / plan["contracts"][0]["outputs"][0]["path"]
        output.write_bytes(b"not-a-png")

        with self.assertRaisesRegex(ContractError, "PNG 无法通过可读性检查"):
            write_visualization_plan(run_dir, plan)

    def test_geometry_requires_3d_scene_and_optimization_requires_search_evidence(self) -> None:
        """图表角色不得以二维示意或模型说明冒充空间/搜索证据。"""
        run_dir = initialize_simple_run(
            self.root,
            "visual-role-semantics",
            required_questions=["Q1", "Q2"],
        )
        self._enter_experiment(run_dir, ["geometry_kinematics", "optimization"])
        self._enter_visualization(run_dir)
        plan = self._complete_visualization(run_dir)

        spatial = next(item for item in plan["contracts"] if item["role"] == "spatial_scene")
        spatial["rendering_mode"] = "2d"
        with self.assertRaisesRegex(ContractError, "3d 空间场景图"):
            write_visualization_plan(run_dir, plan)

        spatial["rendering_mode"] = "3d"
        diagnostic = next(
            item for item in plan["contracts"] if item["role"] == "optimization_diagnostic"
        )
        diagnostic["evidence_scope"] = "model"
        with self.assertRaisesRegex(ContractError, "search_diagnostic"):
            write_visualization_plan(run_dir, plan)

    def test_paper_requires_materialized_known_competition_template(self) -> None:
        """写作只能使用已实例化的完整模板，未知赛事不得默认降级。"""
        run_dir = initialize_simple_run(
            self.root,
            "template-gate",
            competition="全国大学生数学建模竞赛",
            required_questions=["Q1", "Q2"],
        )
        self._enter_experiment(run_dir, ["geometry_kinematics", "optimization"])
        self._enter_visualization(run_dir)
        self._complete_visualization(run_dir)

        with self.assertRaisesRegex(ContractError, "缺少论文模板清单"):
            update_simple_state(run_dir, phase="paper")

        manifest = select_paper_template(
            run_dir,
            language="zh",
            engine="typst",
            selection_reason="全国赛中文稿必须使用仓内完整 Typst 模板，不允许默认降级。",
        )
        self.assertEqual("zh/cumcm", manifest["template_id"])
        materialize_selected_template(run_dir)
        require_materialized_template(run_dir)
        self.assertEqual("paper", update_simple_state(run_dir, phase="paper")["phase"])

        unknown = initialize_simple_run(self.root, "unknown-template", competition="unlisted-contest")
        with self.assertRaisesRegex(ContractError, "未识别比赛类型"):
            select_paper_template(
                unknown,
                language="en",
                engine="typst",
                selection_reason="未知比赛不得静默选择默认模板，必须由用户补充模板映射。",
            )

    def test_missing_route_blocks_experiment_with_contract_error(self) -> None:
        """没有 route 文件时状态机应给出合同错误而非底层文件异常。"""
        run_dir = initialize_simple_run(self.root, "missing-route")
        update_simple_state(run_dir, phase="capability_route")

        with self.assertRaisesRegex(ContractError, "缺少能力路由"):
            update_simple_state(run_dir, phase="experiment")

        self.assertEqual("capability_route", read_simple_state(run_dir)["phase"])


if __name__ == "__main__":
    unittest.main()
