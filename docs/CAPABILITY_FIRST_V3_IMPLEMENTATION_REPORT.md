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
- `results.py`：记录源脚本、命令、输入输出路径和 SHA-256，维护 `current`、`superseded`、`failed` 状态。

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
- `scripts/qa/check_result_references.py`：检查 `[[result:<id>]]` 只引用 current 且允许写作的结果；
- `scripts/qa/check_numeric_consistency.py`：将 `[[metric:<id>.<metric>=<number>]]` 与结果索引的真实指标比对；
- `scripts/qa/run_final_checks.py`：聚合上述检查，生成 `qa/mechanical-qa.json`、`qa/contact-sheet.png` 与 `reports/VERIFY_REPORT.md`。

机械 QA 只报告确定性问题，最终科学审查仍由 `mathmodel-final-check` 在完整论文、代码和结果的上下文中写入 `qa/FINAL_REVIEW.md`，按 P0–P3 分级。

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

执行结果：

```text
python -m pytest -q
196 passed in 487.32s

python -m ruff check src scripts tools tests
All checks passed
```

冻结 v2 的审核合同测试保留并通过；其中的路径断言已改为验证 `legacy/review-v2/skills/` 的归档完整性，而不是要求旧 Skill 继续自动发现。

## A/B 与默认切换的剩余执行条件

以下不是未实现的代码功能，而是必须由真实赛题运行产生的外部证据：

1. 选一套陌生完整旧题，冻结模型、附件、时间、工具权限与初始提示；
2. 分别运行 legacy-v2 和 v3，保留 PDF、代码、结果、运行说明和 token/时间统计；
3. 对最终材料做不暴露工作流的盲评；
4. 验证 v3 的顶层任务数不超过 3、前 20% 预算内得到 baseline/probe、关键数字真实执行、逐问直接回答、致命科学错误更少或相等、盲评分不低于 legacy；
5. 仅在满足条件后，将 `init_run.py` 的默认 workflow 改为 `capability-first-v3`，再决定是否进一步归档旧代码。

PR 关闭、远端 tag 推送和远端分支操作也未执行：它们需要仓库维护者在正确的远端分支上确认，不应由本地实现擅自替代。
