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
→ WAITING_HUMAN_FINAL
→ COMPLETE
```

`state.json` 是唯一状态来源。每次进入新会话，先读状态，再读与当前阶段直接相关的 Skill 和
产物。关闭 Codex、切换 IDE 或发生上下文压缩都不影响恢复。

## 第一个暂停点

`mathmodel-route` 只产出候选路线和简报。候选必须在数学本质、关键假设或决策结构上真正
不同，并同时给出基线、创新、验证、成本、风险和退路。写完后状态变为
`WAITING_HUMAN_ROUTE`，必须停止。

人工填写 `ROUTE_LOCK.yaml` 后，工作流只在批准范围内建模。改变题意、目标函数、核心约束、
模型类别、未批准路线，或新增实验超过剩余预算的 30%，都要重新暂停。

## 执行闭环

每问执行 baseline、primary、robustness/ablation。每轮先运行和登记，再决定是否接受。
结果接受后立即写对应论文章节，避免把写作挤到最后。全部实验完成后才写摘要和结论。

## 第二个暂停点

论文完成后只允许机械检查、一次单一 Critic、一次定向修复和快速复检。生成最终审核备忘后
状态变为 `WAITING_HUMAN_FINAL`。人工未明确批准前，不能标记完成。

## 三种模式

- `competition`：默认轻量主链，两个强制人工点。
- `training`：同一主链，额外记录失败原因和复盘，但不增加评审层。
- `audit`：用于旧题或留出题的严格复现检查，不应成为比赛默认模式。

三种模式共用状态和结果 Schema，避免为模式复制三套文件协议。
