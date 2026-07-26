---
name: mathmodel-red-team
description: 对 Competition-First v3.1 运行执行条件目标语义审查、一次自由科学挑战或相对竞争力 PDF 盲评。
---

# 薄验证壳

目标语义审查只在高影响未决歧义时执行，且只读题面和附件。题面无法唯一确定时如实记录用户裁决与论文声明，不伪装为唯一结论。

科学挑战只做一次，报告 `review/SCIENTIFIC_CHALLENGE.md` 必须回答：独立目标/变量/约束、三处最大风险、对最大风险的实际攻击、最薄弱问题、当前竞争力上限，以及最可能改变结论的下一实验。只有 P0/P1、决定性补充实验或能否继续无法判断时才允许一个 `FOCUSED_FOLLOWUP.md`。

"是否存在明显更强的路线或目标定义"必须用 `record_stronger_alternative` 闭合，不能只写在报告里。发现更强方案时二选一：真的跑一次并绑定真实生产结果，或写明为何在赛程内不可行。未记录时不放行论文——挑战发现了上限却不必去拿，等于取消了搜索义务。

PDF 盲评必须由 `create_thread` 新建独立顶层对话，禁止 fork、子 Agent 或续聊。用 `scripts/review/show_paper_blind_prompt.py` 生成并原样发送极简提示词；新对话只读取冻结 PDF，不读取题面、源码、历史 run、求解上下文、作者说明或前序审核结论。盲评写 `review/PAPER_BLIND_REVIEW.md`，必须严格检查内容、数学逻辑、结果可信度和排版格式，并评价相对普通参赛论文的优势、最可记住之处、最弱章节、模型/结果/图表/写作档次、最可能提升奖项层级的修改和 P0/P1。审查报告绑定冻结 PDF、固定提示词哈希与真实任务回执。

不得创建 coverage declaration、逐风险 follow-up、final audit 或仅以 pass/fail 代替自由判断。已执行反例、独立复算冲突、不可行和性质失败始终阻断。
