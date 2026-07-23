# shumozizi：Capability-First 数学建模工作台

shumozizi 帮助 Codex 在有限比赛时间内完成完整数学建模赛题：理解题目、比较路线、真实执行代码、生成图表，并写出逐问直接回答的论文。核心价值是解题能力、实验信息量和论文说服力，而不是更多状态、Schema 或审核任务。

## v3 架构

```text
能力层：理解题目、建模、实验、写作、改进
             ↓
局部证据层：命令、日志、输出、哈希、随机种子、三段 adapter
             ↓
独立审查层：新对话科学红队 → 新对话 PDF 盲审
             ↓
机械交付层：编译、路径、占位符、匿名、PDF QA
```

局部证据层只证明程序运行过且受控实现彼此一致；它不能排除共享的错误数学语义。实验结束后必须由新的 Codex 对话基于冻结审查包重建问题、做反例和独立挑战，科学红队通过才可写论文。PDF 生成后必须再由另一新对话盲审，机械 QA 只复验提交与追溯。

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
├── review/                  # 冻结审查包、独立报告与摘要
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
- `mathmodel-capability-router`：在实验前冻结能力、工具、独立 oracle 与本地知识资产；
- `mathmodel-experiment`：代码、真实运行、按题型验证、保存搜索轨迹、几何事件和真实绘图数据；
- `mathmodel-matlab`：检测 MATLAB/Octave，提供独立公式实现、优化挑战和三维证据图；
- `mathmodel-visual`：在科学红队通过后，按题型生成模型图、搜索诊断图和结果图；
- `mathmodel-paper`：真实结果到论文、Figure Contract 与一次 Claim–Evidence 自审；
- `mathmodel-red-team`：必须在全新 Codex 对话中执行的科学红队和 PDF 盲审；
- `mathmodel-final-check`：独立盲审后的机械 QA 与追溯复验；
- `mathmodel-learn-paper`：离线论文学习。

默认生产任务不为每问创建审核，也不要求固定实验族。能力路由、题型必需的 Figure Contract 和竞赛模板清单是生产主链的交付前置条件，不是对答案的评分或限制思考；它们只确保所需能力资产、真实图表证据和写作模板实际被使用。

完整主链为：

```text
analysis -> capability_route -> experiment -> scientific_review
-> visualization -> paper -> paper_review -> verify -> complete
```

几何/运动或机理题的能力路由必须指定独立 oracle；若本机存在 MATLAB 或 Octave，可将其作为 Python 生产求解器之外的公式实现、优化挑战或三维图工具。工具探测、路由和图表合同分别由 `scripts/capabilities/detect_tools.py`、`scripts/capabilities/record_route.py`、`scripts/figures/record_visualization.py` 记录。进入论文前使用 `scripts/paper/select_template.py --materialize` 从完整 `skills/5writing` 模板库选择并实例化与比赛、语言、引擎匹配的模板；未识别比赛不会静默回退。

## 独立审查边界

实验完成后将状态推进到 `scientific_review`，由协调任务创建科学包并新建 Codex 对话：

```powershell
python scripts/review/build_review_packet.py runs/<run-id> --kind scientific
```

新对话初始只读该包，不能访问求解上下文、质量日志、历史 run、网络或公开同题答案；它独立重建题意、攻击高风险数学原语并挑战搜索区域。导入合格报告后才能进入 `paper`。PDF 生成后依次进入 `paper_review`，重新建立 `--kind paper-blind` 包，再由另一个只看题面、附件和 PDF 的新对话盲审。PDF 盲审通过后才进入 `verify`；当前 PDF 的机械 QA 也通过后才能 `complete`。任一冻结输入、代码、结果或 PDF 漂移都会撤销相应审查。

## 机械终检

论文编译为 `paper/final.pdf` 后运行：

```powershell
python scripts/qa/run_final_checks.py runs/2026-A-001 --anonymous
```

该命令生成：

- `qa/mechanical-qa.json`：PDF、空白页、裁切、文字重叠、占位符、失效结果引用、current 结果哈希、输出指标来源和关键数字检查；
- `qa/contact-sheet.png`：便于人工快速查看的 PDF 联系表；
- `reports/VERIFY_REPORT.md`：简短可定位的验证摘要。

独立科学红队报告写入 `review/SCIENTIFIC_RED_TEAM.md`：它在论文前通过题面重建、清洁室复现、反例和不同搜索族挑战发现共模错误。PDF 盲审报告写入 `review/PAPER_BLIND_REVIEW.md`：它只看题面、附件、PDF 与提交材料。两者必须是不同的新 Codex 对话，不得读取公开同题答案、历史 run、质量日志或同一求解上下文。图表和表格编号检查仅对 caption 运行且暂为 warning，以避免正文引用误报。

## 按需知识库

`knowledge/` 中保存问题拆解、模型选择、Cookbook、验证、论文写作和 Figure Contract。它们都带来源说明，只作为候选与检查菜单；每阶段最多读取一到两个相关文件，不能替代当前题的路线比较或 probe。`skills/mathmodel-figure-templates/` 保留 11 套可运行科研绘图脚本；它不是第七个主动流程 Skill。v3 已为其中 4 套提供真实结果适配器，调用说明和 JSON 数据格式见 [V3_FIGURE_TEMPLATE_ADAPTER.md](docs/V3_FIGURE_TEMPLATE_ADAPTER.md)。

## legacy-v2

旧的审核生命周期工作流被冻结在 `legacy/review-v2/`，其中包含原有审核 Skill 与历史文档。v3 运行时不导入它们，也不会创建旧审核文件。现阶段 `legacy-v2` 初始化仍为兼容入口；根据计划，只有完成陌生完整旧题 A/B 并满足质量、效率和盲评条件后，才会切换默认并考虑归档更多旧代码。

## 开发验证

```powershell
python -m pytest
python -m ruff check src scripts tools tests
```

第三方来源、许可证和吸收边界见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
