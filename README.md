# shumozizi：Competition-First v3.2 数学建模工作台

shumozizi 帮助参赛者在有限时间内完成题意分析、路线竞争、真实实验、洞察提炼和论文交付。它的主目标是提高路线质量、实验价值和论文的题目特定性，而不是增加 Schema、审核任务或哈希绑定数量。

它不是已被证明能稳定赢得数学建模竞赛的全自动求解器。真实执行、结果追溯、独立挑战和机械 QA 能减少伪造与产物漂移，不能单独证明题意理解、数学模型、全局最优或获奖概率。任何竞争力提升结论都必须来自 held-out A/B 和匿名论文盲评。

## 主链

```text
analysis -> experiment -> paper -> paper_review -> verify -> complete
```

`blocked` 只表示真实生产错误或已验证的负面证据，绝不因为缺少方法画像、主张清单、覆盖声明、图表合同或手工 argument map 而进入该状态。

新运行默认使用 v3.2：可先用仅题面的 fresh thread、获奖论文结构专家卡或网页版 GPT 讨论题意、建模、反例和验证，再为每个问题形成可修订的 `BASELINE_FREEZE.json` 决策快照与轻量 `MODELING_UNITS.json`。进入实验前，后者仍需两次真实 fresh-thread 题意重建；它们只验证独立性，不代替模型、实验和复算。这是质量改进闭环，不是按文件顺序阻塞的状态机：发现反例、实验冲突或审查缺口后，应修订快照、重跑、复审和改写。专家卡与网页讨论只提供研究主线、验证闭环和论文组织的建议，不提供本题模型、参数、结果或引用，也不构成状态门。`compare` 单元要求 baseline、两条数学结构不同的竞争路线和 fallback；`oracle_only` 单元只用于题型明确需要独立 oracle 的情况。首个可行解只能成为深化起点，不得直接充当最终解。

旧 v3.0/v3.1 运行可继续打开。读取 v3.0 时会把旧阶段映射为 v3.1 内存状态；第一次显式更新才写入 `state/migrations.json`，原始阶段保存在 `legacy_phase`，历史审核产物仍可查看。

## 工作原则

- 先提高答案上限，再验证安全底线。
- 每个 `compare` 单元建立一个 baseline、两条数学结构不同的竞争路线和 fallback；仅更换遗传算法、粒子群或差分进化不算新路线。
- `knowledge/award-experts/library.json` 覆盖 2012--2025 年 CUMCM A/B 的 21 张 structure-only 卡和 15 个角色；可按 A/B、阶段和受限 `topic_key` 选择少量卡。未冻结时会明确标注为 `advisory_only`，冻结或修订 baseline 后应重新路由。`provenance.json` 是离线追溯资产，运行时不读取；同题材料只能进入 answer-filter，不能反向改变模型、参数、结果或论文结构。
- 网页版 GPT 可参与题意、建模、反例、验证与论文建议的讨论或审核，但只能分析用户提供的材料，禁止联网检索题目答案、题解、往届答案或相近题现成结论，禁止复用这类内容。并行讨论时先冻结只依赖 `problem/` 的本地路线，首轮网页提示不披露本地路线且直到本地写完才可阅读回应；随后逐项记录差异与本地验证，最后另开 fresh chat 做实现总结。网页只提出可检验的搜索方向，本地 baseline、exact scorer、真实实验、独立复算或 fresh-thread 审核才可比较候选与寻找最优。
- 在第一批结果后先做科学攻击，再用至少两类策略继续深化，并把停止理由限制为预先声明的白名单。统一 exact 目标、实际预算与可行性事实；灵敏度、鲁棒性和独立 oracle 仅按题型条件触发，彼此不能替代。
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

创建 v3.2 运行：

```powershell
python scripts/codex/init_run.py problems/2026-A `
  --workflow competition-first-v3.2 --run-id 2026-A-001 `
  --competition cumcm --question Q1 --question Q2 --question Q3
```

每个影响路线或论文的实验都必须使用执行器登记：

```powershell
python scripts/runtime/run_simple_experiment.py runs/2026-A-001 `
  --question Q1 --kind baseline --result-id q1_baseline `
  --command "python code/q1.py" --expect results/raw/q1.json `
  --metrics-from results/raw/q1.json
```

可选地，先路由结构建议卡以辅助讨论，或先/后写入 baseline 决策快照；未冻结路由不会成为任何事实依据：

```powershell
python scripts/knowledge/award_experts.py freeze runs/2026-A-001 `
  --input analysis/baseline-freeze-input.json
python scripts/knowledge/award_experts.py route runs/2026-A-001 `
  --award-question A --phase analysis --topic-key route_design
python scripts/knowledge/award_experts.py audit runs/2026-A-001
```

`baseline-freeze-input.json` 必须声明 `allowed_inputs: ["problem/"]`，并如实记录 `award_expert_library_used`、`external_discussion_used` 和 `web_answer_search_used: false`。同一快照发现问题后可修订；修订会使旧路由失效，需重新路由。路由与审计是可选辅助，绝不替代实验、exact 比较或独立审核；网页版讨论严禁联网寻找题目答案或现成题解。

需要使用网页讨论时，可选地写入延迟揭示收据。`freeze-local` 的输入只能来自 `problem/`；首轮讨论发出后不得读取回应，直到本地路线已冻结。`compare` 只接受带本地验证动作的差异，`synthesis` 生成只能交给全新网页对话的提示：

```powershell
python scripts/knowledge/external_discussion.py freeze-local runs/2026-A-001 --input analysis/local-route.json
python scripts/knowledge/external_discussion.py launch runs/2026-A-001 --input analysis/web-discussion.json
python scripts/knowledge/external_discussion.py compare runs/2026-A-001 --input analysis/web-comparison.json
python scripts/knowledge/external_discussion.py synthesis runs/2026-A-001
```

进入论文前，选择真实可用的模板并实例化：

```powershell
python scripts/paper/select_template.py runs/2026-A-001 `
  --language zh --engine latex --reason "v3.2 使用无回退 LaTeX 学术模板。" --materialize
```

论文编译和机械检查：

```powershell
python scripts/paper/compile_paper.py runs/2026-A-001
python scripts/qa/run_final_checks.py runs/2026-A-001 --anonymous
```

编译后的冻结 PDF 还应交给网页版 GPT 做补充审查，但只上传 PDF 和固定提示词，必须新开网页对话且不得网上搜索答案。网页报告只作为待验证 finding 来源；每一项都要转为局部修复、重新编译和复核，不把一次评价或“流程全绿”当作竞赛名次保证：

```powershell
python scripts/review/web_paper_audit.py prompt runs/2026-A-001 --pdf paper/final.pdf
# 通过网页“添加照片和文件”将该 JSON 中的 prompt 与唯一 PDF 附件发给全新的网页对话；不要提供其它材料。
python scripts/review/web_paper_audit.py record runs/2026-A-001 --input review/web-paper-audit-input.json
python scripts/review/web_paper_audit.py repair-plan runs/2026-A-001 --input review/web-paper-repair-plan.json
python scripts/review/web_paper_audit.py status runs/2026-A-001
```

每次重编译改变 PDF 后，旧网页审核会自动归档，必须重新生成提示并审核新 PDF。同一运行最多三轮；第三轮仍存在 P0/P1 时，停止网页审核循环并写入失败复盘：

```powershell
python scripts/review/web_paper_audit.py failure-report runs/2026-A-001 `
  --input review/web-paper-audit-failure-input.json
```

失败复盘必须列出工作流、建模、证据、论文/图表问题和下一步，运行会维持 `not_submission_ready`，不能标记完成。网页审核只降低已识别风险，不保证省一或任何奖项。

## 运行产物

```text
runs/<run-id>/
├── analysis/
│   ├── ROUTE_COMPETITION.md
│   ├── NEXT_EXPERIMENTS.md
│   ├── INSIGHTS.md
│   ├── answer_map.json
│   ├── BASELINE_FREEZE.json          # 独立题面分析冻结；专家库介入前不可改写
│   ├── AWARD_EXPERT_ROUTE.json       # 可选：3--6 张提示安全的结构卡
│   ├── AWARD_EXPERT_ROUTE_AUDIT.json # 可选：结构卡路由隔离审计
│   ├── LOCAL_ROUTE_SNAPSHOT.json      # 可选：仅题面的本地路线先行快照
│   ├── EXTERNAL_DISCUSSION_COMPARISON.json # 可选：延迟阅读后的差异及验证
│   ├── EXTERNAL_DISCUSSION_SYNTHESIS.json  # 可选：给全新网页对话的受限提示
│   ├── MODELING_UNITS.json           # v3.2：题意重建、比较/独立 oracle 与真实回填
│   └── method_facts.json             # 显式事实优先；全面审核后查漏的必需输入
├── results/                          # 真实执行与 current/superseded 结果
├── figures/current/                  # 当前数据与脚本产生的图
├── paper/
│   ├── STORYBOARD.md                 # 可选叙事规划
│   ├── CONTRIBUTION_BRIEF.md         # 最多三项贡献，可选
│   ├── WRITING_ACTIONS.md             # 可从模板复制；分段写作动作，不是固定轮次
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

`answer_map.json` 是编译前的必要事实：每个必答问题必须有至少一个当前生产结果和直接答案位置。`STORYBOARD.md` 与 `CONTRIBUTION_BRIEF.md` 用于提高写作质量；`method_facts.json` 在全面审核冻结后的 gap 查漏中是必需输入，和后置提取的强断言共同派生中央风险。

写作采用三种可往返的逻辑动作：先做结构蓝图，再统一共享模型并逐问成文，最后以证据、边界和严格返修收束。`templates/competition-first/WRITING_ACTIONS.md` 提供提示；它吸收“蓝图、共享模型、逐问章节、证据局限、返修”的优点，但不把五轮写作机械固定为状态机。

论文阶段可按草稿状态路由研究主线、模型推导、结果闭环、图表、摘要、LaTeX 版式或严格返修卡；“Word 排版专家”已改为 `latex-layout-editor`。这些卡只帮助组织当前证据，所有数字、图表、声明和引用仍只能来自当前生产结果与独立来源。

## 审查与交付

科学挑战只回答六个问题：独立重建目标/变量/约束、三处最大风险、对最大风险的实际攻击、最薄弱问题、当前竞争力上限、最可能改变结论的下一实验。它必须绑定冻结输入、报告和真实任务回执，但不以覆盖率清单放行。

PDF 盲评必须用 Codex `create_thread` 新建独立顶层对话，不得 fork、调用子 Agent 或续用写作任务。`paper-blind` 包只冻结最终 PDF；使用 `scripts/review/show_paper_blind_prompt.py` 输出固定的“严格审核”提示词并原样发送，不能附加题面、源码、运行记录、作者解释或既有审核意见。盲评必须给出与普通参赛论文相比的优势、最可记住之处、最薄弱章节、模型/结果/图表/写作档次、最可能提升一个奖项层级的修改和 P0/P1 判断。回执会核对提示词哈希和新 `thread_id`。无法创建独立盲评时必须写明跳过原因，不能静默跳过；跳过只允许继续机械 QA，状态为 `unreviewed`，绝不能作为 `complete` 或 `submission_ready` 放行。

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
