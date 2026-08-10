# shumozizi Competition-First v3.4 项目约定

## 目标

这是 Codex 桌面版驱动的数学建模工作台。生产主链的唯一目标是在同等模型、时间、Token、算力和资料条件下，提高路线质量、实验价值、结果洞察和匿名论文表现。不要把 Schema、审核任务、哈希、回执或全绿测试当作竞争力证明。

新 v3.4 运行继续使用六阶段主链，v3.2 运行保持兼容：

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

`mathmodel-matlab`、`mathmodel-geometry-oracle`、`mathmodel-geometry-visual`、`mathmodel-optimizer-benchmark`、`mathmodel-learn-paper` 和 `mathmodel-literature` 是按需工具。`mathmodel-literature` 只记录双语检索、候选来源核验和引用台账，不执行自动登录、凭据存储、绕过验证码或批量抓取。`mathmodel-capability-router` 仅为旧运行或按需工具探测保留，不能成为新运行阶段。`mathmodel-final-check` 只执行机械 QA。

用户提供完整数学建模题面或附件，或要求解答整题、多问建模、真实实验并形成论文/竞赛交付时，必须优先使用 `mathmodel-workflow` 总控；用户无需精确说出 Skill 名称。只有局部分析、调试、单个实验、单图或论文局部修改时才不自动启动完整工作流。

局部分析、调试或论文修改不得自动启动完整工作流。

## 路线与实验

- 题面和数据审计后、路线竞争前，必须生成结构化任务指纹并检索仓内 `knowledge/indexes/papers.json`。检索使用数据结构、统计单位、任务类型、数学困难、目标与约束结构、验证风险和多问继承关系，题名与领域词只能作为辅助。结果写入运行目录的 `knowledge/analysis-retrieval.json`，允许 `matched`、`no_relevant_match` 或有具体原因的 `unavailable_with_reason`；最多保留 3 张结构相似卡、每卡最多 2 个安全模式，有候选模式时必须逐项采用或拒绝，未执行检索不得正式进入 experiment。知识卡只提供路线启发，不得自动晋级为主路线，也不得迁移原题参数、公式和代码、数值结论或奖项评价。知识卡和索引更新不通过哈希反向失效当前实验、结果或科学挑战。
- 前期可用 fresh thread、获奖论文结构卡或网页 GPT 讨论题意、建模、反例、验证和论文建议；专家卡和网页讨论都是发现问题的可选手段，不是阶段门。进入实验前的正式 `MODELING_UNITS.json` 使用 1.4：所有问题先完成一次 `faithful_reconstruction`，忠实重建决策变量、成功事件、聚合和输出；只有任一 `question_delta.must_recheck_aggregation=true` 或 endpoint 仍为 `comparison_planned` 时，才增加 `semantic_adversary`，专项攻击量词、集合/聚合、前问目标复制和分解失效并给出最小反例。报告中的语义结论是科学硬门；thread ID、task receipt 与 `problem/` 树哈希只作独立性记录，缺少这些元数据不得否决低风险题。回执与多份报告的一致只证明独立上下文和共识，绝不证明目标正确。应及时把改变路线的判断写成绑定 `problem/` 的 `analysis/BASELINE_FREEZE.json` 决策快照，并在问题、反例或实验冲突出现后修订、重跑和复审。
- 获奖论文专家库和网页讨论都不是答案库、引用库、结果来源或状态门。运行时只能读取安全 `library.json`；来源、页码与论文标识仅保留于离线 `provenance.json`。未冻结时路由须标记 `advisory_only=true` 和 `requires_independent_verification=true`；冻结或修订后应重新路由，并用 `AWARD_EXPERT_ROUTE_AUDIT.json` 确认 `structure_only=true`、`prompt_safe=true` 和 `raw_sources_returned=0`。审计须说明它没有操作系统级文件访问监控。
- 网页 GPT 仅可基于用户提供的题面讨论和批评，禁止联网检索题目答案、题解、往届答案或相近题的现成结论，也不得复用此类内容。其建议与专家卡只能帮助路线竞争、probe、验证、研究主线和 LaTeX 论文组织；不得作为当前模型、参数、结果、图表、代码、citation、claim evidence 或 exact 比较的替代品。需要并行讨论时，先将仅基于 `problem/` 的路线冻结为 `LOCAL_ROUTE_SNAPSHOT.json`，发给网页的首轮提示不得披露该路线，且在本地路线写完前不得阅读网页回应；之后将差异和本地验证动作写入 `EXTERNAL_DISCUSSION_COMPARISON.json`。实现总结必须另开网页 fresh chat，不能续用首轮讨论；它只能给出可由 exact scorer 和真实实验检验的实现建议，不能替代本地寻找最优。所有可采纳建议必须由当前运行的 baseline、exact scorer、真实实验、独立复算或 fresh-thread 审核验证；同题资料仍只能在 baseline 快照后进入 answer-filter。
- 目标使用 `analysis/OBJECTIVE_CANDIDATES.json` 1.1，顺序必须是题面合法性筛选、同源反例区分、仍合理候选的策略后果。每个候选先说明题面原句、保留/改变的量词、引入的价值偏好和是否只为方便求解，并标为题面直接支持、合理假设支持、仅敏感性或与题意不符；只有前两类可成为正式目标。合法候选只剩一个时不强迫跑多个目标实验；仍有两个以上时才用共同后果度量运行真实低成本 probe，其中至少一个是公平、瓶颈或安全指标。高风险问题不能只写一句 `determined_basis`；必须声明正式目标、被拒绝替代和拒绝理由，并复用 `MODELING_UNITS` 中的区分反例。`analysis/objective-ambiguities.json` 仍有未决且会改变主结果的歧义时，不能用 `determined` 跳过候选比较。
- 每个必答问题在路线比较前必须在 `MODELING_UNITS.json` 写 `question_delta` 和直接答案合同：先比较相邻问题新增的实体、资源、共享约束与聚合层，再声明要求输出、决策对象/总体、主 endpoint/estimand、主判据、自然 baseline 和 fallback。主 endpoint 必须同时用自然语言与公式写清原子成功、实体内、资源间、实体间、时间和量词次序；聚合口径有歧义时标记 `comparison_planned`，先用玩具反例区分，再对仍合法解释跑后果 probe，不能看完结果后换 endpoint。高风险核心问题必须在路线搜索前用 3--5 个人工案例验证 scorer 的预期排序。
- `MODELING_UNITS` 1.4 按题型使用 `evaluation`、`optimization`、`exact_oracle`、`data_modeling`、`simulation` 或 `coordination`。固定评价、数据建模和仿真写主方法与自然核对，不强迫赛马；`exact_oracle` 同时比较正式指标容差和区间/集合结构。普通题使用主方法加自然比较；核心优化/协同题使用 baseline 加一条数学结构不同的 challenger，只有首轮仍不确定、仍在改善或评审明确指出缺口时才增加第二条 challenger。单纯替换 GA、PSO、DE 属于同一数学路线。每个单元显式声明 `core_question`，且运行至少有一个核心问题。
- `optimization`、`simulation`、`exact_oracle` 和 `coordination` 单元必须填写 `capability_decision` 并显式考虑 MATLAB/Octave。默认先运行 `python scripts/capabilities/detect_tools.py <run_dir>`，将 `matlab_availability` 与 `state/tooling.json` 的真实命令、退出状态和哈希绑定；`not_probed` 不再接受。只有解析解、小规模精确枚举、当前环境明确禁止外部引擎或 MATLAB 无法形成不同实现/科学增益时，才可使用对应 `probe_waiver` 并写具体依据。MATLAB 可以不入选，但不得静默忽略；选用时必须声明 `primary_model`、`optimizer_challenger`、`independent_oracle` 或 `scientific_visualization` 角色。MATLAB 图像统一先写入 `figures/work/<figure_id>/<version>/`。
- 任何“分别求解再组合”的路线必须声明为精确分解、启发式分解或仅作联合优化初值。精确分解给出等价依据；启发式/初值路线必须继续用联合 scorer 改进。没有证明、小规模对照或联合后续时，不得把各子问题分别最优写成全局最优。
- 优化比较统一 exact 目标、实际预算与可行性优先。核心优化/协同题出现首个可行解后，先用 `scripts/review/show_first_feasible_prompt.py` 让独立 AI 只审查最高风险、可推翻假设、更强结构路线和最低成本区分实验，将结论写入现有 `actual.refinement.first_feasible_checkpoint`；不创建新阶段或综合审核文件。checkpoint 返回 `return_analysis` 时必须先修订目标、模型或 scorer 并重新取得首解；返回 `continue_experiment` 后必须执行所提区分实验，并用首解之后产生的 `followup_result_ids` 和结论闭环，再完成至少一类计划内深化。reviewer context ID 只作可选独立性记录，真正阻断的是缺少实质结论、未执行 follow-up 或仍要求返回 analysis。第二类深化只在仍有决策价值时增加。停止理由必须与搜索日志一致，灵敏度、鲁棒性和题型 oracle 条件触发，不能互相替代。
- 比较必须真的判胜负。赢家由统一 exact scorer 的实测结果决定，不能由声明指定；核心问题的赢家必须相对 baseline 达到事前声明的 `significant_improvement_ratio`，否则继续搜索、换路线，或用 `baseline_near_bound` 加实际界证据说明已接近上限。深化后的最终结果不得比比较阶段的赢家更差。核心问题的竞争路线要给出可量化的 `expected_improvement_ratio`，实测明显落空时登记 `upside_shortfall` 的原因与决定。
- 逐问结果必须分为 `objective_answer`、`recommended_plan` 和 `evidence_grade`。题面原目标的答案只由 endpoint 已解决、exact 指标存在、硬约束通过和方案可行决定；无全局证书、相对 baseline 改善弱或扰动不稳定只能降低证据等级或形成附加条件下的建议，绝不能用稳健 fallback 替换正式答案。论文 `primary_result_id` 始终绑定 `objective_answer`。
- 有 Excel 提交产物时，`answer_map.submission_export` 必须登记工作簿相对路径、`source_result_id` 和核心指标单元格；来源必须等于 `objective_answer.result_id`。写入 answer-map、机械终检和提交包物化都会打开工作簿复核核心单元格，不能让 exporter 改用 `recommended_plan`。
- 预算优先给真正会改善解的工作。只有优化/协同核心问题给出搜索深化占实际算力约 35% 的 advisory；验证耗时更高或比例不足不阻断。硬阻断只用于没有真实搜索、仅一个随机种子且明显不稳定、challenger 仍持续快速改善，或声明的停止理由与日志冲突。
- 核心问题必须提炼带 `insight_id` 的结构化规律（观察、机制、真实结果证据、边界），其中至少一条属于机制、边际收益、活跃约束或权衡；只有反直觉描述不算理解。
- 将主路线、fallback、切换条件写入 `analysis/ROUTE_COMPETITION.md`；将只有决策价值的实验写入 `analysis/NEXT_EXPERIMENTS.md`。
- 实验必须真实执行，使用 `scripts/runtime/run_simple_experiment.py`。论文数字和图表只能来自 `current` 且 `execution_valid=true` 的生产结果。
- `analysis/method_facts.json` 以实验显式登记为准，并联合结果、命令和源码提示；全面审核后必须连同强断言进入结构化 gap 查漏。`method_profile.json`、`critical_claims.json` 仍是 legacy 兼容，不参与 v3.1 跳转。
- 负面证据仍必须优先级联失效结果、图表和论文：反例、独立复算冲突、不可行、性质测试失败、proxy/exact 冲突、incumbent 不具竞争力都不能被报告文字覆盖。

## 审查

只有高影响且未解决的目标歧义才触发独立目标语义审查。判断来自 `analysis/objective-ambiguities.json`：至少两个合理解释、可能改变主结果、题面未排除、用户未裁决。

**v3.1/v3.2 Competition-First 审查（当前主链）**：实验结束做一次科学挑战，报告 `review/SCIENTIFIC_CHALLENGE.md`。科学挑战采用两阶段阅读：阶段A只读 `problem/`，独立重建数学结构、最简 baseline、可能更强的候选路线和最关键歧义，并先判断核心风险属于目标语义/分解还是模型/搜索。存在多主体、嵌套量词、聚合词、问题实体变化或先分解后组合时，第一攻击必须针对语义或分解等价性并产出独立玩具反例；只有语义风险低时才优先攻击搜索和数值。阶段B再读代码和结果，与阶段A比较后选择一个最高价值结论实施真实攻击，说明攻击结果（推翻/支持/不确定）。风险数量不设要求——一个足以决定论文上限的缺陷可以集中全部篇幅；报告只要求非空（> 300 字符）且包含实质分析，不检查固定关键词或固定栏目数量。”是否存在明显更强的路线或目标定义”必须用 `record_stronger_alternative` 写成 `review/stronger-alternative.json` 闭合——`found=False` 记录会绑定记录时的生产结果集合，如果后续实验新增了生产结果，记录自动失效需重新记录；`found=True` 时要么真的跑一次并绑定真实生产结果，要么写明为何赛程内不可行；未闭合不放行论文。v3.1/v3.2 **不使用** `review/gaps/round-N.json` 查漏系统，该系统仅属于 Capability-First v3.0 路径。

审查发现必须按修复层级分流：措辞、图注、章节组织和证据边界问题进入 paper；会改变 endpoint、目标、模型、代码、结果、主路线、fallback 或行动建议的问题返回 analysis/experiment，并使旧结果、图表和论文口径失效。不能把模型或结果缺陷降级成局限性说明。

**v3.0 Capability-First 审查（旧运行兼容）**：报告冻结后必须提取强断言并生成 `review/gaps/round-N.json`：只有具有攻击描述、报告定位与实际证据文件的 `attacked` 风险才能视为覆盖；未覆盖中央风险须由 fresh-thread 专项审核闭合。所有 blocking P2 必须按 finding ID 逐项绑定恢复条件、修复文件、专项报告和回执，不能只关闭其中一个。

PDF 盲评需要一个与当前运行完全隔离的独立上下文：
- **Codex 桌面端**：用 `create_thread` 新建独立顶层对话，禁止 fork 或续用任何已有对话。
- **Claude.ai / Claude Code**：dispatch 一个子 Agent（Agent tool call），**不能新开浏览器页面**；子 Agent 不得接收任何当前 run 的上下文，只接收冻结 PDF 路径 + 提示词。子 Agent 的 agent ID 即为 `raw_thread_id`，`creation_mode` 为 `dispatch_agent`，`provider` 为 `claude`。

无论哪种平台：新上下文只接收冻结 PDF，提示词必须由 `scripts/review/show_paper_blind_prompt.py` 生成，不附带题面、源码、运行记录、计划文件、作者解释或前序审查结论。盲评写入 `review/PAPER_BLIND_REVIEW.md`，除第一印象、写作风格、可读性、P0/P1 和最高价值修改外，必须在三分钟内逐问找直接答案、复述一句话贡献、说明问题继承、识别主图及其论点、指出工作报告页，并判断前五页是否建立数据直觉；报告末尾必须按固定提示嵌入同源结构化 JSON，逐问记录缺失论证角色、实际页码和具体 finding。导入器把这些事实写入现有 `review/paper-blind-review.json` 并绑定报告哈希、任务/对话 ID 与 `argument_revision`。P0/P1 与已验证负面证据始终阻断。PDF 盲评无法创建时必须明确写 `review/PAPER_BLIND_REVIEW_SKIP.md` 的原因；该说明只允许继续机械 QA，绝不能将运行标记为 `complete` 或 `submission_ready`。

**网页版 GPT 补充审核为可选环节**，只在论文主模型和结果已稳定、需要专项编辑审查时使用，不是每次 PDF 编译后的默认流程。使用时：通过网页”添加照片和文件”只上传当前 PDF 与 `scripts/review/web_paper_audit.py prompt` 生成的固定提示，必须另开网页对话，禁止搜索答案、题解或外部资料。网页审核聚焦写作风格（AI 句式 / 分点堆砌 / 空话）、可读性和论证表达，找出最高价值的修改建议；无法由 PDF 验证的内容标为”需要本地复算/对照题面”。发现需要重写章节、替换主图或回到实验的问题时，直接说明，不要降级为局部修补。将审核结果写入 `WEB_PAPER_AUDIT.json`；如有修复，重新编译并复核。最多使用一轮；确需再次审核时生成新提示。网页评价不能证明省一或任何奖项，只能降低已识别的质量风险。

## 图表与论文

- Author 默认只接收三个概念：`paper/author-pass/RESEARCH_PACKAGE.md`、`paper/author-pass/AUTHOR_BRIEF.md` 和冷读后的高价值编辑反馈；`PAPER_BLUEPRINT.md`、`paper/answer-map.json`、素材池、故事板、`FIGURE_PLAN`、claim gate 与 generated JSON 只作后台兼容、事实投影和最终审计，不得成为创作前置清单。Research Package 必须压缩投影题面必答合同、正式自然语言答案、共享数学对象/必要假设、关键推导、当前图、主张边界和可用文献；Author Pass 只以正式 objective answer、current production 绑定和已关闭 scientific P0/P1 为科学硬门。知识检索零匹配时自动给出通用结构模式；可检索实际使用的方法文献，但禁止同题答案、题解和现成结论，约 6–12 篇参考文献只作紧凑性建议。
- Author Pass 与长篇首稿必须后台生成 `paper/generated/VISUAL_REQUIREMENTS.json`：按数学对象、决定性证据、机制和边界检查 current 图覆盖，未覆盖项自动进入 living visual opportunity pool。该文件不得成为 Author 手填清单；Hero 图只保留少数高记忆点候选，supporting 图按真实论证需要增加且不设总数上限。候选稿前每项需求必须由 current 正式图覆盖或经视觉评阅者实质 `DROP`；`ADD_FIGURE`、`ADD_COMPANION_FIGURE` 和已接受的 `route=visual` 作者请求都必须回流 Visual Sandbox。
- 候选稿前运行 `scripts/paper/audit_report_style.py`。只有 E001 正文泄漏内部术语属于确定性硬错误；E002--E005（重复报账模板、无统一主线的逐问摘要、核心问过度列表化、图后论证薄弱）与句长、标题、列表密度、篇幅和图数均为 editorial signal，由独立 PDF 阅读裁决，不能直接阻断或诱导 Author 按检查项补句。
- Competition-First v3.2 的 CUMCM 正式候选稿使用 `CUMCM_STRUCTURE_MAP` 1.2；1.1 只保留旧运行兼容。`classic` 保留固定栏目兜底；`semantic` 定义为“经典国赛外壳 + 语义内核”。共享对象与问题递进只决定外壳建议，Author 仍可合并相邻问题、集中共享推导并自由安排章节深度；结构适配不得修改模型、数字、结论或证据等级。`presentation_contract` 与 `CUMCM_LAYOUT_AUDIT` 都只消费当前 PDF 和盲评事实，保持 advisory。页数唯一政策为：少于 18 页强编辑复核、18--23 页压缩复核、24--30 页正常规划、超过 30 页压缩复核；四档全部不自动阻断。
- 新视觉先进入 `figures/visual-ideas.json` 和 `figures/sandbox/<idea-id>/`，不要求结果绑定、caption、label、manifest、waiver、`argument_unit_ids`、`obligation_types` 或 `panel_mapping`。关键 insight 用 2--4 个候选做视觉竞争；胜出草图只冻结为 design reference，必须再由 current 数据与正式 renderer 在 `figures/work/` 重生成，之后才进入来源绑定、QA 和 current 晋级。`FIGURE_PLAN` 2.4 只作旧运行兼容与晋级后的后台审计。
- `PAPER_BLUEPRINT.md` 和自动生成的 `argument_coverage.json` 用于成稿后的查漏，不得预生成固定每问小节或阻断 Author 开始长篇写作。直接答案绑定、科学事实和正式结果资格仍是硬门；论证、机制、视觉与叙事缺口交给 longform cold read。
- 写作前蓝图审阅为可选 advisory；第一版 PDF 后必须做独立 cold read。每次最多保留五项最高价值 finding，普通动作默认 advisory，只有明确 `blocking=true` 的 P0/P1 未关闭时阻断候选稿。
- 图表在 `figures/work/<figure_id>/<version>/` 迭代，通过文件可读性、PNG/PDF 几何一致性和人工看图后晋级 `figures/current/`；被替换的 current 自动留入 `figures/archive/`。流程图另查文字越界、重叠、最小字号、箭头穿字和连接点居中。
- 晋级为正式图时声明 `model_understanding`、`decisive_evidence`、`insight` 或 `stability`，并人工复核对象、观察、机制、边界、表格冗余、图注和字号；草图阶段不填这些字段。`stability` 一律进入附录。
- 空间、集合、网络、场、决策面或区间结构优先试真实结构原型；普通柱形图/折线图确实最清楚时由 fresh reviewer 说明理由，不要求 Author 填写预防性 override 表单。
- 图必须由当前数据和当前脚本实际生成，PNG/PDF 可读，并在结果变化后失效。
- 最终论文每个必答问题都要能找到直接答案和足够论证，但允许合并问题、集中共享模型、使用不同章节深度，不强制固定标题或顺序。`analysis/answer_map.json` 或 `paper/answer-map.json` 的 `primary_result_id` 必须与实验晋级/回退决定一致；未消费 insight 只形成编辑 warning。
- PDF 内源码默认不超过一页（`source_code_appendix.pdf_page_budget`），完整代码走 `mode: attachment`；确有赛事要求时显式声明 `competition_requires_full` 与依据。运行时会自动生成 `paper/generated/argument_map.json` 与 `paper/generated/argument_coverage.json`；v3.4 只能使用无回退 LaTeX 学术模板。
- 论文采用可往返链：Research Package → Narrative Competition → Visual Sandbox → Longform Author → Cold Reader → Editorial Compression。贡献最多三项，不能把常规方法组合包装为创新。
- 不把任何页数当作内容目标。先服从赛事上限，再按真实解释任务分配篇幅；页面审计只提示复核，不得反推扩写。正文优先完整讲清一个主模型、一个自然 baseline 和一条真正不同的 challenger；中央推导、必要伪代码和参考文献留在正文，完整代码与稳定性审计进附件。
- 正式编译分别维护 `argument_revision` 与 `render_revision`。正文论证变化才使独立盲评失效；字号、箭头、留白、分页等纯渲染变化只重做当前 render 的版式与机械 QA。科学事实变化仍重做科学挑战、论证和渲染。首稿或 candidate 都不是不可逆冻结；首稿后新增路线、实验、图或审核须记录 review finding、预计成本、预期收益和停止条件。只有用户显式 `final lock` 后才停止新增科学内容。工作流源码哈希只作信息提示，不拥有阶段否决权。

## External Author Handoff

`mathmodel-paper` 的职责从"帮我把整篇论文写出来"扩展为"准备好写作所需的科学材料、
把写作任务安全地交给 Author、再把稿件接回并做科学编辑"。顶层六阶段主链不变；
外部交接只是 `paper` 阶段内的 `authoring_status` checkpoint。

- `authoring_mode`：`internal`（默认，行为不变）或 `external_handoff`。
- `authoring_status`：`preparing_handoff → handoff_ready → waiting_external_author
  → draft_imported / rework_requested / author_pass_accepted / needs_rebase`。
  `waiting_external_author` 是正常暂停，**不是 blocked**；external 模式下
  `compile_paper` / `compile_longform_draft` 在未导入外部稿前被守卫拒绝。
- 交接包：`paper/writer-handoff/` 下默认只有 `RESEARCH_PACKAGE.md` 与
  `AUTHOR_BRIEF.md` 两个人读文件；`answer-and-claims.json` 与 `manifest.json` 供机器审计。
  科学事实、正式答案和主张边界继续阻断；素材、故事板、蓝图与视觉缺口只形成
  `editorial_signals`，由 Author 请求返工。
- 导入：`paper/external-author/draft.tex` 永不覆盖 `main.tex`。
  `import_audit.py` 做隔离编译与数字 / 强主张 / 图 / 引用绑定；`wrong_number`
  先为 `scientific_fact_candidate`，经 machine binding 确认后才成为
  `confirmed_scientific_fact_failure`（不可申诉）。未知图、未知引用、越界强主张
  直接客观失败并阻断。
- 作者请求：`AUTHOR_REQUESTS.json` 只允许
  `fulfill / substitute / waive / reject`，**请求不会自动变成实验任务**；
  `route=experiment` 必须声明科学价值。
- 审阅：Fresh Reviewer 只给 `severity_recommendation`；Editorial Adjudicator
  确认 `confirmed_severity` 并路由返修。机器确认的科学事实错误与 import audit
  客观失败不可被 Adjudicator 主观降级。
- CLI：`prepare_writer_handoff` / `import_external_draft` /
  `resolve_author_requests` / `adjudicate_review`。

## 工程约束

- Python 模块、类和公共函数使用 Google 风格 docstring；注释使用中文并解释 WHY。
- 写入运行目录使用原子写入或同目录安全替换；路径必须限制在运行目录内。
- Windows 可运行，不依赖 Bash；不自动提交或推送 Git。
- 不修改 `legacy/review-v2/` 的业务语义。旧协议函数可保留兼容，但不得成为 v3.2 主链硬门。
- 运行 `python -m pytest` 和 `python -m ruff check src scripts tools tests`。测试通过只证明工程行为，不证明竞赛竞争力；后者必须由 `evaluation/` 中的 held-out A/B、错误注入和匿名 pairwise 验证。
