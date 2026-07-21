---
schema_name: scientific_viability
schema_version: '2.0'
run_id: REPLACE_RUN_ID
question_scope:
- REPLACE_QUESTION_ID
verdict: PENDING
failure_origin: null
evaluated_at: null
threshold_basis: 待根据题目误差、工程尺度、决策边界、baseline 或搜索域说明
highest_risk: 待评估
counterexample: 待设计
falsification_experiment: 待执行
experiment_result: 待记录真实结果
baseline_fallback_comparison: 待比较
decision_reason: 待评估
next_action: 待根据实验结果决定
action_status: pending
remaining_time_minutes: null
investment_limit_minutes: null
sources: []
---

# Scientific Viability Check

## Current Highest Risk

只写当前最可能使路线失败的一个核心原因。

## Falsifying Counterexample

给出能够推翻当前路线的具体反例或应当通过的正例条件。

## Minimum Falsification Experiment

说明成本最低且结果会改变路线决策的实验。

## Actual Result

引用真实执行结果及冻结来源，不使用计划值。

## Baseline And Fallback Comparison

直接比较 primary、baseline 与 fallback；未完成的比较明确写为未完成。

## Decision And Reason

给出 verdict、理由和会改变的下一步行动。

## Remaining Budget And Investment Limit

记录判断时真实剩余分钟数和下一步允许投入的分钟上限。

## Scientific Dimensions Synthesis

连续论证 Direct Answer、Information Value、Positive-Control Capability 和 Repairability，禁止写成
四项 pass/fail 打勾表。
