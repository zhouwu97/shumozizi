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
- `runs/<run_id>/state.json`：唯一工作流状态来源，只能由状态服务写入，可跨会话恢复。
- `runs/<run_id>/config/RUN_CONFIG_LOCK.json`：不可变比赛 Profile、题面、语言与排版配置。
- `schemas/`：全部运行时文件的 Schema v2 结构约束；文档必须自声明名称和版本。
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

必须直接以嵌套 Git 根打开 Codex 桌面工作区。打开外层目录后再进入本仓库会被诊断为错误。
安装正式包并运行环境诊断：

```powershell
python -m pip install -e .[test]
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

人工确认前，系统生成绑定 `RUN_CONFIG_LOCK` 与候选路线哈希的批准请求。人类明确回复后，
批准协议生成 `route_approval_receipt.json` 和 `ROUTE_LOCK.json`；禁止通过复制模板或手改
`approved=true` 绕过回执。

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

新结果先登记为 `candidate`。指标必须由白名单提取器从执行记录中的已哈希输出生成 provenance；
派生指标只允许受限 AST。准入后生成不可改写的 sealed result 与 RFC 8785 seal。撤销只追加
revocation record，论文不得读取 `revoked` 或 `superseded` 结果。

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

论文数字通过 `scripts/generate_paper_evidence.py` 生成 Typst macro，QA 会在最终 PDF 的 claim
标签附近检查真实展示值，而不是信任手填的 `rendered_value`。

## 第二次人工确认：最终论文

工作流只允许一次机械检查、一次评委视角自审、一次定向修复和一次快速复检。完成后生成：

```text
runs/2026-A-001/review/FINAL_REVIEW_MEMO.md
```

状态变为 `WAITING_HUMAN_FINAL`，Codex 再次停止。最终回执绑定当前 PDF、QA 聚合报告、证据
报告与 Profile 哈希；任何一个发生变化都会使批准自动失效。

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
