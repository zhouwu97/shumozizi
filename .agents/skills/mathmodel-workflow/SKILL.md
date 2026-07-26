---
name: mathmodel-workflow
description: 以 Competition-First v3.2 完成整道数学建模赛题的分析、真实实验、论文和轻量审查。仅在用户明确要求完整赛题交付时使用。
---

# Competition-First v3.2 工作流

只在完整赛题任务中创建运行。主链为 `analysis -> experiment -> paper -> paper_review -> verify -> complete`；不要创建 `capability_route`、`scientific_review`、`visualization` 或 `final_review` 阶段。

1. 分析时优先题目结构、baseline、实质不同路线与区分性 probe。开放目标先在 `OBJECTIVE_CANDIDATES.json` 保留候选集合与后果度量，看过策略后果再冻结。标出核心问题。写 `ROUTE_COMPETITION.md` 和 `NEXT_EXPERIMENTS.md`。
2. 只有未决且会改变主结果的题意歧义才创建目标语义审查；歧义未决时不得用 `determined` 跳过候选比较。能力选择属于分析/实验中的按需动作。
3. 实验只运行能改变决定的工作，并把预算优先投给核心问题的搜索深化——核心搜索耗时须超过其验证耗时且占实际算力 40% 以上。比较要真的判胜负，核心问题必须达到事前声明的改善阈值。所有论文事实必须由执行器真实登记；生成 `method_facts.json` 只为建议，不得等待它放行。
4. 结束实验后进行一次自由科学挑战；必要时只允许一个专项追问。用 `record_stronger_alternative` 闭合"是否存在更强路线"。负面证据先级联失效，再决定回退。
5. 图表与洞察嵌入实验和论文：图在 `figures/current/` 并声明 role（稳定性图入附录），核心问题的规律带 `insight_id` 登记，可读版本写入 `INSIGHTS.md`。
6. 论文围绕 strongest question、真实规律和最多三项贡献组织。每个必答问题必须在 answer map 有当前结果和直接答案位置；核心问题还要用 `insight_ids` 引用已挖出的机制或边际收益类规律。源码默认不占正文超过一页。
7. PDF 盲评必须通过 Codex `create_thread` 新建独立顶层对话，禁止 fork、子 Agent 或续用已有对话。新任务只接收 `paper-blind` 包中的冻结 PDF，并原样使用 `scripts/review/show_paper_blind_prompt.py` 生成的“严格审核”提示词；等待它完成后再导入报告和 `thread_id`。盲评采用相对竞争力评价，随后执行机械 QA。无法盲评时的跳过说明只允许继续 QA，状态必须为 `unreviewed`，不能进入 `complete` 或 `submission_ready`；标记完成前重新验证科学挑战仍绑定当前生产事实。不要创建 coverage 或 final audit。

旧 v3.0 运行可查看和更新，运行时会在首次显式更新时记录阶段迁移。不要把 legacy 审核合同重新接入新运行。
