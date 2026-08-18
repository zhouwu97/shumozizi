"""科学评审团 (Scientific Jury) 极简总评审与裁决工具。

定位：第三个独立对话 (Dialogue C)，直接在工作区全量读取 problem/** 与双方完整记录，
执行冲突驱动的代码交叉复算，进行无偏客观裁决并输出 FINAL_SCIENTIFIC_PLAN.md。
"""

from __future__ import annotations

import argparse
from pathlib import Path


def build_scientific_jury_prompt(run_dir: Path) -> str:
    """生成用于独立新对话 C (Scientific Jury 总评审) 的严苛裁决 Brief。

    【核心原则】：不截断代码与结果，指令 Jury 直接在工作区用工具读取全量文件。
    彻底删除强制融合偏见，实行客观四选一裁决。
    """
    prompt = f"""# 数学建模科学评审团 (Scientific Jury) 裁决任务 Brief

你是第三个独立的数学建模总评审对话 (Dialogue C: Scientific Jury)。
你需要针对同一道赛题，独立审查两个解题大脑分别给出的完整方案与推演日志：
- **方案 A (Solver A - shumozizi 路线)**
- **方案 B (Solver B - BZD 路线)**

---

## 1. 必读输入文件清单（请直接在工作区全量查看，禁止凭摘要猜测）

请首先使用文件读取工具完整阅读以下文件：

1. **原始赛题与全部附件**：
   - `problem/**`（包含所有题目正文、PDF 附注、Excel 工作表、CSV 数据及图像）
2. **方案 A 完整解题成果 (Solver A - shumozizi)**：
   - 最终解题方案：`analysis/dual_solver/solver_a/FINAL_SOLUTION.md`
   - 思考推演日志：`analysis/dual_solver/solver_a/SOLVER_LOG.md`（或 `TRANSCRIPT.md`）
   - 全部实现与仿真代码：`analysis/dual_solver/solver_a/code/**`
   - 全部计算与指标数据：`analysis/dual_solver/solver_a/results/**`
3. **方案 B 完整解题成果 (Solver B - BZD)**：
   - 最终解题方案：`analysis/dual_solver/solver_b/FINAL_SOLUTION.md`
   - 思考推演日志：`analysis/dual_solver/solver_b/SOLVER_LOG.md`（或 `TRANSCRIPT.md`）
   - 全部实现与仿真代码：`analysis/dual_solver/solver_b/code/**`
   - 全部计算与指标数据：`analysis/dual_solver/solver_b/results/**`

---

## 2. 科学评审团核心裁决标准

重新从原题出发，客观评价双方方案，严格遵循以下原则：

1. **题意与数学严谨性**：谁对原题物理场景、目标与约束的理解更准确？公式推导展开谁更扎实无漏洞？
2. **模型适配性**：哪个模型最契合题目内在机制？**不因算法更复杂而偏好某方案**。
3. **数值与真实性**：**不因某方案目标值看似更优就直接判胜**！必须核验约束是否满足、数据口径是否一致。
4. **【冲突驱动复算】**：
   - 当双方在关键数值、约束理解或模型结论上出现冲突时，**直接在终端运行双方代码、代入关键数据复算或构造最小边界反例**进行实测检验；
   - 无冲突且推导一致的部分无需重复执行全部代码。
5. **【无偏裁决原则（不要求强迫融合）】**：
   - 对每个必答问题，只能给出以下四类明确决议之一：
     - **采用 A (Adopt A)**
     - **采用 B (Adopt B)**
     - **融合 A+B (Synthesize A+B)**（仅当互补部分经过复算或严密论证确实带来改善时才融合）
     - **两者均淘汰重做 (Reject Both & Redesign)**
   - **如果某一方在题意忠实度、数学推导与计算结果上全面占优，请直接完整采纳该方案，绝不为了“融合感”而生硬拼凑**。

---

## 3. 输出目标与要求

请将你的完整裁决报告输出并保存至：
`analysis/dual_solver/JURY_VERDICT.md`

报告中必须明确：
1. 全篇核心建模骨干决议；
2. 逐问客观判决（采用A / 采用B / 融合 / 重做）与淘汰理由；
3. 双方数值冲突时的实际复算结果与依据；
4. 供后续正式实验重跑与论文撰写的统一方案。
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
        template_text = """# 统一最终科学方案 (FINAL_SCIENTIFIC_PLAN)

> 本方案由 Scientific Jury 综合审核 Solver A 与 Solver B 后的裁决生成。

## 1. 全篇核心建模主线
- 待 Jury 裁决填写

## 2. 分问最终方案与决议
| 问题 | 裁决结果 (Adopt A / Adopt B / Synthesize / Redesign) | 最终采纳模型 | 淘汰原因 | 关键验证与复算判据 |
|---|---|---|---|---|
| Q1 | 待裁决 | 待定 | 待定 | 待定 |
| Q2 | 待裁决 | 待定 | 待定 | 待定 |
| Q3 | 待裁决 | 待定 | 待定 | 待定 |
| Q4 | 待裁决 | 待定 | 待定 | 待定 |
"""
        plan_path.write_text(template_text, encoding="utf-8")
        return plan_path

    verdict_text = v_path.read_text(encoding="utf-8")
    final_plan_text = f"""# 统一最终科学方案 (FINAL_SCIENTIFIC_PLAN)

> 本方案由 Scientific Jury 基于原题对 Solver A 与 Solver B 的独立全文件复算、交叉攻击与无偏裁决生成。

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
