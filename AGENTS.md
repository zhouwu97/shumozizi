# shumozizi Capability-First v3 项目约定

## 项目定位

本仓库是 Codex 桌面版驱动的数学建模能力工作台。默认目标是更快理解题目、选择有效路线、真实运行实验并写出能直接回答题目的论文；不是构建审核生命周期平台。

`legacy/review-v2/` 中保留旧系统和历史材料，处于冻结状态。新功能不得依赖或扩展其中的状态服务、审核模块、回执、裁决、闭环或按问审核机制。

## 主动 Skill

自动发现目录 `.agents/skills/` 只保留以下六项主动能力：

- `mathmodel-workflow`：完整赛题的连续编排与恢复；
- `mathmodel-solve`：题意理解、路线比较、主路线与 fallback；
- `mathmodel-experiment`：真实执行、调试、验证和图表；
- `mathmodel-paper`：从真实 current 结果撰写和编译论文；
- `mathmodel-final-check`：一次机械 QA 和一次整体审查；
- `mathmodel-learn-paper`：离线学习论文，不进入比赛主链。

用户只要求数据分析、调试代码或修改论文时，不得自动启动完整工作流。完整赛题默认最多三个顶层任务：连续生产、一次整体审查、仅在存在 P0/P1 时的定向修复。

## v3 运行目录与状态

使用以下命令创建并行 v3 运行：

```powershell
python scripts/codex/init_run.py <problem_path> `
  --workflow capability-first-v3 --run-id <run-id>
```

或使用 `scripts/codex/init_simple_run.py`。v3 状态只在
`runs/<run-id>/state/run.json`，关键判断记录在 `state/DECISIONS.md`。它只保存进度、路线、下一步、预算和产物路径；不得保存科学是否通过、finding 是否关闭或任何审核状态。

v3 运行时只能使用 `shumozizi.simple`。禁止导入 `shumozizi.workflow.state_service`、审核模块或 legacy 结果准入链。

## 结果与执行

代码必须实际运行，不得编造数据、指标、图表或引用。执行统一使用：

```powershell
python scripts/runtime/run_simple_experiment.py runs/<run-id> `
  --question Q2 --kind primary --command "python code/q2.py" `
  --expect results/raw/q2.json
```

执行器保存命令、退出码、stdout/stderr、源脚本、输入输出路径与哈希。`results/index.json` 只证明运行事实；`current` 且 `paper_allowed=true` 的结果可以用于论文，但这不表示路线科学上优秀。

## 路线、预算和人工决策

先判断数学本质，再按需读取最多一到两个知识文件。生成两到三条实质不同的候选路线，先做最低成本 probe，再确定主路线与 fallback。实现错误直接修复；参数或求解器问题在路线内调整；fallback 更优时直接切换并记录。

只有改变题意解释、核心目标或必做输出，或者新增投入超过剩余预算 30% 时才询问用户。最终提交前可请求一次确认。连续两次无实质改善时停止，记录原因并收缩目标、切换 fallback 或请用户决定。

## 论文与终检

论文每问必须含题目要求、模型理由、核心公式、求解、关键结果、可信性检验、直接回答和边界。关键结果使用 `[[result:<id>]]`，关键数值使用 `[[metric:<id>.<metric>=<number>]]` 以便追溯和一致性检查。

机械终检使用：

```powershell
python scripts/qa/run_final_checks.py runs/<run-id>
```

它生成 `qa/mechanical-qa.json`、`qa/contact-sheet.png` 与 `reports/VERIFY_REPORT.md`，并只检查 PDF、路径、占位符、匿名、编号、图表可读性、结果引用与数值一致性等确定性问题。最终整体审查输出 `qa/FINAL_REVIEW.md`，按 P0–P3 定位问题；除重大模型、数据或结论修改外，不重复整篇审查。

## 代码与文件约束

- Python 模块、类和公共函数使用 Google 风格 docstring；注释使用中文并解释原因。
- 所有文件写入使用原子写入或同目录安全替换；路径必须限制在当前运行目录内。
- Windows 必须可运行；不依赖 Bash 作为唯一入口。
- 不启动 WebUI、Redis、旧多 Agent 框架、云端解释器、数据库或命令行 Codex 调度。
- 不自动提交或推送 Git。
- 不修改 `legacy/review-v2/` 的业务语义；必要的兼容工作仅限归档说明。
