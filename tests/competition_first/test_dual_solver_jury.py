"""验证双解题大脑 (Dual-Solver) 与科学评审团 (Scientific Jury) 极简全文件直读与无偏裁决机制。"""

from __future__ import annotations

from pathlib import Path

from scripts.dual_solver.prepare_solver_a import (
    build_solver_a_prompt,
    prepare_solver_a_workspace,
)
from scripts.dual_solver.prepare_solver_b import (
    build_solver_b_prompt,
    prepare_solver_b_packet,
)
from scripts.dual_solver.run_scientific_jury import (
    build_scientific_jury_prompt,
    import_jury_verdict_to_final_plan,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_solver_a_workspace_and_prompt_assembly(tmp_path: Path) -> None:
    """Solver A 能够初始化独立工作区，生成包含 FINAL_SOLUTION.md 与 SOLVER_LOG.md 保存规范的解题提示词。"""
    run_dir = tmp_path / "run_01"
    problem_dir = run_dir / "problem"
    problem_dir.mkdir(parents=True)
    (problem_dir / "problem.md").write_text("# 2025 A题\n某无人机编队任务...", encoding="utf-8")

    solver_a_dir = prepare_solver_a_workspace(run_dir)
    assert solver_a_dir.is_dir()
    assert (solver_a_dir / "code").is_dir()
    assert (solver_a_dir / "results").is_dir()

    prompt = build_solver_a_prompt(run_dir)
    assert "Solver A - shumozizi" in prompt
    assert "2025 A题" in prompt
    assert "analysis/dual_solver/solver_a/FINAL_SOLUTION.md" in prompt
    assert "analysis/dual_solver/solver_a/SOLVER_LOG.md" in prompt
    assert "analysis/dual_solver/solver_a/code/" in prompt
    assert "analysis/dual_solver/solver_a/results/" in prompt
    assert "根据题型特征决定是否需要 baseline/challenger" in prompt


def test_solver_b_packet_preparation_and_prompt_assembly(tmp_path: Path) -> None:
    """Solver B 能够获得干净隔离包，装配原版 BZD References，并规范 FINAL_SOLUTION.md 与 SOLVER_LOG.md 保存。"""
    run_dir = tmp_path / "run_02"
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

    # 2. 验证提示词生成
    prompt = build_solver_b_prompt(run_dir)
    assert "2025 A题 太阳能光伏与储能协同优化" in prompt
    assert "[CSV数据附件] data.csv" in prompt
    assert "[Excel数据附件] system.xlsx" in prompt
    assert "A 方案主路线" not in prompt  # 绝无 A 方案泄露
    assert "integrated-modeling-patterns.md" in prompt
    assert "strategy-output-standard.md" in prompt
    assert "独立完成整题建模，不参考任何已有外部方案" in prompt
    assert "analysis/dual_solver/solver_b/FINAL_SOLUTION.md" in prompt
    assert "analysis/dual_solver/solver_b/SOLVER_LOG.md" in prompt


def test_scientific_jury_prompt_assembly_no_truncation_and_unbiased_rules(tmp_path: Path) -> None:
    """Jury Brief 必须指导直读全量文件（无截断），具备冲突驱动复算与彻底无偏的客观裁决原则。"""
    run_dir = tmp_path / "run_03"
    problem_dir = run_dir / "problem"
    problem_dir.mkdir(parents=True)
    (problem_dir / "problem.md").write_text("# 2025 C题 生产与检测调度问题\n", encoding="utf-8")

    # 生成 Jury Prompt
    jury_prompt = build_scientific_jury_prompt(run_dir)

    # 1. 验证直读全量文件清单
    assert "problem/**" in jury_prompt
    assert "analysis/dual_solver/solver_a/FINAL_SOLUTION.md" in jury_prompt
    assert "analysis/dual_solver/solver_a/SOLVER_LOG.md" in jury_prompt
    assert "analysis/dual_solver/solver_a/code/**" in jury_prompt
    assert "analysis/dual_solver/solver_a/results/**" in jury_prompt
    assert "analysis/dual_solver/solver_b/FINAL_SOLUTION.md" in jury_prompt
    assert "analysis/dual_solver/solver_b/SOLVER_LOG.md" in jury_prompt
    assert "analysis/dual_solver/solver_b/code/**" in jury_prompt
    assert "analysis/dual_solver/solver_b/results/**" in jury_prompt

    # 2. 验证冲突驱动复算机制
    assert "冲突驱动复算" in jury_prompt
    assert "直接在终端运行双方代码" in jury_prompt

    # 3. 验证无偏客观裁决（四分类，且无强制融合偏见）
    assert "采用 A (Adopt A)" in jury_prompt
    assert "采用 B (Adopt B)" in jury_prompt
    assert "融合 A+B (Synthesize A+B)" in jury_prompt
    assert "两者均淘汰重做 (Reject Both & Redesign)" in jury_prompt
    assert "绝不为了“融合感”而生硬拼凑" in jury_prompt
    # 确保删除了带有主观强加色彩的旧表述
    assert "绝非简单的全盘选" not in jury_prompt
    assert "显著更强" not in jury_prompt


def test_jury_verdict_exported_to_final_scientific_plan_unbiased(tmp_path: Path) -> None:
    """Jury 裁决报告能够正确导出为无偏的统一最终科学方案 FINAL_SCIENTIFIC_PLAN.md。"""
    run_dir = tmp_path / "run_04"
    jury_dir = run_dir / "analysis" / "dual_solver"
    jury_dir.mkdir(parents=True)

    verdict_text = """## 科学评审团裁决意见

### 1. 核心裁决与决策
- **Q1**：采用方案 A（动态规划严格推导，B 存在约束遗漏）。
- **Q2**：采用方案 B（B 在多机连续调度中的 MINLP 结构明显优于 A 的启发式）。
- **Q3**：采用方案 A（A 的空间解析 oracle 经代码复算完全准确）。
- **Q4**：融合 A+B（采纳 A 的事件驱动框架，引入 B 提出的非凸鲁棒参数化）。

### 2. 最终统一建模主线
基于工序状态转移与鲁棒参数化调度模型。
"""
    verdict_file = jury_dir / "JURY_VERDICT.md"
    verdict_file.write_text(verdict_text, encoding="utf-8")

    plan_file = import_jury_verdict_to_final_plan(run_dir, verdict_file)
    assert plan_file.is_file()
    plan_content = plan_file.read_text(encoding="utf-8")

    assert "# 统一最终科学方案 (FINAL_SCIENTIFIC_PLAN)" in plan_content
    assert "Q1" in plan_content and "采用方案 A" in plan_content
    assert "Q2" in plan_content and "采用方案 B" in plan_content
    assert "Q4" in plan_content and "融合 A+B" in plan_content
