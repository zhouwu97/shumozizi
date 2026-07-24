---
name: mathmodel-solve
description: 解析数学建模题面与附件，比较 baseline 和竞争路线，设计区分性 probe、主路线与 fallback。
---

# 路线竞争

先区分题目对象、目标、约束、单位、输出和问题依赖，再做不变量、界、消元、分解、事件边界、小规模 oracle 与可辨识性预检。

每题至少提出一个 baseline 和一条数学结构不同的竞争或反证路线。不要把只更换求解器的 GA、PSO、DE 当成不同路线。每条路线说明结构差异、最低成本 probe、潜在上限、失败方式和切换条件，写入 `analysis/ROUTE_COMPETITION.md`。

将有决策价值的实验排进 `analysis/NEXT_EXPERIMENTS.md`：它必须明确成功或失败会改变什么。优先运行区分性 probe，再冻结主路线与 fallback。连续两轮不能超过 baseline、复杂度上升没有实质收益、优势只在 proxy、或无法提炼题目特定贡献时，考虑切换。

仅当存在至少两个合理解释且会改变主要结果、题面不能排除、用户尚未裁决时，记录到 `analysis/objective-ambiguities.json` 并触发独立目标语义审查。
