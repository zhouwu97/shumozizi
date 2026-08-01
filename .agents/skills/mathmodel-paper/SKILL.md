---
name: mathmodel-paper
description: 从 Competition-First v3.4 的当前真实结果组织、编译和修订数学建模论文。
---

# 论证驱动论文

论文不是结果汇总报告，也不是把复杂四问压到约 13 页的摘要。正文应由共享模型和少量关键数学判断贯穿，同时保留清楚的逐问章节、直接答案和问题间继承关系；不能只按 Q1/Q2/Q3/Q4 罗列方法名、参数和结果表。v3.4 先形成完整的长篇科学首稿，再由独立冷读和编辑判断删减；篇幅和图数是复核信号，不是科学充分性的替代物。

## v3.4 首稿默认链

正式结果先进入 `paper/PAPER_MATERIAL_POOL.md` 与 `paper/generated/material_pool.json`，再进入 `paper/RESEARCH_STORYBOARD.md` 与 `paper/generated/research_storyboard.json`。素材池只给作者提供直接答案、推导、结构观察、机制、对照、边界、示例和视觉机会；日志、回执、哈希、工具探测和调试路径留在控制层。故事板逐问回答评委先需要什么、现象是什么、为什么需要该数学对象、模型如何递进、哪条证据决定答案、机制是什么、边界在哪里以及如何交接到下一问。

默认首稿使用 `python scripts/paper/compile_longform_draft.py <run_dir>`，产物为 `paper/longform-draft.pdf`，并明确“不是最终提交稿”。它要求科学证据层和素材/故事板当前，但不要求最终竞赛叙事门禁；`compile_reviewable_draft.py` 仍保留为时间截止或内容未齐时的披露式 fallback。只有完成长篇冷读、叙事/视觉返修和竞赛版机械 QA 后，才使用严格 `compile_paper.py`。

独立 PDF 冷读可以记录 `EXPAND`、`COMPRESS`、`REORDER`、`ADD_DERIVATION`、`ADD_MECHANISM`、`ADD_COMPARISON`、`ADD_BOUNDARY`、`ADD_FIGURE`、`ADD_COMPANION_FIGURE`、`SPLIT_FIGURE`、`DROP_FIGURE`、`MOVE_TO_APPENDIX` 和 `MERGE_PARAGRAPHS`。这些动作写入 `review/PAPER_COLD_READER_EDITORIAL.json`；未关闭动作会阻断 `compile_paper.py`，但冷读器不能直接修改正式结果或科学事实。

## 第零步：确认可以写论文

逐问读取 `MODELING_UNITS.json` 1.4 的三层结果。`objective_answer` 是题面原目标下的正式答案，`recommended_plan` 是附加风险偏好或稳健条件下的建议，`evidence_grade` 说明证书、搜索与稳定性边界；后两者不得替换前者。`answer_map.primary_result_id` 必须等于 `objective_answer.result_id`。任一必答问题没有有效 objective answer 时，不得编译正式候选版，但可以形成带披露的可审阅草稿。

科学挑战中的发现必须绑定 `action_type`、`rollback_target`、`invalidates`、`required_action` 和关闭证据。未关闭的 `MODEL_REPAIR`、`OBJECTIVE_REDESIGN`、`ANSWER_REJECTION` 阻断论文；只有 `WRITING_FIX` 和已说明不可修复原因的 `DATA_LIMITATION` 可留在 paper 阶段。正式论文检查自然论证内容，不要求出现 `result_id`、实验收据、证明义务或“问题继承”等内部工作流术语。

进入写作后先查看 `delivery_control.py status`。第一版截止前，把当前已完成内容、未完成问题、剩余实验和有真实证据的候选结论写成披露 JSON，执行：

```text
python scripts/paper/compile_reviewable_draft.py <run_dir> --disclosure <json>
```

该专用入口生成 `paper/draft-1.pdf` 和独立草稿回执，允许正式答案资格或科学挑战尚未全部完成，但不允许虚构数字，且 PDF 必须明确“本稿不可作为最终提交”。没有证据支持的候选结论保持空数组，由状态页显示“暂无”。不要用正式 `compile_paper` 冒充首版草稿。

该入口不是“能编译即可”的排版检查：编译前必须完成非占位的 `PAPER_BLUEPRINT.md` 逐问论证覆盖；每个必答问题须在 `FIGURE_PLAN` 2.4 中于首稿前决定展示图 required 或经过复核的 waived，并完成写作前蓝图审核和第一版 PDF 冷读。

候选截止前先闭合所有正式答案资格与科学挑战，再执行严格 `compile_paper.py` 生成当前 `paper/final.pdf`，并保存 candidate 版本进入 `paper_review`。candidate 是可返修版本，不是科学内容的不可逆冻结；只有用户显式 final lock 才停止新增科学内容。

---

## 写作交接：先过滤控制层

论文阶段先读取题面事实、当前模型与推导、逐问直接答案、少量决定性结果、当前正文主图、必要文献，以及会改变结论的机制、竞争解释和边界。默认不要把完整运行目录直接灌入写作上下文；日志、manifest、哈希、回执、工具探测、阶段状态、完整搜索轨迹和普通 QA 只留在控制层。只有为解决数字冲突、复现问题或真实方法依赖时，才临时读取并翻译成自然学术语言。

内部字段负责保证事实可追溯，不能成为正文句式。正文不得直接出现 `result_id`、晋级状态、回执、scorer 或“流程已通过”等工作流表达；软件版本、初值数量、普通复算和环境信息只有在会改变结论时才进入正文，否则进入附录。

## 证据蒸馏与两遍写作

填写逐问机器可解析论证单元之前，先使用 `PAPER_BLUEPRINT.md` 的全局写作层蒸馏每个主要结论：结论、数学原因、决定性证据、竞争解释和适用边界。逐问字段用于完整性复核，不是正文目录，也不能直接转写成固定小节。

第一遍先按“判断或现象 → 必要数学关系 → 推导或计算证据 → 机制解释 → 对后续问题或决策的意义”写成连续论证。第二遍再按共享数学对象和新增困难切分章节，并把已写内容映射回逐问字段，确认题面要求、继承、推导、结果、机制、验证、边界和直接答案没有遗漏。

证据按功能去重，而不是按结论机械限为一项：下界、构造、活跃约束、扰动、独立复算、基线对照和边界检验可以并存，只要它们改变不同的信任判断。`paper/generated/evidence_functions.json` 对同一主张的同功能重复只给出压缩或移入附录建议；不同功能的证据不能因为“验证已存在”被自动删除。稳定性流水账、普通复算、完整环境和搜索记录进入附录。该写作动作不删除或放宽蓝图审核、FIGURE_PLAN 2.4、首稿冷读、返修闭环和最终人工干预。

---

## 第一步：填写 PAPER_BLUEPRINT.md

知识卡不提供当前题证据。候选稿会生成 `paper/generated/knowledge_usage.json` 和过滤后的 `paper/generated/knowledge_context.json`：只有 `validated` 或 `revised` 且绑定当前 production 结果的采用模式可进入论文上下文，`planned`、`not_executed` 和 `rejected_by_evidence` 不能写成方法优势。路线知识绑定建模单元；验证知识绑定验证类型、指标和事前通过准则；视觉知识绑定当前图及结构化数据；论文结构知识同时绑定蓝图锚点、实际源码和正文兑现锚点。知识使用的失败层级应回到 analysis/experiment 或 paper 修复，不能用局限性说明掩盖未兑现。

在动笔前，可执行 `python scripts/knowledge/retrieve_for_run.py <run_dir> --stage paper` 获得结构建议；需要外部文献时按需调用 `$mathmodel-literature` 生成双语检索计划和候选来源审计。零匹配时使用内置通用结构模式；知识应用与兑现只作 advisory。按 `paper/CITATION_PLAN.md` 分配 `background`、`core_method`、`validation`、`uncertainty` 和 `extension` 来源，可以检索实际采用方法的原始文献，但禁止同题答案、题解和现成结论。约 6–12 条只作紧凑性建议，不是数量门禁；每条参考文献必须至少绑定正文一个具体方法、指标、背景判断或验证动作，不能只列在文后。离线优秀论文卡只提供结构启发，明确禁止作为 citation 或当前事实来源。

候选稿检查会自动生成 `paper/generated/citation_coverage.json`，逐项核对正文 citation key、BibTeX/`bibitem` 定义、引用计划和结构化建模合同。未定义 key、计划已声明但正文未引用，以及新五列表格中已识别外部核心方法/验证方法却没有对应已兑现类别，属于高置信度合同错误；未使用条目、引用只集中在引言、来源过少或单一来源跨多个类别属于 warning。普通编号 `[1]` 不视为引用，来源权威性与相关性仍由作者和冷读人工核验，不能用 DOI 或数量自动代替。

作者主要维护 `paper/PAPER_BLUEPRINT.md`、`paper/answer-map.json`、`figures/FIGURE_PLAN.json` 和 `paper/PAPER_REVIEW.md`；v3.4 另维护 `PAPER_MATERIAL_POOL.md`、`RESEARCH_STORYBOARD.md` 和视觉机会池。旧 `ARGUMENT_PLAN.md`、`STORYBOARD.md` 与 `KNOWLEDGE_APPLICATION.md` 仅作兼容或后台建议。

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
- **完整性预算**：逐问预留问题分析、模型流、推导、算法、结果解释和验证边界的空间；复杂四问可用约 25–33 页正文作为初始估计，但赛事上限优先，页数不作为质量硬门
- **摘要**：最后写，见下方规范

---

## 第三步：按问题角色写正文

每个问题章节（尤其问题一、二、三）第一段先给“答案预览”：用一段自然语言和必要数字直接回答题面，并紧接一句证据范围；随后必须展开现象、数学对象、模型、推导、算法、结构、机制和边界。答案预览不是结论的替代物，也不能用一张答案表关闭章节。CUMCM 中文正文默认宋体小四（12pt），数学公式中的拉丁字母使用 Times New Roman 系斜体；编译后在 PDF 中抽查字体、字号、公式、图注和分页。

### 普通问题

```
问题分析与本问输出
→ 继承的共享模型与新增数学对象
→ 关键数学关系和必要推导
→ 可复现算法步骤或伪代码
→ 求解结果与机制解释
→ 验证和适用边界
→ 直接答案
```

普通问题可合并小节，但上述逻辑不能被删成“采用某算法，结果见表”。

### 核心问题

```
核心困难与建模判断（这里是什么真正难解的问题）
→ 关键命题（要在论文中支持的数学判断）
→ 推导（为什么命题成立，哪步是关键）
→ 求解策略（算法如何实现这步推导）
→ 结果与独立对照（计算证据，与MATLAB/替代实现对比）
→ 竞争解释与排除（为什么不是另一种解释）
→ 机制讨论（结果为何呈现这个结构）
→ 适用边界（哪些结论在当前参数外可能不成立）
→ 直接答案
```

核心问题必须把 `PAPER_BLUEPRINT.md` 里的论证单元真正写进正文。

## 展开深度与篇幅

- 先服从竞赛明确的页数上限；没有紧上限时按解释任务分配篇幅，不预设约 13 页。
- 对多问、共享模型复杂、需要分组验证或多条机制解释的论文，约 25–33 页正文可作为起始规划区间，之后按真实内容收缩或扩展。该区间不是机器门禁，也不证明竞争力。
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

该命令输出可机读的 `errors` 与 `warnings`。E001--E005 是可由源文直接复核的高置信度错误：正式正文泄漏工作流内部术语、同一任务报账模板高频重复、摘要逐问流水账且缺统一主线、核心问题由列表/表格主导且同时缺推导与机制、正文图未形成有序的观察—机制—结论消费。候选稿必须修复这些错误；运行说明可以留在附录，但不能进入正式正文。

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

视觉机会池中的候选先写入 `figures/work/<opportunity>/<version>/design-contract.json`，设计合同保留 `visual_question`、`atomic_claim`、候选原型、面板 takeaway、机制/边界标注和政策指纹。它是设计系统输入，不是 PNG/PDF 质量证明；candidate 仍须独立视觉批评、图形 QA 和正文消费闭环。

每个必答问题必须在首稿前于 `FIGURE_PLAN.json` 2.4 中分别声明 `evidence_need` 和 `presentation_need`，每张图绑定 `argument_unit_ids` 与 `obligation_types`。结构性 waived 必须有独立 `waiver_review`；required 图在 `figures/work/` 迭代，经机械 QA 与内容化人工复核后晋级 current，旧 current 自动归档；`stability` 图只能在附录消费。

---

## answer map 硬性要求

- 每个必答问题在 `analysis/answer_map.json` 或 `paper/answer-map.json` 有当前 `result_id` 和直接答案位置
- 核心问题用 `insight_ids` 引用实验阶段登记的机制、边际收益、活跃约束或权衡类规律
- 规律挖了但没引用会阻断编译

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
`--reference-doc` 的样式和外层结构参考，占位文案不具科学权威。CUMCM 正文页数使用
24–30 页软规划：少于 18 页检查论证缺失，18–23 页检查过度压缩，超过 30 页核对
官方上限和重复内容；页数本身不构成质量证据。

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
