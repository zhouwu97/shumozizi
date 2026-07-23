"""验证能力路由、图表合同和完整模板是实际生产门禁。"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from shumozizi.core.io import ContractError, atomic_json, load_json, sha256_file
from shumozizi.paper.templates import (
    materialize_selected_template,
    require_materialized_template,
    select_paper_template,
)
from shumozizi.simple import visualization
from shumozizi.simple.capabilities import (
    record_knowledge_consumption,
    require_capability_route,
    require_independent_oracle_execution,
    write_capability_route,
    write_local_tooling,
)
from shumozizi.simple.execution import execute_simple_experiment
from shumozizi.simple.initialization import initialize_simple_run
from shumozizi.simple.state import read_simple_state, update_simple_state
from shumozizi.simple.visualization import (
    new_visualization_plan,
    require_visualization_complete,
    run_figure_render,
    write_visualization_plan,
)
from tests.quality_protocol_helpers import record_passing_scientific_review


class CapabilityRoutingVisualizationTests(unittest.TestCase):
    """覆盖三条能力链的关键阻断和篡改检测边界。"""

    @classmethod
    def setUpClass(cls) -> None:
        """建立一次真实完成图夹具，供不涉及渲染的合同测试复制使用。"""
        cls.fixture_temporary = tempfile.TemporaryDirectory()
        fixture_root = Path(cls.fixture_temporary.name)
        run_dir = initialize_simple_run(
            fixture_root,
            "completed-visualization",
            competition="全国大学生数学建模竞赛",
            required_questions=["Q1", "Q2"],
        )
        cls._enter_experiment(run_dir, ["geometry_kinematics", "optimization"])
        cls._enter_visualization(run_dir)
        cls._complete_visualization(run_dir)
        cls.fixture_run_dir = run_dir

    @classmethod
    def tearDownClass(cls) -> None:
        """清理一次性真实渲染夹具。"""
        cls.fixture_temporary.cleanup()

    def setUp(self) -> None:
        """建立独立的最小 v3 运行。"""
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        """删除测试运行目录。"""
        self.temporary.cleanup()

    def _completed_visualization_fixture(self) -> Path:
        """复制已冻结的完成图夹具，避免语义测试重复启动渲染进程。"""
        destination = self.root / self.fixture_run_dir.name
        shutil.copytree(self.fixture_run_dir, destination)
        return destination

    @staticmethod
    def _render_output(run_dir: Path, contract: dict[str, object]) -> Path:
        """从真实渲染收据读取首个图表输出，而非相信计划中的手填路径。"""
        reference = contract["render_receipt"]
        receipt_path = reference["path"] if isinstance(reference, dict) else reference
        receipt = load_json(run_dir / str(receipt_path))
        return run_dir / receipt["outputs"][0]["path"]

    @staticmethod
    def _route_payload(run_dir: Path, families: list[str]) -> dict[str, object]:
        """构造可执行且不共享源码的最小能力路由。"""
        payload: dict[str, object] = {
            "schema_version": "1.2",
            "problem_families": families,
            "capabilities": [
                {
                    "id": "geometry-modeling" if "geometry_kinematics" in families else "general-modeling",
                    "reason": "测试运行冻结当前题的主要建模与数值风险。",
                }
            ]
            + (
                [
                    {
                        "id": "nonsmooth-optimization",
                        "reason": "搜索诊断需要识别事件边界和代理失真风险。",
                    }
                ]
                if "optimization" in families
                else []
            ),
            "verification_capability": {
                "id": "independent-geometry-oracle",
                "reason": "使用独立公式与未共享的领域判定实现复算边界。",
            }
            if "geometry_kinematics" in families
            else None,
            "toolchain": {
                "production_engine": "python",
                "independence_strategy": "alternative_formulation"
                if "geometry_kinematics" in families
                else "not_required",
            },
            "knowledge_assets": ["knowledge/cards/structural-preflight.json"],
        }
        if "geometry_kinematics" in families:
            payload["visual_evidence"] = {"spatial_structure_affects_conclusion": True}
        return payload

    @staticmethod
    def _enter_experiment(run_dir: Path, families: list[str]) -> None:
        """登记受控路由并进入实验阶段。"""
        update_simple_state(run_dir, phase="capability_route")
        write_local_tooling(run_dir)
        write_capability_route(run_dir, CapabilityRoutingVisualizationTests._route_payload(run_dir, families))
        record_knowledge_consumption(run_dir)
        update_simple_state(run_dir, phase="experiment")

    @staticmethod
    def _enter_visualization(run_dir: Path) -> None:
        """通过隔离科学审查后进入可视化阶段。"""
        (run_dir / "problem" / "statement.md").write_text("最小题面", encoding="utf-8")
        (run_dir / "code" / "solver.py").write_text("print('solver')\n", encoding="utf-8")
        (run_dir / "results" / "raw" / "candidate.json").write_text(
            json.dumps({"objective": 1.0}), encoding="utf-8"
        )
        CapabilityRoutingVisualizationTests._record_independent_oracle(run_dir)
        record_passing_scientific_review(run_dir)
        update_simple_state(run_dir, phase="visualization")

    @staticmethod
    def _record_independent_oracle(run_dir: Path) -> None:
        """写入真实执行的独立 oracle 夹具，而非伪造状态字段。"""
        production = run_dir / "code" / "production_solver.py"
        production.write_text(
            "import json\n"
            "from pathlib import Path\n"
            "Path('results/raw/production_solver.json').write_text(\n"
            "    json.dumps({'metrics': {'objective': 1.0}}), encoding='utf-8'\n"
            ")\n",
            encoding="utf-8",
        )
        execute_simple_experiment(
            run_dir,
            result_id="oracle-production",
            question_id="shared",
            kind="primary",
            command=f'"{sys.executable}" code/production_solver.py',
            expected_outputs=["results/raw/production_solver.json"],
            metrics_from="results/raw/production_solver.json",
        )
        script = run_dir / "code" / "independent_oracle.py"
        script.write_text(
            "import json\n"
            "from pathlib import Path\n"
            "Path('results/raw/independent_oracle.json').write_text(\n"
            "    json.dumps({\n"
            "        'metrics': {'oracle_cases_checked': 3},\n"
            "        'oracle_semantics': {\n"
            "            'schema_name': 'independent_oracle_semantics',\n"
            "            'schema_version': '1.0',\n"
            "            'formulation': 'quadratic_segment_sphere_intersection',\n"
            "            'production_formulation': 'clipped_projection_distance',\n"
            "            'boundary_cases': ['endpoint', 'tangent', 'degenerate'],\n"
            "            'all_cases_compared': True,\n"
            "        },\n"
            "    }), encoding='utf-8'\n"
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

    @staticmethod
    def _complete_visualization(run_dir: Path) -> dict[str, object]:
        """建立几何、优化和路线图的最小冻结 Figure Contract。"""
        source = run_dir / "state" / "DECISIONS.md"
        script = run_dir / "code" / "figures" / "render.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        # 该统一色块只验证命令/哈希/合同边界；真实三维语义必须由独立视觉审查判断。
        script.write_text(
            "from PIL import Image\n"
            "from pathlib import Path\n"
            "import sys\n"
            "Path(sys.argv[1]).parent.mkdir(parents=True, exist_ok=True)\n"
            "Image.new('RGB', (320, 240), color=(30, 90, 140)).save(sys.argv[1])\n",
            encoding="utf-8",
        )
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
            evidence_roles = {
                "spatial_scene": ["model_structure"],
                "geometric_boundary": ["model_structure"],
                "optimization_convergence": ["solver_process"],
                "optimization_diagnostic": ["optimality_evidence"],
                "method_roadmap": ["method_overview"],
            }[role]
            evidence_modes = {
                "spatial_scene": ["spatial_3d"],
                "geometric_boundary": ["orthographic_geometry"],
                "optimization_convergence": ["heuristic_trace"],
                "optimization_diagnostic": ["proxy_calibration"],
                "method_roadmap": ["workflow_overview"],
            }[role]
            receipt = run_figure_render(
                run_dir,
                figure_id=role,
                engine="python",
                rendering_mode={
                    "spatial_scene": "3d",
                    "geometric_boundary": "orthographic",
                    "optimization_convergence": "2d",
                    "optimization_diagnostic": "2d",
                    "method_roadmap": "diagram",
                }[role],
                script_path=script.relative_to(run_dir).as_posix(),
                input_paths=[source.relative_to(run_dir).as_posix()],
                output_paths=[output.relative_to(run_dir).as_posix()],
                arguments=[output.relative_to(run_dir).as_posix()],
            )
            contracts.append(
                {
                    "figure_id": role,
                    "question_id": "shared",
                    "scientific_question": f"{role} 对当前模型或求解结论提供什么证据。",
                    "conclusion_impact": "supporting",
                    "why_needed": "该图直接支撑当前题的模型边界或求解充分性判断。",
                    "evidence_roles": evidence_roles,
                    "evidence_modes": evidence_modes,
                    "evidence_scope": "model"
                    if role in {"spatial_scene", "geometric_boundary", "method_roadmap"}
                    else "search_diagnostic",
                    "status": "complete",
                    "render_receipt": receipt,
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

    def test_oracle_cannot_share_local_domain_dependency(self) -> None:
        """不同入口若复用同一领域函数，仍不能宣称 oracle 独立。"""
        run_dir = initialize_simple_run(self.root, "shared-oracle-closure")
        self._enter_experiment(run_dir, ["geometry_kinematics"])
        common = run_dir / "code" / "common_geometry.py"
        common.write_text(
            "def wrong_segment_distance() -> float:\n"
            "    return 1.0\n",
            encoding="utf-8",
        )
        production = run_dir / "code" / "production.py"
        production.write_text(
            "import json\n"
            "from pathlib import Path\n"
            "from common_geometry import wrong_segment_distance\n"
            "Path('results/raw/production.json').write_text(\n"
            "    json.dumps({'metrics': {'distance': wrong_segment_distance()}}),\n"
            "    encoding='utf-8',\n"
            ")\n",
            encoding="utf-8",
        )
        oracle = run_dir / "code" / "oracle.py"
        oracle.write_text(
            "import json\n"
            "from pathlib import Path\n"
            "from common_geometry import wrong_segment_distance\n"
            "Path('results/raw/oracle.json').write_text(\n"
            "    json.dumps({\n"
            "        'metrics': {'distance': wrong_segment_distance()},\n"
            "        'oracle_semantics': {\n"
            "            'schema_name': 'independent_oracle_semantics',\n"
            "            'schema_version': '1.0',\n"
            "            'formulation': 'quadratic_segment_sphere_intersection',\n"
            "            'production_formulation': 'clipped_projection_distance',\n"
            "            'boundary_cases': ['endpoint', 'tangent', 'degenerate'],\n"
            "            'all_cases_compared': True,\n"
            "        },\n"
            "    }),\n"
            "    encoding='utf-8',\n"
            ")\n",
            encoding="utf-8",
        )
        production_result = execute_simple_experiment(
            run_dir,
            result_id="production",
            question_id="shared",
            kind="primary",
            command=f'"{sys.executable}" code/production.py',
            expected_outputs=["results/raw/production.json"],
            metrics_from="results/raw/production.json",
        )["result"]
        execute_simple_experiment(
            run_dir,
            result_id="oracle",
            question_id="shared",
            kind="independent-oracle",
            command=f'"{sys.executable}" code/oracle.py',
            expected_outputs=["results/raw/oracle.json"],
            metrics_from="results/raw/oracle.json",
        )

        self.assertIn("code/common_geometry.py", production_result["input_hashes"])
        with self.assertRaisesRegex(ContractError, "源码闭包共享领域模块"):
            require_independent_oracle_execution(run_dir)

    def test_oracle_requires_distinct_formulation_and_boundary_receipt(self) -> None:
        """只换入口而不给不同原理与边界用例收据不能通过。"""
        run_dir = initialize_simple_run(self.root, "missing-oracle-semantics")
        self._enter_experiment(run_dir, ["geometry_kinematics"])
        production = run_dir / "code" / "production.py"
        production.write_text(
            "import json\n"
            "from pathlib import Path\n"
            "Path('results/raw/production.json').write_text(\n"
            "    json.dumps({'metrics': {'distance': 1.0}}), encoding='utf-8'\n"
            ")\n",
            encoding="utf-8",
        )
        execute_simple_experiment(
            run_dir,
            result_id="production",
            question_id="shared",
            kind="primary",
            command=f'"{sys.executable}" code/production.py',
            expected_outputs=["results/raw/production.json"],
            metrics_from="results/raw/production.json",
        )
        script = run_dir / "code" / "oracle.py"
        script.write_text(
            "import json\n"
            "from pathlib import Path\n"
            "Path('results/raw/oracle.json').write_text(\n"
            "    json.dumps({\n"
            "        'metrics': {'oracle_cases_checked': 1},\n"
            "        'oracle_semantics': {\n"
            "            'schema_name': 'independent_oracle_semantics',\n"
            "            'schema_version': '1.0',\n"
            "            'formulation': 'clipped_projection_distance',\n"
            "            'production_formulation': 'clipped_projection_distance',\n"
            "            'boundary_cases': ['endpoint'],\n"
            "            'all_cases_compared': True,\n"
            "        },\n"
            "    }), encoding='utf-8'\n"
            ")\n",
            encoding="utf-8",
        )
        execute_simple_experiment(
            run_dir,
            result_id="oracle",
            question_id="shared",
            kind="independent-oracle",
            command=f'"{sys.executable}" code/oracle.py',
            expected_outputs=["results/raw/oracle.json"],
            metrics_from="results/raw/oracle.json",
        )

        with self.assertRaisesRegex(ContractError, "语义收据"):
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

    def test_selected_knowledge_requires_a_real_consumption_receipt(self) -> None:
        """路由中列出知识文件不能代替受控读取。"""
        run_dir = initialize_simple_run(self.root, "missing-knowledge-consumption")
        update_simple_state(run_dir, phase="capability_route")
        write_local_tooling(run_dir)
        write_capability_route(run_dir, self._route_payload(run_dir, ["other"]))

        with self.assertRaisesRegex(ContractError, "实际消费收据"):
            update_simple_state(run_dir, phase="experiment")

        receipt = record_knowledge_consumption(run_dir)
        self.assertEqual("controlled_binary_read", receipt["reader"]["operation"])
        self.assertEqual("experiment", update_simple_state(run_dir, phase="experiment")["phase"])

    def test_knowledge_consumption_receipt_rejects_byte_count_tampering(self) -> None:
        """只改写读取字节数也不能让旧知识收据继续通过。"""
        run_dir = initialize_simple_run(self.root, "knowledge-byte-tampering")
        self._enter_experiment(run_dir, ["other"])
        receipt_path = run_dir / "state" / "knowledge-consumption.json"
        receipt = load_json(receipt_path)
        receipt["assets"][0]["bytes_read"] += 1
        atomic_json(receipt_path, receipt)

        with self.assertRaisesRegex(ContractError, "读取字节数不一致"):
            require_capability_route(run_dir)

    def test_route_change_invalidates_old_knowledge_consumption_receipt(self) -> None:
        """新路线必须重新读取其选择的知识，不能复用旧路线回执。"""
        run_dir = initialize_simple_run(self.root, "knowledge-route-change")
        self._enter_experiment(run_dir, ["other"])
        replacement = self._route_payload(run_dir, ["other"])
        replacement["knowledge_assets"] = ["knowledge/cards/structured-optimization.json"]
        write_capability_route(run_dir, replacement)

        with self.assertRaisesRegex(ContractError, "未绑定当前能力路由"):
            require_capability_route(run_dir)

        record_knowledge_consumption(run_dir)
        self.assertEqual("ready", require_capability_route(run_dir)["status"])

    def test_visualization_freezes_declared_output_input_and_generator(self) -> None:
        """一次真实渲染后，各项声明性证据漂移都必须阻断论文并可恢复。"""
        run_dir = self._completed_visualization_fixture()
        plan = require_visualization_complete(run_dir)
        require_visualization_complete(run_dir)

        output = self._render_output(run_dir, plan["contracts"][0])
        original_output = output.read_bytes()
        output.write_bytes(b"tampered-output")
        with self.assertRaisesRegex(ContractError, "输出哈希"):
            require_visualization_complete(run_dir)
        output.write_bytes(original_output)
        require_visualization_complete(run_dir)

        script = run_dir / "code" / "figures" / "render.py"
        original_script = script.read_bytes()
        script.write_bytes("# 被改写的图生成器\n".encode())
        with self.assertRaisesRegex(ContractError, "生成脚本哈希"):
            require_visualization_complete(run_dir)
        script.write_bytes(original_script)
        require_visualization_complete(run_dir)

        input_path = run_dir / "state" / "DECISIONS.md"
        original_input = input_path.read_bytes()
        input_path.write_bytes("# 被改写的证据\n".encode())
        with self.assertRaisesRegex(ContractError, "输入哈希"):
            require_visualization_complete(run_dir)
        input_path.write_bytes(original_input)
        require_visualization_complete(run_dir)

    def test_render_receipt_records_a_real_command_without_claiming_input_reads(self) -> None:
        """成功收据只证明命令与声明文件被冻结，不能推断脚本读取了输入。"""
        run_dir = initialize_simple_run(self.root, "real-render-receipt")
        update_simple_state(run_dir, phase="capability_route")
        write_local_tooling(run_dir)
        script = run_dir / "code" / "figures" / "render.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(
            "from PIL import Image\n"
            "from pathlib import Path\n"
            "import sys\n"
            "Path(sys.argv[1]).parent.mkdir(parents=True, exist_ok=True)\n"
            "Image.new('RGB', (32, 24), color=(30, 90, 140)).save(sys.argv[1])\n",
            encoding="utf-8",
        )

        receipt_reference = run_figure_render(
            run_dir,
            figure_id="real-command",
            engine="python",
            rendering_mode="2d",
            script_path="code/figures/render.py",
            input_paths=["state/DECISIONS.md"],
            output_paths=["figures/real-command.png"],
            arguments=["figures/real-command.png"],
        )

        receipt = load_json(run_dir / receipt_reference["path"])
        self.assertEqual(0, receipt["exit_code"])
        self.assertEqual(["state/DECISIONS.md"], [item["path"] for item in receipt["inputs"]])
        self.assertTrue((run_dir / receipt["outputs"][0]["path"]).is_file())

    def test_complete_visualization_rejects_non_image_png(self) -> None:
        """文件扩展名不能替代真实图像内容。"""
        run_dir = initialize_simple_run(
            self.root,
            "invalid-visual-output",
            required_questions=["Q1", "Q2"],
        )
        self._enter_experiment(run_dir, ["geometry_kinematics", "optimization"])
        script = run_dir / "code" / "figures" / "non_image.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(
            "from pathlib import Path\n"
            "import sys\n"
            "Path(sys.argv[1]).write_bytes(b'not-a-png')\n",
            encoding="utf-8",
        )
        receipt = run_figure_render(
            run_dir,
            figure_id="invalid-image",
            engine="python",
            rendering_mode="3d",
            script_path="code/figures/non_image.py",
            input_paths=["state/DECISIONS.md"],
            output_paths=["figures/invalid-image.png"],
            arguments=["figures/invalid-image.png"],
        )
        plan = new_visualization_plan(
            run_dir,
            [
                {
                    "figure_id": "invalid-image",
                    "question_id": "shared",
                    "scientific_question": "图表文件是否确实可作为可读取的空间证据。",
                    "conclusion_impact": "supporting",
                    "why_needed": "不可读取的图片不能承担模型边界说明。",
                    "evidence_roles": ["model_structure"],
                    "evidence_modes": ["spatial_3d"],
                    "evidence_scope": "model",
                    "status": "complete",
                    "render_receipt": receipt,
                }
            ],
        )

        with self.assertRaisesRegex(ContractError, "PNG 无法通过可读性检查"):
            write_visualization_plan(run_dir, plan)

    def test_geometry_requires_spatial_evidence_and_optimization_accepts_equivalents(self) -> None:
        """三维风险只在空间结论核心时要求，优化允许等价的求解证据。"""
        run_dir = self._completed_visualization_fixture()
        plan = require_visualization_complete(run_dir)

        spatial = next(item for item in plan["contracts"] if item["figure_id"] == "spatial_scene")
        spatial["evidence_modes"] = ["planar_geometry"]
        write_visualization_plan(run_dir, plan)
        with self.assertRaisesRegex(ContractError, "model_structure"):
            require_visualization_complete(run_dir)

        spatial["evidence_modes"] = ["spatial_3d"]
        diagnostic = next(
            item for item in plan["contracts"] if item["figure_id"] == "optimization_diagnostic"
        )
        diagnostic["evidence_modes"] = ["workflow_overview"]
        write_visualization_plan(run_dir, plan)
        with self.assertRaisesRegex(ContractError, "optimality_evidence"):
            require_visualization_complete(run_dir)

    def test_spatial_mode_must_match_the_frozen_declared_render_receipt(self) -> None:
        """空间模式标签必须匹配冻结回执声明，内容语义另由独立审查判断。"""
        run_dir = self._completed_visualization_fixture()
        plan = require_visualization_complete(run_dir)
        spatial = next(item for item in plan["contracts"] if item["figure_id"] == "spatial_scene")
        reference = spatial["render_receipt"]
        receipt_path = run_dir / reference["path"]
        receipt = load_json(receipt_path)
        receipt["rendering_mode"] = "orthographic"
        atomic_json(receipt_path, receipt)
        reference["sha256"] = sha256_file(receipt_path)

        with self.assertRaisesRegex(ContractError, "spatial_3d"):
            write_visualization_plan(run_dir, plan)

    def test_matlab_and_octave_render_command_construction_is_unit_only(self) -> None:
        """命令拼装不依赖本机引擎；可用性由运行期烟雾测试另行决定。"""
        self.assertEqual(
            ["matlab", "-batch", "run('code/matlab/plot.m')"],
            visualization._render_command("matlab", "matlab", "code/matlab/plot.m", []),
        )
        self.assertEqual(
            ["octave", "--quiet", "--no-gui", "--eval", "run('code/matlab/plot.m')"],
            visualization._render_command("octave", "octave", "code/matlab/plot.m", []),
        )
        with self.assertRaisesRegex(ContractError, "环境变量"):
            visualization._render_command("octave", "octave", "code/matlab/plot.m", ["output.png"])

    def test_paper_requires_materialized_known_competition_template(self) -> None:
        """写作只能使用已实例化的完整模板，未知赛事不得默认降级。"""
        run_dir = self._completed_visualization_fixture()

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

        unknown = initialize_simple_run(
            self.root,
            "unknown-template",
            competition="unlisted-contest",
            required_questions=["Q1"],
        )
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
