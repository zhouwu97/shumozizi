---
name: mathmodel-review
description: 编排 R1-R5 五类独立审核；R5 采用有界全盲审循环，结束时停在人工最终核包点。
---

# 五层独立审核

R1 建模、R2 实验复现、R3 论文逻辑、R4 格式视觉和 R5 全面盲审均使用独立请求、报告和回执。每一轮审核必须创建全新的 Codex 桌面任务，禁止使用子 agent、fork、续用旧任务或继承任何旧聊天上下文；新任务只能读取本轮 `review_request.json` 声明的 `read_paths`。审核任务默认只读；模型、数字、核心图表、假设、约束或结论变化时，按影响范围重跑实验并新开 R5。

## 前置条件

1. 只在主状态链规定的阶段执行：R1 在 `MODEL_SPEC_READY`，R2 在每问实验完成后，R3/R4 在 `PAPER_DRAFTED`，R5/J0 在 QA 通过阶段。
2. 完整读取 `skills/6verity/SKILL.md`，只复用其中的机械检查和小范围修复规则。
3. 读取路线锁、数学规格、结果注册表、论文源文件和最终 PDF。

## 固定预算

R1-R4 各执行一次，R5 竞赛模式最多 2 轮、训练模式最多 5 轮。只有 P0/P1 或评级低于 B 才允许第二轮；单轮 A/B 且无 P0/P1 即可通过。J0 只执行一次，不属于 R5 循环。

机械错误可以直接小修；任何路线漂移必须写 `review/ROUTE_DRIFT_MEMO.md` 并返回人工路线确认。

## 输出和暂停

写入：

每轮写入 `review/<stage>/<round>/review_request.json`、`review_report.json` 和 `review_receipt.json`，并由 `StateService.record_review_gate()` 登记到 `state.json.review_gates`。

每轮请求必须记录 `execution_policy`（`new_codex_thread=true`、`subagents_forbidden=true`、`context_inheritance=false`）和实际 `codex_thread_id`。主工作流在登记回执前必须独立复验线程身份、输入绑定、报告 Schema、哈希、证据和 remediation 可行性。

把 `state.json` 更新为：

- `status`: `WAITING_HUMAN_FINAL`
- `completed_stages`: 加入 `R1`、`R2`、`R3`、`R4` 及已完成的 R5 轮次
- `active_stage`: `human_final_review` 或 `comprehensive_review`
- `paper_ready`: `true`

执行状态校验，向用户报告最终 PDF 路径、关键风险和建议小改，然后停止。只有用户明确批准后，
完整工作流才能把状态改为 `COMPLETE`。
