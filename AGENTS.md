# MathModelAgent Codex Desktop Project

## 项目定位

本项目是由 Codex 桌面版 AI 驱动的项目级数学建模工作流包。
不启动 WebUI、Redis、后端任务队列、旧多 Agent 框架或云端解释器。

## 完整工作流入口

只有用户明确要求完成整道赛题、实验和论文时，才使用：

`$mathmodel-workflow`

用户只要求分析数据、调试代码或修改论文时，不得自动启动完整工作流。

## 两个人工确认点

1. 路线确认：生成 2–3 条真正不同的候选路线和 `route_approval_request.json`，通过
   `PROBLEM_MANIFEST.json` 冻结必做问题全集，再由 `StateService.transition()` 把状态设为
   `WAITING_HUMAN_ROUTE`，然后停止。只有明确的人类回复后才能物化批准回执和
   `ROUTE_LOCK.json`。
2. 最终审核：只有所需 R1/R2/R3/R4/R5 阶段回执均登记在当前 `state.json.review_gates`，并且
   `final_approval_request.json` 绑定当前 PDF、QA、证据报告和配置锁时，才可把状态设为
   `WAITING_HUMAN_FINAL`；然后停止。J0 只作为可选自然评委模拟，不是硬门。只有绑定当前事实的
   人类回执有效时，才可进入 `COMPLETE`。

改变题意解释、目标函数、核心约束、模型类别、已锁路线，或新增实验预计占剩余预算
30% 以上时，视为路线漂移，必须再次停下并请求人工确认。

## 状态与结果

- `runs/<run_id>/state.json` 是唯一工作流状态来源，只有
  `shumozizi.workflow.state_service.StateService` 可以写入。
- 不依赖聊天历史、任务 ID 或 Codex 会话 ID 判断进度。
- 代码必须实际运行，不得编造数据、指标、图表或引用。
- 论文关键数值必须来自可复验的 metric provenance 与 RFC 8785 sealed result。
- 只有注册表中仍为 `accepted`、`paper_allowed=true` 且封条有效的结果可进入论文；
  `revoked` 与 `superseded` 结果一律禁止引用。
- Route、Paper、QA、Final Approval 必须读取同一份 `config/RUN_CONFIG_LOCK.json`，不得接收
  调用方临时传入的 Profile。
- 路线锁定后，`problem/PROBLEM_MANIFEST.json` 是权威问题全集；完整论文和最终审核必须覆盖
  其中全部 `required=true` 的问题。

## 实验预算

每个子问题默认执行三个实验族：baseline、primary、robustness/ablation。实验族不是三次程序
执行；族内允许在冻结预算内执行多随机种子、交叉验证、多初值、参数搜索、情景模拟、扰动和
收敛测试。预算限制必须落到最大执行时间、拟合次数、优化评估次数和无效调参次数。失败时依次
修代码或数据、调整同路线参数或求解器、使用已确认备用路线；再失败则申请路线漂移确认。
禁止无限调参、无限搜索和无限自审。

## 五层独立审核

模型规格完成后创建对应范围 R1；每问实验完成后创建该问 R2；章节存在后可执行局部 R3；PDF
快照存在后可执行 R4；机械 QA 通过后执行 R5 全面盲审。审核按依赖关系执行，不要求 R1-R5
严格编号升序。竞赛模式 R5 最多 3 轮，但只有首次候选或重大修复才消耗完整轮次；L0/L1 和纯
L2 修改只做差异检查或局部复核。J0 为可选评委模拟。每一轮审核必须由用户在 Codex 桌面版
中新开一个独立顶层对话；用户只负责创建/切换到该对话并提交审核请求，审核对话中的 AI 自动
读取冻结材料、执行对应 R1-R5 Skill、完成检查并写入自己的报告和回执。用户不参与逐项审核，
不代替 AI 复现、测量、判断或手工填写报告。审核任务默认只读，只写自己的报告和回执；
模型、数字、核心图表、假设、约束或结论变化时必须按影响范围重跑实验并刷新受影响回执。
R5 同时输出 A 轴完整性和 B 轴竞赛质量；只有 `A_PASS` 且 B 轴达到最低阈值时，联合结论才可为
`FINAL_CANDIDATE`。失败审核必须生成带哈希的 `REPAIR_PLAN.json`，按受影响阶段定向返工。

审核完成后，报告返回生产主对话，由主 AI 独立核验每条 finding 并决定是否接受、降级、驳回或
申请复核；审核对话不得直接修改生产产物、推进状态或生成修复命令。

主 AI 的逐条裁决必须写入当前审核目录的 `REVIEW_ADJUDICATION.json`；报告不能直接生成
`REPAIR_PLAN.json` 或 `review_receipt.json`。回执必须绑定报告、session、request、输入清单和
裁决文件的 SHA-256。R4/R5 使用机器生成的 `FORMAT_AUDIT.json` 作为硬门；R5 的正式竞赛分数
必须区分 `raw_score` 与受硬条件封顶的 `calibrated_score`，竞赛模式全局最多三轮。

## 本地执行与检查

- 优先使用项目或赛题目录已有 Python 环境。
- 运行后检查退出码、输出文件、约束、单位和核心指标。
- 论文必须编译，并检查最终 PDF 的图片、占位符、数值一致性和提交格式。
- 使用 `python scripts/codex/validate_state.py runs/<run_id>` 校验状态、配置、批准与 sealed result。
- 使用 `python scripts/doctor.py` 检查本机工具。

## 目录职责

- `.agents/skills/`：Codex 原生包装 Skills。
- `skills/`：上游原始 Skills，只作能力基线；不要为适配而整体重写。
- `schemas/`：路线、状态与结果注册的机器可读约束。
- `scripts/codex/`：运行目录初始化与状态校验工具，不负责调用或调度 Codex。
- `scripts/runtime/`：实验执行、证据复验和结果准入工具。
- `problems/`：题面和附件，工作流不得修改原始文件。
- `runs/`：每次运行的状态、代码、结果、图表和论文；默认不提交 Git。

## 禁止事项

- 不通过命令行脚本启动、续跑或调度 Codex。
- 不在路线确认前写完整建模报告、正式实验或论文。
- 不为了创新堆叠未经基线、对照或消融验证的复杂模型。
- 不引入 SDK、App Server、MCP 自建服务、数据库或多 Agent 调度。
- 不自动提交或推送 Git。
