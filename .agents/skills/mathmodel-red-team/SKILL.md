---
name: mathmodel-red-team
description: 在 Capability-First v3 的实验完成后进行独立科学红队审查，或在 PDF 生成后进行独立盲审。用于发现模型、几何、约束、搜索和论证中的共模错误；必须在全新的 Codex 对话中使用，不得由求解对话角色扮演替代。
---

# 独立红队审查

此 Skill 是生产工作流中的隔离审查阶段，不是 legacy-v2 审核生命周期。它不评分、不决定奖项，也不把哈希、`exact` 名称、两份相同实现的一致性或机械 QA 当作科学正确性证明。

## 隔离规则

1. 审查必须在**全新的 Codex 对话**完成。新对话初始只接收本 Skill、审查包路径和任务说明；不得继承求解对话、其摘要、`DECISIONS.md`、`results/quality.json`、既有审查、QA 结论或预期结果。
2. 审查期间只读取对应 `review/packet/` 的冻结副本。可按需读取仓库的通用本地知识库来选择方法或攻击，但不得读取历史 run、同题旧解、公开同题答案或网络内容。
3. 审查者独立形成判断。不能为了“通过流程”默认认可候选，也不能以缺少外部标准答案为理由跳过复现、反例或挑战。
4. 对发现的 P0/P1，保存最小复现、受影响问题和恢复条件；不得替求解器直接改写模型、结果、论文或历史运行。审查报告写完即交回原任务。

## 科学红队

仅在当前 run 已进入 `scientific_review` 时执行。先由协调任务创建包：

```powershell
python scripts/review/build_review_packet.py runs/<run-id> --kind scientific
```

新建 Codex 对话时只给它生成的 `review/packet/scientific/<packet-id>/`。该包只含题面与附件、当前运行内源代码和候选原始结果；不含质量标签、决策日志、审查结论或 QA。

审查者应根据题目和风险自由选择最有信息量的攻击，而不是机械逐项打勾。通常要完成：

- 从题面独立重建目标、变量、约束、量纲和“至多/至少/并集”等语义；
- 对最危险的共同原语做清洁室推导或独立小实现，特别检查端点、退化、边界和单位；
- 构造能推翻当前结论的反例、极端输入或小规模穷举；
- 以不同参数化、不同搜索族或局部剖面挑战候选区域，区分“可行”“已搜索到足够区域”和“具有竞赛竞争力”；
- 检查 proxy、exact 和 oracle 是否共享同一数学定义，避免把共模一致性误报为验证；
- 检查下游问题是否继承了未经充分挑战的搜索区域或题意解释。

对涉及几何、优化或多实体的题，优先选择与题目相关的反例，而非只重复原求解器。高风险攻击菜单包括：有限线段与无限直线混淆、端点落入球体、烟幕/区间重叠重复计数、把“至多”误写为“恰好”、量纲不一致、数据或未来信息泄漏、proxy 与 exact 排序反转、高维联合覆盖被投影伪造、两个 oracle 共享同一判定语义，以及下游继承前题的弱搜索区域。命中任一项时，报告其是否污染候选、exact、oracle、图表和论文。

将自由报告写入 `runs/<run-id>/review/SCIENTIFIC_RED_TEAM.md`。报告至少给出独立重建、已执行攻击及证据、每个 P0/P1 的最小复现和污染范围、可支持的结论与未证明边界。只有没有未解决 P0/P1、无需全量重跑且审查者认为证据可支撑继续时，才能建议 `pass`。

求解任务收到报告后，使用实际新对话 ID 绑定结论：

```powershell
python scripts/review/import_review.py runs/<run-id> `
  --kind scientific --manifest review/packet/scientific/<packet-id>/manifest.json `
  --verdict pass --severity none --competition-strength qualified `
  --thread-id <fresh-codex-thread-id>
```

导入只记录隔离声明、冻结输入和报告哈希；它不替代报告本身。源代码、输入或结果在审查后变化会使结论失效，必须重新审查。通过后状态才可从 `scientific_review` 进入 `visualization`。图表叙事完成且冻结后才进入 `paper`；这不会让红队替视觉阶段验收美学或排版。

## PDF 盲审

仅在 PDF 已生成、当前 run 进入 `paper_review` 时执行：

```powershell
python scripts/review/build_review_packet.py runs/<run-id> --kind paper-blind
```

为此再新建一个 Codex 对话，只给 `review/packet/paper-blind/<packet-id>/`。它初始只含题面、附件、匿名 PDF 和提交材料；不得读取源码、科学审查、质量结果或 QA。

盲审依据题意和 PDF 判断：是否逐问直接回答、建模假设与结论是否自洽、推导和图表能否支撑主张、结果解释是否诚实、是否存在空洞章节、不可读图表、无证据的竞争力宣称或匿名问题。对声明为空间、求解或稳定性证据的图，要核查实际可见对象、坐标/单位、边界和论证关系；一张漂亮但不呈现这些对象的 3D 散点图不能承担模型验证。它可标出需要求解任务进一步复核的证据，但不能在看不到代码时臆造数值或数学结论。

将报告写入 `runs/<run-id>/review/PAPER_BLIND_REVIEW.md`，再由协调任务导入：

```powershell
python scripts/review/import_review.py runs/<run-id> `
  --kind paper-blind --manifest review/packet/paper-blind/<packet-id>/manifest.json `
  --verdict pass --severity none --thread-id <fresh-codex-thread-id>
```

PDF 或提交材料变更会撤销盲审。盲审通过后进入 `verify`，由 `$mathmodel-final-check` 仅做机械检查；机械 QA 和盲审都通过后才可标记 `complete`。
