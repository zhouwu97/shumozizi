# shumozizi：Codex 原生数学建模工作流

这是一个可直接放进赛题目录、由 Codex CLI、IDE 或桌面应用驱动的项目级数学建模工作流包。

项目只保留一条主线：

```text
Codex 读题
→ 人工确认题意与路线
→ Codex 完成建模和有界实验
→ Codex 按真实结果增量写论文
→ Codex 做一次有界自审
→ 人工终审
```

不需要 WebUI、Redis、后端任务队列、自建 Agent 框架、数据库或云端解释器。

## 核心设计

- `AGENTS.md`：项目总规则和两个强制人工确认点。
- `.agents/skills/`：Codex 可原生发现的五个轻量包装 Skill。
- `skills/`：保留 MathModelAgent 上游原始 Skills，便于对照和同步。
- `runs/<run_id>/state.json`：唯一工作流状态来源，可跨会话恢复。
- `schemas/`：候选路线、路线锁、状态和结果注册表的结构约束。
- `scripts/codex/`：初始化、校验、环境诊断和 `codex exec` 辅助脚本。

## 安全默认值

项目级 [.codex/config.toml](.codex/config.toml) 使用：

```toml
approval_policy = "on-request"
sandbox_mode = "workspace-write"
web_search = "cached"
```

不建议使用 `codex --yolo` 或 `danger-full-access`。项目配置只会在 Codex 信任该仓库时加载。

## 快速开始

先运行环境诊断：

```powershell
pwsh -File scripts/codex/doctor.ps1
```

把题面和附件放到 `problems/<problem-id>/`，初始化运行目录：

```powershell
python scripts/codex/init_run.py problems/2026-A --run-id 2026-A-001
```

启动 Codex，在对话中显式调用唯一完整入口：

```text
$mathmodel-workflow

读取 runs/2026-A-001/state.json，从当前状态继续，运行到下一个人工确认点后停止。
```

完整工作流被设置为不允许隐式调用。用户只说“分析这个 Excel”时，不会自动启动整篇论文流程。

## 第一次人工确认：路线锁

首次运行会生成：

```text
runs/2026-A-001/brief/ROUTE_BRIEF.md
runs/2026-A-001/brief/route_candidates.json
```

并把状态设为 `WAITING_HUMAN_ROUTE`。此时 Codex 必须停止，不得开始正式建模。

人工确认后，把 `ROUTE_LOCK.template.yaml` 复制为 `ROUTE_LOCK.yaml`，填写并将
`approved` 改为 `true`。然后再次调用 `$mathmodel-workflow`。

路线锁固定：

- 题意解释；
- 主路线与备用路线；
- 必须保留的基线；
- 创新主张及验证方式；
- 每问最多三轮主实验；
- 文献搜索、自审与路线漂移预算。

## 实验和结果

每个子问题最多执行：

1. baseline；
2. primary；
3. robustness 或 ablation。

新结果先登记为 `candidate`。只有源代码、输出、指标、约束和结论都通过检查，才能变成
`accepted`。论文只能读取 `accepted` 且 `paper_allowed=true` 的结果。

随时校验状态与结果来源：

```powershell
python scripts/codex/validate_state.py runs/2026-A-001
```

## 第二次人工确认：最终论文

工作流只允许一次机械检查、一次评委视角自审、一次定向修复和一次快速复检。完成后生成：

```text
runs/2026-A-001/review/FINAL_REVIEW_MEMO.md
```

状态变为 `WAITING_HUMAN_FINAL`，Codex 再次停止。只有人工明确批准后才能进入 `COMPLETE`。

## 非交互继续

路线锁定后的确定性阶段可以使用：

```powershell
pwsh -File scripts/codex/continue_run.ps1 -RunId 2026-A-001
```

脚本固定使用 `--sandbox workspace-write`，事件写入 `runs/<run_id>/logs/`。人工决策仍建议在
交互式 Codex 中完成。

## 包装 Skills

| Skill | 职责 |
| --- | --- |
| `$mathmodel-workflow` | 唯一完整入口；按状态推进并在两个人工点停止 |
| `$mathmodel-route` | 题意、歧义和 2–3 条差异化候选路线 |
| `$mathmodel-experiment` | baseline → primary → robustness/ablation |
| `$mathmodel-paper` | 依据已接受结果逐问增量写作 |
| `$mathmodel-review` | 一次机械检查、自审、定向修复和快速复检 |

详细流程见 [docs/CODEX_WORKFLOW.md](docs/CODEX_WORKFLOW.md)。

## 来源与许可

本仓库以 `jihe520/MathModelAgent` 的 Skills 为能力基线，并在其外部增加 Codex 包装层。
第三方来源和许可边界见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
