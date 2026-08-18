"""验证双解题大脑 (Dual-Solver) 与科学评审团 (Scientific Jury) 极简架构的输入准备、审核包组装与方案融合。"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.dual_solver.prepare_solver_b import (
    build_solver_b_prompt,
    prepare_solver_b_packet,
)
from scripts.dual_solver.run_scientific_jury import (
    build_scientific_jury_prompt,
    import_jury_verdict_to_final_plan,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_solver_b_packet_preparation_and_prompt_assembly(tmp_path: Path) -> None:
    """Solver B 必须获得物理隔离的赛题与附件，并装配原版 BZD References 进行独立全题建模。"""
    run_dir = tmp_path / "run_01"
    problem_dir = run_dir / "problem"
    problem_dir.mkdir(parents=True)
    (problem_dir / "problem.md").write_text("# 2025 A题 太阳能光伏与储能协同优化\n\n背景与各问要求...", encoding="utf-8")
    (problem_dir / "data.csv").write_text("t,load,pv\n1,100,50\n2,120,60\n", encoding="utf-8")
    (problem_dir / "system.xlsx").write_text("dummy xlsx binary", encoding="utf-8")

    # 污染源（Solver A 的本地内容，必须被隔离屏蔽）
    (run_dir / "analysis").mkdir(parents=True)
    (run_dir / "analysis" / "ROUTE_COMPETITION.md").write_text("A 方案主路线: 混合整数规划", encoding="utf-8")

    # 1. 验证隔离包构建
    packet_dir = prepare_solver_b_packet(run_dir)
    assert packet_dir.is_dir()
    assert (packet_dir / "problem" / "problem.md").is_file()
    assert (packet_dir / "problem" / "data.csv").is_file()
    assert (packet_dir / "problem" / "system.xlsx").is_file()
    assert (packet_dir / "INPUT_MANIFEST.md").is_file()
    assert not (packet_dir / "ROUTE_COMPETITION.md").exists()

    # 2. 验证提示词生成（包含原版 References 与独立全题建模要求）
    prompt = build_solver_b_prompt(run_dir)
    assert "2025 A题 太阳能光伏与储能协同优化" in prompt
    assert "[CSV数据附件] data.csv" in prompt
    assert "[Excel数据附件] system.xlsx" in prompt
    assert "A 方案主路线" not in prompt  # 绝无 A 方案泄露
    assert "integrated-modeling-patterns.md" in prompt
    assert "strategy-output-standard.md" in prompt
    assert "独立完成整题建模，不参考任何已有外部方案" in prompt
    assert "analysis/dual_solver/solver_b/SOLUTION_B.md" in prompt


def test_scientific_jury_prompt_assembly_with_both_solvers(tmp_path: Path) -> None:
    """Scientific Jury 提示词必须完整聚合原题、Solver A 与 Solver B 的方案、代码与结果，并注入 10 项严苛审核规则。"""
    run_dir = tmp_path / "run_02"
    problem_dir = run_dir / "problem"
    problem_dir.mkdir(parents=True)
    (problem_dir / "problem.md").write_text("# 2025 C题 生产与检测调度问题\n\n要求求解最优抽检与装配策略...", encoding="utf-8")

    # 准备 Solver A 记录
    solver_a_dir = run_dir / "analysis" / "dual_solver" / "solver_a"
    solver_a_dir.mkdir(parents=True)
    (solver_a_dir / "SOLUTION_A.md").write_text("## 方案 A (shumozizi)\n采用状态转移动态规划，精确刻画每道工序检测成本与良品率传递。", encoding="utf-8")
    (solver_a_dir / "code").mkdir(parents=True)
    (solver_a_dir / "code" / "model_a.py").write_text("def solve_dp(): return 1234.5", encoding="utf-8")
    (solver_a_dir / "results").mkdir(parents=True)
    (solver_a_dir / "results" / "q1_a.json").write_text(json.dumps({"total_cost": 1234.5}), encoding="utf-8")

    # 准备 Solver B 记录
    solver_b_dir = run_dir / "analysis" / "dual_solver" / "solver_b"
    solver_b_dir.mkdir(parents=True)
    (solver_b_dir / "SOLUTION_B.md").write_text("## 方案 B (BZD)\n采用混合整数非线性规划 (MINLP)，引入极端工况下的风险置信惩罚项。", encoding="utf-8")
    (solver_b_dir / "code").mkdir(parents=True)
    (solver_b_dir / "code" / "model_b.py").write_text("def solve_minlp(): return 1198.0", encoding="utf-8")
    (solver_b_dir / "results").mkdir(parents=True)
    (solver_b_dir / "results" / "q1_b.json").write_text(json.dumps({"total_cost": 1198.0}), encoding="utf-8")

    # 生成 Jury Prompt
    jury_prompt = build_scientific_jury_prompt(run_dir)

    # 验证原题与双脑材料聚合
    assert "2025 C题 生产与检测调度问题" in jury_prompt
    assert "状态转移动态规划" in jury_prompt
    assert "1234.5" in jury_prompt
    assert "混合整数非线性规划 (MINLP)" in jury_prompt
    assert "1198.0" in jury_prompt

    # 验证 10 项核心审核规则
    assert "严禁因为方案复杂、推导篇幅长或数值看似更优就直接判胜" in jury_prompt
    assert "交叉复算与数值真实性" in jury_prompt
    assert "漏洞与隐式假设挖掘" in jury_prompt
    assert "边界崩塌分析" in jury_prompt
    assert "最优方案融合 (Synthesis)" in jury_prompt
    assert "采纳 A / 采纳 B / 融合 A+B / 均推翻重做" in jury_prompt


def test_jury_verdict_exported_to_final_scientific_plan(tmp_path: Path) -> None:
    """Jury 裁决报告能够直接导出为统一最终科学方案 FINAL_SCIENTIFIC_PLAN.md。"""
    run_dir = tmp_path / "run_03"
    jury_dir = run_dir / "analysis" / "dual_solver"
    jury_dir.mkdir(parents=True)

    verdict_text = """## 科学评审团裁决意见

### 1. 核心裁决与融合决策
- **Q1**：采纳方案 A（动态规划模型推导严谨，B 方案松弛后存在约束违反）。
- **Q2**：融合 A+B（采纳 A 的工序状态转移框架，同时引入 B 提出的非凸惩罚参数化）。
- **Q3**：采纳方案 B（B 在多机协同冲突消解上的数学结构明显优于 A 的启发式）。

### 2. 最终统一建模主线
建立基于工序状态转移与鲁棒风险惩罚的统一调度框架。
"""
    verdict_file = jury_dir / "JURY_VERDICT.md"
    verdict_file.write_text(verdict_text, encoding="utf-8")

    plan_file = import_jury_verdict_to_final_plan(run_dir, verdict_file)
    assert plan_file.is_file()
    plan_content = plan_file.read_text(encoding="utf-8")

    assert "# 统一最终科学方案 (FINAL_SCIENTIFIC_PLAN)" in plan_content
    assert "Q1" in plan_content and "采纳方案 A" in plan_content
    assert "Q2" in plan_content and "融合 A+B" in plan_content
    assert "Q3" in plan_content and "采纳方案 B" in plan_content
