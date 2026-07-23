---
name: mathmodel-experiment
description: 在 Capability-First v3 中编写、实际运行和调试数学建模实验，保存可追溯结果、图表数据和按题型选择的验证；用于整题或已明确的子问题实验。
---

# 真实执行与有信息量的实验

实验回答题目并挑战关键主张，不是完成固定实验清单。

1. 读取当前状态、决策和建模报告。确认路由选定的本地知识已经有消费收据；从最低成本 baseline 或可行性 probe 开始，再决定是否投入主模型。
2. 代码写入 `code/`，原始输出写入 `results/raw/`，为后续图表保留真实参数、轨迹、几何事件和搜索诊断。不要把模板或模拟数据写成题目结果。
3. 对需要用于论文或关键决策的运行，使用执行器登记真实命令、输出和指标：

   ```powershell
   python scripts/runtime/run_simple_experiment.py runs/<run-id> `
     --question Q2 --kind primary --result-id q2_primary `
     --command "python code/q2.py" --expect results/raw/q2.json `
     --input problem/attachments/data.xlsx --metrics-from results/raw/q2.json
   ```

   非零退出、空输出或损坏 JSON 时先修复或如实记录，不能继续解释结果。
4. 搜索型题目让候选探索、题目特定精确评分和独立搜索审计分工；它们必须从原始候选和真实输入复算，而不是互信布尔字段。脚本冻结详细来源和收据，主对话只说明数学评分、约束、覆盖/最优性证据和结果边界。不要让弱候选覆盖已验证的结果。
5. 按主张选最低成本验证：预测关注切分/泄漏/误差；优化关注可行性、baseline、多初值、界或扰动；机理关注恢复、守恒或可辨识性；评价关注权重扰动与排名翻转。验证应能改变决策，而不是凑表格。
6. 每问更新 `RESULTS_REPORT.md` 和 `DECISIONS.md`：当前结果、对照、是否直接回答题目、最可能失败原因、下一实验，以及继续、修复、切换或停止。探索结果明确标为 diagnostic，绝不写进正式图表、论文或提交。
7. 图表阶段再决定最终视觉叙事。普通图足以回答问题时优先普通图；需要复杂科研图时按需读取 `skills/3coding-visual/SKILL.md`，并仅在真实数据接口匹配时使用 `skills/mathmodel-figure-templates/`。模板示例数据不得进入论文。
