---
name: mathmodel-workflow
description: 以科学优先的 Competition-First v3.4 完成整道数学建模赛题；默认单主线、风险触发、结果冻结，局部分析或单独改稿不启动完整工作流。
---

# 科学优先数学建模工作流

本流程的目标是得到正确、有解释力、可交付的答案。运行日志、哈希、回执和审计文件是后台记录，不是科学目标，也不得进入作者上下文。

## 主链

```text
discovery → science_checkpoint → production → freeze → author → delivery
```

系统默认使用科学优先语义：一个主路线、至多一个结构不同的 challenger、一个针对最高风险的独立 reviewer。新 CLI 以 `science-editorial-v1` 质量策略承载该语义；也可显式传 `--execution-policy science-first-v1`。只有路线分歧无法裁决时，才启动第二套完整求解。旧运行和显式 `competition-quality-v1` 继续兼容。

初始化新运行：

```powershell
python scripts/codex/init_simple_run.py <problem_path> --run-id <run-id> --workflow-version 3.2 --question Q1
```

## 1. Discovery

允许自由记录题意解释、候选目标、反例、路线假设和低成本试算。此阶段不要求完整 `MODELING_UNITS`、图计划、工作簿、哈希或论文字段；探索结果只能登记为 `diagnostic`，不能冒充正式答案。

## 2. Science checkpoint

在 `analysis/science-checkpoint.json` 中确认：正式目标、信息集、时间和单位、结算与终端规则、聚合口径、自然 baseline、结构 challenger、统一 scorer，以及能够推翻路线的最小反例。`status=ready` 后才允许进入 production。人只在题意歧义、路线冻结和首个可行解挑战处介入。

可用 `python scripts/simple/manage_science_checkpoint.py status <run_dir>` 检查缺口，使用 `update <run_dir> --input <checkpoint.json> --status ready` 原子更新。

语义反例优先检查未来信息、伪滚动、重复计费、SOC/边界条件、预测器与误差库同源性、分解是否等价。普通格式和文档完整度不能替代这些检查。

## 3. Production

先在共同评价窗口运行 baseline 与 challenger，再从同一输入重跑唯一正式结果。生产结果必须是真实执行、输出新鲜、硬约束可行、账本一致，并登记到 `results/index.json`。同一问题允许多个历史结果，但只有明确选中的一个进入 `current`；被替换结果进入 `archive` 或标记失效。

参数只能由统一 scorer 的比较冻结；不得因为“已经运行过”或流程字段齐全而保留参数。固定评价、解析题和普通仿真不强迫路线赛马。任何“分别求解再组合”必须标明等价证明、启发式初值或联合优化结果。

## 4. Freeze

结果、图表、论文和工作簿全部单向绑定 `production_manifest`。manifest 记录每问的 `objective_answer`、正式结果、源码、输入、指标和输出路径；结果发生变化时，旧论文、图表和导出件自动失效。`recommended_plan` 和稳健 fallback 不能替换题面正式答案。

## 5. Author

只把 `RESEARCH_PACKAGE.md`、`AUTHOR_BRIEF.md` 和已关闭的高价值科学意见交给作者。作者不读取运行日志、协调器记录、内部 scorer/challenger 名称、哈希和修复台账。

写作前建立一张 `THESIS_CARD`：中心矛盾、最多三项贡献、每问机制判断、正式答案、边界和主图。作者可以合并问题、重排章节、调整图文节奏；不得把检查项改写成正文小节，也不得凭空补结果。

## 6. Delivery

只保留三个硬门：语义事实、生产事实、论文事实一致。冷读、文风、图表节奏和页数属于编辑建议；科学事实错误、数字漂移和 manifest 不一致才阻断交付。科学事实变化才返回 production，纯排版变化只重新渲染和机械 QA。

独立 PDF 冷读最多保留五项最高价值意见；外部评委和网页讨论是可选编辑工具，不是默认阶段门。

## 兼容规则

旧 `MODELING_UNITS`、`FIGURE_PLAN`、review JSON 和状态文件继续支持读取。兼容文件只能作为后台投影或旧运行硬门，不能让新 `science-first-v1` 运行重新回到旧的全协议链。
