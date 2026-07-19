---
name: mathmodel-workflow
description: 启动或继续完整数学建模竞赛工作流。仅在用户明确要求完成整道赛题、可运行实验、图表和论文时使用；必须在路线确认与最终论文审核处停止，不能因单项数据分析请求而隐式启动。
---

# 数学建模完整工作流

把 `runs/<run_id>/state.json` 作为唯一状态来源，运行到下一个人工确认点后立即停止。

## 启动或恢复

1. 确认用户明确要求完整工作流；否则不要使用本 Skill。
2. 找到用户指定的运行目录。没有运行目录时执行：
   `python scripts/codex/init_run.py <problem_path> --run-id <run_id>`。
3. 完整读取 `state.json`，再决定下一步；不要仅根据聊天记录判断阶段。
4. 先执行 `python scripts/codex/validate_state.py runs/<run_id>`。若校验失败，修复状态文件后再继续。

## 状态路由

| 当前状态 | 行为 | 下一状态 |
| --- | --- | --- |
| `NEW` | 调用 `$mathmodel-route` | `WAITING_HUMAN_ROUTE` |
| `WAITING_HUMAN_ROUTE` | 只检查人工填写的 `brief/ROUTE_LOCK.json`；未批准则停止 | `ROUTE_LOCKED` |
| `ROUTE_LOCKED` | 完整读取 `skills/2analysis-modeling/SKILL.md`，按锁定路线生成数学规格 | `MODEL_SPEC_READY` |
| `MODEL_SPEC_READY` / `EXPERIMENTING` | 对每问调用 `$mathmodel-experiment`，每问结果接受后调用 `$mathmodel-paper` | `RESULTS_ACCEPTED` |
| `RESULTS_ACCEPTED` | 用 `$mathmodel-paper` 完成摘要、结论和全文组装 | `PAPER_DRAFTED` |
| `PAPER_DRAFTED` | 调用 `$mathmodel-review` | `WAITING_HUMAN_FINAL` |
| `WAITING_HUMAN_FINAL` | 只处理人工终审意见；未明确批准则停止 | `COMPLETE` |
| `COMPLETE` | 报告产物与复现命令，不再改动 | `COMPLETE` |

## 路线确认

在第一次调用 `$mathmodel-route` 后，确认这些文件已经生成：

- `brief/ROUTE_BRIEF.md`
- `brief/route_candidates.json`
- `state.json` 中 `status=WAITING_HUMAN_ROUTE`

随后停止。不得自动替人工选择路线，不得生成 `ROUTE_LOCK.json` 的批准内容。

用户确认后，检查路线锁至少包含：题意解释、主路线、备用路线、基线、创新、验证和预算。
只有完整运行 `validate_state.py` 且 `approved=true` 时才能把状态改为 `ROUTE_LOCKED`。

## 执行主链

路线锁定后按以下顺序推进：

1. 完整读取 `skills/2analysis-modeling/SKILL.md`，只采用已锁路线，生成可编码的数学规格。
2. 逐子问题调用 `$mathmodel-experiment`。不要并行启动多个 Agent。
3. 每个子问题有已接受结果后立即调用 `$mathmodel-paper` 写对应章节。
4. 仅当论文需要解释方法链路时，完整读取并使用 `skills/4drawio/SKILL.md`。
5. 全部子问题完成后用 `$mathmodel-paper` 汇总摘要、结论、优缺点和推广。
6. 调用 `$mathmodel-review`，运行到 `WAITING_HUMAN_FINAL` 并停止。

## 预算和漂移

每问只允许 baseline、primary、robustness/ablation 三个主要循环。普通调参、修代码、换求解器
和改图表不算漂移。改变题意、目标函数、核心约束、模型类别或未批准路线，以及新增实验占
剩余预算 30% 以上时，写入 `review/ROUTE_DRIFT_MEMO.md`，把状态改回
`WAITING_HUMAN_ROUTE`，然后停止。

## 完成终审

只有用户明确批准最终论文后，才把状态改为 `COMPLETE`。若用户要求小改，执行一次小范围修订
和快速复检，再回到 `WAITING_HUMAN_FINAL`；不得开启新一轮完整审稿。
