# Competition-First v3.1 工作流

## 阶段与恢复

```text
analysis -> experiment -> paper -> paper_review -> verify -> complete
```

进入 `experiment` 前，仅当 `analysis/objective-ambiguities.json` 表明存在未解决的高影响歧义时，才要求目标语义审查。进入 `paper` 前必须有每个必答问题的 current production 答案、没有已知负面证据、有效模板和一次有效科学挑战。进入 `verify` 前必须有 PDF、有效 PDF 盲评或明确跳过原因、没有 P0/P1。进入 `complete` 前必须通过机械 QA，当前结果、图表和 PDF 都没有漂移。

旧 v3.0 状态按内存映射读取，更新时生成 `state/migrations.json`，不改写历史审核产物。

## 分析

先写 `analysis/ROUTE_COMPETITION.md`：问题结构、baseline、每条候选路线的数学差异、最低成本 probe、主路线、fallback 和切换条件。至少一个 baseline 与一个数学结构不同的竞争或反证路线是硬要求；第三条路线只在有高潜力方向时增加。

再写 `analysis/NEXT_EXPERIMENTS.md`。每个实验必须说明要改变的决定、成本、成功/失败后的动作和优先级。不能改变路线、模型、主要结论、机制、贡献或反证当前结果的实验不应占用比赛预算。

## 实验与洞察

所有生产实验通过执行器登记。`method_facts.json` 自动推断随机、proxy、时间切分、连续几何、启发式和下游依赖等事实，无法判断时写 `unknown`，只产生针对性建议。

在写论文前维护 `analysis/INSIGHTS.md`。每项洞察写观察、真实证据、可能机制、验证、论文价值和不能推出的边界。没有稳定规律时明确写出，不得为了文件制造阈值、因果或反直觉结论。

## 图表与论文

图表默认写入 `figures/current/`，每张图登记 `source`、`question`、`takeaway` 和可选 `limitations`。删除图后论文不会失去信息时，删除该图。不得默认要求每问图、3D、收敛图、多种子图、敏感性图或重复 evidence/publication 图。

论文先写 `paper/STORYBOARD.md` 和至多三项的 `paper/CONTRIBUTION_BRIEF.md`。这两者是警告项。硬门只有：每个必答问题存在 `answer_map` 直接答案映射、引用 current 生产结果、引用的图有效、没有负面证据、模板和正文可编译、源码策略符合比赛要求。`paper/generated/argument_map.json` 自动生成，禁止要求人工维护哈希地图。摘要最后写。

## 审查与重跑

科学挑战只进行一次自由攻击，报告六项固定问题。只有 P0/P1、需要确认的决定性实验或无法判断是否继续时才建立一个 `FOCUSED_FOLLOWUP.md`。PDF 盲评采用相对评价，不能只写 pass/fail。机械 QA 只检查交付，不重定义数学正确性。

正文小改：重新编译和机械 QA。解释、图表、主要结论改动：重新编译、PDF 盲评和机械 QA。代码、数据、目标或主要结果改动：回到实验、科学挑战、PDF 盲评和机械 QA。
