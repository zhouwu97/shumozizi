---
name: mathmodel-review
description: 编排 R1-R5 五类独立审核；R5 采用有界全盲审循环，结束时停在人工最终核包点。
---

# 五层独立审核

R1 建模、R2 实验复现、R3 论文逻辑、R4 格式视觉和 R5 全面盲审均使用独立请求和报告。每一轮审核必须由用户在 Codex 桌面版中新开一个独立顶层对话，禁止使用子 agent、fork、续用旧任务或继承任何旧聊天上下文。用户只负责创建/切换对话并提交请求，不参与审核判断或手工填写报告；新对话中的审核 AI 必须自动读取本轮 `review_request.json` 声明的 `read_paths`、执行对应审核 Skill 并产出报告，不得等待用户逐步辅助。报告返回生产主对话后，由主 AI 写入 `REVIEW_ADJUDICATION.json`，逐条独立裁决 finding，再由主 AI 物化回执。审核任务默认只读；模型、数字、核心图表、假设、约束或结论变化时，按影响范围重跑实验并新开 R5。

## 前置条件

1. 按材料依赖执行：模型规格存在后可执行 R1；相关 R1 和实验存在后可执行 R2；章节存在后可执行局部 R3；PDF 快照存在后可执行 R4；QA 通过后执行 R5。J0 仅为可选评委模拟。
2. 完整读取 `skills/6verity/SKILL.md`，只复用其中的机械检查和小范围修复规则。
3. 读取路线锁、数学规格、结果注册表、论文源文件和最终 PDF。

## 固定预算

R1-R4 按受影响范围执行，R5 竞赛模式最多 3 轮、训练模式最多 5 轮。只有 `full_scientific` 请求计入完整 R5 轮次；`targeted_recheck`、`diff_check` 和 `machine_check` 不占用该配额。只有首次完整候选或重大修复才消耗完整 R5 轮次；L0/L1 和纯 L2 修改只做差异或局部检查。单轮 A/B 且无 P0/P1 即可通过。J0 最多执行一次，不属于 R5 循环且不是硬门。

机械错误可以直接小修；任何路线漂移必须写 `review/ROUTE_DRIFT_MEMO.md` 并返回人工路线确认。

## 审核模式

<!-- REVIEW_MODES_START -->
```text
full_scientific
targeted_recheck
diff_check
machine_check
```
<!-- REVIEW_MODES_END -->

- `full_scientific`：首次科学审核或科学前提发生根本变化，读取阶段完整冻结材料。
- `targeted_recheck`：只读取原 finding、生产裁决、修改前后 diff、修复证据和直接依赖。
- `diff_check`：只检查原 finding、生产裁决、声明的局部差异与修复证据，不使无关 R1/R2 回执失效。
- `machine_check`：只读取原 finding、生产裁决和确定性机器证据。

`targeted_recheck` 禁止重新读取完整题面、其他 review report 或无关生产文件，禁止新增无关
P2/P3。新增 P0/P1 必须说明与本次修改的关系、此前无法合理发现的原因、重新打开证据和
`reopen_justification`。

reviewer finding v3 只记录问题、证据、错误理由、严重度建议、`confidence` 和经验未知状态。
生产主 AI 在 adjudication 中决定 `effective_severity`、`domain`、`verification_mode`、
`gate_effect`、受影响问题与重测。机器 P1 走 `machine_check`，科学 P0/P1 走
`targeted_recheck`，非语义 P2 走 `diff_check`，P3 可直接作为不阻断建议关闭。P2/P3 修复若
改变科学语义，必须重新分类为科学 P1。

`deferred_empirical` 只允许表达需要实验回答的未知，并必须声明 `block_before`、
`closure_condition` 和 `failure_action`；不得用它掩盖未定义的方程、目标、约束或算法语义。
完整根登记后它会形成 `state.json.deferred_obligations`：`formal_experiment` 在实验开始前阻断，
`model_selection` 与 `paper_claim` 当前最迟在论文完成前阻断，`final_submission` 在 QA 通过或最终
批准前阻断。义务只能由绑定同一完整根和目标 finding 的合法 scoped closure 关闭。
关闭状态必须从当前完整根和真实 closure 回执重建，不能信任手工修改的
`deferred_obligations.status` 或 `closed_by_receipt_sha256`。R1 `model_selection` 义务允许在
`EXPERIMENTING` 或 `RESULTS_ACCEPTED` 完成定向关闭。

R1 还必须输出完整 `coverage` 矩阵，`unchecked_items` 必须为空；矩阵中的每个 `fail` 都要
绑定一个带 `check_id` 的 finding。

## 输出和暂停

写入：

每轮写入 `review/<stage>/<round>/review_request.json`、`review_report.json`、`REVIEW_ADJUDICATION.json` 和 `review_receipt.json`。`full_scientific` 只由 `StateService.record_review_gate()` 登记完整根；`targeted_recheck`、`diff_check` 和 `machine_check` 必须绑定该根的 gate ID、receipt、report、adjudication 哈希链，并由 `StateService.record_review_closure()` 追加关闭历史，不能创建或覆盖完整门。审核 AI 只写 session 和报告；裁决、修复计划和回执属于生产主对话。

`stale` 完整根禁止继续创建或登记 scoped closure，必须重新执行 `full_scientific`。新完整根替换
旧根时不得继承旧 closures 或绑定旧 root receipt 的 deferred obligations；旧证据只保留在历史中。

主工作流先创建 `REVIEW_INPUT_MANIFEST.json` 和 `review_request.json`，再由全新顶层 Codex
审核对话中的 AI 自动调用 `claim_review_request()` 领取并生成 `review_session.json`，随后连续
完成材料校验、阶段审核和报告写入，除明确阻塞外不向用户拆分审核步骤。请求本身不得预填或伪造
线程 ID。session 必须声明 `new_thread=true`、`subagent=false`、`forked=false` 和
`context_inherited=false`；同一 request 只能领取一次，thread ID 不得复用。
领取必须通过独占创建和仓库级 claim registry 原子完成；同一 thread ID 在整个仓库所有
`runs/*/review` 中只能领取一次，不能先后审核不同 run。

报告必须绑定 `request_sha256`、`input_manifest_sha256` 和 `session_sha256`，回执必须同时绑定
request、input manifest、session、report 和 adjudication 哈希。`attestation_level=self_declared` 只表示协议声明；只有桌面编排器或平台提供可信元数据时，
才可使用 `orchestrator_verified` 或 `platform_verified`，不得把自声明布尔值宣传为平台证明。

审核 AI 结束后不得修改模型、代码、实验、论文或 `state.json`。原生产主对话中的主 AI 读取报告
后必须逐条独立核验 finding，先写 `REVIEW_ADJUDICATION.json`，再决定是否接受和修复；审核意见不能直接替代生产裁决。P0/P1 不能无证据单方面驳回，P0 接受必须附第二次独立复核或人工决定证据。

R4/R5 的 `review/FORMAT_AUDIT.json` 是机器硬门；字体嵌入、页边距、摘要、匿名、图表、引用链接和 DPI 等硬失败不能被文字结论覆盖。R5 的 `raw_score` 与 `calibrated_score` 分离，后者受必做问题、required output、baseline/primary、robustness/ablation、P0/P1 和格式硬失败封顶；正式竞赛声明只能使用校准分。

把 `state.json` 更新为：

- `status`: `WAITING_HUMAN_FINAL`
- `completed_stages`: 加入 `R1`、`R2`、`R3`、`R4` 及已完成的 R5 轮次
- `active_stage`: `human_final_review` 或 `comprehensive_review`
- `paper_ready`: `true`

执行状态校验，向用户报告最终 PDF 路径、关键风险和建议小改，然后停止。只有用户明确批准后，
完整工作流才能把状态改为 `COMPLETE`。
