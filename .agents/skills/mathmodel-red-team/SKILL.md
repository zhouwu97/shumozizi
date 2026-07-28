---
name: mathmodel-red-team
description: 对 Competition-First v3.2 运行执行条件目标语义审查、一次两阶段科学挑战、独立 PDF 盲评或按需网页 PDF 编辑审核。
---

# 薄验证壳

目标语义审查只在高影响未决歧义时执行，且只读题面和附件。题面无法唯一确定时如实记录用户裁决与论文声明，不伪装为唯一结论。

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

不要按清单作答。某个问题足够关键时，可以把大部分篇幅集中在它上面。把阶段A的独立判断明确写入报告——哪怕只是几段，这是防止锚定的核心。

### 阶段B：读代码和结果，对照比较

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

无论哪种平台，新上下文只读取冻结 PDF，提示词由 `scripts/review/show_paper_blind_prompt.py` 生成并原样传入；不读取题面、源码、历史 run、求解上下文、作者说明或前序审核结论。盲评写 `review/PAPER_BLIND_REVIEW.md`，除第一印象、写作风格、可读性、P0/P1 和最高价值修改外，必须完成三分钟冷读：逐问定位直接答案、复述一句话贡献、说明问题继承、识别主图及其论点、指出工作报告页，并判断前五页是否建立数据直觉。审查报告绑定冻结 PDF、固定提示词哈希、当前 `paper_render_revision` 与真实任务回执。

不得创建 coverage declaration、逐风险 follow-up、final audit 或仅以 pass/fail 代替自由判断。已执行反例、独立复算冲突、不可行和性质失败始终阻断。

对 CUMCM v3.2，盲评后把同一轮冷读结果与结构完整性、核心问题论证深度、问题继承和叙事风险写入 `paper/CUMCM_LAYOUT_AUDIT.json`，不另开审核阶段。使用 1.2 时，系统自动附上 `presentation_contract` 的源码/图表兑现检查和 PDF 页面节奏探针，并把本地 `learning_checks` 与 `KNOWLEDGE_APPLICATION.md` 中预先采用的模式合并为 `learning_realization`；每项 `learning_checks` 只填写 `pattern_id`、`pdf_realization=pass|partial|fail` 和具体 `finding`，卡片、模式、正文位置与证据由系统从知识应用文件重建。该项只检查计划是否在 PDF 中兑现，始终 advisory，不能评价奖项水平或充当当前证据。高文字密度页、图表后置、数据直觉不足、主图难识别和工作报告感先作为 advisory，逐问直接答案在三分钟内找不到则阻断。每个核心问题仍检查数学困难、数学对象、建模依据、关键推导、求解、主结果、机制、竞争路线或反例、结论近端验证和直接答案；四问可任意换序、统一套句、用步骤冒充推导、图不支撑论点或用文件/公式/页数充当质量时不得进入 verify。使用 `python scripts/paper/cumcm_adapter.py <run_dir> paper-review --input <json>` 写入。

---

## 按需网页 PDF 审核

这不是 PDF 盲评的替代品。只有运行初始化时显式要求网页审核，或论文稳定后需要一轮专项编辑审查时，生成 `WEB_PAPER_AUDIT_PROMPT`，由用户在网页版普通新对话中只上传当前 PDF 和固定提示词。记录 `provider=chatgpt_web`、`creation_mode=manual_new_chat` 与 `waiting_external_review`，等待结果导入；不得用当前对话、联网检索、题面、代码或作者解释替代该输入边界。

导入后只把意见用于写作风格、可读性、图表说明与论证表达的风险定位。P0/P1 必须写入局部修复计划并重新编译；若意见要求改变模型、主结果、主图或章节主线，返回 paper 或 experiment，不要降级成文字润色。未显式要求网页审核时，它保持可选，不能阻断纯 Codex 盲评路径。
