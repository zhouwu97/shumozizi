---
name: mathmodel-visual
description: 用当前真实结果探索、比较并晋级数学建模图表；适用于单图、整篇视觉节奏、机制图和 Visual Sandbox。图型由数学结构和论证作用动态选择，但正式稿必须满足逐问和全篇配额硬门。
---

# 洞察驱动图表

先从问题和 takeaway 出发，再选择图种。每个视觉想法回答：它要解释什么、读者一眼应看见什么、删除后论文失去什么。第三问答不出时不画。先读 [visual-pattern-cards.md](references/visual-pattern-cards.md)，但不要从图库名称反推图，也不要复制来源论文的数据、公式、坐标、配色或结论。

## Stage A：Visual Sandbox

若已形成长篇首稿，先运行 `python scripts/paper/build_visual_requirements.py <run_dir>`。该命令从建模合同、正式答案、论文论证材料和 current 图覆盖关系生成 `paper/generated/VISUAL_REQUIREMENTS.json`，并将未覆盖项追加到 living visual opportunity pool；不得只消费实验阶段偶然留下的已有图。

对方法、流程、机制和时间过程的解释型候选，可在此基础上运行 `python scripts/figures/build_paper_image_prompts.py <run_dir>`。该命令只生成 A/B 设计 Prompt；AI 候选只能进入 Sandbox 作为设计参考，正式图必须由 current 数据的确定性 renderer 或 DrawIO 重建。

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

### 选模板前必须看预览（sci-box 母版优先）

需要真实数据图时，选图顺序固定为 sci-box 母版优先（见 `skills/sci-box/scibox-figure/SKILL.md`）：
① 母版原生模板（`use_template.py --adaptation direct`，复制原脚本只换数据入口）→
② 模板深度改造/组合 → ③ `scibox-diagram` 结构图 → ④ 本题专用高级图 → ⑤ 普通
scatter/heatmap/line → ⑥ bar。柱状/折线**不是禁止**，而是前面能表达清楚就不准偷懒。

**禁止只凭 template_id 名称选模板。** 选择前必须打开
`skills/sci-box/scibox-figure/assets/previews/` 的 preview PNG 实际看图，
回答三个问题：结构是否匹配数据？比普通图多表达了什么？换真实数据后视觉优势是否保留？
满足才用；不满足换下一张。需要结构解释图（路线/框架/流程）时直接用
`scibox-diagram`（`selected_skill: skills/sci-box/scibox-diagram`），它是**一等候选**，
不需要先试 ImageGen。

## Stage C：晋级与审计

运行 `python scripts/figures/visual_sandbox.py graduate <run_dir> <idea-id>`，冻结胜出草图为 design reference，并取得 `target_work_dir`。草图不能直接复制成正式候选；必须从 current 数据与正式 renderer 在目标目录重新生成。从这里开始才执行现有正式流程：

- 绑定 current production 来源、渲染脚本和 PNG/PDF 输出。
- 实际打开 PNG/PDF，检查文字、比例、图例、面板、黑白可读性和正文栏宽。
- 图示额外检查越界、重叠、最小字号、箭头穿字和连接点。
- 通过人工看图与机械 QA 后晋级 `figures/current/`，旧版进入 `figures/archive/`。
- 结果或脚本变化后重新生成，不允许脚本直接覆盖 current。

正式图只保留真正需要的来源、claim、script、output、paper location、caption 和接受结论。`FIGURE_PLAN` 2.4 继续兼容旧运行和后台审计，但不再要求 Author 为草图或每问手写 `argument_unit_ids`、`obligation_types`、waiver、`panel_mapping`、`expected_observation` 或 `decision_consequence`。

## Stage D：PDF 开放发现与需求对账

形成冻结 PDF 后，必须先让全新 reviewer 只读 PDF 做开放式视觉发现，再查看作者已有需求并对账。第一阶段不得提供视觉需求、figure index、机会池、源码、历史审核或作者解释，防止审核退化成“把已有条目全部处置掉”。生成盲审提示：

```powershell
python scripts/paper/visual_discovery.py prompt <run_dir> > <prompt.txt>
```

审核者从零检查数学对象、决定性证据、机制路径、约束/边界/不确定性、论文尺寸可读性和整篇视觉节奏，最多保留五个最高价值 finding。将其 JSON 记录为：

```powershell
python scripts/paper/visual_discovery.py record <run_dir> <review.json> `
  --reviewer-context-id <fresh-id>
python scripts/paper/visual_discovery.py status <run_dir>
```

只有开放发现落盘后，才允许查看 `VISUAL_REQUIREMENTS.json` 做第二阶段 reconciliation。P0/P1 的 `ADD_FIGURE`、`REVISE_FIGURE` 或 `REPLACE_FIGURE` 自动进入 living visual opportunity pool，必须由明确绑定该 finding 的 current 正式图关闭；逐需求 `DROP` 不能抵消它。`RELAYOUT` 必须提交修订 PDF 并重新开放审查。PDF 哈希或 `argument_revision` 变化后旧记录自动失效。开放发现无 finding 时，六个维度仍必须分别给出充分性理由，不能用空数组代替判断。

## 数据与角色

在 analysis 阶段按需要保存候选解、可行边界、活跃约束、Pareto 点、状态轨迹或不确定性样本。只保存最终标量时先修模型输出，不让绘图阶段猜造结构数据。

正式图可承担 `model_understanding`、`decisive_evidence`、`insight` 或 `stability`。`stability` 一律进附录。一个问题可以没有 hero、拥有多个互补图，或与相邻问题共享一张图。正式 competition-quality 论文必须满足：每个必答问题 **2–3 张** current 正文图【硬门】；四问及以上全篇 **13–18 张** current 正文图【硬门】且覆盖至少 **3 种**可审计 visual archetype【硬门】。数量门不允许用重复图、拆图、换色图或装饰图凑数；在该配额内，图型仍由数学结构和论证作用动态选择。

空间、集合、网络、场、决策面、区间或不确定性结构出现时，优先选择能呈现其真实结构的原型。柱形图或折线图确实最清楚时可以使用，由人工视觉评审说明理由，不要求 Author 填写预防性 override 表单。2D/3D 都不是质量标签：精确阈值和区间优先 2D，真实空间或场结构才使用 3D。

## 整篇视觉节奏

在 PDF 层面检查模型首次出现时是否需要理解图、关键结果是否有决定性图、核心 insight 是否有视觉证据、是否连续多页只有公式和表、是否连续堆叠大图。Hero / memorable figures 可优先保留 2--3 张；argument-supporting figures 按数学对象、机制、比较和边界的实际论证需要增加。把缺口送回 Sandbox，按逐问 2–3 张和全篇 13–18 张的配额规划补图，不按“一问一图”机械均摊，也不用装饰图或拆图凑数。

知识库 visual pattern 只提供表达候选。使用前核对当前题是否真实具有所需结构数据；不满足时拒绝，不为匹配模式补造数据。所有正式图、表和结论最终只能来自本次 run 的 current/production/accepted 证据链。

