---
name: mathmodel-workflow
description: 以 Competition-First v3.2 完成整道数学建模赛题的分析、真实实验、论文和轻量审查。仅在用户明确要求完整赛题交付时使用。
---

# Competition-First v3.2 工作流

只在完整赛题任务中创建运行。主链为 `analysis -> experiment -> paper -> paper_review -> verify -> complete`；不要创建 `capability_route`、`scientific_review`、`visualization` 或 `final_review` 阶段。

1. 分析先逐问冻结直接答案合同：题目最终要求交付什么、决策对象/总体是谁、主终点如何定义、什么判据决定答案、哪个是自然 baseline、何时切换 fallback。开放目标仍在 `OBJECTIVE_CANDIDATES.json` 保留候选集合与共同后果度量；主终点必须预先声明，目标聚合有歧义时显式计划比较，不得看完结果再更换 endpoint。随后比较 baseline、实质不同路线与区分性 probe，标出核心问题，写 `ROUTE_COMPETITION.md` 和 `NEXT_EXPERIMENTS.md`。
2. 只有未决且会改变主结果的题意歧义才创建目标语义审查；歧义未决时不得用 `determined` 跳过候选比较。能力选择属于分析/实验中的按需动作。
3. 实验只运行能改变决定的工作，并把预算优先投给核心问题的搜索深化——核心搜索耗时须超过其验证耗时且占实际算力 40% 以上。exact 赢家还不是主答案：必须通过事前改善阈值、endpoint 一致性、guard 约束和决策稳定性检查才能晋级。失败时启用已验证的 fallback；fallback 也不可靠时，按失败来源返回 analysis 重设计目标/策略，或返回 experiment 继续搜索。所有论文事实必须由执行器真实登记；生成 `method_facts.json` 只为建议，不得等待它放行。
4. 结束实验后进行一次自由科学挑战；必要时只允许一个专项追问。用 `record_stronger_alternative` 闭合"是否存在更强路线"。负面证据先级联失效，再决定回退。
5. 图表与洞察嵌入实验和论文：图在 `figures/current/` 并声明 role（稳定性图入附录），核心问题的规律带 `insight_id` 登记，可读版本写入 `INSIGHTS.md`。
6. 只有逐问主答案与 fallback 均冻结后才进入论文。论文用共享模型和问题继承关系组织，但保留清楚的逐问直接回答。每问按复杂度展开问题分析、数学对象、关键推导、算法步骤、结果机制、验证边界和直接答案；核心问题再用 `insight_ids` 写完整的竞争解释排除和讨论节。复杂四问论文可先按约 25–33 页正文估算，再受赛事页数上限和实际内容约束调整；不得把该区间做成硬门，也不得预设约 13 页后删掉推导与解释。正文优先讲一个主模型、一个自然 baseline 和一条真正不同的 challenger，完整代码走附件，中央推导与必要参考文献留在正文。
7. PDF 盲评必须通过 Codex `create_thread` 新建独立顶层对话，禁止 fork、子 Agent 或续用已有对话。新任务只接收 `paper-blind` 包中的冻结 PDF，并原样使用 `scripts/review/show_paper_blind_prompt.py` 生成的“严格审核”提示词；等待它完成后再导入报告和 `thread_id`。盲评采用相对竞争力评价，随后执行机械 QA。无法盲评时的跳过说明只允许继续 QA，状态必须为 `unreviewed`，不能进入 `complete` 或 `submission_ready`；标记完成前重新验证科学挑战仍绑定当前生产事实。不要创建 coverage 或 final audit。

旧 v3.0 运行可查看和更新，运行时会在首次显式更新时记录阶段迁移。不要把 legacy 审核合同重新接入新运行。
