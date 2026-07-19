# shumozizi：Codex 原生数学建模工作流

这是一个可直接放进赛题目录、由 Codex 桌面版 AI 驱动的项目级数学建模工作流包。

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
- `schemas/`：候选路线、路线锁、状态和结果注册表的运行时结构约束。
- `scripts/codex/`：初始化运行目录和校验工作流状态。
- `scripts/runtime/`：统一执行实验、复验执行证据和接受结果。
- `scripts/doctor.py`：跨平台环境诊断，不调用或调度 Codex。

## 安全默认值

项目级 [.codex/config.toml](.codex/config.toml) 使用：

```toml
approval_policy = "on-request"
sandbox_mode = "workspace-write"
web_search = "cached"
```

桌面版打开仓库后，应先确认工作区和授权范围。项目配置只会在 Codex 信任该仓库时加载。

## 快速开始

先运行环境诊断：

```powershell
python scripts/doctor.py
```

把题面和附件放到 `problems/<problem-id>/`，初始化运行目录：

```powershell
python scripts/codex/init_run.py problems/2026-A --run-id 2026-A-001
```

在 Codex 桌面版中为该仓库新建任务，并显式调用唯一完整入口：

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

人工确认后，把 `ROUTE_LOCK.template.json` 复制为 `ROUTE_LOCK.json`，填写并将
`approved` 改为 `true`。然后再次调用 `$mathmodel-workflow`。路线锁使用 JSON，运行时会把
完整嵌套文档送入 JSON Schema Validator，而不是只检查顶层字段。

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

新结果先登记为 `candidate`。只有执行命令成功、源代码与输出哈希匹配、指标非空、约束和
验证检查通过、基线及创新证据引用完整，才能变成 `accepted`。论文只能读取 `accepted` 且
`paper_allowed=true` 的结果。

实验必须先写结构化执行清单，再由统一执行器运行：

```powershell
python scripts/runtime/execute_experiment.py runs/2026-A-001 runs/2026-A-001/executions/manifests/q1-baseline.json
```

`scripts/runtime/accept_result.py` 是把 `candidate` 提升为 `accepted` 的唯一受支持入口。不得在
注册表中直接手改 `accepted`。

随时校验状态与结果来源：

```powershell
python scripts/codex/validate_state.py runs/2026-A-001
```

首次使用先安装唯一 Python 运行依赖：

```powershell
python -m pip install -r requirements.txt
```

## 第二次人工确认：最终论文

工作流只允许一次机械检查、一次评委视角自审、一次定向修复和一次快速复检。完成后生成：

```text
runs/2026-A-001/review/FINAL_REVIEW_MEMO.md
```

状态变为 `WAITING_HUMAN_FINAL`，Codex 再次停止。只有人工明确批准后才能进入 `COMPLETE`。

## 跨任务继续

本项目不提供调用 AI 的脚本调度或后台续跑。关闭任务或新建桌面任务后，重新发送：

```text
$mathmodel-workflow

读取 runs/2026-A-001/state.json，从当前状态继续，运行到下一个人工确认点后停止。
```

恢复只依赖 `state.json` 和运行目录产物，不依赖旧对话历史。

## 包装 Skills

| Skill | 职责 |
| --- | --- |
| `$mathmodel-workflow` | 唯一完整入口；按状态推进并在两个人工点停止 |
| `$mathmodel-route` | 题意、歧义和 2–3 条差异化候选路线 |
| `$mathmodel-experiment` | baseline → primary → robustness/ablation |
| `$mathmodel-paper` | 依据已接受结果逐问增量写作 |
| `$mathmodel-review` | 一次机械检查、自审、定向修复和快速复检 |

详细流程见 [docs/CODEX_WORKFLOW.md](docs/CODEX_WORKFLOW.md)。
桌面版端到端验收使用 [tests/fixtures/e2e_linear_fit/problem.md](tests/fixtures/e2e_linear_fit/problem.md)
和 [docs/e2e/DESKTOP_E2E_REPORT.template.md](docs/e2e/DESKTOP_E2E_REPORT.template.md)，当前不把模板视为已验收报告。

## 来源与许可

本仓库以 `jihe520/MathModelAgent` 的 Skills 为能力基线，并在其外部增加 Codex 包装层。
第三方来源和许可边界见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
