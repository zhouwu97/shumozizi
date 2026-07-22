# shumozizi：Capability-First 数学建模工作台

shumozizi 帮助 Codex 在有限比赛时间内完成完整数学建模赛题：理解题目、比较路线、真实执行代码、生成图表，并写出逐问直接回答的论文。核心价值是解题能力、实验信息量和论文说服力，而不是更多状态、Schema 或审核任务。

## v3 架构

```text
能力层：理解题目、建模、实验、写作、改进
             ↓
证据层：命令、日志、输出、哈希、随机种子
             ↓
验收层：编译、路径、占位符、匿名、PDF QA、一次整体审查
```

证据层只证明程序运行过；机械 QA 只发现确定性错误；科学质量由完整结果和一次整体审查判断。

## 快速开始

安装依赖并检查环境：

```powershell
python -m pip install -e .[test]
python scripts/doctor.py
```

创建一个 v3 运行：

```powershell
python scripts/codex/init_run.py problems/2026-A `
  --workflow capability-first-v3 --run-id 2026-A-001 `
  --competition cumcm --question Q1 --question Q2 --question Q3
```

运行目录是：

```text
runs/<run-id>/
├── problem/                 # 题面与附件副本
├── state/run.json           # 最小进度状态
├── state/DECISIONS.md       # 路线与关键判断
├── reports/                 # 分析、结果和验证报告
├── code/                    # 可执行代码
├── results/index.json       # 执行事实与 current/superseded 结果
├── figures/
├── paper/                   # 源文件、章节与 final.pdf
└── qa/                      # 机械 QA、联系表和最终审查
```

在 Codex 中，仅当用户明确要求完成整题、实验和论文时调用 `$mathmodel-workflow`。局部任务直接用 `$mathmodel-solve`、`$mathmodel-experiment`、`$mathmodel-paper` 或 `$mathmodel-final-check`。

## 实际执行和结果追溯

每一个要进入论文或影响路线的运行必须经过执行器：

```powershell
python scripts/runtime/run_simple_experiment.py runs/2026-A-001 `
  --question Q2 --kind primary --result-id q2_primary `
  --command "python code/q2.py" `
  --expect results/raw/q2.json `
  --input problem/attachments/data.xlsx `
  --metrics-from results/raw/q2.json
```

脚本必须将可引用指标写入 JSON 输出，例如 `{"metrics": {"objective": 123.45}}`。执行器固定 `shell=False`，从输出自动提取指标、记录 JSON 路径、文件哈希、命令、退出码、stdout/stderr、源脚本和执行时间；不接受手填数值。新结果会将同问同类型旧结果标记为 `superseded`；只有仍为 `current` 且 `execution_valid=true` 的结果才可作为论文事实候选。

## 主动 Skill

- `mathmodel-workflow`：完整赛题的连续执行与断点恢复；
- `mathmodel-solve`：题意、数据、候选路线、probe、主路线与 fallback；
- `mathmodel-experiment`：代码、真实运行、按题型验证、图表和路线切换；
- `mathmodel-paper`：真实结果到论文、Figure Contract 与一次 Claim–Evidence 自审；
- `mathmodel-final-check`：机械 QA 和一次整体科学审查；
- `mathmodel-learn-paper`：离线论文学习。

默认生产任务不为每问创建审核，不要求固定实验族，也不把知识库、决策记录或图表合同变成阻断门。

## 机械终检

论文编译为 `paper/final.pdf` 后运行：

```powershell
python scripts/qa/run_final_checks.py runs/2026-A-001 --anonymous
```

该命令生成：

- `qa/mechanical-qa.json`：PDF、空白页、裁切、文字重叠、占位符、失效结果引用、current 结果哈希、输出指标来源和关键数字检查；
- `qa/contact-sheet.png`：便于人工快速查看的 PDF 联系表；
- `reports/VERIFY_REPORT.md`：简短可定位的验证摘要。

一次整体审查写入 `qa/FINAL_REVIEW.md`，只判断题目覆盖、逐问回答、模型目标一致性、结果信息量、baseline/正控制、公平性、可辨识性和结论边界。P0/P1 可触发一次定向修复；P2/P3 和排版小改不重新开启完整审查。图表和表格编号检查仅对 caption 运行且暂为 warning，以避免正文引用误报。

## 按需知识库

`knowledge/` 中保存问题拆解、模型选择、Cookbook、验证、论文写作和 Figure Contract。它们都带来源说明，只作为候选与检查菜单；每阶段最多读取一到两个相关文件，不能替代当前题的路线比较或 probe。

## legacy-v2

旧的审核生命周期工作流被冻结在 `legacy/review-v2/`，其中包含原有审核 Skill 与历史文档。v3 运行时不导入它们，也不会创建旧审核文件。现阶段 `legacy-v2` 初始化仍为兼容入口；根据计划，只有完成陌生完整旧题 A/B 并满足质量、效率和盲评条件后，才会切换默认并考虑归档更多旧代码。

## 开发验证

```powershell
python -m pytest
python -m ruff check src scripts tools tests
```

第三方来源、许可证和吸收边界见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
