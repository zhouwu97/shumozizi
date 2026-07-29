# Competition-First v3.2 工作流

## 阶段与恢复

```text
analysis -> experiment -> paper -> paper_review -> verify -> complete
```

进入 `experiment` 前，v3.2 要有包含题面语义结论的 `analysis/MODELING_UNITS.json`：低风险题只需一次 `faithful_reconstruction`；任一问题要求重查聚合或 endpoint 尚待比较时，再增加 `semantic_adversary` 和最小反例。fresh-thread 回执、thread ID 和题面树哈希只记录独立性，不作为科学否决权。专家库和网页讨论可在其前后用于提出或攻击假设，但不得替代语义结论；发现冲突后回到分析、修订、重跑即可。仅当 `analysis/objective-ambiguities.json` 表明存在未解决的高影响歧义时，才要求目标语义审查。进入 `paper` 前必须有每个必答问题的 current production 答案、已回填的攻击/深化/条件验证证据、没有已知负面证据、无回退 LaTeX 模板和一次有效科学挑战。进入 `verify` 前必须有 PDF、有效 PDF 盲评或明确跳过原因、没有 P0/P1；跳过盲评只能继续机械 QA，状态为 `unreviewed`。进入 `complete` 前必须重新验证科学挑战、通过真实 PDF 盲评和机械 QA，且当前结果、图表、Excel 提交产物和 PDF 都没有漂移。

旧 v3.0 状态按内存映射读取，更新时生成 `state/migrations.json`，不改写历史审核产物。

## 分析

v3.2 前期先预扫描语义风险，再按风险完成一次 faithful 或 faithful + adversary 重建并写 `MODELING_UNITS` 1.4。逐问选择 `evaluation`、`optimization`、`exact_oracle`、`data_modeling`、`simulation` 或 `coordination`；固定评价类问题使用主方法与自然核对，exact oracle 同时核对数值容差和区间结构，核心优化/协同默认 baseline + 一条结构 challenger。优化、仿真、exact oracle 和协同单元必须写 `capability_decision`，显式比较 MATLAB/Octave 与 Python；可以拒绝 MATLAB，但不能静默忽略。正式结果分为题面 `objective_answer`、条件化 `recommended_plan` 和 `evidence_grade`：名义答案稳定时推荐层仍指向题面赢家，只有不稳定或题面答案不可用时才考虑已验证 fallback。旧 `oracle_only` 必须迁移到 1.4 并完成 agreement 才能进入正式候选稿；Excel 提交产物通过 `submission_export` 绑定 objective result 和核心单元格。

专家库运行时只读取 `knowledge/award-experts/library.json`：21 张跨题结构卡与 15 个规则组合角色，覆盖 2012--2025 年官方展示的 A/B 论文。来源 URL、页码、论文 ID 和哈希只留在离线 `provenance.json`。路由按 A/B、当前阶段和受限 `topic_key` 选择少量结构建议；同题资料只能在 baseline 快照后进入 answer-filter，不能改变当前题模型、参数、结果或论文结构。网页版 GPT 也只能对用户提供的题面进行讨论或批评，禁止联网检索题目答案、题解、往届答案或相近题的现成结论，且不得复用这类内容。专家库和网页建议必须由当前 baseline、exact scorer、真实实验、独立复算或 fresh-thread 审核独立确认。审计的 `access_monitoring.enabled=false` 仅说明序列化输出检查的边界，不宣称操作系统级文件访问监控。

再写 `analysis/NEXT_EXPERIMENTS.md`。每个实验必须说明要改变的决定、成本、成功/失败后的动作和优先级。不能改变路线、模型、主要结论、机制、贡献或反证当前结果的实验不应占用比赛预算。

## 实验与洞察

所有生产实验通过执行器登记。`method_facts.json` 以显式登记为最高优先级，并联合结果指标、执行命令和源码静态提示推断随机、proxy、时间切分、连续/离散近似、启发式和下游依赖等事实；未知值会成为查漏项，不能静默跳过中央风险。

在写论文前维护 `analysis/INSIGHTS.md`。每项洞察写观察、真实证据、可能机制、验证、论文价值和不能推出的边界。没有稳定规律时明确写出，不得为了文件制造阈值、因果或反直觉结论。

## 图表与论文

图表在 `figures/work/` 版本化迭代，经 QA 晋级 `figures/current/`，旧 current 进入 `figures/archive/`。首稿前每个必答问题都必须在 `FIGURE_PLAN` 2.3 中把展示图明确为 required 或 waived；几何、集合、名义—稳健和共享模型还须完成 whole-paper 决策。

论文只维护 `PAPER_BLUEPRINT.md`、`answer-map.json`、`FIGURE_PLAN.json` 和 `PAPER_REVIEW.md` 四个主要控制文件。知识应用为 advisory，零匹配时自动提供通用结构模式。CUMCM 候选稿使用 `CUMCM_STRUCTURE_MAP` 1.2：三问以上、共享数学对象且后问新增资源、共享约束或聚合层时默认 semantic，并保留明确“模型假设与符号”入口；否则 classic 兜底。

## 审查与重跑

科学挑战只进行一次，采用两阶段阅读：阶段A只读题面，独立重建数学结构和关键歧义，先写入报告；阶段B读代码和结果，与阶段A对照，选择一个最高价值结论实施真实攻击并说明结论。风险数量不设要求，一个根本性缺陷可以集中全部篇幅。只有 P0/P1、需要确认的决定性实验或无法判断是否继续时才建立一个 `FOCUSED_FOLLOWUP.md`。PDF 盲评采用相对评价（第一印象与竞争力 → 写作风格诊断 → 可读性 → P0/P1 → 最高价值修改），不能只写 pass/fail。

最终 PDF 盲评绑定 `argument_revision`；字号、分页、箭头和留白等纯 render 修改只递增 `render_revision`，重做版式与机械 QA，不重做盲评。正文论证或科学事实变化才使盲评失效。

**网页版 GPT 补充审核为可选环节**，只在论文主模型和结果已稳定、需要专项写作质量改进时使用，不是每次 PDF 编译后的默认流程。使用时用 `scripts/review/web_paper_audit.py prompt` 生成提示，另开网页对话并只上传 PDF。网页审核聚焦写作风格（固定句式 / 分点堆砌 / 空话总结 / 讨论缺位）和可读性，给出最高价值修改建议（≤ 5 条）；发现需要重写章节、替换主图或回到实验的问题时直接说明，不要降级为加几行文字的修补。最多使用一轮。两种审核都只能发现风险，不能证明竞赛名次或保证省一；机械 QA 只检查交付，不重定义数学正确性。

正文小改不回到实验或科学挑战，但正式重编后仍须让 PDF 盲评、CUMCM 版式审计和机械 QA 绑定新修订。代码、数据、目标或主要结果改动：回到实验、科学挑战，再重做论文审查与机械 QA。
