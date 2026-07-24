# shumozizi Capability-First v3 项目约定

## 项目定位

本仓库是 Codex 桌面版驱动的数学建模能力工作台。默认目标是更快理解题目、选择有效路线、真实运行实验并写出能直接回答题目的论文；不是构建审核生命周期平台。

`legacy/review-v2/` 中保留旧系统和历史材料，处于冻结状态。新功能不得依赖或扩展其中的状态服务、审核模块、回执、裁决、闭环或按问审核机制。

## 主动 Skill

自动发现目录 `.agents/skills/` 保留以下十三项主动能力：

- `mathmodel-workflow`：完整赛题的连续编排与恢复；
- `mathmodel-solve`：题意理解、路线比较、主路线与 fallback；
- `mathmodel-capability-router`：冻结主能力、交叉能力、本地知识、可用工具和独立验证路线；
- `mathmodel-experiment`：真实执行、调试、验证和图表；
- `mathmodel-matlab`：MATLAB/Octave 的独立 oracle、优化挑战和三维证据图；
- `mathmodel-visual`：按题型生成模型、搜索与结果的 Figure Contract；
- `mathmodel-paper`：从真实 current 结果撰写和编译论文；
- `mathmodel-red-team`：在全新 Codex 对话中执行科学红队或 PDF 盲审；
- `mathmodel-final-check`：独立盲审后的机械 QA 与追溯复验；
- `mathmodel-learn-paper`：离线学习论文，不进入比赛主链。

用户只要求数据分析、调试代码或修改论文时，不得自动启动完整工作流。完整赛题由连续生产、独立科学红队、论文、独立 PDF 盲审和最终交付审核组成；目标语义预审、科学红队、PDF 盲审和最终审核必须各自新建 Codex 对话，不能复用求解或论文上下文。最终审核按数学建模竞赛论文标准自由判断，不能按表格勾选代替结论；论文必须直接收录完整 Python/MATLAB 源码文本，MATLAB 高风险路线还需正文使用 `.m` 生成的证明图。一次集中修订后的二次仍不通过即停止。

## v3 运行目录与状态

使用以下命令创建并行 v3 运行：

```powershell
python scripts/codex/init_run.py <problem_path> `
  --workflow capability-first-v3 --run-id <run-id>
```

或使用 `scripts/codex/init_simple_run.py`。v3 状态只在
`runs/<run-id>/state/run.json`，关键判断记录在 `state/DECISIONS.md`。它只保存进度、路线、下一步、预算和产物路径；不得保存科学是否通过、finding 是否关闭或任何审核状态。阶段必须依次经过 `analysis -> capability_route -> experiment -> scientific_review -> visualization -> paper -> paper_review -> verify -> complete`；`blocked` 只能回到 `analysis`、`capability_route` 或 `experiment`。独立审查的冻结包、报告和可机读摘要只允许存放在 `review/`，不写回 `run.json`。

`capability_route` 先冻结工具探测、主能力、至多两个交叉能力、独立验证能力和至多五项本地知识资产；几何/机理题必须有独立 oracle，并在进入 `scientific_review` 前以 `kind=independent-oracle` 实际运行、登记相应的 `.py` 或 `.m` 源码。`scientific_review` 必须由新对话只读取 `review/packet/scientific/`：从题面独立重建问题，攻击最高风险模型原语与搜索区域，检查共模错误和下游继承。通过后先进入 `visualization`，完成按题型要求的模型、搜索和结果证据图及完整模板实例化，才可写论文。`paper_review` 必须由另一个新对话只读取 `review/packet/paper-blind/`，初始不可见源码、科学审查和质量标签；PDF 变更会使盲审失效。`verify` 只执行机械 QA，不能重新定义科学正确性。

v3 运行时只能使用 `shumozizi.simple`。禁止导入 `shumozizi.workflow.state_service`、审核模块或 legacy 结果准入链。

## 结果与执行

代码必须实际运行，不得编造数据、指标、图表或引用。执行统一使用：

```powershell
python scripts/runtime/run_simple_experiment.py runs/<run-id> `
  --question Q2 --kind primary --command "python code/q2.py" `
  --expect results/raw/q2.json
```

执行器保存命令、退出码、stdout/stderr、源脚本、输入输出路径与哈希。指标只能从本次 JSON 输出的 `metrics` 字段或显式 JSON 路径提取，并记录字段来源与文件哈希。`results/index.json` 只证明运行事实；`current` 且 `execution_valid=true` 的结果可作为论文事实候选，但这不表示路线科学上优秀。

## 路线、预算和人工决策

先做不变量/上下界、重参数化、分解、事件、小规模 oracle 与可辨识性风险的结构预检；再由能力路由登记主能力、交叉能力、验证能力和按需本地知识资产。知识只提出候选，先生成两到三条实质不同的候选路线，再做最低成本 probe 并确定主路线与 fallback。实现错误直接修复；参数或求解器问题在路线内调整；fallback 更优时直接切换并记录。比赛解题和独立审查默认禁止联网检索同题答案、公开题解或历史 run；只可使用当前题面、运行包和通用本地知识库。

只有改变题意解释、核心目标或必做输出，或者新增投入超过剩余预算 30% 时才询问用户。最终提交前可请求一次确认。连续两次无实质改善时停止，记录原因并收缩目标、切换 fallback 或请用户决定。

## 论文与终检

论文每问必须含题目要求、模型理由、核心公式、求解、关键结果、可信性检验、直接回答和边界。追溯信息必须写入源码注释，Typst 使用 `// @result <id>` 与 `// @metric <id>.<metric> <number>`（LaTeX 使用 `%`、Markdown 使用 `<!-- -->`）；不得使用会出现在 PDF 中的 `[[result:...]]` 或 `[[metric:...]]` 标记。

机械终检使用：

```powershell
python scripts/qa/run_final_checks.py runs/<run-id>
```

它生成 `qa/mechanical-qa.json`、`qa/contact-sheet.png` 与 `reports/VERIFY_REPORT.md`，并检查 PDF、路径、占位符、匿名、图表可读性、current 结果哈希、指标来源、结果引用与数值一致性等确定性问题。匿名投稿必须显式追加 `--anonymous`，必要时用 `--anonymous-term` 指定禁止身份词；图表/表格编号目前只作 warning。机械 QA 只复验事实和可提交性，不判定几何、模型、搜索充分性或竞赛竞争力；这些内容必须在论文前的独立科学红队中处理。

## 代码与文件约束

- Python 模块、类和公共函数使用 Google 风格 docstring；注释使用中文并解释原因。
- 所有文件写入使用原子写入或同目录安全替换；路径必须限制在当前运行目录内。
- Windows 必须可运行；不依赖 Bash 作为唯一入口。
- 不启动 WebUI、Redis、旧多 Agent 框架、云端解释器、数据库或命令行 Codex 调度。
- 不自动提交或推送 Git。
- 不修改 `legacy/review-v2/` 的业务语义；必要的兼容工作仅限归档说明。
