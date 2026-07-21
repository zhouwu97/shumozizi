---
name: mathmodel-review-r1-modeling
description: 在正式实验前以全新上下文独立审核题意、模型规格、变量、目标、约束和验证计划。
---

# R1 建模审核

## 执行主体

本 Skill 只能在用户新开的独立 Codex 桌面版顶层对话中执行。用户只负责提交审核请求；当前
对话中的审核 AI 必须自动完成领取、校验、审核和报告写入，不得要求用户辅助逐项检查或代填报告。
禁止使用子 Agent、fork、生产聊天上下文或生产主对话直接执行本审核。

## 审核模式

`full_scientific` 执行下述 Phase A/B 和完整 coverage。`targeted_recheck` 只读取 request 中的
`original_finding`、`source_adjudication`、`before_after_diff`、`repair_evidence` 和
`direct_dependencies`，不得执行 Phase A、重读完整题面或重新扫描整份模型规格。`diff_check`
与 `machine_check` 只执行各自 request 声明的局部或确定性检查，不得伪装为完整 R1。

## 输入文件与两阶段隔离

Phase A 只允许读取原始题面、官方附件、比赛规则、问题清单、数据字典、数据概况和必要的单位
说明。禁止读取作者路线、`route_candidates`、`ROUTE_LOCK`、`model_spec`、作者 validation plan、
知识检索输出或论文卡。Phase A 必须完整输出 `required_outputs`、`decision_variables`、
`observable_variables`、`latent_variables`、`units`、`hard_constraints`、`boundary_conditions`、
`plausible_model_families`、`identifiability_risks`、`minimum_validation_requirements` 和
`possible_failure_modes`，并通过 `create_r1_phase_a()` 写入不可覆盖的 `PHASE_A.json`。

Phase B 只能在 `verify_r1_phase_a()` 复验输入与文件哈希后开始。正式
`REVIEW_INPUT_MANIFEST.json`、`review_request.json` 和 `review_session.json` 必须绑定
`phase_a`；此后才允许读取候选路线、路线锁、模型规格、validation plan 和实验预算，并对照
Phase A 判断作者是否漏问、模型族是否匹配机制、参数是否可辨识、输出是否回答题问、约束是否
完整，以及验证是否能区分正确与错误模型。

## 禁止读取

- 作者解释、聊天记录和未在 request 中声明的路径；
- Phase A 中的任何作者路线、模型规格、验证计划或论文知识材料；
- 任何实验结果、论文草稿、R2-R5 报告或上一轮修复说明；
- `runs/*/review` 中其他任务的报告；
- 禁止修改生产代码、结果、论文和 state。

## 执行步骤

1. 在 Phase A 独立重构题意和最低科学验证要求，并哈希冻结 `PHASE_A.json`。
2. 领取 Phase B 请求，校验 manifest、request、session、当前 revision、配置锁、Phase A 和全部绑定哈希。
3. **先进行独立科学分析**：在填写 coverage 或 finding 表格之前，独立分析题意、数据机制、
   作者结论、替代解释、反例、失败模式和可证伪方法。不得把 coverage 顺序当作推理顺序；
   允许发现不属于任何已有 `check_id` 的问题。无法确定时保留 `unknown`，不得为了填满清单
   而写 `verified`。
4. **再做结果映射**：完成独立分析后，把判断映射到 coverage 和 findings。coverage 只记录
   基础检查状态，不是推理步骤，也不是模型正确性评分。清单外科学问题可使用 `check_id=null`，
   仍需提供证据和建议验证方式。
5. 对照 Phase A 检查每个模型输出、机制、可辨识性、变量单位、目标、硬约束和边界条件；检查
   数据划分、指标、停止规则、失败边界，以及 baseline、primary、robustness/ablation 的辨识力和预算。
6. 复验 `analysis/MINIMUM_SCIENTIFIC_CONTRACT.md` 已在正式实验前冻结 required outputs、核心
   目标、硬约束、baseline、primary 模型族、数据划分、主要指标、positive control、失败判据、
   fallback 触发条件和实验预算；事后放宽失败判据或删除 fallback 条件必须重新判断路线。
7. 在允许进入实验前明确回答路线存活问题：题目目标、模型输出与评价指标是否同向；最低成本
   正控制是什么；什么观测会证明路线失败；fallback 是否与 primary 实质不同且能在剩余预算内启动。
   未预注册正控制、失败判据或真实 fallback 时，不能仅因模型规格完整而判路线值得投入。
8. 只写本轮报告；不替作者裁决 finding、生成回执或修复。

## 路线存活结论

R1 不使用跨题统一数值阈值。判断必须来自题目容许误差、工程尺度、决策边界、baseline、搜索域
或领域合理范围，并在 finding 证据中写明依据。若评价指标与题目目标错位、required output 无法由
模型输出得到，或最低正控制本身不可执行，至少给出 P1；若已足以证明路线无法回答必做问题，
建议 P0。R1 只判断“是否值得进入最小实验”，不要求一次锁死所有实现细节。

## 基础 Skill 与脚本

- 基础能力：`mathmodel-route`、`mathmodel-experiment` 的规格术语；
- `python scripts/codex/validate_state.py runs/<run_id>`；
- 必要时使用结构化 Schema 校验器，不运行正式实验。

## Finding 证据格式

v3 reviewer finding 只需说明问题本身：`finding_id`、`severity_recommendation`、`title`、
`claim`、`evidence`、`why_it_may_be_wrong`、`confidence` 和 `status`；可选 `check_id`
（清单外问题填 `null`）与
`recommended_resolution`。生产返工等级、影响题号和路线影响由主 AI 在 adjudication 中裁决，
不得由 reviewer 报告预先决定。证据不得使用聊天记忆或未声明文件。

targeted recheck 只能复核原 finding、修改范围和直接依赖；不得新增无关 P2/P3。新增 P0/P1
必须提供 `reopen_context`，说明与修改的关系、此前无法合理发现的原因、重新打开证据和建议
理由。`deferred_empirical` 必须同时声明 `block_before`、`closure_condition` 和
`failure_action`。`block_before=model_selection` 的义务可在 `EXPERIMENTING` 或
`RESULTS_ACCEPTED` 由绑定同一完整根与 finding 的 `targeted_recheck` 关闭；关闭状态必须由真实
closure 回执重建。

`full_scientific` 报告还必须提供 `coverage`：逐项给出题意解释、问与输出映射、变量完整性、数据与附件映射、单位、方程闭合、
参数可辨识性、目标、约束、算法、停止规则、基线、模型选择准则、不确定性、稳健性/消融、
失败边界和证据计划的 `verified`、`challenged`、`unknown` 或 `not_applicable`，并且
`unchecked_items` 必须为空。每个 `challenged` 必须有对应 `check_id` 的 finding；每个 `unknown`
也必须有 finding，并用 `recommended_resolution` 指定 `needs_probe`、`needs_second_review` 或
`needs_human_decision`。禁止把未知项当成通过。

Schema、Python 常量和本 Skill 共用以下精确集合；目标与约束是两个独立项：

<!-- R1_REQUIRED_CHECK_IDS_START -->
```text
problem_interpretation
question_output_mapping
variable_completeness
data_and_attachment_mapping
unit_consistency
equation_closure
parameter_identifiability
objective_definition
constraint_completeness
algorithm_executability
stopping_rule
baseline_design
model_selection_criterion
uncertainty_quantification
robustness_and_ablation
failure_boundary
evidence_plan
```
<!-- R1_REQUIRED_CHECK_IDS_END -->

参数可辨识性、模型选择准则和不确定性填 `verified` 时，模型规格必须分别具有参数来源/估计、
边界与可辨识说明，比较准则/对象/方向，以及方法、输出口径和计算次数或区间口径。

以下五项填 `verified` 时，每问 `r1_evidence` 还必须提供结构化最低证据：

- `data_and_attachment_mapping`：源文件/字段、模型变量、源/目标单位、转换规则、派生变量公式，
  以及缺失和异常处理；没有派生变量时必须明确原因；
- `equation_closure`：方程、已声明符号和可计算输出符号，所有声明符号必须存在于变量表；
- `stopping_rule`：迭代上限、容差和收敛条件，或解析解声明，同时提供失败处理和 fallback；
- `baseline_design`：baseline ID、与 primary 相同的输入口径、共同指标和比较规则；
- `evidence_plan`：与 `PROBLEM_MANIFEST.json` 每个必做输出精确对应的实验/结果 ID、图表 ID 和
  论文章节。

运行时预检只保证最低结构证据存在，不替代审核员判断公式、方法和实验设计质量。

路线影响、修改等级和复测范围不属于 v3 reviewer finding；只有主 AI 在 adjudication 中形成
最终有效等级后，才判断是否需要路线重新批准。`affected_stage=R1_MODELING` 本身绝不代表
需要重新批准路线。

## 严重度

- P0：题意、核心目标或硬约束错误，导致结果无效；
- P1：模型无法回答一问、关键变量/单位/验证缺失，或路线与锁不一致；
- P2：不影响核心可行性的假设、记录或解释缺口。

## 通过条件

无 P0/P1，且题面、模型规格、约束、验证计划和每问输出一一对应；可以进入正式实验。
无 finding 时为 `ACCEPT`；仅有不影响路线的 P2/P3 时为
`ACCEPT_WITH_MINOR_FIXES`；规格不完整但路线核心不变时为
`SPEC_REVISION_REQUIRED`；只有题意解释或路线核心变化时为
`ROUTE_REAPPROVAL_REQUIRED`；审核材料不足时为 `BLOCKED_MISSING_INPUT`。

## 输出格式

按 request 的唯一 `output_path` 写 `review_report.json` v3，并绑定 `phase_a_sha256`。审核对话到此
结束，不生成生产回执。报告返回生产主对话后，由主 AI 写入 `REVIEW_ADJUDICATION.json`，再生成
绑定裁决哈希的 `review_receipt.json`；报告 verdict 只能是 `ACCEPT`、`ACCEPT_WITH_MINOR_FIXES`、
`SPEC_REVISION_REQUIRED`、`ROUTE_REAPPROVAL_REQUIRED` 或 `BLOCKED_MISSING_INPUT`。

## 结束前自检

- [ ] 只读取 request 的 `read_paths`；
- [ ] 每个 P0/P1 有可定位证据和建议验证方式；
- [ ] `read_only_confirmed=true`；
- [ ] 报告绑定当前 request、input manifest 和不可变 session 的 SHA-256；
- [ ] 报告 Schema、request_id、run_id、stage、review_round_id 全部匹配。
