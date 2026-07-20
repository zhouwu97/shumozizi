---
name: mathmodel-workflow
description: 启动或继续完整数学建模竞赛工作流。仅在用户明确要求完成整道赛题、可运行实验、图表和论文时使用；必须在人工确认点与独立审核对话交接点停止，不能因单项数据分析请求而隐式启动。
---

# 数学建模完整工作流

把 `runs/<run_id>/state.json` 作为唯一状态来源，运行到下一个人工确认点或独立审核对话交接点后
立即停止。审核交接只要求用户新开对话，不要求用户参与审核。

## 启动或恢复

1. 确认用户明确要求完整工作流；否则不要使用本 Skill。
2. 找到用户指定的运行目录。没有运行目录时执行：
   `python scripts/codex/init_run.py <problem_path> --run-id <run_id>`。
3. 完整读取 `state.json`，再决定下一步；不要仅根据聊天记录判断阶段。
4. 先执行 `python scripts/codex/validate_state.py runs/<run_id>`，该命令包含统一的
   `verify_run_integrity()` 检查。若校验失败，修复状态文件后再继续。

## 状态路由

| 当前状态 | 行为 | 下一状态 |
| --- | --- | --- |
| `NEW` | 先调用 `$mathmodel-retrieve-patterns`，再调用 `$mathmodel-route` | `WAITING_HUMAN_ROUTE` |
| `WAITING_HUMAN_ROUTE` | 只检查人工填写的 `brief/ROUTE_LOCK.json`；未批准则停止 | `ROUTE_LOCKED` |
| `ROUTE_LOCKED` | 完整读取 `skills/2analysis-modeling/SKILL.md`，按锁定路线生成数学规格 | `MODEL_SPEC_READY` |
| `MODEL_SPEC_READY` | 先登记通过的 `R1_MODELING` 回执，再开始正式实验 | `EXPERIMENTING` |
| `EXPERIMENTING` | 对每问调用 `$mathmodel-experiment`；每问完成后登记 `R2_EXPERIMENT_<question_id>` | `RESULTS_ACCEPTED` |
| `RESULTS_ACCEPTED` | 用 `$mathmodel-paper` 完成摘要、结论和全文组装 | `PAPER_DRAFTED` |
| `PAPER_DRAFTED` | 完整论文和 PDF 后依次登记 R3/R4，再启动机械 QA | `QA_RUNNING` |
| `QA_RUNNING` | 机械 QA 通过后登记 R5；J0 仅为可选评委模拟 | `WAITING_HUMAN_FINAL` |
| `WAITING_HUMAN_FINAL` | 只处理人工终审意见；未明确批准则停止 | `COMPLETE` |
| `COMPLETE` | 报告产物与复现命令，不再改动 | `COMPLETE` |

R1 要求补全或澄清模型规格时，使用 `MODEL_SPEC_REVISED` 保持在
`MODEL_SPEC_READY`，绑定旧/新 `model_spec`、`REPAIR_PLAN.json` 和当前 `ROUTE_LOCK.json`，
将旧 R1 回执标记为 `stale` 后创建新 R1。不得把 `affected_stage=R1_MODELING` 当作路线漂移。

## 审核对话交接

R1-R5 的每个 `review_request.json` 都必须由一个全新、独立的 Codex 桌面版顶层对话执行。
生产主对话创建请求和输入清单后立即停止，并输出请求路径及对应审核 Skill；不得在当前对话中
直接审核，也不得调用子 Agent、fork 或继承上下文完成审核。

用户只负责新建/切换到独立审核对话并提交请求，不负责逐项检查、复现、测量、判分、解释材料
或手工填写报告。独立审核对话中的 AI 收到请求后必须自动完成以下工作，不得把审核步骤转交给
用户：

1. 领取请求并生成 `review_session.json`；
2. 读取且仅读取 request 声明的冻结材料；
3. 执行对应 R1-R5 Skill 的校验、复现或视觉检查；
4. 写入结构化 `review_report.json`，结束审核对话；审核 AI 不生成生产回执；
5. 报告完成后结束审核对话，不修改生产文件或推进 `state.json`。

报告返回生产主对话后，主 AI 必须独立核验每条 finding，写入 `REVIEW_ADJUDICATION.json`，
再物化绑定裁决哈希的回执并决定接受、降级、驳回、复核或定向修复；不得机械照单全收。若审核 AI 因冻结材料、环境或合同错误无法继续，应自行完成所有安全的
诊断，只把明确阻塞写入报告，不要求用户代做审核。

## 路线确认

在第一次调用 `$mathmodel-route` 后，确认这些文件已经生成：

- `knowledge/TASK_FINGERPRINT.json`
- `knowledge/RETRIEVED_PATTERNS.md`
- `knowledge/PATTERN_TRANSFER_PLAN.md`
- `brief/MODEL_STORYBOARD.md`
- `brief/ROUTE_BRIEF.md`
- `brief/route_candidates.json`
- `problem/PROBLEM_MANIFEST.json`（全部题目、必做输出和依赖）
- `state.json` 中 `status=WAITING_HUMAN_ROUTE`

随后停止。不得自动替人工选择路线，不得生成 `ROUTE_LOCK.json` 的批准内容。

用户确认后，检查路线锁至少包含：题意解释、主路线、备用路线、基线、创新、验证、预算以及
`problem_manifest_sha256`。只有完整运行 `validate_state.py` 且 `approved=true` 时才能把状态改为
`ROUTE_LOCKED`。

## 执行主链

路线锁定后按以下顺序推进：

1. 完整读取 `skills/2analysis-modeling/SKILL.md`，只采用已锁路线，生成可编码的数学规格。
2. 逐子问题调用 `$mathmodel-experiment`。不要并行启动多个 Agent。
3. 每个子问题实验完成后先创建 R2 请求并停在独立对话交接点；审核 AI 自动执行并返回报告后，
   主 AI 独立裁决 finding、登记有效回执，再调用 `$mathmodel-paper` 写对应章节。
4. 仅当论文需要解释方法链路时，完整读取并使用 `skills/4drawio/SKILL.md`。
5. 全部子问题完成后用 `$mathmodel-paper` 汇总摘要、结论、优缺点和推广。
6. 依次为 R3、R4 和 R5 创建独立审核请求；每次都由用户新开对话、其中的 AI 自动审核，主 AI
   返回生产对话后裁决，再执行机械 QA 或后续阶段。只有所需回执登记且绑定仍有效时，运行到
   `WAITING_HUMAN_FINAL` 并停止。

J0 可在 R5 后作为自然评委模拟执行，但不是进入人工终审或 `COMPLETE` 的必要条件。

R5 必须同时通过 A 轴完整性和 B 轴质量阈值；机器 `FORMAT_AUDIT.json` 硬失败、必做问题/输出
缺失、缺 baseline/primary 验证或缺 robustness/ablation 时，校准分自动封顶，不能由文字评分
覆盖；否则读取其 `REPAIR_PLAN.json`，只执行列出的定向修复和重测。完整论文必须覆盖 Manifest
中全部必做问题，不能只完成已登记子集。

## 预算和漂移

每问默认执行 baseline、primary、robustness/ablation 三个实验族；实验族内允许在冻结的执行时间、
拟合次数、优化评估次数和无效调参次数预算内执行多个子实验。普通调参、修代码、换求解器
和改图表不算漂移。改变题意、目标函数、核心约束、模型类别或未批准路线，以及新增实验占
剩余预算 30% 以上时，写入 `review/ROUTE_DRIFT_MEMO.md`，把状态改回
`WAITING_HUMAN_ROUTE`，然后停止。

## 完成终审

只有用户明确批准最终论文后，才把状态改为 `COMPLETE`。若用户要求小改，执行一次小范围修订
和快速复检，再回到 `WAITING_HUMAN_FINAL`；不得开启新一轮完整审稿。
