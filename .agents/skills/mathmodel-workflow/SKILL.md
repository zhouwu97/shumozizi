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

首版截止只改变交付优先级，不拥有路线否决权。首版或 candidate 后仍可按评审发现返回分析、实验或图表；新增项须同时记录 `review_finding`、`estimated_cost`、`expected_benefit` 和 `stop_condition`，单次最多 5 项。只有用户显式执行 `final lock` 后才停止新增科学内容。工作流源码哈希只提供信息提示，不再需要公开的 approve/verify source-lock 命令，也不得阻断当前赛题。

1. 分析先审计题面、数据结构和统计单位，形成任务指纹，执行 `python scripts/knowledge/retrieve_for_run.py <run_dir> --stage analysis --input <fingerprint.json>` 检索仓内论文卡。检索主要使用结构字段，不按题名找答案；最多保留 3 张结构相似卡、每卡 2 个安全模式，对这些候选逐项记录采用或拒绝。知识卡只提供路线启发，原题参数、公式和代码、数值结论及奖项评价不得迁移。
2. 先预扫描全部 `question_delta` 与 endpoint 状态。低风险运行只完成一次 `faithful_reconstruction`；任一问题要求重查聚合或 endpoint 为 `comparison_planned` 时，再增加 `semantic_adversary` 和最小反例。语义结论本身是硬门，fresh-thread 回执、thread ID 与题面树哈希只作独立性记录。随后用 `MODELING_UNITS` 1.4 选择 `evaluation`、`optimization`、`exact_oracle`、`data_modeling`、`simulation` 或 `coordination`，并冻结直接答案合同。核心高风险优化问题再用 3--5 个人工案例实测 scorer。固定评价、数据建模和仿真不强迫路线赛马；exact oracle 必须同时核对指标容差与区间/集合结构。
3. 只有未决且会改变主结果的题意歧义才创建目标语义审查；歧义未决时不得用 `determined` 跳过候选比较。`optimization`、`simulation`、`exact_oracle` 和 `coordination` 单元必须调用 `mathmodel-matlab` 完成一次结构触发的能力判断，并在 `capability_decision` 中记录 Python/MATLAB 是否考虑、真实可用性、所选引擎、MATLAB 科学角色、理由和预期增益。可以因解析枚举更直接、工具箱不可用、无法形成不同算法族或 Python 已有精确证书而放弃 MATLAB，但不能静默默认 Python。
4. 实验只登记原始结果指标。核心优化/协同默认使用自然 baseline 加一条结构 challenger，第二条只在首轮不确定、仍在改善或评审明确指出缺口时增加；首解后至少一类深化。搜索占实际算力约 35% 只是 advisory。硬阻断只用于没有真实搜索、单随机种子且明显不稳定、challenger 仍快速改善或停止理由与日志冲突。系统输出 `objective_answer`、`recommended_plan`、`evidence_grade` 三层结果：endpoint、exact 指标、硬约束和可行性决定题面答案；名义答案稳定时推荐层继续指向题面赢家，只有不稳定或题面答案不可用时才可按已验证条件推荐 fallback。旧 1.2/1.3 `oracle_only` 只能以 `legacy_unverified` 查看，迁移 1.4 并完成 agreement 后才能进入正式答案。
5. 结束实验后进行一次自由科学挑战；必要时只允许一个专项追问。阶段 A 先判断核心风险在目标语义/分解还是模型/搜索；多主体、嵌套量词、聚合词、问题实体变化或分解后组合存在时，第一攻击必须针对语义并给出独立玩具反例。只有语义风险低时才优先攻击搜索和数值。其余发现分类、回退和更强路线闭合规则不变。
6. 图表在 `figures/work/` 迭代，通过 QA 后晋级 `figures/current/`，旧版进入 `figures/archive/`。首稿前每个必答问题都须在 `FIGURE_PLAN` 2.3 中把展示图决定为 required 或 waived；几何、并集/交集、名义—稳健和共享模型还须作 whole-paper 决策。正文 hero 先声明 `information_structure`，再按空间、时间/集合、网络、场、权衡或不确定性选择原型，并标注临界事件、活跃约束、边界和最终决策。普通柱形图/折线图不能成为这些结构的默认唯一主图；确实最合适时必须显式登记 override 理由。稳定性图入附录。
7. 进入论文后只维护 `PAPER_BLUEPRINT.md`、`answer-map.json`、`FIGURE_PLAN.json` 和 `PAPER_REVIEW.md` 四个主要控制文件。知识应用是 advisory；零匹配时使用通用结构模式，可检索实际采用的方法文献，禁止同题答案和现成结论。CUMCM 使用 `CUMCM_STRUCTURE_MAP` 1.2：多问共享对象并有资源/约束/聚合递进时默认 semantic，保留明确“模型假设与符号”入口；否则 classic 兜底。候选稿前运行 `python scripts/paper/audit_report_style.py <run_dir>`，把重复问答模板、内部工作流词、报账式摘要、列表堆叠、核心问缺推导/机制和主图脱离论证作为 warning 交给作者与独立盲评复核，不新增状态门。

返修分别维护 `argument_revision` 与 `render_revision`：`science` 重做科学挑战、论证和渲染，`argument` 使盲评失效，`render` 只使版式和机械 QA 失效。编译默认 `auto`，也可用 `--revision-impact` 显式声明。
8. PDF 盲评必须使用独立上下文，只接收冻结 PDF 和固定提示词。导入记录绑定当前 `argument_revision`；纯渲染重编不要求重做盲评。`CUMCM_LAYOUT_AUDIT` 仍绑定当前 `render_revision` 并直接消费盲评事实。

旧 v3.0 运行可查看和更新，运行时会在首次显式更新时记录阶段迁移。不要把 legacy 审核合同重新接入新运行。
