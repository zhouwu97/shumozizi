# shumozizi：Competition-First v3.1 数学建模工作台

shumozizi 帮助参赛者在有限时间内完成题意分析、路线竞争、真实实验、洞察提炼和论文交付。它的主目标是提高路线质量、实验价值和论文的题目特定性，而不是增加 Schema、审核任务或哈希绑定数量。

它不是已被证明能稳定赢得数学建模竞赛的全自动求解器。真实执行、结果追溯、独立挑战和机械 QA 能减少伪造与产物漂移，不能单独证明题意理解、数学模型、全局最优或获奖概率。任何竞争力提升结论都必须来自 held-out A/B 和匿名论文盲评。

## 主链

```text
analysis -> experiment -> paper -> paper_review -> verify -> complete
```

`blocked` 只表示真实生产错误或已验证的负面证据，绝不因为缺少方法画像、主张清单、覆盖声明、图表合同或手工 argument map 而进入该状态。

旧 v3.0 运行可只读打开。读取时会把旧阶段映射为 v3.1 内存状态；第一次显式更新才写入 `state/migrations.json`，原始阶段保存在 `legacy_phase`，历史审核产物仍可查看。

## 工作原则

- 先提高答案上限，再验证安全底线。
- 每题至少建立一个 baseline 和一条数学结构不同的竞争或反证路线；仅更换遗传算法、粒子群或差分进化不算新路线。
- 首先运行能改变路线选择的区分性 probe。没有可能改变路线、模型、主要结论、机制解释或论文贡献的实验，只记录为低优先级建议。
- 生产结果必须由执行器真实运行。`current` 结果、输入输出哈希和指标来源仍是论文数字与图表的唯一事实来源。
- 已发现的反例、独立复算冲突、不可行解、性质测试失败和 incumbent 不具竞争力仍会级联失效结果、图表和论文。
- 目标语义审查只在存在两个以上合理解释、会改变主要结果且题面和用户裁决都无法排除时触发。
- 每轮只做一次自由科学挑战，必要时最多一个专项追问；不再创建默认 coverage、逐风险 follow-up 或 final audit。
- 论文围绕最强问题、结果规律和最多三项真实贡献组织，允许不同问题使用不同篇幅。

## 快速开始

安装依赖并检查环境：

```powershell
python -m pip install -e .[test]
python scripts/doctor.py
```

创建 v3.1 运行：

```powershell
python scripts/codex/init_run.py problems/2026-A `
  --workflow competition-first-v3.1 --run-id 2026-A-001 `
  --competition cumcm --question Q1 --question Q2 --question Q3
```

每个影响路线或论文的实验都必须使用执行器登记：

```powershell
python scripts/runtime/run_simple_experiment.py runs/2026-A-001 `
  --question Q1 --kind baseline --result-id q1_baseline `
  --command "python code/q1.py" --expect results/raw/q1.json `
  --metrics-from results/raw/q1.json
```

进入论文前，选择真实可用的模板并实例化：

```powershell
python scripts/paper/select_template.py runs/2026-A-001 `
  --language zh --engine auto --reason "比赛与语言匹配。" --materialize
```

论文编译和机械检查：

```powershell
python scripts/paper/compile_paper.py runs/2026-A-001
python scripts/qa/run_final_checks.py runs/2026-A-001 --anonymous
```

## 运行产物

```text
runs/<run-id>/
├── analysis/
│   ├── ROUTE_COMPETITION.md
│   ├── NEXT_EXPERIMENTS.md
│   ├── INSIGHTS.md
│   ├── answer_map.json
│   └── method_facts.json             # 可选建议，不是门禁
├── results/                          # 真实执行与 current/superseded 结果
├── figures/current/                  # 当前数据与脚本产生的图
├── paper/
│   ├── STORYBOARD.md                 # 可选叙事规划
│   ├── CONTRIBUTION_BRIEF.md         # 最多三项贡献，可选
│   ├── answer-map.json               # 可替代 analysis/answer_map.json
│   ├── generated/argument_map.json   # 后台自动生成
│   └── final.pdf
├── review/
│   ├── SCIENTIFIC_CHALLENGE.md
│   ├── FOCUSED_FOLLOWUP.md           # 最多一个，仅在需要时
│   └── PAPER_BLIND_REVIEW.md
└── qa/mechanical-qa.json
```

`ROUTE_COMPETITION.md` 记录 baseline、竞争路线、区分性 probe、主路线、fallback 和切换条件；`NEXT_EXPERIMENTS.md` 只保留能改变决定的实验；`INSIGHTS.md` 区分观察、证据、机制、验证和边界，允许诚实写出尚未发现稳定规律。

`answer_map.json` 是编译前的必要事实：每个必答问题必须有至少一个当前生产结果和直接答案位置。`STORYBOARD.md`、`CONTRIBUTION_BRIEF.md` 和 `method_facts.json` 用于提高写作质量与验证针对性，缺失只产生警告。

## 审查与交付

科学挑战只回答六个问题：独立重建目标/变量/约束、三处最大风险、对最大风险的实际攻击、最薄弱问题、当前竞争力上限、最可能改变结论的下一实验。它必须绑定冻结输入、报告和真实任务回执，但不以覆盖率清单放行。

PDF 盲评必须给出与普通参赛论文相比的优势、最可记住之处、最薄弱章节、模型/结果/图表/写作档次、最可能提升一个奖项层级的修改和 P0/P1 判断。无法创建独立盲评时必须写明跳过原因，不能静默跳过；跳过只允许继续机械 QA，状态为 `unreviewed`，绝不能作为 `complete` 或 `submission_ready` 放行。

完成前重新检查科学挑战仍绑定当前代码、数据和生产结果，再检查 PDF、匿名、占位符、乱码、裁切、空白页、当前结果和当前图表漂移。P0/P1、真实负面证据或失效的事实产物始终阻断 `complete`。

## Skill

主动 Skill 只有六个：`mathmodel-workflow`、`mathmodel-solve`、`mathmodel-experiment`、`mathmodel-visual`、`mathmodel-paper`、`mathmodel-red-team`。

`mathmodel-matlab`、`mathmodel-geometry-oracle`、`mathmodel-geometry-visual`、`mathmodel-optimizer-benchmark` 和 `mathmodel-learn-paper` 是按需工具。`mathmodel-capability-router` 保留给旧运行和按需能力探测；`mathmodel-final-check` 是机械执行器，不承担独立思考。

## 评测边界

`evaluation/` 提供 3 题烟雾、held-out 清单、pairwise 匿名顺序、错误注入和过程指标工具。当前仓库不声称已完成 12--16 题 A/B，也不声称流程已证明提高竞赛竞争力。只有在固定模型、时间、Token、算力、资料和人工干预的真实对照完成后，才可报告胜率、致命错误发现率和协议维护成本变化。

## 开发验证

```powershell
python -m pytest
python -m ruff check src scripts tools tests
```

`legacy/review-v2/` 和 v3.0 协议只用于兼容与归档；新功能不得重新把它们接回 v3.1 生产主链。
