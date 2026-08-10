---
name: mathmodel-paper
description: 从 Competition-First v3.4 的当前真实结果组织、编译和修订数学建模论文。
---

# 论证驱动论文

论文不是结果汇总报告，也不是把复杂四问压到约 13 页的摘要。正文应由共享模型和少量关键数学判断贯穿，同时保留清楚的逐问章节、直接答案和问题间继承关系；不能只按 Q1/Q2/Q3/Q4 罗列方法名、参数和结果表。v3.4 先形成完整的长篇科学首稿，再由独立冷读和编辑判断删减；篇幅和图数是复核信号，不是科学充分性的替代物。

## v3.4 首稿默认链

先运行 `python scripts/paper/prepare_longform_author.py <run_dir>`，把题面必答合同、current 正式自然语言答案、共享数学对象与必要假设、关键推导、机制、当前图、主张边界和文献压缩投影成 `paper/author-pass/RESEARCH_PACKAGE.md`。该入口只检查正式 objective answer、current production 绑定和 scientific P0/P1 已关闭，不检查素材池、故事板、蓝图或 Figure Plan 完整度。随后完成 Narrative Competition；选中的中心主线、阅读顺序、记忆点、风险和修订建议写回现有 `AUTHOR_BRIEF.md` 并刷新 manifest。Author 默认只读取最终这两份文件，后台素材池、故事板、蓝图、图计划、回执和哈希继续保留兼容与审计价值，但不得成为创作前置清单。

Author Pass 的前五页合同是答案优先而非研究过程优先：第 1 页摘要直接给出逐问方法、关键数值、条件边界和模型判定；第 2 页给出逐问直接答案表与共享对象路线图；第 3 页解释原始数据与分析窗口；第 4–5 页提前放置至少一张绑定 current 数据的 Hero 图及其机制解释。`claim_boundary=conditional_on_assumption/sensitivity_only` 必须原样表达为条件结果或范围，不能在摘要或结论中升级为无条件唯一答案。

从同一 Research Package 生成 2--3 个 Narrative Candidates，例如问题递进型、数学结构型或机制型；使用 fresh reviewer 选择最能让评委记住论文的一种，并说明风险与修订建议。不要让 `layout_optimizer.py` 的固定 block 顺序支配正文；旧布局输出只作 advisory 兼容。

让 Author 独立撰写 `paper/longform-source.tex` 或 `paper/longform-source.typ`，并把无法支撑的推导、机制、反事实、视觉或研究证据写入 `paper/AUTHOR_GAPS.md`。随后运行 `python scripts/paper/compile_longform_draft.py <run_dir>` 生成 `paper/longform-draft.pdf`；该命令只编译 Author 源文件，拒绝把正式入口原样重编冒充 Author Pass。编译前会刷新 `paper/generated/VISUAL_REQUIREMENTS.json`，把未被 current 图覆盖的数学对象、决定性证据、机制和边界需求自动追加到 living visual opportunity pool；不得因已有 2--3 张主图而跳过这些 supporting requirements。`compile_reviewable_draft.py` 仍保留为时间截止或内容未齐时的披露式 fallback。

独立 PDF 冷读只记录少量最高价值动作。普通扩写、压缩、重排、补机制或加图动作保持 advisory；只有 Reviewer 明确标记 `blocking=true` 的 P0/P1 且未关闭时阻断 `compile_paper.py`。`ADD_FIGURE` 与 `ADD_COMPANION_FIGURE` 都必须携带结构化 figure 描述并自动进入 living visual opportunity pool，不能停在冷读清单。冷读器不能直接修改正式结果；Author 也不能擅自修改科学层，但可请求 `writing_fix`、`visual_exploration`、`experiment` 或 `analysis` 返工。

## 第零步：确认可以写论文

逐问读取 `MODELING_UNITS.json` 1.4 的三层结果。`objective_answer` 是题面原目标下的正式答案，`recommended_plan` 是附加风险偏好或稳健条件下的建议，`evidence_grade` 说明证书、搜索与稳定性边界；后两者不得替换前者。`answer_map.primary_result_id` 必须等于 `objective_answer.result_id`。任一必答问题没有有效 objective answer 时，不得编译正式候选版，但可以形成带披露的可审阅草稿。

科学挑战中的发现必须绑定 `action_type`、`rollback_target`、`invalidates`、`required_action` 和关闭证据。未关闭的 `MODEL_REPAIR`、`OBJECTIVE_REDESIGN`、`ANSWER_REJECTION` 阻断论文；只有 `WRITING_FIX` 和已说明不可修复原因的 `DATA_LIMITATION` 可留在 paper 阶段。正式论文检查自然论证内容，不要求出现 `result_id`、实验收据、证明义务或“问题继承”等内部工作流术语。

进入写作后先查看 `delivery_control.py status`。第一版截止前，把当前已完成内容、未完成问题、剩余实验和有真实证据的候选结论写成披露 JSON，执行：

```text
python scripts/paper/compile_reviewable_draft.py <run_dir> --disclosure <json>
```

该专用入口生成 `paper/draft-1.pdf` 和独立草稿回执，允许正式答案资格或科学挑战尚未全部完成，但不允许虚构数字，且 PDF 必须明确“本稿不可作为最终提交”。没有证据支持的候选结论保持空数组，由状态页显示“暂无”。不要用正式 `compile_paper` 冒充首版草稿。

该入口不是“能编译即可”的排版检查，但不要求 Author 在动笔前填满蓝图字段或 `FIGURE_PLAN`。科学事实、正式答案绑定和不可伪造的证据仍是硬门；论证深度、视觉节奏与逐问覆盖在长篇 PDF 冷读和最终审计中检查。

候选截止前先闭合所有正式答案资格与科学挑战，再执行严格 `compile_paper.py` 生成当前 `paper/final.pdf`，并保存 candidate 版本进入 `paper_review`。candidate 是可返修版本，不是科学内容的不可逆冻结；只有用户显式 final lock 才停止新增科学内容。

---

## 写作交接：先过滤控制层

论文阶段先读取经过筛选的研究素材：题面事实、当前模型与推导、逐问直接答案、正式结果、结构观察、机制、反例、当前正文主图、必要文献，以及会改变结论的竞争解释和边界。默认不要把完整运行目录直接灌入写作上下文；日志、manifest、哈希、回执、工具探测、阶段状态、完整搜索轨迹和普通 QA 只留在控制层。只有为解决数字冲突、复现问题或真实方法依赖时，才临时读取并翻译成自然学术语言。

内部字段负责保证事实可追溯，不能成为正文句式。正文不得直接出现 `result_id`、晋级状态、回执、scorer 或“流程已通过”等工作流表达；软件版本、初值数量、普通复算和环境信息只有在会改变结论时才进入正文，否则进入附录。

## 控制面到纸面的措辞转换

结构地图、叙事竞争、蓝图与验证台账中的 `reason`、`risks`、`evidence`、`support`、`boundary` 等字段属于
control-plane material。Author 可以吸收其中表达的科学事实和写作目的，但不得继承其元评审措辞。

禁止直接进入正文的规划层表达包括但不限于：

- 证据桥
- 可信边界
- 结构证据
- 支持边界
- 关键验证证据
- 把“独立复核”当作审校过程描述

正文需要论证支持时，改写为具体的：对象 + 数学事实/数值 + 所说明的模型性质。转换示例：

```text
错误：“图5给出了双源不可分解性的关键证据桥。”
正确：“以共享巷道 H0898 为例，两个水源在该巷道内发生汇合，
说明双源传播不能由两个单源结果直接叠加得到。”
```

```text
错误：“临界反例提供了结构证据。”
正确：“该反例中两个单源水深均未超过阈值，而联合水深超过阈值，
因此逐源判定不能保证联合状态安全。”
```

```text
错误：“表10给出了四类关键验证证据及支持边界。”
正确：“从质量守恒、事件时序、路径到达和连续水深四个方面检验模型。”
```

## 证据蒸馏与两遍写作

把 `PAPER_BLUEPRINT.md` 视为后台结构快照，不作为 Author 模板。可从中蒸馏结论、数学原因、决定性证据、竞争解释和适用边界，但不得把这些角色逐项变成固定小节。

先根据选中的 Narrative Candidate 写完整连续论证，自由决定从现象、数学对象、问题递进或机制切入。成稿后再映射回后台完整性字段，检查题面要求、继承、推导、结果、机制、验证、边界和直接答案是否遗漏；Reviewer rubric 不得直接转写成正文结构。

证据按功能去重，而不是按结论机械限为一项：下界、构造、活跃约束、扰动、独立复算、基线对照和边界检验可以并存，只要它们改变不同的信任判断。同功能重复只给出压缩或移入附录建议；稳定性流水账、普通复算、完整环境和搜索记录进入附录。

---

## 第一步：填写 PAPER_BLUEPRINT.md

知识卡不提供当前题证据。候选稿会生成 `paper/generated/knowledge_usage.json` 和过滤后的 `paper/generated/knowledge_context.json`：只有 `validated` 或 `revised` 且绑定当前 production 结果的采用模式可进入论文上下文，`planned`、`not_executed` 和 `rejected_by_evidence` 不能写成方法优势。路线知识绑定建模单元；验证知识绑定验证类型、指标和事前通过准则；视觉知识绑定当前图及结构化数据；论文结构知识同时绑定蓝图锚点、实际源码和正文兑现锚点。知识使用的失败层级应回到 analysis/experiment 或 paper 修复，不能用局限性说明掩盖未兑现。

在动笔前，可执行 `python scripts/knowledge/retrieve_for_run.py <run_dir> --stage paper` 获得结构建议；需要外部文献时按需调用 `$mathmodel-literature` 生成双语检索计划和候选来源审计。零匹配时使用内置通用结构模式；知识应用与兑现只作 advisory。按 `paper/CITATION_PLAN.md` 分配 `background`、`core_method`、`validation`、`uncertainty` 和 `extension` 来源，可以检索实际采用方法的原始文献，但禁止同题答案、题解和现成结论。约 6–12 条只作紧凑性建议，不是数量门禁；每条参考文献必须至少绑定正文一个具体方法、指标、背景判断或验证动作，不能只列在文后。离线优秀论文卡只提供结构启发，明确禁止作为 citation 或当前事实来源。

候选稿检查会自动生成 `paper/generated/citation_coverage.json`，逐项核对正文 citation key、BibTeX/`bibitem` 定义、引用计划和结构化建模合同。未定义 key、计划已声明但正文未引用，以及新五列表格中已识别外部核心方法/验证方法却没有对应已兑现类别，属于高置信度合同错误；未使用条目、引用只集中在引言、来源过少或单一来源跨多个类别属于 warning。普通编号 `[1]` 不视为引用，来源权威性与相关性仍由作者和冷读人工核验，不能用 DOI 或数量自动代替。

Author 面向的概念只保留 `RESEARCH_PACKAGE.md`、`AUTHOR_BRIEF.md` 和冷读后的 `EDITORIAL_REVIEW.md`/等价编辑反馈。`paper/answer-map.json`、`PAPER_BLUEPRINT.md`、素材池、故事板、`FIGURE_PLAN`、claim gate 和各种 generated JSON 留在后台，由工具维护、投影和最终审计。

每个必答问题先填写逐问完整性卡：题面要求、与前问的继承、数学对象、关键推导、算法、主结果、机制解释、验证边界和直接答案。核心问题（`core_question=true`）在此基础上再填写完整论证单元；普通问题可以更短，但不能退化为只有 answer map 位置和一张结果表。

---

## 第二步：在同一蓝图中规划主线

在 `paper/PAPER_BLUEPRINT.md` 中继续填写：

- **中心判断**：本文最终要主张什么？
- **论证链**：从哪些题面事实出发 → 导出什么数学关系 → 哪一步需要数值求解 → 什么证据支持结论 → 哪种替代解释被排除 → 结论在哪些边界内成立
- **各问递进**：每一问怎样为下一问提供模型、算法或规律
- **核心矛盾**：效率、均衡、安全、资源之间的主要冲突是什么
- **主要讨论**：最终结果为什么呈现当前结构
- **论文主图**：每张图支持哪一步论证（不是哪一问的图）
- **篇幅分配**：核心问题允许显著更多篇幅
- **完整性预算**：按真实论证任务分配篇幅；赛事上限优先，页数不作为质量证明，也不设推荐最低页数
- **摘要**：最后写，见下方规范

---

## 第三步：自由组织正文

确保评委能在合理时间内找到每问直接答案，同时允许 Author 自由决定答案出现于段首、节末、答案总览或共享模型后的问题链中。可以合并相邻问题、让不同问题使用不同深度，或把共享推导集中一次；不要为普通问和核心问预生成相同小节序列。

成稿必须在自然论证中实际覆盖必要的数学对象、关键推导、算法、结果解释、机制、验证和边界，但这些角色是审计对象，不是标题清单。若某问只能写成“采用某算法，结果见表”，在 `AUTHOR_GAPS.md` 判断缺少的是推导、机制、案例、图还是研究证据。CUMCM 中文正文默认宋体小四（12pt），公式变量使用 Times New Roman 系斜体；编译后在 PDF 中抽查字体、图注和分页。

## 展开深度与篇幅

- 先服从竞赛明确的页数上限；没有紧上限时按解释任务分配篇幅，不预设约 13 页。
- 对多问、共享模型复杂、需要分组验证或多条机制解释的论文，按真实内容分配篇幅，不用预设页数区间反推扩写。
- 优先完整讲清一个主模型、一个自然 baseline 和一条数学结构真正不同的 challenger。路线名称大表不能替代模型流、核心推导和算法步骤。
- 中央公式、关键推导、必要伪代码和正式参考文献留在正文；完整源码、稳定性审计和次要表格进入附件。
- 若使用分组验证、删失处理、不平衡样本、聚合指标或代理变量，正文先做足够的数据分析，说明为何这样处理以及它如何影响主 endpoint。
- 验证应紧跟它所支持的主结果；不要先用大量稳定性图淹没主模型和答案。

---

## 证据类型声明

写作时必须明确区分四种证据类型，不得混用：

| 类型 | 含义 |
|------|------|
| **解析证明** | 从假设和公式严格推出，无需数值 |
| **计算证书** | 有限枚举、上下界或最优性证书 |
| **数值证据** | 多次实验或独立复算 |
| **建模假设** | 题面未唯一规定，由本文定义 |

**禁止**把数值证据写成"由以上分析可知"式的伪推导。"计算表明"只能用于数值证据。

---

## 讨论节

每道核心问题必须有实质讨论，不强制单独命名为"讨论"，但至少回答：

- 为什么最优解呈现当前形态
- 哪些约束真正活跃（移除后结果怎么变）
- 资源增加后为什么收益递减（如果有）
- 不同目标权重怎样改变策略
- 哪个动作或场景是真正瓶颈
- 哪些结论可推广，哪些只适用于当前参数

---

## 摘要

最后写。结构：

```
背景与核心困难（一句话，什么使这道题非显然）
→ 关键建模定义或结构（本文怎么把问题变成可解形式）
→ 主方法（用什么算法/框架，一句话）
→ 最重要的 2-3 个结果（数字，不是问题编号）
→ 结果规律与决策含义（发现了什么，意味着什么）
→ 可信边界（哪些假设如果改变则结论变化）
```

**不要**按 Q1/Q2/Q3/Q4/Q5 逐句罗列。除非五个问题的方法完全不同，否则不要在摘要里提问题编号。

---

## 反工作报告审计

候选稿编译前运行：

```text
python scripts/paper/audit_report_style.py <run_dir>
```

该命令输出可机读的 `errors` 与 `warnings`。只有 E001 正式正文泄漏工作流内部术语是确定性硬错误。E002--E005 分别提示报账模板重复、摘要逐问流水账、核心问题过度列表化和图后论证薄弱；它们必须由冷读结合上下文裁决，不能直接阻断编译或诱导 Author 按检查项补句。

标题碎片化、列表密度、重复问题模板，以及仅缺推导或仅缺机制等依赖上下文的信号继续保留为 `warnings`，由 `PAPER_REVIEW.md` 记录 `accepted`、`repaired`、`false_positive` 或 `deferred_with_reason`，并交给独立 PDF 盲评结合页码裁决。自动信号不能判断数学正确性，也不能替代独立阅读。

---

## 图与论证绑定

每张正文图必须在 `PAPER_BLUEPRINT.md` 中对应一步论证，而不仅仅是 `role=insight` 标签。

| 图应回答 | 不是 |
|---------|------|
| 这张图支持哪个命题 | 这张图属于哪一问 |
| 读者看完后应接受哪个判断 | 结果是多少 |

`role=stability` 的图（舍入、采样层级、数值稳定性审计）一律进附录。

每问优先提供一张紧凑的直接答案表；当空间、流程、机制或权衡无法靠短文说清时，加入一张模型/机制图。图必须解释数学对象或支持判断，不能只美化流程。

视觉想法先用 `write_visual_ideas.py` 写入轻量列表，并在 `figures/sandbox/<idea-id>/` 生成多个草图。草图不要求结果绑定、最终 caption、LaTeX label、manifest、panel mapping 或 design contract。fresh reviewer 选出最快说明机制且最不重复表格的候选后，`visual_sandbox.py graduate` 只记录 design reference、其哈希和目标 work 目录；必须再用 current 数据与正式 renderer 重新生成 work 候选，此时才进入来源绑定、图形 QA 和正文消费闭环。

Author Pass 和长篇首稿会自动维护 `paper/generated/VISUAL_REQUIREMENTS.json`。也可手动运行 `python scripts/paper/build_visual_requirements.py <run_dir>` 刷新并路由；`--no-sync` 仅用于只读审计准备。需求按 `hero_figure` 与 `supporting_figure` 分层：前者追求少数可记忆主图，后者按真实论证需要生成且不设数量上限。候选稿必须逐项由 current 正式图覆盖，或由视觉评阅者给出实质 `DROP` 记录；缺少旧 `FIGURE_PLAN` 本身不阻断 Author 开稿。

v3.4 的 `figure_templates_v34.py` 注册科研图、模型示意图和 CUMCM semantic/classic 外壳。`design_only` 只提供当前题的结构启发，只有明确标记 `renderer_available` 的模板才可进入渲染计划；注册表不携带其他题目的数据、公式或结论。

`FIGURE_PLAN.json` 2.4 只作旧运行兼容和晋级后的后台审计，不再要求 Author 为每个问题手写 required/waived、`argument_unit_ids`、`obligation_types` 或 `panel_mapping`。最终图仍须绑定当前来源、脚本、输出、claim、placement、caption 和人工接受结论；`stability` 图只能在附录消费。

---

## answer map 硬性要求

- 每个必答问题在 `analysis/answer_map.json` 或 `paper/answer-map.json` 有当前 `result_id` 和直接答案位置
- 核心问题用 `insight_ids` 引用实验阶段登记的机制、边际收益、活跃约束或权衡类规律
- 未消费的 insight 只产生编辑 warning；正式答案仍必须绑定 current production 结果

---

## 源码

PDF 内只保留核心算法伪代码、一段真正关键的数学判断代码和运行入口。`source_code_appendix.pdf_page_budget` 默认不超过 1 页，完整代码走 `mode: attachment`。

---

## 修订范围

- `render`：字号、箭头、留白、分页和不改论证的图形样式，只递增 `render_revision`，不使盲评失效；重做版式和机械 QA。
- `argument`：正文结构、推导表达、图表论证位置或直接答案表述，重做论证、编译和 PDF 盲评。
- `science`：代码、数据、目标、主要结果或行动建议，回到实验和科学挑战，再重做论证与渲染。

可用 `python scripts/simple/delivery_control.py revision-impact <paths...>` 机械分类；它不替代对实际语义的判断。

---

## CUMCM 结构适配

仅对 Competition-First v3.2 的 CUMCM 正式候选稿，在编译前写 1.2 版
`paper/CUMCM_STRUCTURE_MAP.json`；1.1 只用于旧运行兼容。`profile=classic` 保留固定国赛栏目作为稳定兜底；
`profile=semantic` 定义为“经典国赛外壳 + 语义内核”，不是自由结构。必答问题不少于三问、
至少两问共享同一数学对象，且问题链新增资源、共享约束或聚合层时，省略 `profile`
会自动选择 `semantic`；证据不足时自动使用 `classic`，作者仍可显式选择兜底画像。

`semantic` 必须保持以下外层顺序：

```text
摘要
1 问题重述与分析
2 模型假设与符号
3 统一数学对象、共享模型与判据
4...n 按共享对象和新增困难组织的问题链求解
n+1 模型检验、评价与结论
参考文献
附录
```

同一一级章可以承担相邻语义角色，所以问题重述与分析、模型假设与符号、检验评价与结论
可以分别合并；Q1--Q3 等共享模型的问题也可合并讲述。必须保留一个标题同时包含“假设”
和“符号”的明确入口。支持主结论的近端验证与对应求解同章，综合检验只汇总跨问题内容；
数据处理仅在数据结构影响统计单位、聚合或模型选择时单列。全部必答问题仍须覆盖并保持
首次出现顺序，`PAPER_BLUEPRINT` 的论证顺序不得打乱。结构适配不得改变模型、数字、结论或证据等级。

1.1 同时填写轻量 `presentation_contract`：前五页阅读路线、跨问题主线、直接答案总览、
数据画像和逐问 hero figure。每项必须给源码锚点或具体豁免理由；初期使用 `mode=advisory`，
只有直接答案、证据必需图、结构语义缺失等稳定低风险项才可单独硬阻断。综合检验只保留跨问题
内容，支持主结论的近端验证继续留在各问正文。

通过 `python scripts/paper/cumcm_adapter.py <run_dir> structure-map --input <json>`
写入。适配只允许章节映射、段落移动、标题改写、去重、图表重排和交叉引用修复；
禁止修改模型、重新选择数字或创造结论。上传的 Word 模板只作为 Pandoc
`--reference-doc` 的样式和外层结构参考，占位文案不具科学权威；候选编译回执必须绑定模板路径和摘要。CUMCM 正文页数使用
CUMCM 2026 正文不得超过 30 页；低页数不自动触发扩写，内容是否充分交给论证覆盖、
Fresh Reviewer 与 Editorial Adjudicator 判断。

每次正式编译递增 `render_revision`；正文论证变化时才递增 `argument_revision`。独立 PDF
最终 PDF 盲评还必须执行固定人工干预提示：按数学建模国赛标准对照优秀论文，逐项判断图表缺口、报告/论文形态、笔法文风、排版、论证主线和十几页篇幅原因，并输出带优先级、修复层级与验收标准的修改清单。该干预只接收冻结 PDF，记录在盲评回执中，不联网、不读取题面或源码，也不新增工作流阶段。

盲评绑定 argument，版式审计绑定 render。纯渲染重编沿用仍有效的论证盲评，但必须重做当前
render 的版式与机械检查。

---

## 编译产物规定

`compile_paper` 在完成 PDF 后**尝试**生成 `paper/final.docx`（Word 版本），由 pandoc 从 LaTeX/Typst 源文件转换。PDF 是唯一始终必交的格式；Word 是否必交由竞赛交付配置（`profiles/<competition>.json` 的 `delivery.docx_required`）决定。

| 文件 | 路径 | 用途 |
|------|------|------|
| PDF | `paper/final.pdf` | 主要提交格式，进入 paper-blind 审查包，始终必交 |
| Word | `paper/final.docx` | 存在时同步进入 `paper/submission/final.docx`；是否必交见竞赛 `delivery` 配置 |

**环境要求**：`delivery.docx_required=true` 的竞赛需安装 [pandoc](https://pandoc.org/installing.html)。若 pandoc 不可用，`compile_paper` 不阻断 PDF 冻结，而是在回执写入 `docx_skipped_reason`；补装 pandoc 后可重跑或单独调用 `compile_docx` 补生成。

`materialize_submission_package` 按竞赛 `delivery` 配置处理 Word：`docx_required=false`（当前所有内置 Profile 的默认值）时缺少 Word 不阻断提交包，仍产出纯 PDF 提交；Word 存在则一并纳入。仅当竞赛显式声明 `docx_required=true` 时，缺少非空 `paper/final.docx` 才阻断物化。
