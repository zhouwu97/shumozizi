---
name: mathmodel-review-r5-comprehensive
description: 在机械 QA 通过后以全新上下文执行有界全面盲审，输出 A-E 评级和证据。
---

# R5 全面盲审

## 输入文件

- 本轮 manifest、request、session、原始题面及比赛允许附件；
- 当前冻结的 final PDF、必要代码/结果证据和 request 声明的路径；
- 当前 QA 通过报告和配置锁，仅用于验证冻结包。

## 禁止读取

- 作者解释、聊天记录、R1-R4/J0 报告、上一轮 R5、修复说明、目标奖项或路线争论；
- 未在 request `read_paths` 中的文件；
- 禁止修改任何生产文件、state 或审核报告。

## 执行步骤

1. 校验 manifest、request、session、QA 通过状态、绑定哈希和当前冻结 revision。
2. 只从评委可见材料判断题目覆盖、结果可信度、论文表达、图表和提交风险。
3. A 轴复验完整性并给出 `A_PASS` 或 `A_BLOCKED`；B 轴独立评价竞赛质量并给出总分、分项分和
   `B_STRONG`、`B_PASS`、`B_WEAK` 或 `B_REBUILD`。
4. 同时给出 A-E grade、confidence、basis、downgrade_reasons 以及与双轴一致的联合结论。
5. 每条问题按 P0/P1/P2/P3 给出定位证据、所属轴、受影响阶段、文件、重测项和预期改进；不执行修复，不读取前轮报告。

## 基础 Skill 与脚本

- 基础能力：`mathmodel-paper`、`pdf:pdf`、`mathmodel-review-r1-modeling` 至多用于术语核对；
- `python scripts/codex/validate_state.py runs/<run_id>`；
- 机械 QA 必须在 R5 前已通过，R5 不替代 QA。

## Finding 证据格式

`evidence` 必须是评委可见材料中的 PDF 页码、题目条目、表格/图号、代码路径或结果 ID；
不得引用 R1-R4 报告和作者陈述。每条 finding 同时声明 `change_class`、`route_impact` 和
`changed_route_core_fields`；问题所在阶段不得替代路线影响判断。

## 严重度与竞赛预算

- P0：提交包不可评审或某问基本未回答；
- P1：核心结论、数字或硬约束有重大问题；
- P2：不影响主结论的表达、引用或次要视觉问题。

竞赛模式最多 2 轮：第一轮达到 A/B 且无 P0/P1 直接结束；只有出现 P0/P1 或低于 B 才允许
第二轮。训练模式最多 5 轮，但不要求连续两轮 B/A。J0 不属于 R5 循环且只执行一次。

## 通过条件

A 轴必须为 `A_PASS`；B 轴总分至少 75，且题目覆盖、模型深度、实验验证均至少 60，并评为
`B_STRONG` 或 `B_PASS`；同时不得有 P0/P1。满足时联合结论为 `FINAL_CANDIDATE`，否则只能是
`QUALITY_REPAIR`、`INTEGRITY_REPAIR` 或 `FULL_REPAIR`，并由协调器生成带哈希的
`REPAIR_PLAN.json`。修改核心模型、数字、图表或结论时必须刷新受影响实验和审核绑定。

## 输出格式

报告必须包含 `rating`、`integrity_axis`、`quality_axis`、`joint_verdict`、`repair_scope`、
`required_retests`，并按 request 唯一路径写入 `review_report.json`。

## 结束前自检

- [ ] 没有读取前轮审核报告或作者解释；
- [ ] 没有修改生产文件；
- [ ] 评级有可定位证据和降级原因；
- [ ] 双轴分数、联合结论和 P0/P1 finding 相互一致；
- [ ] 竞赛模式没有无理由创建第二轮；
- [ ] 报告通过 Schema 并可由回执绑定。
