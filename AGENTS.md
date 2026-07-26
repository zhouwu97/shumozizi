# shumozizi Competition-First v3.2 项目约定

## 目标

这是 Codex 桌面版驱动的数学建模工作台。生产主链的唯一目标是在同等模型、时间、Token、算力和资料条件下，提高路线质量、实验价值、结果洞察和匿名论文表现。不要把 Schema、审核任务、哈希、回执或全绿测试当作竞争力证明。

新 v3.2 运行使用：

```text
analysis -> experiment -> paper -> paper_review -> verify -> complete
```

`blocked` 仅用于真实生产失败或实际负面证据，不能因为缺少 metadata、可选文档或旧协议文件阻断。v3.1 与 v3.0 状态保持兼容：读取 v3.0 时映射 `capability_route -> analysis`、`scientific_review/visualization -> experiment`、`final_review -> verify`；第一次显式更新才保存 v3.1 和迁移日志。

## 主动 Skill

完整赛题只使用以下六个主动 Skill：

- `mathmodel-workflow`
- `mathmodel-solve`
- `mathmodel-experiment`
- `mathmodel-visual`
- `mathmodel-paper`
- `mathmodel-red-team`

`mathmodel-matlab`、`mathmodel-geometry-oracle`、`mathmodel-geometry-visual`、`mathmodel-optimizer-benchmark` 和 `mathmodel-learn-paper` 是按需工具。`mathmodel-capability-router` 仅为旧运行或按需工具探测保留，不能成为新运行阶段。`mathmodel-final-check` 只执行机械 QA。

局部分析、调试或论文修改不得自动启动完整工作流。

## 路线与实验

- 前期可用 fresh thread、获奖论文结构卡或网页 GPT 讨论题意、建模、反例、验证和论文建议；专家卡和网页讨论都是发现问题的可选手段，不是阶段门。进入实验前的正式 `MODELING_UNITS.json` 仍须有两次只绑定 `problem/` 的真实 fresh-thread 题意重建，但回执只证明独立性，绝不证明模型或结论已正确。应及时把改变路线的判断写成绑定 `problem/` 的 `analysis/BASELINE_FREEZE.json` 决策快照，并在问题、反例或实验冲突出现后修订、重跑和复审。
- 获奖论文专家库和网页讨论都不是答案库、引用库、结果来源或状态门。运行时只能读取安全 `library.json`；来源、页码与论文标识仅保留于离线 `provenance.json`。未冻结时路由须标记 `advisory_only=true` 和 `requires_independent_verification=true`；冻结或修订后应重新路由，并用 `AWARD_EXPERT_ROUTE_AUDIT.json` 确认 `structure_only=true`、`prompt_safe=true` 和 `raw_sources_returned=0`。审计须说明它没有操作系统级文件访问监控。
- 网页 GPT 仅可基于用户提供的题面讨论和批评，禁止联网检索题目答案、题解、往届答案或相近题的现成结论，也不得复用此类内容。其建议与专家卡只能帮助路线竞争、probe、验证、研究主线和 LaTeX 论文组织；不得作为当前模型、参数、结果、图表、代码、citation、claim evidence 或 exact 比较的替代品。需要并行讨论时，先将仅基于 `problem/` 的路线冻结为 `LOCAL_ROUTE_SNAPSHOT.json`，发给网页的首轮提示不得披露该路线，且在本地路线写完前不得阅读网页回应；之后将差异和本地验证动作写入 `EXTERNAL_DISCUSSION_COMPARISON.json`。实现总结必须另开网页 fresh chat，不能续用首轮讨论；它只能给出可由 exact scorer 和真实实验检验的实现建议，不能替代本地寻找最优。所有可采纳建议必须由当前运行的 baseline、exact scorer、真实实验、独立复算或 fresh-thread 审核验证；同题资料仍只能在 baseline 快照后进入 answer-filter。
- 目标不得在看到策略后果之前冻结。题面留有解释空间时，`analysis/OBJECTIVE_CANDIDATES.json` 必须保留至少两个候选目标（各含公式、预期策略偏好、题面依据）和一组共同后果度量，其中至少一个是公平、瓶颈或安全指标。每个候选都要有真实低成本 probe；若冻结候选让某 guard 指标跌破下限而其它候选没有，必须写出权衡裁决并绑定至少两点真实 Pareto 证据。`analysis/objective-ambiguities.json` 仍有未决且会改变主结果的歧义时，不能用 `determined` 跳过候选比较。
- v3.2 每个 `compare` 单元必须有 baseline、两条数学结构不同的竞争路线和 fallback；`oracle_only` 仅用于题型明确需要独立 oracle 的单元。单纯替换 GA、PSO、DE 等求解器属于同一路线比较。每个单元必须显式声明 `core_question`，且运行至少有一个核心问题。
- 比较统一 exact 目标、实际预算与可行性优先；首个可行解后必须至少用两类异构策略深化，且只可使用计划声明的停止理由白名单。灵敏度、鲁棒性和题型 oracle 条件触发，不能互相替代。
- 比较必须真的判胜负。赢家由统一 exact scorer 的实测结果决定，不能由声明指定；核心问题的赢家必须相对 baseline 达到事前声明的 `significant_improvement_ratio`，否则继续搜索、换路线，或用 `baseline_near_bound` 加实际界证据说明已接近上限。深化后的最终结果不得比比较阶段的赢家更差。核心问题的竞争路线要给出可量化的 `expected_improvement_ratio`，实测明显落空时登记 `upside_shortfall` 的原因与决定。
- 预算优先给搜索。核心问题的搜索与深化耗时必须超过其验证与复算耗时，核心搜索还要占实际算力的 40% 以上；分母统计全部已执行结果，把复算跑成 exploration 不能稀释这条检查。
- 核心问题必须提炼带 `insight_id` 的结构化规律（观察、机制、真实结果证据、边界），其中至少一条属于机制、边际收益、活跃约束或权衡；只有反直觉描述不算理解。
- 将主路线、fallback、切换条件写入 `analysis/ROUTE_COMPETITION.md`；将只有决策价值的实验写入 `analysis/NEXT_EXPERIMENTS.md`。
- 实验必须真实执行，使用 `scripts/runtime/run_simple_experiment.py`。论文数字和图表只能来自 `current` 且 `execution_valid=true` 的生产结果。
- `analysis/method_facts.json` 以实验显式登记为准，并联合结果、命令和源码提示；全面审核后必须连同强断言进入结构化 gap 查漏。`method_profile.json`、`critical_claims.json` 仍是 legacy 兼容，不参与 v3.1 跳转。
- 负面证据仍必须优先级联失效结果、图表和论文：反例、独立复算冲突、不可行、性质测试失败、proxy/exact 冲突、incumbent 不具竞争力都不能被报告文字覆盖。

## 审查

只有高影响且未解决的目标歧义才触发独立目标语义审查。判断来自 `analysis/objective-ambiguities.json`：至少两个合理解释、可能改变主结果、题面未排除、用户未裁决。

**v3.1/v3.2 Competition-First 审查（当前主链）**：实验结束做一次科学挑战，报告 `review/SCIENTIFIC_CHALLENGE.md`。科学挑战采用两阶段阅读：阶段A只读 `problem/`，独立重建数学结构、最简 baseline、可能更强的候选路线和最关键歧义，并明确写入报告；阶段B再读代码和结果，与阶段A比较后选择一个最高价值结论实施真实攻击，说明攻击结果（推翻/支持/不确定）。风险数量不设要求——一个足以决定论文上限的缺陷可以集中全部篇幅；报告只要求非空（> 300 字符）且包含实质分析，不检查固定关键词或固定栏目数量。”是否存在明显更强的路线或目标定义”必须用 `record_stronger_alternative` 写成 `review/stronger-alternative.json` 闭合——`found=False` 记录会绑定记录时的生产结果集合，如果后续实验新增了生产结果，记录自动失效需重新记录；`found=True` 时要么真的跑一次并绑定真实生产结果，要么写明为何赛程内不可行；未闭合不放行论文。v3.1/v3.2 **不使用** `review/gaps/round-N.json` 查漏系统，该系统仅属于 Capability-First v3.0 路径。

**v3.0 Capability-First 审查（旧运行兼容）**：报告冻结后必须提取强断言并生成 `review/gaps/round-N.json`：只有具有攻击描述、报告定位与实际证据文件的 `attacked` 风险才能视为覆盖；未覆盖中央风险须由 fresh-thread 专项审核闭合。所有 blocking P2 必须按 finding ID 逐项绑定恢复条件、修复文件、专项报告和回执，不能只关闭其中一个。

PDF 盲评需要一个与当前运行完全隔离的独立上下文：
- **Codex 桌面端**：用 `create_thread` 新建独立顶层对话，禁止 fork 或续用任何已有对话。
- **Claude.ai / Claude Code**：dispatch 一个子 Agent（Agent tool call），**不能新开浏览器页面**；子 Agent 不得接收任何当前 run 的上下文，只接收冻结 PDF 路径 + 提示词。子 Agent 的 agent ID 即为 `raw_thread_id`，`creation_mode` 为 `dispatch_agent`，`provider` 为 `claude`。

无论哪种平台：新上下文只接收冻结 PDF，提示词必须由 `scripts/review/show_paper_blind_prompt.py` 生成，不附带题面、源码、运行记录、作者解释或前序审查结论。盲评写入 `review/PAPER_BLIND_REVIEW.md`，报告结构：第一印象与竞争力定位 → 写作风格诊断（AI 句式、过度分点、空话总结）→ 可读性与论证清晰度 → P0/P1 阻断性问题 → 最高价值修改建议（不超过 5 条）。P0/P1 与已验证负面证据始终阻断。PDF 盲评无法创建时必须明确写 `review/PAPER_BLIND_REVIEW_SKIP.md` 的原因；该说明只允许继续机械 QA，绝不能将运行标记为 `complete` 或 `submission_ready`。

**网页版 GPT 补充审核为可选环节**，只在论文主模型和结果已稳定、需要专项编辑审查时使用，不是每次 PDF 编译后的默认流程。使用时：通过网页”添加照片和文件”只上传当前 PDF 与 `scripts/review/web_paper_audit.py prompt` 生成的固定提示，必须另开网页对话，禁止搜索答案、题解或外部资料。网页审核聚焦写作风格（AI 句式 / 分点堆砌 / 空话）、可读性和论证表达，找出最高价值的修改建议；无法由 PDF 验证的内容标为”需要本地复算/对照题面”。发现需要重写章节、替换主图或回到实验的问题时，直接说明，不要降级为局部修补。将审核结果写入 `WEB_PAPER_AUDIT.json`；如有修复，重新编译并复核。最多使用一轮；确需再次审核时生成新提示。网页评价不能证明省一或任何奖项，只能降低已识别的质量风险。

## 图表与论文

- 图表输出默认在 `figures/current/`。每张图只需要真实来源、它回答的问题、读者看到的 takeaway，以及可选边界；不得为每题、3D、多种子、敏感性或双版本输出凑数量，也不靠输出份数凑数量。
- v3.2 每张图必须声明 role：`model_understanding`、`decisive_evidence`、`insight` 或 `stability`。`stability`（舍入、采样层级、数值稳定性）一律进入附录，不得占据正文版面。省略 role 会被拒绝，否则附录约束形同虚设。
- 图必须由当前数据和当前脚本实际生成，PNG/PDF 可读，并在结果变化后失效。
- 论文只硬性要求每个必答问题在 `analysis/answer_map.json` 或 `paper/answer-map.json` 有直接答案位置和当前结果。核心问题另需用 `insight_ids` 引用实验阶段登记的机制或边际收益类规律——规律只生产不消费时会退化成旁路产物。
- PDF 内源码默认不超过一页（`source_code_appendix.pdf_page_budget`），完整代码走 `mode: attachment`；确有赛事要求时显式声明 `competition_requires_full` 与依据。运行时会自动生成 `paper/generated/argument_map.json`；v3.2 只能使用无回退 LaTeX 学术模板。
- 论文采用可往返的三种逻辑动作：结构蓝图，统一共享模型并逐问成文，证据边界与严格返修。可借鉴蓝图、共享模型、逐问章节、证据局限和返修的五轮思路，但不得把次数固定成状态机或伪造完成度。论文阶段按需路由研究主线、公式语境、结果闭环、图表、摘要、严格评阅和 `latex-layout-editor`，但永远不把专家卡当作当前事实。`paper/STORYBOARD.md` 和 `paper/CONTRIBUTION_BRIEF.md` 是提高质量的软产物；贡献最多三项，不能把常规方法组合包装为创新。
- 小的正文文字改动只需重新编译和机械 QA；影响结论或图表的改动需重新盲评；代码、数据、目标或主要结果改动需回到实验和科学挑战。标记 `complete` 前必须重新验证科学挑战仍绑定当前生产事实。

## 工程约束

- Python 模块、类和公共函数使用 Google 风格 docstring；注释使用中文并解释 WHY。
- 写入运行目录使用原子写入或同目录安全替换；路径必须限制在运行目录内。
- Windows 可运行，不依赖 Bash；不自动提交或推送 Git。
- 不修改 `legacy/review-v2/` 的业务语义。旧协议函数可保留兼容，但不得成为 v3.2 主链硬门。
- 运行 `python -m pytest` 和 `python -m ruff check src scripts tools tests`。测试通过只证明工程行为，不证明竞赛竞争力；后者必须由 `evaluation/` 中的 held-out A/B、错误注入和匿名 pairwise 验证。
