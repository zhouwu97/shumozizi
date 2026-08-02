---
name: mathmodel-workflow
description: 以 Competition-First v3.4 完成整道数学建模赛题。当用户提供完整题面或附件，要求解答整题、多问建模、真实实验、图表、论文或竞赛交付时主动使用；局部分析、调试和单独改稿不启动完整工作流。
---

# Competition-First v3.4 工作流

## 触发与初始化

用户不需要说出 Skill 名称。收到完整数学建模题面或附件，或用户要求“解整题”“完成各问”“做实验并写论文”“形成竞赛交付”时，必须先使用本 Skill 总控，再按阶段调用主动 Skill。只有局部分析、单个实验、代码调试、单图制作或论文局部修改时，才不创建完整运行。

新任务先定位题面路径和必答问题，再执行：

```powershell
python scripts/codex/init_simple_run.py <problem_path> --run-id <run-id> --workflow-version 3.2 --question Q1
```

多问任务为每一问追加 `--question`。初始化成功后以命令返回的 `run_dir` 为唯一生产目录，立即执行 `python scripts/simple/delivery_control.py status <run_dir>`，然后进入 `analysis`。主链为 `analysis -> experiment -> paper -> paper_review -> verify -> complete`；不要创建 `capability_route`、`scientific_review`、`visualization` 或 `final_review` 阶段。

## 交付控制

知识库的优先级始终低于当前题面、当前数据、当前生产实验和独立验证。证据、方法和验证模式继续登记 `application_layer`、`target_ids`、当前题依据、适配动作、预期效果和可推翻条件；进入实验前验证目标存在，进入论文前只允许 `validated` 或 `revised` 状态。表达启发使用只读 Inspiration Library，可同时参考多张卡，但只能学习页面节奏、图出现时机、推导深度、章节节奏、摘要策略和发现感，不绑定 current result，也不得迁移事实、公式、数据、引用或结论。

实验完成后用 `python scripts/knowledge/record_usage_outcomes.py <run_dir> --input <outcomes.json>` 回填 `validated`、`revised`、`rejected_by_evidence` 或 `not_executed`。回填会复核 current production result ID；候选论文只读取自动生成的 `paper/generated/knowledge_context.json`，不得把整份论文卡或未兑现模式灌入写作上下文。

初始化 v3.2 运行后，先执行 `python scripts/simple/delivery_control.py status <run_dir>`，并在阶段切换或准备扩展协议前重查。运行时按阶段自动记录一个 phase session，不再要求每段命令手动 `start-work/stop-work`，也不追查 20 分钟墙钟空档。只有协议、执行器或 P0 交付修复需要精确核算开销时，才用细粒度工时命令登记，不能用实验耗时掩盖协议开销。

交付状态返回的唯一最高优先级动作覆盖普通探索：第一版 PDF 截止后，将四类披露写入 JSON（`completed_content`、`unfinished_questions`、`remaining_experiments`、`provisional_conclusions`），执行 `python scripts/paper/compile_reviewable_draft.py <run_dir> --disclosure <json>`；该命令直接生成、复验并冻结 `paper/draft-1.pdf`。它允许答案资格尚未全部完成，但必须使用当前真实内容，并在 PDF 中明确“本稿不可作为最终提交”。候选截止后仍用严格 `compile_paper.py` 生成 `paper/final.pdf`，再执行 `freeze-pdf candidate`；盲评截止后先创建或恢复盲评。

首版截止只改变交付优先级，不拥有路线否决权。首版或 candidate 后仍可按评审发现返回分析、实验或图表；新增项须同时记录 `review_finding`、`estimated_cost`、`expected_benefit` 和 `stop_condition`，单次最多 5 项。只有用户显式执行 `final lock` 后才停止新增科学内容。工作流源码哈希只提供信息提示，不再需要公开的 approve/verify source-lock 命令，也不得阻断当前赛题。

1. 分析先审计题面、数据结构和统计单位，形成任务指纹，执行 `python scripts/knowledge/retrieve_for_run.py <run_dir> --stage analysis --input <fingerprint.json>` 检索仓内论文卡。检索主要使用结构字段，不按题名找答案；最多保留 3 张结构相似卡、每卡 2 个安全模式，对这些候选逐项记录采用或拒绝。知识卡只提供路线启发，原题参数、公式和代码、数值结论及奖项评价不得迁移。
2. 先预扫描全部 `question_delta` 与 endpoint 状态。低风险运行只完成一次 `faithful_reconstruction`；任一问题要求重查聚合或 endpoint 为 `comparison_planned` 时，再增加 `semantic_adversary` 和最小反例。语义结论本身是硬门，fresh-thread 回执、thread ID 与题面树哈希只作独立性记录。随后用 `MODELING_UNITS` 1.4 选择 `evaluation`、`optimization`、`exact_oracle`、`data_modeling`、`simulation` 或 `coordination`，并冻结直接答案合同。核心高风险优化问题再用 3--5 个人工案例实测 scorer。固定评价、数据建模和仿真不强迫路线赛马；exact oracle 必须同时核对指标容差与区间/集合结构。
3. 只有未决且会改变主结果的题意歧义才创建目标语义审查；歧义未决时不得用 `determined` 跳过候选比较。`optimization`、`simulation`、`exact_oracle` 和 `coordination` 单元必须调用 `mathmodel-matlab` 完成一次结构触发的能力判断。默认先运行 `scripts/capabilities/detect_tools.py`，在 `capability_decision` 中绑定真实 tooling 哈希、可用性、所选引擎、MATLAB 科学角色、理由和预期增益，不接受 `not_probed`；只有解析解、小规模精确枚举、外部引擎被环境禁止或不能形成异构科学增益时允许明确 waiver。
4. 实验只登记原始结果指标。核心优化/协同默认使用自然 baseline 加一条结构 challenger，第二条只在首轮不确定、仍在改善或评审明确指出缺口时增加。首个可行解后先用 `show_first_feasible_prompt.py` 交给独立 AI，复核最高风险、可推翻假设、更强结构路线和下一项最低成本区分实验；结果写回现有 refinement，不新增阶段。返回 analysis 时先修订并重新取得首解；继续 experiment 时执行所提实验，并绑定首解之后产生的 follow-up 结果与结论，再完成至少一类深化。搜索占实际算力约 35% 只是 advisory。硬阻断只用于没有真实搜索、checkpoint 缺少实质结论/后续实验、checkpoint 要求返回 analysis、单随机种子且明显不稳定、challenger 仍快速改善或停止理由与日志冲突。系统输出 `objective_answer`、`recommended_plan`、`evidence_grade` 三层结果：endpoint、exact 指标、硬约束和可行性决定题面答案；名义答案稳定时推荐层继续指向题面赢家，只有不稳定或题面答案不可用时才可按已验证条件推荐 fallback。旧 1.2/1.3 `oracle_only` 只能以 `legacy_unverified` 查看，迁移 1.4 并完成 agreement 后才能进入正式答案。
5. 结束实验后进行一次自由科学挑战；必要时只允许一个专项追问。阶段 A 先判断核心风险在目标语义/分解还是模型/搜索；多主体、嵌套量词、聚合词、问题实体变化或分解后组合存在时，第一攻击必须针对语义并给出独立玩具反例。只有语义风险低时才优先攻击搜索和数值。其余发现分类、回退和更强路线闭合规则不变。
6. 先用 `visual-ideas.json` 和 `figures/sandbox/<idea-id>/` 低成本试图；草图不要求结果绑定、caption、label、manifest、panel mapping 或 Figure Contract。关键 insight 可生成 2--4 个候选，由 fresh reviewer 选择最能说明机制且最不重复表格的方案，再用 `visual_sandbox.py graduate` 送入 `figures/work/`。只有晋级候选才进入现有 QA、来源绑定和 `figures/current/`；旧 `FIGURE_PLAN` 2.4 只作后台兼容与最终审计，不能成为草图或首稿前置门。稳定性图入附录。
7. 进入论文后运行 `python scripts/paper/prepare_longform_author.py <run_dir>`，让 Author 默认只读取 `RESEARCH_PACKAGE.md` 与 `AUTHOR_BRIEF.md`；后台蓝图、素材池、故事板、图计划、回执和哈希不进入默认作者上下文。先生成 2--3 个 Narrative Candidates，让 fresh reviewer 选择最容易让评委记住的主线；选择只影响表达，不改变模型、数字或证据等级。Author 自由合并问题、重排章节、展开推导和改变图文节奏，并把缺推导、机制、反事实、视觉或科学证据写入 `AUTHOR_GAPS.md`；Author 不得篡改科学事实，但可请求返回 visual、experiment 或 analysis。只有独立生成 `paper/longform-source.tex` 或 `.typ` 后，才运行 `compile_longform_draft.py`；正式入口的重新编译不算 Author Pass。`reviewable_draft` 仍是有披露的时间 fallback。
   候选稿前运行 `python scripts/paper/audit_report_style.py <run_dir>`。只有 E001 正文泄漏控制层术语是确定性硬错误；E002--E005、标题、列表密度、章节碎片、篇幅和图数只作为编辑信号交给冷读。直接答案必须容易定位，但不要强制每问首段或固定小节。页数统一由 `page_budget.py` 给出 advisory：少于 18 页强编辑复核，18--23 页压缩复核，24--30 页正常规划，超过 30 页压缩复核；内容缺口由 cold reader 决定是否阻断。

长篇首稿冷读后，使用 `review/PAPER_COLD_READER_EDITORIAL.json` 记录少量高价值动作。普通动作保持 advisory；只有明确 `blocking=true` 的 P0/P1 且未关闭时阻断候选稿。`ADD_COMPANION_FIGURE` 可回到 Visual Sandbox。返修分别维护 `argument_revision` 与 `render_revision`：`science` 重做科学挑战、论证和渲染，`argument` 使盲评失效，`render` 只使版式和机械 QA 失效。
8. PDF 盲评必须使用独立上下文，只接收冻结 PDF 和固定提示词。最终盲评内置一条人工干预：按数学建模国赛标准，对照优秀论文表现审查图表缺口、报告/论文形态、笔法文风、排版、论证链和十几页篇幅原因，并给出带优先级、修复层级和验收标准的修改清单；不得联网或读取题面、源码、运行记录。该干预记录在盲评回执中，不新增阶段，也不创建作者填写的平行表单。导入记录绑定当前 `argument_revision`；纯渲染重编不要求重做盲评。`CUMCM_LAYOUT_AUDIT` 仍绑定当前 `render_revision` 并直接消费盲评事实。

旧 v3.0 运行可查看和更新，运行时会在首次显式更新时记录阶段迁移。不要把 legacy 审核合同重新接入新运行。
