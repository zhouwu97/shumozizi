---
name: mathmodel-review-r3-paper-logic
description: 在完整论文和 PDF 生成后独立检查逐问直接回答、公式、数字、claim 和证据链。
---

# R3 论文逻辑审核

## 执行主体

本 Skill 只能在用户新开的独立 Codex 桌面版顶层对话中执行。用户只负责提交审核请求；当前
对话中的审核 AI 必须自动完成领取、校验、逐问核对和报告写入，不得要求用户辅助判断或代填
报告。禁止使用子 Agent、fork、生产聊天上下文或生产主对话直接执行本审核。

## 输入文件

- 本轮 manifest、request、session、原始题面、配置锁和 `brief/model_spec.json`；
- request 声明的完整论文章节、`paper_plan.json`、`claim_gate.json`、accepted/paper_allowed sealed results、`QUESTION_ACCEPTANCE.json` 和 `final.pdf`；
- request 绑定的图表与引用映射。

## 禁止读取

- 作者解释、聊天记录、R1/R2/R4/R5/J0 报告和上一轮修复说明；
- 未在 request `read_paths` 中的文件；
- 禁止修改论文、数字、结果、claim gate 或 state。

## 执行步骤

1. 校验 manifest、request、session、全部材料哈希和当前 revision。
2. 按题目逐问建立“要求 → 模型输出 → accepted result → 章节直接回答”映射。
3. 逐项核对公式变量、单位、数字、baseline、uncertainty、限制和 claim status。
4. 检查 rejected/inconclusive claim 没有被写成已验证创新，且章节没有引用 revoked/superseded 结果。
5. 输出带定位证据的 finding，不进行作者修复。

## 基础 Skill 与脚本

- 基础能力：`mathmodel-paper`、`skills/5writing`、`paper.gate`；
- `python scripts/codex/validate_state.py runs/<run_id>`；
- `python scripts/runtime/gate_paper_claims.py runs/<run_id>`。

## Finding 证据格式

`evidence` 必须同时给出题目要求和论文/结果中的路径、章节、表格、公式或 PDF 页码；数字问题
附 result ID、metric_spec ID 和 claim gate 字段。每条 finding 同时声明 `change_level`、
`affected_questions`、`change_class`、`route_impact` 和 `changed_route_core_fields`；
问题所在阶段不得替代路线影响判断，只有最终有效等级为 `L5` 才要求路线重新批准。

## 严重度

- P0：某问未回答、核心数字无证据或结论与模型相反；
- P1：公式/单位/claim 权限/逐问映射不一致，足以误导结论；
- P2：措辞、限制、引用位置或非核心逻辑缺口。

## 通过条件

无 P0/P1，所有问题有直接答案和可追溯证据，论文 claim 与 evaluator 状态一致；verdict 为
`READY_FOR_COMPREHENSIVE_REVIEW`。否则为 `MAJOR_REVISION` 或 `NOT_READY`。

## 输出格式

只写 request 的 `review_report.json`，报告 verdict 只能使用既定三值，由协调器生成回执。

## 结束前自检

- [ ] 每问至少一条 direct-answer 证据；
- [ ] 每个摘要/结论数字可追溯到 accepted result；
- [ ] 没有越过 claim gate 的创新措辞；
- [ ] 没有读取前轮审核报告或作者解释。
