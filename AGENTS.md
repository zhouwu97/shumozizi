# shumozizi Capability-First v3 项目约定

## 项目定位

本仓库是 Codex 桌面版驱动的数学建模能力工作台。默认目标是更快理解题目、选择有效路线、真实运行实验并写出能直接回答题目的论文；不是构建审核生命周期平台。

`legacy/review-v2/` 中保留旧系统和历史材料，处于冻结状态。新功能不得依赖或扩展其中的状态服务、审核模块、回执、裁决、闭环或按问审核机制。

## 主动 Skill

自动发现目录 `.agents/skills/` 保留以下十四项主动能力：

- `mathmodel-workflow`：完整赛题的连续编排与恢复；
- `mathmodel-solve`：题意理解、路线比较、主路线与 fallback；
- `mathmodel-capability-router`：冻结主能力、交叉能力、本地知识、可用工具和独立验证路线；
- `mathmodel-experiment`：真实执行、调试、验证和图表；
- `mathmodel-matlab`：MATLAB/Octave 的独立 oracle、优化挑战和三维证据图；
- `mathmodel-visual`：按题型生成模型、搜索与结果的 Figure Contract；
- `mathmodel-paper`：从真实 current 结果撰写和编译论文；
- `mathmodel-research-writing`：把当前方法画像、关键主张、结果和出版图组织为逐问论证；
- `mathmodel-red-team`：在全新 Codex 对话中执行目标语义预审、科学红队或 PDF 盲审；
- `mathmodel-final-check`：独立盲审后的机械 QA 与追溯复验；
- `mathmodel-learn-paper`：离线学习论文，不进入比赛主链；
- `mathmodel-geometry-visual`：按几何题要求绘制临界边界、投影与三维证据图；
- `mathmodel-geometry-oracle`：独立几何公式/数值交叉验证；
- `mathmodel-optimizer-benchmark`：为优化题提供多种子、同预算的搜索质量证据。

用户只要求数据分析、调试代码或修改论文时，不得自动启动完整工作流。完整赛题遵循“自由分析 → 首轮真实实验 → method profile → critical claims → 开放科学审核 → 动态风险查漏 → 独立验证 → 负面证据级联回退 → 科学图 → 论文 → 开放 PDF 盲审 → 动态论文风险查漏 → 终检”。目标语义预审、科学红队、PDF 盲审和最终审核必须各自使用真实的新任务回执，不能复用求解或论文上下文。源码按赛事规则在 PDF 关键代码和附件完整工程之间分配；MATLAB/Octave 只是可选独立引擎，不能因工具存在而强制 proxy-exact 或证明图。一次集中修订后的二次仍不通过即停止。

## v3 运行目录与状态

使用以下命令创建并行 v3 运行：

```powershell
python scripts/codex/init_run.py <problem_path> `
  --workflow capability-first-v3 --run-id <run-id>
```

或使用 `scripts/codex/init_simple_run.py`。v3 状态只在
`runs/<run-id>/state/run.json`，关键判断记录在 `state/DECISIONS.md`。它只保存进度、路线、下一步、预算和产物路径；不得保存科学是否通过、finding 是否关闭或任何审核状态。阶段必须依次经过 `analysis -> capability_route -> experiment -> scientific_review -> visualization -> paper -> paper_review -> verify -> final_review -> complete`；`blocked` 只能回到 `analysis`、`capability_route` 或 `experiment`。独立审查的冻结包、报告和可机读摘要只允许存放在 `review/`，不写回 `run.json`。

`capability_route` 冻结工具探测、主能力、交叉能力、独立验证能力和少量本地知识资产，但不预填方法画像。进入 `experiment` 后先实际运行 baseline/首轮 production 实验，再根据真实方法属性、代码和执行收据生成 `analysis/method_profile.json` 与独立的 `analysis/critical_claims.json`。所有 production 结果绑定逐问 objective semantics 哈希及 dependency scope。科学审核先由自由审核任务在不可见 `required_risks` 的条件下输出报告，报告冻结后才动态生成风险并由独立 coverage task 查漏；覆盖、专项 follow-up 和 `not_applicable` 都必须绑定可复验事实与真实任务回执。任何独立引擎、反例、性质失败或更优候选形成负面证据时，必须在 verdict 检查前通过 `independent_evidence_consequence` 级联失效相关结果、图、argument map、论文和审核。

实验诊断与验证图写入 `figures/evidence/`，科学审核通过后的论文图写入 `figures/publication/`。`paper_review` 同样先开放盲审、后动态生成论文风险并独立查漏；additional findings 的 P0/P1 必须阻断。`verify` 只执行机械 QA，不能重新定义科学正确性或论文论证质量。

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

它生成 `qa/paper-structure-signals.json`、`qa/mechanical-qa.json`、`qa/contact-sheet.png` 与 `reports/VERIFY_REPORT.md`。结构信号只检查缺问、空章节、直接答案、当前结果以及 120 字符、3 个句子、技术内容和解释词等最低非空壳信号；新报告状态只能是 `signals_present` 或 `missing_required_signals`，并明确 `assesses_mathematical_correctness=false`、`assesses_argument_quality=false`、`independent_pdf_review_required=true`。即使 `mechanical_gate_passed=true`，没有有效开放 PDF 盲审、动态覆盖与已关闭专项追问也不得放行。模型合理性、推导有效性、结果解释和说服力只由独立盲审裁决；additional findings 中的 P0/P1 必须阻断。

## 代码与文件约束

- Python 模块、类和公共函数使用 Google 风格 docstring；注释使用中文并解释原因。
- 所有文件写入使用原子写入或同目录安全替换；路径必须限制在当前运行目录内。
- Windows 必须可运行；不依赖 Bash 作为唯一入口。
- 不启动 WebUI、Redis、旧多 Agent 框架、云端解释器、数据库或命令行 Codex 调度。
- 不自动提交或推送 Git。
- 不修改 `legacy/review-v2/` 的业务语义；必要的兼容工作仅限归档说明。
