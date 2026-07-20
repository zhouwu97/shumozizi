---
name: mathmodel-review-r2-experiment
description: 按问独立复现实验、指标 provenance、约束和 accepted result，确认结果可进入论文。
---

# R2 实验复现审核

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
2. 运行 `python scripts/runtime/verify_execution.py` 或等价的只读复验，检查退出码、输入/输出哈希、随机种子和预期产物。
3. 复核 metric provenance、单位、基线引用、硬约束、验证检查和 sealed result seal。
4. 在允许预算内复现一次；若环境不具备复现条件，明确区分 BLOCKED 与可复现警告。
5. 记录图表数据是否来自 accepted result，不对生产文件做修复。

## 基础 Skill 与脚本

- 基础能力：`mathmodel-experiment`、`skills/3coding-visual` 的 provenance 要求；
- `python scripts/runtime/verify_execution.py`；
- `python scripts/codex/validate_state.py runs/<run_id>`。

## Finding 证据格式

`evidence` 至少包含 execution record、metric_spec 或 sealed result 的相对路径及字段/哈希；
复现数值必须记录单位、容差和命令退出码。每条 finding 同时声明 `change_class`、
`route_impact` 和 `changed_route_core_fields`；问题所在阶段不得替代路线影响判断。

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
