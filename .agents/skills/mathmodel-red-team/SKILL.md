---
name: mathmodel-red-team
description: 对 Competition-First v3.2 运行执行条件目标语义审查、一次两阶段科学挑战、独立 PDF 盲评或按需网页 PDF 编辑审核。
---

# 薄验证壳

目标语义审查只在高影响未决歧义时执行，且只读题面和附件。题面无法唯一确定时如实记录用户裁决与论文声明，不伪装为唯一结论。

---

## 审核原则（不可协商）

所有问题审核（目标语义审查、科学挑战、PDF 盲评、网页审核）必须先遵守四条原则：

1. **全量先于逐项**。先通读整体（整篇题面、整篇论文、全部结果），给出全局问题清单，
   再逐项核对具体需求。不得只拿着单个 requirement/章节逐条打勾——那样会只见树木不见
   森林，漏掉跨问题、跨章节的共性问题。
2. **有问题就写，结构 JSON 只是载体**。发现问题必须用自由语言完整写出（什么问题、
   为什么是问题、在哪、严重度、建议），绝不为了符合输出 schema 而省略或改写。
   结构化字段（finding_id、严重度、action_type 等）只用于登记和路由，不允许因为
   "这个发现塞不进某个枚举"就把它丢掉。
3. **鼓励发现问题**。发现问题是审核的贡献，不因问题数量多而受罚；风险数量不做硬性
   要求，相互关联的问题可以合并分析，足够关键的单一缺陷值得全部精力。不得用
   "通过/未通过"之类的单一判词替代自由判断。
4. **批量修复，不因小问题反复来回**。同一轮发现的同类小问题（措辞、图注、章节组织、
   格式、证据边界说明）合并成一批一次处理；已分类为 WRITING_FIX / DATA_LIMITATION
   的发现不阻断、不进入下一轮审核。只有会改变模型、结果、endpoint 或正式答案的
   MODEL_REPAIR / OBJECTIVE_REDESIGN / ANSWER_REJECTION 才返回对应阶段并阻断，
   且每一轮只针对真实新增的高价值发现，不得为了"全绿"而无限循环。

---

## 首解轻量 checkpoint

核心优化/协同题首个可行解后的独立 AI checkpoint 发生在大规模深化前，只回答“最可能错在哪里、什么假设会推翻、是否有结构不同路线、下一项最低成本实验、继续 experiment 还是返回 analysis”。使用 `scripts/review/show_first_feasible_prompt.py` 生成固定提示，结果回填 `MODELING_UNITS.actual.refinement`；不生成审查包、报告或回执，也不替代全部问题完成后的两阶段科学挑战。

---

## 科学挑战：两阶段阅读

科学挑战只做一次。必须按阶段顺序执行，**不能跳过阶段A直接读代码**。

### 阶段A：只读题面，独立建模

只阅读 `review/packet/scientific/*/problem/` 目录，不读取代码和结果。

自由重建并记录：
1. 题目的核心数学结构——什么才是真正决定解答上限的数学对象？
2. 一个最简单可靠的 baseline，以及至少一个结构上不同、可能更强的候选路线；
3. 最可能导致目标函数失真或题意偏离的建模选择；
4. 最值得通过实验区分的两个假设。

先判断当前核心问题更可能错在目标语义/分解，还是模型/搜索。出现多主体、嵌套量词、总体/共同/同时/分别/至少一个、和与最小值或并集与交集竞争、相邻问题实体数变化、先分解后组合时，第一攻击必须针对语义或分解等价性，并构造一个让两个解释排序相反的玩具反例；反例无法区分时才把攻击预算转向几何、代理评分、搜索、鲁棒性或数值精度。阶段 A 的这一判断与反例随科学挑战证据登记，不增加审核轮次。

不要按清单作答。某个问题足够关键时，可以把大部分篇幅集中在它上面。把阶段A的独立判断明确写入报告——哪怕只是几段，这是防止锚定的核心。

### 阶段B：读代码和结果，对照比较

阶段 B 开始前先复验 `MODELING_UNITS`：系统从 coordination、资源间聚合文本、
非联合分解、待比较 endpoint 和显式嵌套量词派生风险；每个派生或人工登记的高风险单元必须已经各自
执行至少一个能区分量词/聚合解释的 scorer 反例。缺少任何一个时直接返回 experiment，
不允许用本轮“一个最高价值攻击”替代逐单元的低成本语义覆盖。

在阶段A的独立重建基础上，再阅读代码和当前结果，重点回答：
1. 当前方案利用了哪些题目结构？遗漏了哪些？
2. 哪个结论最可能是目标定义偏差、代理评分器失真或搜索不足造成的假象？
3. **选择一个最高价值判断，设计并实际执行能够推翻或支持它的最低成本攻击**——说明攻击结论（推翻 / 支持 / 仍不确定）；
4. 是否存在值得真实尝试的更强路线或目标定义？
5. 下一项实验中，哪一项最可能提升模型结果、机制洞察或论文竞争力？

每个发现必须写入 `scientific-challenge-evidence.json.findings`，登记 `finding_id`、问题、严重度、`action_type`、`rollback_target`、`invalidates`、`required_action`、状态和真实关闭证据。只涉及措辞、图表说明、证据边界或章节组织的用 `WRITING_FIX`；确实无法用当前数据或实验修复且说明原因的用 `DATA_LIMITATION`。会改变模型或结果的用 `MODEL_REPAIR` 返回 experiment，会改变 endpoint 或目标的用 `OBJECTIVE_REDESIGN` 返回 analysis，当前问没有正式答案时用 `ANSWER_REJECTION`。后三类未关闭时阻断 paper，不得降级成“在局限性中说明”。

风险数量不做硬性要求——问题相互关联时可以合并分析，足够关键的单一缺陷值得全部精力。

---

## 专项追问

只有 P0/P1、决定性补充实验或能否继续无法判断时才允许一个 `FOCUSED_FOLLOWUP.md`。

专项追问只回答一个问题：**什么实验结果会改变当前路线、目标或主结论？** 然后运行最低成本的区分性实验，不要把它写成第二份综合审核。

---

## 更强路线的闭合

"是否存在明显更强的路线或目标定义"必须用 `record_stronger_alternative` 闭合，不能只写在报告里。发现更强方案时二选一：真的跑一次并绑定真实生产结果，或写明为何在赛程内不可行。未记录时不放行论文——挑战发现了上限却不必去拿，等于取消了搜索义务。

---

## PDF 盲评

PDF 盲评需要独立上下文，**不能新开浏览器页面**，平台区分如下：

- **Codex 桌面端**：用 `create_thread` 新建顶层对话，`provider=codex`，`creation_mode=create_thread`，`parent_context_inherited=false`。
- **Claude.ai / Claude Code**：用 Agent tool dispatch 一个子 Agent，**不传入任何当前 run 的上下文**，只传冻结 PDF 路径 + 提示词；子 Agent ID 即为 `raw_thread_id`，`provider=claude`，`creation_mode=dispatch_agent`，`parent_context_inherited=false`。

无论哪种平台，新上下文只读取冻结 PDF，提示词由 `scripts/review/show_paper_blind_prompt.py` 生成并原样传入；不读取题面、源码、历史 run、求解上下文、作者说明或前序审核结论。最终提示词还固定记录用户人工干预：按国赛标准对照优秀论文，审查图表缺口、报告/论文形态、笔法文风、排版、论证主线、篇幅不足原因和具体修改优先级；不得把它缩减成只看建模思路。盲评写 `review/PAPER_BLIND_REVIEW.md`，除第一印象、写作风格、可读性、P0/P1 和最高价值修改外，必须完成三分钟冷读，并在同一报告末尾按固定提示嵌入 `## 结构化盲评结果` JSON：逐问记录直接答案、论证缺失角色、实际页码、具体 finding、问题继承和叙事风险。导入器把该块写入现有 `review/paper-blind-review.json`，并将人工干预来源、PDF-only 边界和覆盖维度写入回执，绑定报告哈希、任务/对话 ID、固定提示词和当前 `paper_render_revision`；不得另交一份作者填写的冷读 JSON。

每个科学版本至少做一次独立盲评；默认上限为两轮。同一轮的措辞、图注、章节组织和证据边界修改必须批量合并，不能为小改连开第三轮。只有新的 P0/P1、中心论证重构或科学事实变化才有第二轮必要性；纯渲染变化沿用仍有效的盲评，只重做版式和机械 QA。

不得创建 coverage declaration、逐风险 follow-up、final audit 或仅以 pass/fail 代替自由判断。已执行反例、独立复算冲突、不可行和性质失败始终阻断。

对 CUMCM v3.2，`paper/CUMCM_LAYOUT_AUDIT.json` 1.3 直接读取当前 `review/paper-blind-review.json`，把同一轮独立盲评的冷读、结构、逐问缺失角色与页码、问题继承和叙事风险作为唯一评审事实源；`paper-review --input` 禁止再次传入 `cold_read`、`argument_depth`、`question_progression` 或 verdict。系统只在本地追加 `presentation_contract` 兑现、PDF 页面节奏探针和 `learning_checks`；每项 `learning_checks` 只填写 `pattern_id`、`pdf_realization=pass|partial|fail` 和具体 `finding`，并始终 advisory。核心问题只要盲评 `missing_roles` 非空就阻断，不能用四十多个全 true 布尔值覆盖。使用 `python scripts/paper/cumcm_adapter.py <run_dir> paper-review --input <json>` 写入，其中 JSON 只含可选的 `learning_checks`。

---

## 按需网页 PDF 审核

这不是 PDF 盲评的替代品。只有运行初始化时显式要求网页审核，或论文稳定后需要一轮专项编辑审查时，生成 `WEB_PAPER_AUDIT_PROMPT`，由用户在网页版普通新对话中只上传当前 PDF 和固定提示词。记录 `provider=chatgpt_web`、`creation_mode=manual_new_chat` 与 `waiting_external_review`，等待结果导入；不得用当前对话、联网检索、题面、代码或作者解释替代该输入边界。

导入后只把意见用于写作风格、可读性、图表说明与论证表达的风险定位。P0/P1 必须写入局部修复计划并重新编译；若意见要求改变模型、主结果、主图或章节主线，返回 paper 或 experiment，不要降级成文字润色。未显式要求网页审核时，它保持可选，不能阻断纯 Codex 盲评路径。
