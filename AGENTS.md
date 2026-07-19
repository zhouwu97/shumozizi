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
   `StateService.transition()` 把状态设为 `WAITING_HUMAN_ROUTE`，然后停止。只有人类明确
   回复后才能物化批准回执和 `ROUTE_LOCK.json`。
2. 最终审核：完成实验、论文、证据校验、QA 聚合和定向修复，写入
   `final_approval_request.json`，把状态设为 `WAITING_HUMAN_FINAL`，然后停止。只有绑定当前
   PDF、QA、证据报告和配置锁的人类回执有效时，才可进入 `COMPLETE`。

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

## 实验预算

每个子问题默认最多执行三个主要循环：baseline、primary、robustness/ablation。
失败时依次修代码或数据、调整同路线参数或求解器、使用已确认备用路线；再失败则申请
 路线漂移确认。禁止无限调参、无限搜索和无限自审。

## 五层独立审核

论文生产后依次创建 R1 建模、R2 实验复现、R3 论文逻辑、R4 格式视觉审核请求，再由全新
Codex 对话执行 R5 全面盲审。R5 竞赛模式最多 3 轮、训练模式最多 5 轮；单轮出现 P0/P1
或评级低于 B 必须修复，连续两轮 B/A 且无 P0/P1 才能进入人工最终核包。审核任务默认只读，
只写自己的报告和回执；模型、数字、核心图表、假设、约束或结论变化时必须按影响范围重跑
实验并新开 R5。

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
