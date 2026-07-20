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

每条 finding 都必须声明 `change_class`、`route_impact` 和
`changed_route_core_fields`。`affected_stage` 只决定修复与重测位置，不能用于判断路线漂移；
只有 `ROUTE_CORE_CHANGE`、`PROBLEM_INTERPRETATION_CHANGE` 或显式
`route_impact=material` 才要求路线重新批准。

R1 还必须输出完整 `coverage` 矩阵，`unchecked_items` 必须为空；矩阵中的每个 `fail` 都要
绑定一个带 `check_id` 的 finding。

## 输出和暂停

写入：

每轮写入 `review/<stage>/<round>/review_request.json`、`review_report.json` 和 `review_receipt.json`，并由 `StateService.record_review_gate()` 登记到 `state.json.review_gates`。

主工作流先创建 `REVIEW_INPUT_MANIFEST.json` 和 `review_request.json`，再由全新顶层 Codex
任务调用 `claim_review_request()` 领取并生成 `review_session.json`。请求本身不得预填或伪造
线程 ID。session 必须声明 `new_thread=true`、`subagent=false`、`forked=false` 和
`context_inherited=false`；同一 request 只能领取一次，thread ID 不得复用。
领取必须通过独占创建和仓库级 claim registry 原子完成；同一 thread ID 在整个仓库所有
`runs/*/review` 中只能领取一次，不能先后审核不同 run。

报告必须绑定 `request_sha256`、`input_manifest_sha256` 和 `session_sha256`，回执必须同时绑定
request、input manifest、session 和 report 哈希。`attestation_level=self_declared` 只表示协议声明；只有桌面编排器或平台提供可信元数据时，
才可使用 `orchestrator_verified` 或 `platform_verified`，不得把自声明布尔值宣传为平台证明。

把 `state.json` 更新为：

- `status`: `WAITING_HUMAN_FINAL`
- `completed_stages`: 加入 `R1`、`R2`、`R3`、`R4` 及已完成的 R5 轮次
- `active_stage`: `human_final_review` 或 `comprehensive_review`
- `paper_ready`: `true`

执行状态校验，向用户报告最终 PDF 路径、关键风险和建议小改，然后停止。只有用户明确批准后，
完整工作流才能把状态改为 `COMPLETE`。
