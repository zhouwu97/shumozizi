# Codex 原生工作流说明

## 为什么先做减法

Codex 已能读取题面、操作本地文件、运行 Python/Typst/LaTeX、保存状态并与人工交互。第一版
因此移除了旧 WebUI、Redis、后端队列、Docker 和自建多 Agent 应用，只保留可复用的原始
Skills。这样比赛时间主要投入题意、建模、实验和论文，而不是维护控制面。

## 状态序列

```text
NEW
→ WAITING_HUMAN_ROUTE
→ ROUTE_LOCKED
→ MODEL_SPEC_READY
→ EXPERIMENTING
→ RESULTS_ACCEPTED
→ PAPER_DRAFTED
→ QA_RUNNING
→ WAITING_HUMAN_FINAL
→ COMPLETE
```

主枚举之外，`state.json.review_gates` 是同一状态机内的阶段证明，不是第二套状态机：

```text
MODEL_SPEC_READY --R1_MODELING--> EXPERIMENTING
每问实验完成 --R2_EXPERIMENT_<question_id>--> RESULTS_ACCEPTED
PAPER_DRAFTED --R3_PAPER_LOGIC + R4_FORMAT_VISUAL--> QA_RUNNING
QA 机械通过 --R5_STANDARD_FINAL--> J0_FINAL_BLIND_JUDGE
J0 一次性回执 --> WAITING_HUMAN_FINAL
```

QA hard failure 的唯一修复回路为：

```text
QA_RUNNING → BLOCKED → PAPER_DRAFTED → QA_RUNNING
```

禁止从 `BLOCKED` 直接进入最终批准或完成状态。

`state.json` 是唯一状态来源。每次进入新的桌面任务，先读状态，再读与当前阶段直接相关的
Skill 和产物。关闭任务或发生上下文压缩都不影响恢复。

## 第一个暂停点

`mathmodel-route` 只产出候选路线和简报。候选必须在数学本质、关键假设或决策结构上真正
不同，并同时给出基线、创新、验证、成本、风险和退路。写完后状态变为
`WAITING_HUMAN_ROUTE`，必须停止。

人工明确回复后，批准协议物化绑定候选路线、配置锁和原始回复的 receipt，再生成
`ROUTE_LOCK.json`。工作流只在批准范围内建模。所有运行时文件显式声明 Schema 名称和 2.0
版本；随后再检查跨文件 ID、文件哈希和证据引用。
改变题意、目标函数、核心约束、
模型类别、未批准路线，或新增实验超过剩余预算的 30%，都要重新暂停。

## 执行闭环

每问执行 baseline、primary、robustness/ablation。每轮先写执行清单，由统一执行器以结构化
参数运行 Python，生成包含退出码、日志、输入输出哈希的不可变执行记录。指标由白名单提取器
生成 provenance，候选结果必须通过约束、基线和来源复验后，才按 RFC 8785 封存；创新主张由
独立 evaluator 评估，不阻断 primary 的事实准入。每问实验完成后先登记 R2 回执，再进入结果
汇总和论文。

桌面版 AI 负责读取状态和决定下一阶段；项目不提供调用 AI 的 CLI 调度器。新建任务后再次
调用 `$mathmodel-workflow`，即可从 `state.json` 恢复。

## 第二个暂停点

完整论文和 PDF 后依次创建 R3/R4 请求；机械 QA 通过后由全新对话执行 R5，随后只执行一次 J0
自然评委盲评。竞赛模式 R5 最多两轮，仅 P0/P1 或低于 B 才重跑。所有回执必须登记到
`review_gates` 并绑定当前生产事实；未登记或任一绑定变化时，不能进入 `WAITING_HUMAN_FINAL`。

## 三种模式

- `competition`：默认轻量主链，两个强制人工点。
- `training`：同一主链，额外记录失败原因和复盘，但不增加评审层。
- `audit`：用于旧题或留出题的严格复现检查，不应成为比赛默认模式。

三种模式共用状态和结果 Schema，避免为模式复制三套文件协议。
