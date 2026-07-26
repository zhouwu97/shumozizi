---
name: mathmodel-solve
description: 解析数学建模题面与附件，比较候选目标的策略后果，比较 baseline 和竞争路线，设计区分性 probe、主路线与 fallback。
---

# 路线竞争

先区分题目对象、目标、约束、单位、输出和问题依赖，再做不变量、界、消元、分解、事件边界、小规模 oracle 与可辨识性预检。

目标不要在实验前冻结。题面留有解释空间时，在 `analysis/OBJECTIVE_CANDIDATES.json` 保留至少两个候选目标，各自写出公式、预期偏好的策略和题面依据，并声明一组共同的后果度量：至少一个效率指标，以及至少一个公平、瓶颈或安全指标。只有跑过低成本后果 probe、看清各候选会产生什么策略之后才冻结。若冻结的目标让某个 guard 指标跌破可接受下限而其它候选没有，必须写出显式权衡裁决并绑定至少两点真实 Pareto 证据。题意歧义仍未决时不得声明 `determined` 跳过比较。

标出决定奖项上限的核心问题（`core_question=true`）。核心问题必须事前声明 `significant_improvement_ratio`，其竞争路线还要写清结构利用方式和可量化的 `expected_improvement_ratio`——纯文字的"高上限"事后无法与实测对照。

每题至少提出一个 baseline 和一条数学结构不同的竞争或反证路线。不要把只更换求解器的 GA、PSO、DE 当成不同路线。每条路线说明结构差异、最低成本 probe、潜在上限、失败方式和切换条件，写入 `analysis/ROUTE_COMPETITION.md`。

将有决策价值的实验排进 `analysis/NEXT_EXPERIMENTS.md`：它必须明确成功或失败会改变什么。优先运行区分性 probe，再冻结主路线与 fallback。连续两轮不能超过 baseline、复杂度上升没有实质收益、优势只在 proxy、或无法提炼题目特定贡献时，考虑切换。

仅当存在至少两个合理解释且会改变主要结果、题面不能排除、用户尚未裁决时，记录到 `analysis/objective-ambiguities.json` 并触发独立目标语义审查。
