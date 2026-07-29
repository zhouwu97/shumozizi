# Competition-First v3.2 工作流

## 阶段与恢复

```text
analysis -> experiment -> paper -> paper_review -> verify -> complete
```

进入 `experiment` 前，v3.2 要有包含两次仅题面的真实 fresh-thread 重建的 `analysis/MODELING_UNITS.json`；这是最终分析计划的独立性证据，而不是“流程合规即模型正确”的证明。专家库和网页讨论可在其前后用于提出或攻击假设，但不得替代它；发现冲突后回到分析、修订、重跑即可。仅当 `analysis/objective-ambiguities.json` 表明存在未解决的高影响歧义时，才要求目标语义审查。进入 `paper` 前必须有每个必答问题的 current production 答案、已回填的攻击/深化/条件验证证据、没有已知负面证据、无回退 LaTeX 模板和一次有效科学挑战。进入 `verify` 前必须有 PDF、有效 PDF 盲评或明确跳过原因、没有 P0/P1；跳过盲评只能继续机械 QA，状态为 `unreviewed`。进入 `complete` 前必须重新验证科学挑战、通过真实 PDF 盲评和机械 QA，且当前结果、图表和 PDF 都没有漂移。

旧 v3.0 状态按内存映射读取，更新时生成 `state/migrations.json`，不改写历史审核产物。

## 分析

v3.2 前期可按问题需要用只绑定 `problem/` 的 fresh thread、CUMCM A/B 获奖论文的 3--6 张 structure-only 卡和网页版 GPT 讨论题意、建模、反例、验证与论文建议。它们只用于提出假设和攻击点，不能替代本地验证，也不参与状态跳转。需要并行网页讨论时，先冻结 `analysis/LOCAL_ROUTE_SNAPSHOT.json`：它只绑定 `problem/`、明确尚未阅读外部材料；首轮网页提示不披露本地路线，且本地路线写完前不得阅读回应。随后用 `EXTERNAL_DISCUSSION_COMPARISON.json` 将每项同意、冲突或新增假设绑定到本地验证动作；最后仅可使用 `EXTERNAL_DISCUSSION_SYNTHESIS.json` 另开 fresh chat 做实现总结。新对话只提出可验证的实验与搜索方向，实际最优或最强下界只能由本地 exact scorer 和真实执行确定。可在讨论前后写入 `analysis/BASELINE_FREEZE.json`：它是绑定当前 `problem/` 哈希、带建议来源记录和修订号的决策快照，不是禁止纠错的终局文件。发现反例、目标歧义、实验冲突或审查缺口后，应修订快照，重跑受影响实验、重新路由和复审。未冻结的路由写为 `advisory_only=true`；冻结或修订后旧路由因 SHA 漂移失效，必须重新生成。随后按决策价值写 `analysis/MODELING_UNITS.json`。每个 `compare` 单元冻结 baseline、两条数学结构不同的候选路线、统一 exact 目标和实际预算、fallback、首批攻击、至少两类首解后深化、停止理由白名单及条件验证；`oracle_only` 只用于明确需要独立 oracle 的题型。`ROUTE_COMPETITION.md` 仍用于人类可读的路线叙事。

专家库运行时只读取 `knowledge/award-experts/library.json`：21 张跨题结构卡与 15 个规则组合角色，覆盖 2012--2025 年官方展示的 A/B 论文。来源 URL、页码、论文 ID 和哈希只留在离线 `provenance.json`。路由按 A/B、当前阶段和受限 `topic_key` 选择少量结构建议；同题资料只能在 baseline 快照后进入 answer-filter，不能改变当前题模型、参数、结果或论文结构。网页版 GPT 也只能对用户提供的题面进行讨论或批评，禁止联网检索题目答案、题解、往届答案或相近题的现成结论，且不得复用这类内容。专家库和网页建议必须由当前 baseline、exact scorer、真实实验、独立复算或 fresh-thread 审核独立确认。审计的 `access_monitoring.enabled=false` 仅说明序列化输出检查的边界，不宣称操作系统级文件访问监控。

再写 `analysis/NEXT_EXPERIMENTS.md`。每个实验必须说明要改变的决定、成本、成功/失败后的动作和优先级。不能改变路线、模型、主要结论、机制、贡献或反证当前结果的实验不应占用比赛预算。

## 实验与洞察

所有生产实验通过执行器登记。`method_facts.json` 以显式登记为最高优先级，并联合结果指标、执行命令和源码静态提示推断随机、proxy、时间切分、连续/离散近似、启发式和下游依赖等事实；未知值会成为查漏项，不能静默跳过中央风险。

在写论文前维护 `analysis/INSIGHTS.md`。每项洞察写观察、真实证据、可能机制、验证、论文价值和不能推出的边界。没有稳定规律时明确写出，不得为了文件制造阈值、因果或反直觉结论。

## 图表与论文

图表默认写入 `figures/current/`，每张图登记 `source`、`question`、`takeaway` 和可选 `limitations`。新运行使用 `FIGURE_PLAN` 2.3：`evidence_need` 判断科学证据是否缺图不可，`presentation_need` 判断评委是否需要视觉入口；后者初期只告警。数据结构决定统计单位、删失、聚合或模型选择时，可规划 `scope=whole_paper` 的 `data_portrait`；它通过 `register_presentation_figure.py` 绑定冻结输入、脚本、current 输出与人工晋级回执，不伪造实验结果。删除图后论文不会失去信息时，删除该图。不得默认要求每问图、3D、收敛图、多种子图、敏感性图或重复 evidence/publication 图。

先用 `paper/STORYBOARD.md` 形成结构蓝图；再统一共享符号、假设和数学对象，并逐问成文；最后把结论逐项与 `answer_map`、结果、图表和限制对齐后严格返修。分析检索最多保留 3 张结构相似卡、每卡 2 个安全模式；写 `ARGUMENT_PLAN.md` 前生成 `paper/KNOWLEDGE_APPLICATION.md`，默认只重新判断分析已采用项，分析拒绝自动继承，只有显式 reopen 才重开。实际采用最多来自 1--2 张卡，并绑定当前题证据、实际正文源码和兑现锚点。知识卡永远不提供当前数字、结论或 citation。CUMCM 候选稿使用 `CUMCM_STRUCTURE_MAP` 1.1：`classic` 是固定栏目兜底，`semantic` 暂为实验画像且不设默认；两者都填写 advisory `presentation_contract`。

## 审查与重跑

科学挑战只进行一次，采用两阶段阅读：阶段A只读题面，独立重建数学结构和关键歧义，先写入报告；阶段B读代码和结果，与阶段A对照，选择一个最高价值结论实施真实攻击并说明结论。风险数量不设要求，一个根本性缺陷可以集中全部篇幅。只有 P0/P1、需要确认的决定性实验或无法判断是否继续时才建立一个 `FOCUSED_FOLLOWUP.md`。PDF 盲评采用相对评价（第一印象与竞争力 → 写作风格诊断 → 可读性 → P0/P1 → 最高价值修改），不能只写 pass/fail。

最终 PDF 盲评先构建 `paper-blind` 冻结包，再运行 `scripts/review/show_paper_blind_prompt.py <run-dir> --manifest <manifest> --json`，把提示词原样交给独立上下文。新上下文只读取冻结 PDF，并在同一 Markdown 报告末尾输出固定结构化 JSON。导入后，现有 `review/paper-blind-review.json` 同时绑定自由报告、结构化冷读、逐问缺失角色/页码/finding、任务与对话 ID、提示词和渲染修订。`CUMCM_LAYOUT_AUDIT` 1.3 直接消费该记录，不接受另一套作者冷读或全 true 布尔值；本地只追加呈现计划、页面节奏和 advisory 学习兑现。正式编译、盲评、版面审计修订不一致时当前稿自动显示未审。

**网页版 GPT 补充审核为可选环节**，只在论文主模型和结果已稳定、需要专项写作质量改进时使用，不是每次 PDF 编译后的默认流程。使用时用 `scripts/review/web_paper_audit.py prompt` 生成提示，另开网页对话并只上传 PDF。网页审核聚焦写作风格（固定句式 / 分点堆砌 / 空话总结 / 讨论缺位）和可读性，给出最高价值修改建议（≤ 5 条）；发现需要重写章节、替换主图或回到实验的问题时直接说明，不要降级为加几行文字的修补。最多使用一轮。两种审核都只能发现风险，不能证明竞赛名次或保证省一；机械 QA 只检查交付，不重定义数学正确性。

正文小改不回到实验或科学挑战，但正式重编后仍须让 PDF 盲评、CUMCM 版式审计和机械 QA 绑定新修订。代码、数据、目标或主要结果改动：回到实验、科学挑战，再重做论文审查与机械 QA。
