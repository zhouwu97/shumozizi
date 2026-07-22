# Capability-First v3 实施总结

日期：2026-07-22
目标：将主动生产主链从审核生命周期模式迁移为 Capability-First v3，同时冻结 legacy-v2，保留可恢复性、真实执行证据和确定性提交检查。

## 实施结论

v3 的并行运行时、主动 Skill、按需知识库、机械 QA、迁移边界和回归测试均已实现。新运行完全位于 `shumozizi.simple`，不导入旧 `StateService`、审核、回执、裁决或闭环模块；自动发现目录仅保留六个 v3 Skill。

尚未把 v3 设为默认，也没有删除 legacy-v2。该限制是计划本身的安全条件：默认切换必须先在同一陌生完整旧题、同一模型与同一时间预算下完成真实 A/B，且由独立盲评确认质量不低于旧链。代码测试不能代替该经验验证，因此没有伪造 A/B 结论。

## 已交付内容

### 1. 并行 simple 运行时

新增 `src/shumozizi/simple/`：

- `initialization.py`：创建计划定义的 v3 目录、隔离复制题面与附件、初始化最小状态、决策记录和结果索引；
- `state.py`：Schema 校验、原子读写和受保护的修订更新；
- `execution.py`：固定 `shell=False` 运行、保存 stdout/stderr、退出码、耗时和失败原因；
- `results.py`：记录源脚本、命令、输入输出路径和 SHA-256，维护 `current`、`superseded`、`failed` 状态，并在终检时重新校验 current 结果的输入、输出和指标来源哈希。

新增 Schema：

- `schemas/simple_run_state.schema.json`（状态版本 3.0）；
- `schemas/simple_result_index.schema.json`（结果索引版本 1.0）。

新增入口：

```powershell
python scripts/codex/init_run.py <problem_path> `
  --workflow capability-first-v3 --run-id <run-id>

python scripts/codex/init_simple_run.py <problem_path> --run-id <run-id>

python scripts/runtime/run_simple_experiment.py runs/<run-id> `
  --question Q2 --kind primary --command "python code/q2.py" `
  --expect results/raw/q2.json
```

`init_run.py` 的 legacy-v2 默认行为仍保持兼容；v3 必须显式选择，直到 A/B 通过后再变更默认值。

### 2. 主动 Skill 与 legacy 归档

`.agents/skills/` 现在恰好包含：

```text
mathmodel-workflow
mathmodel-solve
mathmodel-experiment
mathmodel-paper
mathmodel-final-check
mathmodel-learn-paper
```

新 Skill 采用“分析/路线比较 → 真实实验 → 论文 → 一次终检”的连续主链，限制无意义的全量读取、固定实验族、重复审查和顶层任务膨胀。路线切换以 probe 和 `DECISIONS.md` 为依据；只有题意、核心目标、必做输出或重大预算变化才请求用户决定。

旧审核、路线和检索 Skill 已迁移至 `legacy/review-v2/skills/`，相关历史文档迁移至 `legacy/review-v2/docs/`。它们仍受冻结回归测试保护，但不再自动发现，也不会被 v3 运行时调用。

### 3. 机械 QA 与论文追溯

新增 Windows 可运行的工具：

- `tools/qa/figqa.py`：检查图片可读性和绘图脚本导出的文字边界重叠；
- `tools/qa/pdf_qa.py`：检查 PDF 打开、空白页、文字裁切/重叠、重复图表编号和可选匿名元数据；
- `tools/qa/make_contact_sheet.py`：渲染 PDF 联系表；
- `scripts/qa/check_placeholders.py`：扫描源文件占位符；
- `scripts/qa/check_result_references.py`：检查源码注释中的 `@result` 只引用 `current` 且 `execution_valid=true` 的结果；
- `scripts/qa/check_numeric_consistency.py`：将源码注释中的 `@metric` 与结果索引内、由当前 JSON 输出提取的真实指标比对；
- `scripts/qa/run_final_checks.py`：聚合上述检查，生成 `qa/mechanical-qa.json`、`qa/contact-sheet.png` 与 `reports/VERIFY_REPORT.md`。

机械 QA 只报告确定性问题，最终科学审查仍由 `mathmodel-final-check` 在完整论文、代码和结果的上下文中写入 `qa/FINAL_REVIEW.md`，按 P0–P3 分级。图表和表格重复编号采用图注/表题行匹配，当前作为 warning，避免正文“如图 1 所示”造成硬阻断；匿名检查必须通过 `--anonymous` 显式启用，附加身份词可通过 `--anonymous-term` 指定。

### 4. 知识、模板与来源边界

新增可按需读取的知识文件：问题拆解、模型选择矩阵、预测/优化/评价/机理 Cookbook、模型检验菜单、论文写作说明和 Figure Contract。每个文件明确“仅生成候选，不能自动决定路线”，并在 `knowledge/README.md` 规定当前阶段最多读取一到两个相关文件。

`THIRD_PARTY_NOTICES.md` 已更新：v3 QA 是对参考项目思路的独立 Windows 实现，不复制其工作流、状态机或审核机制。现有 MathModelAgent 模板作为能力基线继续保留。

### 5. 文档与运行边界

已重写：

- `README.md`：v3 架构、命令、目录、主动 Skill、机械 QA 和 legacy 状态；
- `AGENTS.md`：v3 运行约束、结果证据边界、预算策略、论文追溯和禁止事项；
- `docs/CODEX_WORKFLOW.md`：连续生产、一次整体审查和定向修复流程。

## 验证结果

新增 `tests/test_capability_first_v3.py`，覆盖：

- v3 初始化、题面/附件隔离复制和最小状态更新；
- Windows 带空格 Python 路径的真实子进程执行；
- 输入输出哈希、日志、结果替代和论文可用性；
- v3 CLI 初始化；
- PDF 缺失时可定位的机械 QA 报告；
- 图表文字边界重叠检测；
- 真实 PDF 联系表生成；
- 主动 Skill 目录只包含六项 v3 能力。

### 6. 评审后的确定性加固

在合并前评审中发现的确定性问题已进一步收敛：

- 实验 CLI 不再接受手工 `--metric`；指标只能从本次注册的 JSON 输出中，经 `--metrics-from` 或 `--metric-path` 提取，并保存 JSON 路径与输出文件哈希；
- 结果资格字段统一为 `execution_valid`，仅表示执行证据仍可验证，不将科学质量混入索引状态；
- `run_final_checks.py` 会重新计算所有 current 结果的输入、输出和指标来源哈希，失败覆盖输出会阻断终检；
- `@result`、`@metric` 追溯标记只存在于 Typst/LaTeX/Markdown 注释；旧的可渲染双中括号标记会被源码和 PDF 检查拦截；
- 匿名检查支持 PDF 元数据与用户指定身份词，并在 `--anonymous` 启用时成为硬检查；
- v3 运行阶段收敛为 `analysis → experiment → paper → verify → complete`，避免 `analysis` 与 `solve` 的职责重叠；
- Windows PR CI 现在覆盖 v3 运行时、主动 Skill、机械 QA 与核心 legacy smoke；完整 legacy 回归改为每周定时或手动触发，避免其重型审核闭环拖慢 v3 小改反馈。

本轮评审修订后的验证结果：

```text
python -m pytest --collect-only -q
241 tests collected

# 按全部 31 个测试文件分组执行（避免单进程累计超过桌面工具 10 分钟上限）
241 passed

python -m ruff check src scripts tools tests
All checks passed

python -m py_compile <v3 CLI、QA 及 simple 运行时入口>
All checks passed

git diff --check
No whitespace errors
```

其中冻结的 `test_review_closures.py` 单独用时约 3 分 29 秒；首次组合运行超过工具时限后，已改为逐文件复跑并全部通过。迁移暴露的一处旧测试路径已更正为读取 `legacy/review-v2/skills/mathmodel-review/`，不会恢复该 Skill 的自动发现。

冻结 v2 的审核合同测试保留并通过；其中的路径断言已改为验证 `legacy/review-v2/skills/` 的归档完整性，而不是要求旧 Skill 继续自动发现。

## A/B 与默认切换的剩余执行条件

以下不是未实现的代码功能，而是必须由真实赛题运行产生的外部证据：

1. 选一套陌生完整旧题，冻结模型、附件、时间、工具权限与初始提示；
2. 分别运行 legacy-v2 和 v3，保留 PDF、代码、结果、运行说明和 token/时间统计；
3. 对最终材料做不暴露工作流的盲评；
4. 验证 v3 的顶层任务数不超过 3、前 20% 预算内得到 baseline/probe、关键数字真实执行、逐问直接回答、致命科学错误更少或相等、盲评分不低于 legacy；
5. 仅在满足条件后，将 `init_run.py` 的默认 workflow 改为 `capability-first-v3`，再决定是否进一步归档旧代码。

PR 关闭、远端 tag 推送和远端分支操作也未执行：它们需要仓库维护者在正确的远端分支上确认，不应由本地实现擅自替代。
