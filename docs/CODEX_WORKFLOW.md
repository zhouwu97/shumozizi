# Competition-First v3.2 工作流

## 阶段与恢复

```text
analysis -> experiment -> paper -> paper_review -> verify -> complete
```

进入 `experiment` 前，v3.2 必须先完成两次仅题面的 fresh-thread 重建和 `analysis/MODELING_UNITS.json`；仅当 `analysis/objective-ambiguities.json` 表明存在未解决的高影响歧义时，才要求目标语义审查。进入 `paper` 前必须有每个必答问题的 current production 答案、已回填的攻击/深化/条件验证证据、没有已知负面证据、无回退 LaTeX 模板和一次有效科学挑战。进入 `verify` 前必须有 PDF、有效 PDF 盲评或明确跳过原因、没有 P0/P1；跳过盲评只能继续机械 QA，状态为 `unreviewed`。进入 `complete` 前必须重新验证科学挑战、通过真实 PDF 盲评和机械 QA，且当前结果、图表和 PDF 都没有漂移。

旧 v3.0 状态按内存映射读取，更新时生成 `state/migrations.json`，不改写历史审核产物。

## 分析

v3.2 先用两个只绑定 `problem/` 的 fresh thread 重建题意，再只基于题面冻结 `analysis/BASELINE_FREEZE.json`。冻结文件会绑定当前 `problem/` 哈希，并声明 `award_expert_library_used=false`。随后可按需路由 CUMCM A/B 获奖论文的 3--6 张 structure-only 卡，写入 `analysis/AWARD_EXPERT_ROUTE.json` 并用 `AWARD_EXPERT_ROUTE_AUDIT.json` 复验隔离边界；它们不参与状态跳转，也不能成为模型、参数、结果、图表、代码、引用或 claim evidence。最后才写 `analysis/MODELING_UNITS.json`。每个 `compare` 单元冻结 baseline、两条数学结构不同的候选路线、统一 exact 目标和实际预算、fallback、首批攻击、至少两类首解后深化、停止理由白名单及条件验证；`oracle_only` 只用于明确需要独立 oracle 的题型。`ROUTE_COMPETITION.md` 仍用于人类可读的路线叙事。

专家库运行时只读取 `knowledge/award-experts/library.json`：21 张跨题结构卡与 15 个规则组合角色，覆盖 2012--2025 年官方展示的 A/B 论文。来源 URL、页码、论文 ID 和哈希只留在离线 `provenance.json`。路由按 A/B、当前阶段和受限 `topic_key` 选择少量结构建议；同题资料只能在 baseline 冻结后进入 answer-filter，不能改变当前题模型、参数、结果或论文结构。审计的 `access_monitoring.enabled=false` 仅说明序列化输出检查的边界，不宣称操作系统级文件访问监控。

再写 `analysis/NEXT_EXPERIMENTS.md`。每个实验必须说明要改变的决定、成本、成功/失败后的动作和优先级。不能改变路线、模型、主要结论、机制、贡献或反证当前结果的实验不应占用比赛预算。

## 实验与洞察

所有生产实验通过执行器登记。`method_facts.json` 以显式登记为最高优先级，并联合结果指标、执行命令和源码静态提示推断随机、proxy、时间切分、连续/离散近似、启发式和下游依赖等事实；未知值会成为查漏项，不能静默跳过中央风险。

在写论文前维护 `analysis/INSIGHTS.md`。每项洞察写观察、真实证据、可能机制、验证、论文价值和不能推出的边界。没有稳定规律时明确写出，不得为了文件制造阈值、因果或反直觉结论。

## 图表与论文

图表默认写入 `figures/current/`，每张图登记 `source`、`question`、`takeaway` 和可选 `limitations`。删除图后论文不会失去信息时，删除该图。不得默认要求每问图、3D、收敛图、多种子图、敏感性图或重复 evidence/publication 图。

先用 `paper/STORYBOARD.md` 形成结构蓝图；再统一共享符号、假设和数学对象，并逐问成文；最后把结论逐项与 `answer_map`、结果、图表和限制对齐后严格返修。三者按草稿和证据状态往返，不按 R1--R5 固定轮次推进，也不把文档填写变成门禁。获奖论文专家卡可按草稿状态提示研究主线、模型推导、算法说明、结果闭环、图表任务、摘要、严格返修和 LaTeX 版式，但不能提供当前事实。`CONTRIBUTION_BRIEF.md` 最多三项贡献且为警告项。硬门只有：每个必答问题存在 `answer_map` 直接答案映射、引用 current 生产结果、引用的图有效、没有负面证据、v3.2 的无回退 LaTeX 模板和正文可编译、源码策略符合比赛要求。`paper/generated/argument_map.json` 自动生成，禁止要求人工维护哈希地图。摘要最后写。

## 审查与重跑

科学挑战只进行一次自由攻击，报告六项固定问题。只有 P0/P1、需要确认的决定性实验或无法判断是否继续时才建立一个 `FOCUSED_FOLLOWUP.md`。PDF 盲评采用相对评价，不能只写 pass/fail。

最终 PDF 盲评必须由 `create_thread` 创建全新独立顶层对话，不得使用 fork、子 Agent、续聊或写作对话。先构建 `paper-blind` 冻结包，再运行 `scripts/review/show_paper_blind_prompt.py <run-dir> --manifest <manifest> --json`；把返回的提示词原样交给新对话。新对话只读取冻结 PDF，不读取题面、源码、实验、作者说明或既有审核意见。主流程等待审核完成，将报告和新 `thread_id` 写入回执；提示词哈希不匹配时拒绝导入。机械 QA 只检查交付，不重定义数学正确性。

正文小改：重新编译和机械 QA。解释、图表、主要结论改动：重新编译、PDF 盲评和机械 QA。代码、数据、目标或主要结果改动：回到实验、科学挑战、PDF 盲评和机械 QA。
