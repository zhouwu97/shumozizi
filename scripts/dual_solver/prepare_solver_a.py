"""shumozizi 独立解题大脑 (Solver A) 准备工具。

作用：
1. 创建 Solver A 独立解题工作区目录 (analysis/dual_solver/solver_a/)；
2. 一键生成 Solver A 独立全题解题提示词，指导在新对话 A 中独立完成整题形式化、求解与计算；
3. 规范完整对话记录 (TRANSCRIPT.md)、代码 (code/) 与结果 (results/) 的保存路径。
"""

from __future__ import annotations

import argparse
from pathlib import Path


def prepare_solver_a_workspace(run_dir: Path) -> Path:
    """初始化 Solver A 工作区目录结构。"""
    solver_a_dir = run_dir / "analysis" / "dual_solver" / "solver_a"
    (solver_a_dir / "code").mkdir(parents=True, exist_ok=True)
    (solver_a_dir / "results").mkdir(parents=True, exist_ok=True)
    return solver_a_dir


def build_solver_a_prompt(run_dir: Path) -> str:
    """生成用于独立新对话 A (Solver A - shumozizi) 的完整解题提示词。"""
    prepare_solver_a_workspace(run_dir)

    problem_dir = run_dir / "problem"
    problem_texts: list[str] = []
    if problem_dir.is_dir():
        for path in sorted(problem_dir.glob("*.md")) + sorted(problem_dir.glob("*.txt")):
            problem_texts.append(f"=== {path.name} ===\n{path.read_text(encoding='utf-8', errors='ignore')}")

    joined_problem = "\n\n".join(problem_texts) if problem_texts else "【题面文件存放在 problem/ 目录下】"

    prompt = f"""你现在作为数学建模解题专家 (Solver A - shumozizi)。

---

## 原始题面信息

{joined_problem}

---

## 解题核心要求

1. **独立完整解题**：请使用文件读取工具完整查看 `problem/**` 下的所有题面、数据表格（Excel/CSV）、PDF 附注与图像，独立完成整道赛题的全部建模与计算。
2. **严谨形式化**：
   - 明确定义各小问的形式化决策对象、决策变量、目标函数与物理/逻辑硬约束；
   - 建立 baseline 模型与深入优化/仿真模型；
   - 构造最小反例或性质检验，验证模型与算法的边界可靠性。
3. **真实计算与收敛验证**：
   - 编写完整的 Python/MATLAB 算法代码，真实运行并输出各项关键指标与数据结果；
   - 给出保守、可复验的数值结论。

---

## 成果归档要求

在对话完成后，请将本次解题成果保存至：
- **完整解题与对话记录**：`analysis/dual_solver/solver_a/TRANSCRIPT.md`（或 `SOLUTION_A.md`）
- **核心算法与仿真代码**：`analysis/dual_solver/solver_a/code/`
- **计算与指标数据文件**：`analysis/dual_solver/solver_a/results/`
"""
    return prompt


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 Solver A (shumozizi 独立解题) 提示词与工作区")
    parser.add_argument("run_dir", type=Path, help="运行目录路径")
    args = parser.parse_args()

    prompt = build_solver_a_prompt(args.run_dir)
    print(prompt)


if __name__ == "__main__":
    main()
