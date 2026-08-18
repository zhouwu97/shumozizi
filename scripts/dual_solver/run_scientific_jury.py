"""科学评审团 (Scientific Jury) 总评审与裁决工具。

作用：
1. 聚合：原始题面与全部附件 + Solver A (shumozizi) 完整解题记录/代码/结果 + Solver B (BZD) 完整解题记录/代码/结果；
2. 生成严苛的独立裁决提示词 (Jury Prompt)，指令其执行代码交叉复算、边界反例攻击与模型融合；
3. 将 Jury 裁决报告解析并生成最终可执行的 `analysis/FINAL_SCIENTIFIC_PLAN.md`。
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any


def _collect_solver_materials(solver_dir: Path, fallback_dir: Path | None = None) -> dict[str, str]:
    """收集指定解题大脑的方案、代码与结果。"""
    materials = {
        "solution": "（未找到解题报告文本）",
        "code_summary": "（未提供独立代码）",
        "results_summary": "（未提供独立计算结果）",
    }

    # 1. 查找解题方案 Markdown
    sol_md = next(solver_dir.glob("*.md"), None)
    if sol_md and sol_md.is_file():
        materials["solution"] = sol_md.read_text(encoding="utf-8", errors="ignore")
    elif fallback_dir and fallback_dir.is_dir():
        fallback_md = next(fallback_dir.glob("*.md"), None)
        if fallback_md and fallback_md.is_file():
            materials["solution"] = fallback_md.read_text(encoding="utf-8", errors="ignore")

    # 2. 收集代码
    code_dir = solver_dir / "code"
    if not code_dir.is_dir() and fallback_dir:
        code_dir = fallback_dir / "code"
    if code_dir.is_dir():
        code_files = [f for f in sorted(code_dir.rglob("*.py")) if f.is_file()]
        if code_files:
            snippets = []
            for cf in code_files[:5]:
                snippets.append(f"--- [代码文件: {cf.name}] ---\n{cf.read_text(encoding='utf-8', errors='ignore')}")
            materials["code_summary"] = "\n\n".join(snippets)

    # 3. 收集结果
    results_dir = solver_dir / "results"
    if not results_dir.is_dir() and fallback_dir:
        results_dir = fallback_dir / "results"
    if results_dir.is_dir():
        res_files = [f for f in sorted(results_dir.rglob("*.json")) if f.is_file()]
        if res_files:
            snippets = []
            for rf in res_files[:5]:
                snippets.append(f"--- [结果文件: {rf.name}] ---\n{rf.read_text(encoding='utf-8', errors='ignore')}")
            materials["results_summary"] = "\n\n".join(snippets)

    return materials


def build_scientific_jury_prompt(run_dir: Path) -> str:
    """生成用于独立新对话 C (Scientific Jury 总评审) 的严苛裁决提示词。"""
    # 1. 读取原题与附件
    problem_dir = run_dir / "problem"
    problem_texts: list[str] = []
    if problem_dir.is_dir():
        for path in sorted(problem_dir.glob("*.md")) + sorted(problem_dir.glob("*.txt")):
            problem_texts.append(f"=== {path.name} ===\n{path.read_text(encoding='utf-8', errors='ignore')}")
        if not problem_texts:
            for path in sorted(problem_dir.glob("*.pdf")):
                problem_texts.append(f"=== [PDF题面] {path.name} ({path.stat().st_size} bytes) ===")

    raw_problem = "\n\n".join(problem_texts) if problem_texts else "【题面文件存放在 problem/ 目录下】"

    # 2. 收集 Solver A (shumozizi) 材料
    solver_a_dir = run_dir / "analysis" / "dual_solver" / "solver_a"
    solver_a_mats = _collect_solver_materials(solver_a_dir, fallback_dir=run_dir)

    # 3. 收集 Solver B (BZD) 材料
    solver_b_dir = run_dir / "analysis" / "dual_solver" / "solver_b"
    solver_b_fallback = run_dir / "analysis" / "external"
    solver_b_mats = _collect_solver_materials(solver_b_dir, fallback_dir=solver_b_fallback)

    prompt = f"""# 数学建模科学评审团 (Scientific Jury) 总评审与融合裁决任务

你不是简单的方案投票者，而是具有最高科学裁决权的**数学建模总评审 (Scientific Jury)**。

你需要同时审查针对同一赛题独立完成的两个解题方案：
- **方案 A (Solver A - shumozizi 路线)**
- **方案 B (Solver B - BZD 路线)**

---

## 原始赛题与附件数据

{raw_problem}

---

## 方案 A 完整解题记录 (Solver A: shumozizi)

### 解题思路与方案正文：
{solver_a_mats['solution']}

### 方案 A 核心代码：
{solver_a_mats['code_summary']}

### 方案 A 计算结果：
{solver_a_mats['results_summary']}

---

## 方案 B 完整解题记录 (Solver B: BZD)

### 解题思路与方案正文：
{solver_b_mats['solution']}

### 方案 B 核心代码：
{solver_b_mats['code_summary']}

### 方案 B 计算结果：
{solver_b_mats['results_summary']}

---

## 科学评审团 10 项严苛审核规则与裁决标准

请重新从原题出发，逐项执行深度审查与交叉复算：

1. **题意忠实度**：双方对原题目标、物理场景与约束条件的理解谁更精准？是否存在偷换目标或漏读关键约束？
2. **数学严谨性**：决策变量、目标函数与约束公式的形式化推导谁更严谨可信？
3. **模型适配性**：哪个模型最切合题目内在机制，而不是盲目追求复杂算法堆砌？
4. **约束完备性**：双方方案在极端或边界条件下是否满足所有硬约束？
5. **交叉复算与数值真实性**：
   - 严禁因为方案复杂、推导篇幅长或数值看似更优就直接判胜！
   - 双方数值存在差异时，必须审查：是否在同一数据口径？是否同一目标？是否存在未满足约束？是否因搜索未收敛导致劣势？
6. **漏洞与隐式假设挖掘**：分别指出方案 A 与方案 B 的根本缺陷与未经证明的假设。
7. **边界崩塌分析**：在什么极端参数或反例下各方案会失效？
8. **方案 A 的独到优势**：有哪些方案 B 未考虑到的精确结构、oracle 验证或判据？
9. **方案 B 的独到优势**：有哪些方案 A 未考虑到的创新视角、优化参数化或宏观联动？
10. **最优方案融合 (Synthesis)**：
    - 绝非简单的“全盘选 A”或“全盘选 B”；
    - 必须逐问裁决：**采纳 A / 采纳 B / 融合 A+B / 均推翻重做**；
    - 给出比单一方案 A 或 B 都显著更强的最终统一科学方案。

---

## 输出要求

请将你的完整裁决报告输出并保存至：
`analysis/dual_solver/JURY_VERDICT.md`

报告中必须包含各小问的明确判决、双方淘汰与采纳理由，以及可直接供正式实验重跑与论文撰写的统一方案。
"""
    return prompt


def import_jury_verdict_to_final_plan(
    run_dir: Path, verdict_path: Path | None = None
) -> Path:
    """将 Jury 裁决报告整理并导出为直接指导实验与论文的统一科学方案 (analysis/FINAL_SCIENTIFIC_PLAN.md)。"""
    v_path = verdict_path or (run_dir / "analysis" / "dual_solver" / "JURY_VERDICT.md")
    plan_path = run_dir / "analysis" / "FINAL_SCIENTIFIC_PLAN.md"
    plan_path.parent.mkdir(parents=True, exist_ok=True)

    if not v_path.is_file():
        # 如果暂无独立评审报告，生成结构化待评审模板
        template_text = f"""# 统一最终科学方案 (FINAL_SCIENTIFIC_PLAN)

> 本方案由 Scientific Jury 综合审核 Solver A (shumozizi) 与 Solver B (BZD) 后的裁决与融合结果生成。

## 1. 全篇核心建模主线与统一骨干
- 最终采纳主线：待 Jury 裁决填写
- 方案选择理由：结合 A 与 B 的优势进行融合

## 2. 分问最终方案与融合决议
| 问题 | 裁决结果 (Adopt A / Adopt B / Synthesize / Redesign) | 最终采纳模型 | 淘汰方案及淘汰原因 | 关键验证与复算判据 |
|---|---|---|---|---|
| Q1 | 待裁决 | 待定 | 待定 | 待定 |
| Q2 | 待裁决 | 待定 | 待定 | 待定 |
| Q3 | 待裁决 | 待定 | 待定 | 待定 |
| Q4 | 待裁决 | 待定 | 待定 | 待定 |

## 3. 正式实验重跑与论文交接清单
- 核心模型重跑命令与产物路径
- 论文选型对比与机制分析原料
"""
        plan_path.write_text(template_text, encoding="utf-8")
        return plan_path

    verdict_text = v_path.read_text(encoding="utf-8")

    # 提取 Jury 裁决中的核心决议
    final_plan_text = f"""# 统一最终科学方案 (FINAL_SCIENTIFIC_PLAN)

> 本方案由 Scientific Jury 基于原题对 Solver A (shumozizi) 与 Solver B (BZD) 的独立复算、交叉攻击与融合裁决生成。

{verdict_text}
"""
    plan_path.write_text(final_plan_text, encoding="utf-8")
    return plan_path


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 Scientific Jury 评审提示词或导出统一科学方案")
    parser.add_argument("run_dir", type=Path, help="运行目录路径")
    parser.add_argument("--import-verdict", action="store_true", help="将 JURY_VERDICT.md 导出为 FINAL_SCIENTIFIC_PLAN.md")
    args = parser.parse_args()

    if args.import_verdict:
        out_plan = import_jury_verdict_to_final_plan(args.run_dir)
        print(f"已成功导出统一最终科学方案: {out_plan}")
    else:
        prompt = build_scientific_jury_prompt(args.run_dir)
        print(prompt)


if __name__ == "__main__":
    main()
