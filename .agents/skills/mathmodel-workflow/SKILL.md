---
name: mathmodel-workflow
description: 以 Competition-First v3.2 完成整道数学建模赛题的分析、真实实验、论文和轻量审查。仅在用户明确要求完整赛题交付时使用。
---

# Competition-First v3.2 工作流

只在完整赛题任务中创建运行。主链为 `analysis -> experiment -> paper -> paper_review -> verify -> complete`；不要创建 `capability_route`、`scientific_review`、`visualization` 或 `final_review` 阶段。

## 交付控制

初始化 v3.2 运行后，先执行 `python scripts/simple/delivery_control.py status <run_dir>`，并在阶段切换或准备扩展协议前重查。运行时按阶段自动记录一个 phase session，不再要求每段命令手动 `start-work/stop-work`，也不追查 20 分钟墙钟空档。只有协议、执行器或 P0 交付修复需要精确核算开销时，才用细粒度工时命令登记，不能用实验耗时掩盖协议开销。

交付状态返回的唯一最高优先级动作覆盖普通探索：第一版 PDF 截止后，将四类披露写入 JSON（`completed_content`、`unfinished_questions`、`remaining_experiments`、`provisional_conclusions`），执行 `python scripts/paper/compile_reviewable_draft.py <run_dir> --disclosure <json>`；该命令直接生成、复验并冻结 `paper/draft-1.pdf`。它允许答案资格尚未全部完成，但必须使用当前真实内容，并在 PDF 中明确“本稿不可作为最终提交”。候选截止后仍用严格 `compile_paper.py` 生成 `paper/final.pdf`，再执行 `freeze-pdf candidate`；盲评截止后先创建或恢复盲评。

首版截止或提前冻结 `first_reviewable` 后，公开写入口继续硬拒绝新增路线、额外审核任务、协议迁移和执行器重构；候选 PDF 冻结前允许按 PDF 评审发现限量新增实验或正文图。每个新增项必须写 12 字以上 `review_finding`，单次最多 5 项；候选 PDF 冻结后停止新增科学内容。实验计划使用受控 `write_next_experiments()`，图表计划使用 `python scripts/figures/write_figure_plan.py <run_dir> --input <json>`。运行初始化后的工作流源码已经锁定；只有确实阻断当前实验或 PDF 交付的 P0 修补，才可在登记 `blocking_delivery_repair=true` 的真实工时后执行 `approve-p0-patch`。其余通用改进写入 backlog，赛题结束后再改仓库。

1. 分析先逐问冻结直接答案合同：题目最终要求交付什么、决策对象/总体是谁、主终点如何定义、什么判据决定答案、哪个是自然 baseline、何时切换 fallback。开放目标仍在 `OBJECTIVE_CANDIDATES.json` 保留候选集合与共同后果度量；主终点必须预先声明，目标聚合有歧义时登记全部候选 endpoint、题面依据和裁决规则，不得看完结果再更换 endpoint。随后比较 baseline、实质不同路线与区分性 probe，标出核心问题，写 `ROUTE_COMPETITION.md` 和 `NEXT_EXPERIMENTS.md`。
2. 只有未决且会改变主结果的题意歧义才创建目标语义审查；歧义未决时不得用 `determined` 跳过候选比较。能力选择属于分析/实验中的按需动作。
3. 实验只登记原始结果指标，把预算优先投给核心问题的搜索深化——核心搜索耗时须超过其验证耗时且占实际算力 40% 以上。exact 赢家还不是主答案：系统根据事前改善阈值、最终 endpoint 裁决、guard 和行动稳定性派生 `promoted`、`fallback_selected` 或 `redesign_required`；不得手填四个通过布尔值覆盖失败事实。fallback 也不可靠时，endpoint/目标问题返回 analysis，其余模型、搜索或验证问题返回 experiment。所有论文事实必须由执行器真实登记；生成 `method_facts.json` 只为建议，不得等待它放行。
4. 结束实验后进行一次自由科学挑战；必要时只允许一个专项追问。每条发现必须分类为 `WRITING_FIX`、`MODEL_REPAIR`、`OBJECTIVE_REDESIGN`、`DATA_LIMITATION` 或 `ANSWER_REJECTION`，并登记回退目标、失效范围和关闭证据。未关闭的模型修复、目标重设或答案拒绝必须阻断论文。用 `record_stronger_alternative` 闭合"是否存在更强路线"。
5. 图表与洞察嵌入实验和论文：图在 `figures/current/` 并声明 role（稳定性图入附录），核心问题的规律带 `insight_id` 登记，可读版本写入 `INSIGHTS.md`。每个核心问题还必须在 `FIGURE_PLAN.json` 中显式选择 `required` 或 `waived`；旧 2.1 兼容读取，新计划使用含视觉原型与决策后果的 2.2。前者至少绑定一张非 stability 正文主图，后者写具体理由，不靠省略计划静默零图。
6. 只有每个必答问题都由系统派生出正式答案或可靠 fallback，且没有阻断类科学发现时才进入正式候选论文。首版草稿可以披露未完成问题，但编译前必须已有非占位的 `ARGUMENT_PLAN.md` 和 `STORYBOARD.md`；已完成核心问题至少写出判断、证据、竞争解释和边界。论文用共享模型和逐问关系组织，但保留清楚的直接回答。每问按复杂度展开问题分析、数学对象、必要推导、算法步骤、结果分析、机制解释、自然 baseline 比较、模型检验和适用边界；正式文本不要求出现 `result_id`、实验收据、证明义务或“问题继承”等内部工作流术语。核心问题再用 `insight_ids` 写完整的竞争解释排除和讨论节。复杂四问论文可先按约 25–33 页正文估算，再受赛事页数上限和实际内容约束调整；不得把该区间做成硬门，也不得预设约 13 页后删掉推导与解释。正文优先讲一个主模型、一个自然 baseline 和一条真正不同的 challenger，完整代码走附件，中央推导与必要参考文献留在正文。

返修时运行 `python scripts/simple/delivery_control.py revision-impact <paths...>` 判断最小重验范围：`science` 重做科学挑战、论证和渲染，`argument` 只重做论证和渲染，`render` 只重做图像/PDF 检查。字号、箭头、留白和纯排版修改不得让已验证科学结果无故失效。
7. PDF 盲评必须通过 Codex `create_thread` 新建独立顶层对话，禁止 fork、子 Agent 或续用已有对话。新任务只接收 `paper-blind` 包中的冻结 PDF，并原样使用 `scripts/review/show_paper_blind_prompt.py` 生成的“严格审核”提示词；等待它完成后再导入报告和 `thread_id`。盲评采用相对竞争力评价，随后执行机械 QA。无法盲评时的跳过说明只允许继续 QA，状态必须为 `unreviewed`，不能进入 `complete` 或 `submission_ready`；标记完成前重新验证科学挑战仍绑定当前生产事实。不要创建 coverage 或 final audit。

旧 v3.0 运行可查看和更新，运行时会在首次显式更新时记录阶段迁移。不要把 legacy 审核合同重新接入新运行。
