---
name: mathmodel-review-r2-experiment
description: 按问独立复现实验、指标 provenance、约束和 accepted result，确认结果可进入论文。
---

# R2 实验复现审核

## 执行主体

本 Skill 只能在用户新开的独立 Codex 桌面版顶层对话中执行。用户只负责提交审核请求；当前
对话中的审核 AI 必须自动完成领取、校验、复现、判断和报告写入，不得要求用户辅助运行实验、
判断结果或代填报告。禁止使用子 Agent、fork、生产聊天上下文或生产主对话直接执行本审核。

## 输入文件

- 当前问的 `REVIEW_INPUT_MANIFEST.json`、`review_request.json`、`review_session.json` 和配置锁；
- request `read_paths` 中的 execution manifest、execution record、代码、输入输出、metric provenance、sealed result 和实验计划；
- 原始题面中与该问直接相关的要求。

## 禁止读取

- 作者解释、聊天记录、R1/R3-R5 报告和上一轮 R2 报告；
- 未在 request 中声明的结果、图表或代码；
- 禁止修改候选、注册表、sealed result、论文和 state。

## 执行步骤

1. 校验 manifest、request、session 绑定及 `R2_EXPERIMENT_<question_id>` 题号。
2. 在查看 primary 结果前，核对实验计划中预注册的 oracle；至少选择一种能证伪核心结论的 oracle。
3. 运行 `python scripts/runtime/verify_execution.py` 或等价的只读复验，检查退出码、输入/输出哈希、随机种子和预期产物。
4. 独立检查数据划分与重复测量边界、时间/目标泄漏、指标对目标的适用性、单位、硬约束和解的可信度。
5. 检查参数可辨识性与多初值稳定性、结论是否超出证据，以及 robustness/ablation 的扰动是否足以区分竞争模型。
6. 在允许预算内复现一次并执行预注册 oracle；环境不足时明确区分 `unknown` 与 `challenged`。
7. 记录图表是否来自 accepted sealed result，不对生产文件做修复。

## 双轴报告

`review_report.json` v3 必须分别写入：

- `execution_reproducibility`：`code_execution`、`config_reproducibility`、`hash_integrity`、
  `random_seed_control`、`result_figure_consistency`、`accepted_result_seal`；
- `scientific_correctness`：`split_design`、`leakage_control`、`metric_suitability`、
  `constraint_completeness`、`solution_credibility`、`parameter_stability`、
  `conclusion_bounds`、`robustness_discrimination`。

每项状态只能是 `verified`、`challenged`、`unknown` 或 `not_applicable`，并附定位证据。
任一 `challenged` 或 `unknown` 都必须有同 `check_id` 的 finding；`unknown` finding 必须用
`recommended_resolution` 进入 probe、独立二审或人工决定，不能自动通过。

`preregistered_oracles` 必须在查看 primary 结果前冻结，类型只能选自 `exact_solution`、
`small_instance_exhaustive_solution`、`synthetic_recovery`、`independent_implementation`、
`known_limiting_case`、`permutation_null`、`multiple_start_consistency`、`grid_convergence` 或
`constraint_feasibility_oracle`。每项必须给出问题、成功条件和证据路径，禁止事后按结果改 oracle。

## 基础 Skill 与脚本

- 基础能力：`mathmodel-experiment`、`skills/3coding-visual` 的 provenance 要求；
- `python scripts/runtime/verify_execution.py`；
- `python scripts/codex/validate_state.py runs/<run_id>`。

## Finding 证据格式

`evidence` 至少包含 execution record、metric_spec 或 sealed result 的相对路径及字段/哈希；
复现数值必须记录单位、容差和命令退出码。每条 finding 同时声明 `change_level`、
`affected_questions`、`change_class`、`route_impact` 和 `changed_route_core_fields`；
问题所在阶段不得替代路线影响判断，只有最终有效等级为 `L5` 才要求路线重新批准。

## 严重度

- P0：结果来自伪造/缺失执行，或硬约束、单位和核心指标错误；
- P1：不可复现、baseline 不公平、provenance 断裂或 accepted 结果无效；
- P2：随机性、日志、图表来源或次要诊断记录不完整。

## 通过条件

无 P0/P1，执行证据、指标、约束、baseline 和 seal 均可复验；允许无阻断的 P2 时使用
`REPRODUCIBLE_WITH_WARNINGS`，否则使用 `REPRODUCIBLE` 或 `BLOCKED`。

## 输出格式

按 request 唯一路径写 `review_report.json`，由协调器物化回执。verdict 只能是
`REPRODUCIBLE`、`REPRODUCIBLE_WITH_WARNINGS`、`BLOCKED`。

## 结束前自检

- [ ] 未读取其他审核报告或作者解释；
- [ ] 每个核心指标都有 provenance 和单位；
- [ ] 复现命令、退出码、容差和哈希均有证据；
- [ ] 报告只写 review 目录并通过 Schema。
