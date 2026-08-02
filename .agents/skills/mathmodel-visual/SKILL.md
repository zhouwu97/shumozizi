---
name: mathmodel-visual
description: 用当前真实结果探索、比较并晋级数学建模图表；适用于单图、整篇视觉节奏、机制图和 Visual Sandbox，不强制固定图种或图数。
---

# 洞察驱动图表

先从问题和 takeaway 出发，再选择图种。每个视觉想法回答：它要解释什么、读者一眼应看见什么、删除后论文失去什么。第三问答不出时不画。先读 [visual-pattern-cards.md](references/visual-pattern-cards.md)，但不要从图库名称反推图，也不要复制来源论文的数据、公式、坐标、配色或结论。

## Stage A：Visual Sandbox

用 `python scripts/figures/write_visual_ideas.py <run_dir> --input <ideas.json>` 写入轻量想法。每项只需：

```json
{
  "id": "q3-capacity-story",
  "question": "为什么峰值日决定人数？",
  "sources": ["Q3"],
  "idea": "联合展示需求峰值、活跃下界与覆盖冗余",
  "status": "sketch"
}
```

把草图放到 `figures/sandbox/<idea-id>/`。此阶段不要求 current-result binding、caption、LaTeX label、manifest、review receipt、panel mapping 或 Figure Contract。允许快速尝试普通图、机制图、示意图、合并图和拆分图；草图不得进入论文或冒充证据。

## Stage B：视觉竞争

对关键 insight 优先生成 2--4 个结构不同的候选。让 fresh reviewer 只比较：哪张最快说明机制、哪张值得正文整栏、哪张重复表格、哪张阅读路径最清楚。使用：

```powershell
python scripts/figures/visual_sandbox.py review <run_dir> <idea-id> `
  --selected-candidate <figures/sandbox/...> `
  --reviewer-context-id <fresh-id> `
  --fastest-mechanism <text> --full-width-value <text> `
  --table-redundancy <text> --rationale <text>
```

评审只选择表达方案，不证明科学正确，也不改变正式答案。

## Stage C：晋级与审计

运行 `python scripts/figures/visual_sandbox.py graduate <run_dir> <idea-id>`，冻结胜出草图为 design reference，并取得 `target_work_dir`。草图不能直接复制成正式候选；必须从 current 数据与正式 renderer 在目标目录重新生成。从这里开始才执行现有正式流程：

- 绑定 current production 来源、渲染脚本和 PNG/PDF 输出。
- 实际打开 PNG/PDF，检查文字、比例、图例、面板、黑白可读性和正文栏宽。
- 图示额外检查越界、重叠、最小字号、箭头穿字和连接点。
- 通过人工看图与机械 QA 后晋级 `figures/current/`，旧版进入 `figures/archive/`。
- 结果或脚本变化后重新生成，不允许脚本直接覆盖 current。

正式图只保留真正需要的来源、claim、script、output、paper location、caption 和接受结论。`FIGURE_PLAN` 2.4 继续兼容旧运行和后台审计，但不再要求 Author 为草图或每问手写 `argument_unit_ids`、`obligation_types`、waiver、`panel_mapping`、`expected_observation` 或 `decision_consequence`。

## 数据与角色

在 analysis 阶段按需要保存候选解、可行边界、活跃约束、Pareto 点、状态轨迹或不确定性样本。只保存最终标量时先修模型输出，不让绘图阶段猜造结构数据。

正式图可承担 `model_understanding`、`decisive_evidence`、`insight` 或 `stability`。`stability` 一律进附录。一个问题可以没有 hero、拥有多个互补图，或与相邻问题共享一张图；图数和义务数都不是质量指标。

空间、集合、网络、场、决策面、区间或不确定性结构出现时，优先选择能呈现其真实结构的原型。柱形图或折线图确实最清楚时可以使用，由人工视觉评审说明理由，不要求 Author 填写预防性 override 表单。2D/3D 都不是质量标签：精确阈值和区间优先 2D，真实空间或场结构才使用 3D。

## 整篇视觉节奏

在 PDF 层面检查模型首次出现时是否需要理解图、关键结果是否有决定性图、核心 insight 是否有视觉证据、是否连续多页只有公式和表、是否连续堆叠大图、是否有 2--3 张真正 memorable 的图。把缺口送回 Sandbox，不按“一问一图”或“图数不少于 N”补图。

知识库 visual pattern 只提供表达候选。使用前核对当前题是否真实具有所需结构数据；不满足时拒绝，不为匹配模式补造数据。所有正式图、表和结论最终只能来自本次 run 的 current/production/accepted 证据链。
