---
name: mathmodel-workflow
description: 以 Competition-First v3.2 完成整道数学建模赛题。当用户提供完整题面或附件，要求解答整题、多问建模、真实实验、图表、论文或竞赛交付时主动使用；局部分析、调试和单独改稿不启动完整工作流。
---

# Competition-First v3.2 工作流

## 触发与初始化

用户不需要说出 Skill 名称。收到完整数学建模题面或附件，或用户要求“解整题”“完成各问”“做实验并写论文”“形成竞赛交付”时，必须先使用本 Skill 总控，再按阶段调用主动 Skill。只有局部分析、单个实验、代码调试、单图制作或论文局部修改时，才不创建完整运行。

新任务先定位题面路径和必答问题，再执行：

```powershell
python scripts/codex/init_simple_run.py <problem_path> --run-id <run-id> --workflow-version 3.2 --question Q1
```

多问任务为每一问追加 `--question`。初始化成功后以命令返回的 `run_dir` 为唯一生产目录，立即执行 `python scripts/simple/delivery_control.py status <run_dir>`，然后进入 `analysis`。主链为 `analysis -> experiment -> paper -> paper_review -> verify -> complete`；不要创建 `capability_route`、`scientific_review`、`visualization` 或 `final_review` 阶段。

## 交付控制

初始化 v3.2 运行后，先执行 `python scripts/simple/delivery_control.py status <run_dir>`，并在阶段切换或准备扩展协议前重查。运行时按阶段自动记录一个 phase session，不再要求每段命令手动 `start-work/stop-work`，也不追查 20 分钟墙钟空档。只有协议、执行器或 P0 交付修复需要精确核算开销时，才用细粒度工时命令登记，不能用实验耗时掩盖协议开销。

交付状态返回的唯一最高优先级动作覆盖普通探索：第一版 PDF 截止后，将四类披露写入 JSON（`completed_content`、`unfinished_questions`、`remaining_experiments`、`provisional_conclusions`），执行 `python scripts/paper/compile_reviewable_draft.py <run_dir> --disclosure <json>`；该命令直接生成、复验并冻结 `paper/draft-1.pdf`。它允许答案资格尚未全部完成，但必须使用当前真实内容，并在 PDF 中明确“本稿不可作为最终提交”。候选截止后仍用严格 `compile_paper.py` 生成 `paper/final.pdf`，再执行 `freeze-pdf candidate`；盲评截止后先创建或恢复盲评。

首版截止或提前冻结 `first_reviewable` 后，公开写入口继续硬拒绝新增路线、额外审核任务、协议迁移和执行器重构；候选 PDF 冻结前允许按 PDF 评审发现限量新增实验或正文图。每个新增项必须写 12 字以上 `review_finding`，单次最多 5 项；候选 PDF 冻结后停止新增科学内容。实验计划使用受控 `write_next_experiments()`，图表计划使用 `python scripts/figures/write_figure_plan.py <run_dir> --input <json>`。运行初始化后的工作流源码已经锁定；只有确实阻断当前实验或 PDF 交付的 P0 修补，才可在登记 `blocking_delivery_repair=true` 的真实工时后执行 `approve-p0-patch`。其余通用改进写入 backlog，赛题结束后再改仓库。

1. 分析先审计题面、数据结构和统计单位，形成任务指纹，执行 `python scripts/knowledge/retrieve_for_run.py <run_dir> --stage analysis --input <fingerprint.json>` 检索仓内论文卡。检索主要使用结构字段，不按题名找答案；最多保留 3 张结构相似卡、每卡 2 个安全模式，对这些候选逐项记录采用或拒绝。知识卡只提供路线启发，原题参数、公式和代码、数值结论及奖项评价不得迁移。
2. 两轮只读 `problem/` 的题意重建分别承担 `faithful_reconstruction` 和 `semantic_adversary`，不是两个同质复述。逐问先写 `question_delta`，识别相对前问新增的实体、资源、共享约束和聚合层；再用 `MODELING_UNITS` 1.3 冻结直接答案合同，明确原子成功、资源、主体、时间和量词聚合。高风险问题先构造最小语义反例，核心问题再用 3--5 个人工案例实测 scorer，全部通过后才比较优化路线。`OBJECTIVE_CANDIDATES` 1.1 先筛题面合法性，再用同源反例区分，只对仍合理的候选运行后果 probe；不得用结果更漂亮反推题意。
3. 只有未决且会改变主结果的题意歧义才创建目标语义审查；歧义未决时不得用 `determined` 跳过候选比较。能力选择属于分析/实验中的按需动作。
4. 实验只登记原始结果指标，把预算优先投给核心问题的搜索深化——核心搜索耗时须超过其验证耗时且占实际算力 40% 以上。exact 赢家还不是主答案：系统根据事前改善阈值、最终 endpoint 裁决、guard 和行动稳定性派生 `promoted`、`fallback_selected` 或 `redesign_required`；不得手填四个通过布尔值覆盖失败事实。fallback 也不可靠时，endpoint/目标问题返回 analysis，其余模型、搜索或验证问题返回 experiment。所有论文事实必须由执行器真实登记；生成 `method_facts.json` 只为建议，不得等待它放行。
5. 结束实验后进行一次自由科学挑战；必要时只允许一个专项追问。阶段 A 先判断核心风险在目标语义/分解还是模型/搜索；多主体、嵌套量词、聚合词、问题实体变化或分解后组合存在时，第一攻击必须针对语义并给出独立玩具反例。只有语义风险低时才优先攻击搜索和数值。其余发现分类、回退和更强路线闭合规则不变。
6. 图表与洞察嵌入实验和论文：图在 `figures/current/` 并声明 role（稳定性图入附录），核心问题的规律带 `insight_id` 登记，可读版本写入 `INSIGHTS.md`。新运行使用 `FIGURE_PLAN.json` 2.3，逐项区分 `evidence_need` 与 `presentation_need`，并用 `presentation_role` 标记数据画像、逐问主图、辅助图或附录图。科学必需图继续硬闭环；呈现必需图初期只告警。数据结构决定模型选择时应规划 `scope=whole_paper` 的数据画像，但纯解析题可以有理由地豁免，不按问题数凑图。
7. 只有每个必答问题都由系统派生出正式答案或可靠 fallback，且没有阻断类科学发现时才进入正式候选论文。写 `ARGUMENT_PLAN.md` 前先执行 `python scripts/knowledge/retrieve_for_run.py <run_dir> --stage paper`；模板只重新判断分析已采用项，分析拒绝自动继承，只有 `--force --reopen <pattern_id>` 才重开。采用模式最多来自 1--2 张卡，并绑定当前题证据、实际正文源码和兑现锚点。其余论文展开、证据边界和图表要求不变。CUMCM v3.2 使用 `CUMCM_STRUCTURE_MAP` 1.1：`classic` 为固定栏目兜底，`semantic` 暂为实验画像且不设默认；两者都填写 advisory `presentation_contract`。适配器不得改模型、挑数字或造结论。

返修时运行 `python scripts/simple/delivery_control.py revision-impact <paths...>` 判断最小重验范围：`science` 重做科学挑战、论证和渲染，`argument` 重做论证和渲染，`render` 不重做科学挑战或论证内容。字号、箭头、留白和纯排版修改不得让已验证科学结果无故失效；但只要正式重编，盲评、版式审计和图像/PDF 检查仍须绑定新的 `paper_render_revision`。
8. PDF 盲评必须使用独立上下文，只接收冻结 PDF 和固定提示词。自由报告末尾必须包含同源结构化 JSON；导入后写入现有 `review/paper-blind-review.json`，绑定报告哈希、任务/对话 ID 和当前渲染修订。`CUMCM_LAYOUT_AUDIT` 1.3 直接读取该记录的冷读、逐问缺失角色/页码/finding、问题递进和叙事风险；不得让作者再次填写平行 `cold_read` 或全 true 论证布尔值。本地只追加呈现合同、页面探针和 advisory 学习兑现。verify 和失效规则不变。

旧 v3.0 运行可查看和更新，运行时会在首次显式更新时记录阶段迁移。不要把 legacy 审核合同重新接入新运行。
