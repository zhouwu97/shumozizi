---
name: mathmodel-solve
description: 解析数学建模题面与附件，比较候选目标的策略后果，比较 baseline 和竞争路线，设计区分性 probe、主路线与 fallback。
---

# 路线竞争

先比较相邻问题新增的实体、资源、共享约束和聚合层，再区分题目对象、目标、约束、单位、输出和问题依赖。两次 problem-only 重建固定为非对称职责：一次忠实重建决策变量、成功事件、聚合和输出；一次语义攻击专查量词次序、和/最小值/并集/交集、前问目标机械复制与分解失效，并构造能让两个解释排序相反的最小反例。两份重建一致只说明共识，不证明正确。

每个必答问题在提出复杂模型前先写直接答案合同，并进入 `MODELING_UNITS.json`：

- `required_output`：最终必须交付的数值、区间、分类、策略或解释；
- `decision_scope`：决策对象、目标总体、时间窗与适用场景；
- `primary_endpoint`：主估计量/主终点的名称、数学定义及其与 exact metric 的对应；
- `primary_criterion`：什么实测条件足以支持主答案；
- 自然 baseline 及其合理性；
- fallback 与可执行切换条件。

主终点必须在正式路线比较前显式声明。若 endpoint/聚合口径仍有合理歧义，标记 `comparison_planned`，登记至少两个候选 endpoint、题面依据和裁决规则，并运行候选后果 probe。实验结束必须写出 `actual_endpoint_resolution`；合理 endpoint 下路线翻转、行动漂移越界或缺少题意裁决依据时，答案资格由系统判为 `redesign_required / analysis`，不能降级成普通敏感性说明。

新运行使用 `MODELING_UNITS` 1.3。每问在答案合同前填写轻量 `question_delta`；新增实体、资源、共享约束、聚合词或分解后组合时必须重新检查目标。`primary_endpoint` 同时用自然语言和公式声明原子成功、实体内、资源间、实体间、时间和量词次序六项聚合。高风险问题复用这一处 `semantic_counterexample`，不在其它协议重复抄写。高风险核心问题在任何路线搜索前先运行 3--5 个人工评分案例，包括同时满足、错开满足、单主体长期满足、总量高但瓶颈为零，以及必要时多资源联合成功；评分器未按预期排序时先改 endpoint/scorer，不比较优化器。

目标候选使用 `OBJECTIVE_CANDIDATES` 1.1，顺序固定为“题面合法性 -> 同源反例区分 -> 仍合理候选的策略后果”。每个候选先声明题面原句、保留/改变的量词、引入的价值偏好、是否只为方便求解，并分为直接支持、合理假设支持、仅敏感性或与题意不符；只有前两类能成为正式目标。仅剩一个合法候选时不强迫跑多目标实验；仍有两个及以上时，才用共同的效率与公平/瓶颈/安全指标跑低成本后果 probe。高风险问题不能靠一句 `determined_basis` 跳过：必须明确正式目标、一个被拒绝替代及拒绝理由，并由 `MODELING_UNITS` 中的反例区分。

标出决定奖项上限的核心问题（`core_question=true`）。核心问题必须事前声明 `significant_improvement_ratio`，其竞争路线还要写清结构利用方式和可量化的 `expected_improvement_ratio`——纯文字的"高上限"事后无法与实测对照。

每题至少提出一个 baseline 和一条数学结构不同的竞争或反证路线。不要把只更换求解器的 GA、PSO、DE 当成不同路线。每条路线说明结构差异、最低成本 probe、潜在上限、失败方式和切换条件，写入 `analysis/ROUTE_COMPETITION.md`。

任何“分别求解再组合”的路线都必须声明为 `exact_decomposition`、`heuristic_decomposition` 或 `initialization_only`；精确分解给出等价依据，后两者必须继续接受联合 scorer 改进。无法证明可分、小规模对照不一致且又不继续联合优化时，不得把各子问题最优写成全局最优。

将有决策价值的实验排进 `analysis/NEXT_EXPERIMENTS.md`：它必须明确成功或失败会改变什么，以及失败后回到 analysis 还是 experiment。优先运行区分性 probe，再冻结主路线与 fallback。只登记用于资格计算的真实指标和阈值，不手填晋级结论。连续两轮不能超过 baseline、复杂度上升没有实质收益、优势只在 proxy、endpoint 排序翻转、guard 跌破下限或行动方案不稳定时，不得把弱赢家包装成最终建议；系统应选择已验证 fallback，或返回 analysis/experiment 重设计。

当单一加权分数掩盖效率、公平、瓶颈或安全冲突时，优先报告可靠性约束下的最优解、真实 Pareto 后果，或稳健/最小后悔决策。最终只保留一个主答案和一个明确 fallback，不并列多个同等地位答案让评委替作者决策。

仅当存在至少两个合理解释且会改变主要结果、题面不能排除、用户尚未裁决时，记录到 `analysis/objective-ambiguities.json` 并触发独立目标语义审查。
