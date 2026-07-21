---
schema_name: scientific_viability
schema_version: '2.0'
run_id: quality-first-replay
question_scope:
- Q1
- Q2
- Q3
verdict: ROUTE_FAILED
failure_origin: route
evaluated_at: '2026-07-21T00:14:15Z'
threshold_basis: 以冻结的 0.5-500 μm 搜索域、预注册正控制、最佳单角度 baseline 和题目要求的厚度判定为依据
highest_risk: 当前联合反演路线无法稳定恢复物理厚度，也不能可靠区分双光束与多光束模型
counterexample: 若路线有效，应在已知厚度的合成谱上恢复真值，并在可分 DB/TMM 正例上正确选择模型
falsification_experiment: 运行 Q1/Q2 合成厚度恢复和 Q3 DB/TMM 模型选择正控制，并与单角度及解析 baseline 同口径比较
experiment_result: Q1 最大合成偏差 849.51%，Q2 合成中位偏差 81.47%，Q3 模型选择正确率 50%
baseline_fallback_comparison: 双角度联合反演相对最佳单角度增益为 -1.374%，TMM 相对 DB 改善仅 6.726174e-10
decision_reason: 正控制、信息量和复杂模型增益同时失败，继续调同一联合反演不能恢复题目所需厚度判定
next_action: 停止联合反演 primary，保留 DB 与峰间距 baseline，返回路线竞争并重建可辨识输出
action_status: completed
remaining_time_minutes: 724
investment_limit_minutes: 90
sources:
- path: SOURCE_SNAPSHOT.md
  sha256: 570b8ed13143a18de51e83f69ef78ac6ab0e93c0bc9de3afdcfe6334536c9fd8
---

# Scientific Viability Check

## Current Highest Risk

当前最高风险不是排版或 provenance，而是附件数据下的联合反演路线既不能稳定恢复厚度，也不能
可靠完成 DB/TMM 模型选择，继续投入会把无信息量输出加工成形式完整的论文。

## Falsifying Counterexample

若路线具备题目价值，它至少应在已知厚度合成谱上恢复真值，并在特意构造的 DB/TMM 可分正例
上选对模型。任一最低正控制失败，都足以推翻“可在真实附件上给出可靠厚度与模型判断”。

## Minimum Falsification Experiment

使用已有 Q1/Q2 合成恢复、Q3 模型选择正控制和同输入 baseline，直接比较恢复误差、区间宽度和
模型选择正确率。这些实验已经真实运行，无需等待 R3-R5 或完整 PDF。

## Actual Result

Q1 最大合成偏差为 849.51%，Q2 合成中位偏差为 81.47%，Q3 模型选择正确率仅 50%。Q2/Q3
区间从 0.5 μm 延伸到百微米量级，不能支持厚度决策。

## Baseline And Fallback Comparison

双角度联合相对最佳单角度的中位增益为 -1.374%，TMM 相对 DB 的改善仅 6.726174e-10。复杂
路线没有提供足以抵偿成本的信息价值；峰间距和群光学厚度应作为低复杂度 fallback 先验证。

## Decision And Reason

总体判定 `ROUTE_FAILED`，来源为 `route`。Q1 的局部实现仍可单独排查，但 Q2/Q3 已证明当前
联合路线不能作为全文中心；停止 primary，保留失败证据并返回路线竞争。

## Remaining Budget And Investment Limit

状态历史显示 Q2 首轮结果约在 00:14 完成，正式论文约在 12:18 组装，回放时尚有约 724 分钟的
实际观察窗口。只允许最多 90 分钟比较峰间距 fallback 和可分 DB/TMM 正例，失败后不再调参。

## Scientific Dimensions Synthesis

Direct Answer 只有形式覆盖，Q2/Q3 没有可用厚度判定；Information Value 因近全域区间而失败；
Positive-Control Capability 在合成恢复和模型选择上失败；Repairability 需要改变可辨识输出或
路线中心，已超出同模型族局部修复。因此不能进入正式全文组装。
