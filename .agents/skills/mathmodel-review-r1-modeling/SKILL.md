---
name: mathmodel-review-r1-modeling
description: 在正式实验前以全新上下文独立审核题意、模型规格、变量、目标、约束和验证计划。
---

# R1 建模审核

## 输入文件

- 本轮 `REVIEW_INPUT_MANIFEST.json`、`review_request.json` 和已领取的 `review_session.json`；
- manifest 强制绑定的原始题面、附件清单、问题清单、配置锁、候选路线和路线锁；
- manifest 强制绑定的模型规格、数据字典、数据剖面和验证计划；
- request 声明的 `read_paths`，且只能是 manifest materials 的子集。

## 禁止读取

- 作者解释、聊天记录和未在 request 中声明的路径；
- 任何实验结果、论文草稿、R2-R5 报告或上一轮修复说明；
- `runs/*/review` 中其他任务的报告；
- 禁止修改生产代码、结果、论文和 state。

## 执行步骤

1. 校验 manifest、request、session、当前 revision、配置锁和所有绑定哈希。
2. 对照题面逐条列出 required outputs、变量单位、目标函数、硬约束和边界假设。
3. 检查每个模型输出能否回答题问，验证指标、数据划分、停止规则和失败边界是否可执行。
4. 检查 baseline、primary、robustness/ablation 计划是否属于同一路线且预算有界。
5. 只写本轮报告和回执；不替作者修复。

## 基础 Skill 与脚本

- 基础能力：`mathmodel-route`、`mathmodel-experiment` 的规格术语；
- `python scripts/codex/validate_state.py runs/<run_id>`；
- 必要时使用结构化 Schema 校验器，不运行正式实验。

## Finding 证据格式

每条 finding 必须包含 `finding_id`、`severity`、`title`、`evidence`（文件路径、字段或行号）、
`remediation`、`status`、`change_level`、`affected_questions`、`change_class`、
`route_impact` 和 `changed_route_core_fields`。证据不得使用聊天记忆或未声明文件。

报告还必须提供 `coverage`：逐项给出题意解释、问与输出映射、变量完整性、数据与附件映射、单位、方程闭合、
参数可辨识性、目标、约束、算法、停止规则、基线、模型选择准则、不确定性、稳健性/消融、
失败边界和证据计划的 `pass`/`fail`，并且 `unchecked_items` 必须为空。每个 `fail` 必须有
对应 `check_id` 的 finding；不能只报告发现的几个问题后结束审核。

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

参数可辨识性、模型选择准则和不确定性填 `pass` 时，模型规格必须分别具有参数来源/估计、
边界与可辨识说明，比较准则/对象/方向，以及方法、输出口径和计算次数或区间口径。

以下五项填 `pass` 时，每问 `r1_evidence` 还必须提供结构化最低证据：

- `data_and_attachment_mapping`：源文件/字段、模型变量、源/目标单位、转换规则、派生变量公式，
  以及缺失和异常处理；没有派生变量时必须明确原因；
- `equation_closure`：方程、已声明符号和可计算输出符号，所有声明符号必须存在于变量表；
- `stopping_rule`：迭代上限、容差和收敛条件，或解析解声明，同时提供失败处理和 fallback；
- `baseline_design`：baseline ID、与 primary 相同的输入口径、共同指标和比较规则；
- `evidence_plan`：与 `PROBLEM_MANIFEST.json` 每个必做输出精确对应的实验/结果 ID、图表 ID 和
  论文章节。

运行时预检只保证最低结构证据存在，不替代审核员判断公式、方法和实验设计质量。

`change_class` 只能是 `SPEC_CLARIFICATION`、`SPEC_COMPLETION`、
`IMPLEMENTATION_DETAIL`、`VALIDATION_DETAIL`、`EVIDENCE_METADATA`、
`EXPERIMENT_DESIGN_CHANGE`、`ROUTE_CORE_CHANGE` 或
`PROBLEM_INTERPRETATION_CHANGE`。后两类或 `route_impact=material` 应推导为 `L5`；只有最终
有效等级为 `L5` 才属于路线漂移，`affected_stage=R1_MODELING` 本身绝不代表需要重新批准路线。

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

按 request 的唯一 `output_path` 写 `review_report.json`，随后由审核协调器生成
`review_receipt.json`；报告 verdict 只能是 `ACCEPT`、`ACCEPT_WITH_MINOR_FIXES`、
`SPEC_REVISION_REQUIRED`、`ROUTE_REAPPROVAL_REQUIRED` 或 `BLOCKED_MISSING_INPUT`。

## 结束前自检

- [ ] 只读取 request 的 `read_paths`；
- [ ] 每个 P0/P1 有可定位证据和修复建议；
- [ ] `read_only_confirmed=true`；
- [ ] 报告绑定当前 request、input manifest 和不可变 session 的 SHA-256；
- [ ] 报告 Schema、request_id、run_id、stage、review_round_id 全部匹配。
