---
name: mathmodel-review-r1-modeling
description: 在正式实验前以全新上下文独立审核题意、模型规格、变量、目标、约束和验证计划。
---

# R1 建模审核

## 输入文件

- 当前运行目录的 `state.json`、`config/RUN_CONFIG_LOCK.json`；
- 原始题面及题目附件；
- `brief/ROUTE_LOCK.json`、`brief/model_spec.json` 和模型规格引用的验证计划；
- request 声明的 `read_paths`，仅限这些文件。

## 禁止读取

- 作者解释、聊天记录和未在 request 中声明的路径；
- 任何实验结果、论文草稿、R2-R5 报告或上一轮修复说明；
- `runs/*/review` 中其他任务的报告；
- 禁止修改生产代码、结果、论文和 state。

## 执行步骤

1. 校验 request、当前 revision、配置锁和所有绑定哈希。
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
`remediation` 和 `status`。证据不得使用聊天记忆或未声明文件。

## 严重度

- P0：题意、核心目标或硬约束错误，导致结果无效；
- P1：模型无法回答一问、关键变量/单位/验证缺失，或路线与锁不一致；
- P2：不影响核心可行性的假设、记录或解释缺口。

## 通过条件

无 P0/P1，且题面、模型规格、约束、验证计划和每问输出一一对应；可以进入正式实验。
仅 P2 时 verdict 为 `ACCEPT_WITH_FIXES`，否则为 `ACCEPT` 或 `REBUILD`。

## 输出格式

按 request 的唯一 `output_path` 写 `review_report.json`，随后由审核协调器生成
`review_receipt.json`；报告 verdict 只能是 `ACCEPT`、`ACCEPT_WITH_FIXES`、`REBUILD`。

## 结束前自检

- [ ] 只读取 request 的 `read_paths`；
- [ ] 每个 P0/P1 有可定位证据和修复建议；
- [ ] `read_only_confirmed=true`；
- [ ] 报告 Schema、request_id、run_id、stage、review_round_id 全部匹配。
