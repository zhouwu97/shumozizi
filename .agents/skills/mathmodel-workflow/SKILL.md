---
name: mathmodel-workflow
description: 以 Capability-First v3 完成整道数学建模赛题的分析、求解、真实实验、论文和一次终检。仅在用户明确要求完整赛题交付时使用；局部分析、调试或改写论文不得隐式启动。
---

# Capability-First v3 数学建模工作流

目标是在有限时间内提高解题、实验和论文质量。能力 Skill 负责思考与产出；结果索引只证明程序真实运行；机械 QA 只拦截确定性提交错误。不要把任何其中一层误当成科学结论。

## 启动与恢复

1. 仅在用户要求整题、可运行实验和完整论文时使用本 Skill。局部任务直接使用相应能力 Skill。
2. 新运行使用：

   ```powershell
   python scripts/codex/init_run.py <problem_path> --workflow capability-first-v3 --run-id <run-id>
   ```

   也可使用 `scripts/codex/init_simple_run.py`。运行目录是 `runs/<run-id>/`。
3. 每次恢复先读取 `state/run.json` 和 `state/DECISIONS.md`，只读取当前阶段需要的材料。题面、数据摘要和已完成报告不得无目的重复全量读取。
4. 默认生产链只有一个连续任务：分析、建模、代码、图表、论文；随后最多一次整体审查；只有存在 P0/P1 时才进行一次定向修复。不要为每问、每个发现或格式小改创建顶层任务。

## 阶段路由

| `phase` | 行动 | 主要产物 |
| --- | --- | --- |
| `analysis` | 调用 `$mathmodel-solve`，理解题意、数据和候选路线 | `reports/ANALYSIS_MODELING_REPORT.md` |
| `solve` | 补齐主路线、fallback 与最低成本 probe，再调用 `$mathmodel-experiment` | `state/DECISIONS.md` |
| `experiment` | 实际运行代码、记录结果、按题型验证并生成图表 | `results/index.json`、`reports/RESULTS_REPORT.md` |
| `paper` | 调用 `$mathmodel-paper`，只用仍为 current 的真实结果写作和编译 | `paper/final.pdf` |
| `verify` | 调用 `$mathmodel-final-check`，执行一次机械检查和整体科学审查 | `qa/mechanical-qa.json`、`qa/FINAL_REVIEW.md` |
| `complete` | 仅报告产物、复现命令与局限 | 交付摘要 |

用 `shumozizi.simple.state.update_simple_state()` 或受支持 CLI 更新阶段、路线、已完成问题和产物路径；不写入审核闭环、裁决、回执或科学判定状态。

## 人工决策与路线切换

默认只在两种情况暂停询问用户：

1. 题意、核心目标或必做输出存在重大歧义；
2. 最终提交前请求确认。

以下情况无需重新请求批准：修复实现错误、调整参数或求解器、用已有 fallback 替代主路线、同一题意下更换模型类别。只有改变题意解释、核心目标、必做输出，或预计额外投入超过剩余预算 30% 时，才停下给出编号选项和推荐项。

## 预算与停止规则

- `fast`、`standard`、`deep` 的 token 软上限分别建议为 50k、200k、500k；达到软上限时缩减上下文和任务，而不是制造新的门禁。
- 每阶段最多加载一到两个知识文件；文献检索最多五次。
- 数据摘要和关键决策优先落盘；局部修改只读受影响章节。
- 连续两次修改没有实质改善时停止，记录原因并切换 fallback、缩小目标或请用户决定。
- 剩余时间少于 15% 时只处理 P0/P1 和可提交性。

本 Skill 不使用审核生命周期、独立审核对话编排或每问固定实验数量。最终科学判断来自完整结果和一次整体审查，而非状态文件。
