# 高级图与竞赛论文表现改造计划

## 1. 目标与结论

本计划的目标不是机械复制参考论文的图数、配色或三维效果，而是在保留本项目正确性优势的前提下，做到参考稿已经具备的三项核心体验：

1. 评委在前三至五页就能看到题目对象、直接答案和一张可记住的主图。
2. 每个关键结论附近都有对应的模型原生图，而不是只有公式、表格和两张通用统计图。
3. 求解结束后能从已冻结的结构化数据快速批量生成正式图，不在论文阶段重新猜数据或临时拼图。

本次改造必须同时满足两条底线：

- 高级感来自模型对象、机制、边界和视觉节奏，不来自无意义的 3D、渐变、装饰流程图或图数堆积。
- 所有正式图只能由本次运行的 current production 数据和正式 renderer 生成；参考稿只能提供表达启发，不能提供当前事实、数字、公式、代码或结论。

针对当前华数杯 A 题，预期形成约 8--10 张正文图和 2--3 张附录验证图。这是基于当前论证对象推导出的实施预估，不是工作流的固定图数门槛；若某张图不能改变读者对模型、结果、机制或边界的理解，就不应保留。

## 2. 项目与对照入口

### 2.1 当前项目

- [项目根目录](../README.md)
- [Competition-First v3.4 项目约定](../AGENTS.md)
- [既有提速、正确性和论文修复计划](SPEED_CORRECTNESS_PAPER_REPAIR_PLAN.md)
- [模型原生视觉 Skill](../.agents/skills/mathmodel-visual/SKILL.md)
- [论文 Skill](../.agents/skills/mathmodel-paper/SKILL.md)
- [视觉模式卡](../.agents/skills/mathmodel-visual/references/visual-pattern-cards.md)

### 2.2 当前华数杯 A 题运行

- [运行目录](../runs/huashu-2026-a-v32-20260809-001)
- [长篇首稿](../runs/huashu-2026-a-v32-20260809-001/paper/longform-draft.pdf)
- [建模单元](../runs/huashu-2026-a-v32-20260809-001/analysis/MODELING_UNITS.json)
- [当前视觉需求](../runs/huashu-2026-a-v32-20260809-001/paper/generated/VISUAL_REQUIREMENTS.json)
- [当前正式图目录](../runs/huashu-2026-a-v32-20260809-001/figures/current)
- [当前论文绘图脚本](../runs/huashu-2026-a-v32-20260809-001/code/render_paper_figures.py)

### 2.3 参考工作区

- [参考论文 ACM2600001.pdf](<C:/Users/haha/AppData/Roaming/@mathmodel/desktop/workspace/A题_华数杯2026/ACM2600001.pdf>)
- [参考工作区](<C:/Users/haha/AppData/Roaming/@mathmodel/desktop/workspace/A题_华数杯2026>)
- [参考绘图模块 1](<C:/Users/haha/AppData/Roaming/@mathmodel/desktop/workspace/A题_华数杯2026/code/figs_part1.py>)
- [参考绘图模块 2](<C:/Users/haha/AppData/Roaming/@mathmodel/desktop/workspace/A题_华数杯2026/code/figs_part2.py>)
- [参考绘图模块 3](<C:/Users/haha/AppData/Roaming/@mathmodel/desktop/workspace/A题_华数杯2026/code/figs_part3.py>)
- [参考绘图模块 4](<C:/Users/haha/AppData/Roaming/@mathmodel/desktop/workspace/A题_华数杯2026/code/figs_part4.py>)
- [参考统一图形样式](<C:/Users/haha/AppData/Roaming/@mathmodel/desktop/workspace/A题_华数杯2026/code/figstyle.py>)
- [参考图输出目录](<C:/Users/haha/AppData/Roaming/@mathmodel/desktop/workspace/A题_华数杯2026/results/figs>)

## 3. 当前差距的可验证事实

### 3.1 参考稿为什么显得“高级”

参考 PDF 共 45 页，其中真正建立论文视觉印象的是前约 20 页；后约 25 页主要是代码附录，不应照搬。前 20 页至少包含 17 个编号图，覆盖以下对象：

- 统一技术路线流程图。
- 题目真实三维几何与边界示意。
- Q1 的 3D 粒子结构、接触网络和统计比较。
- Q2 的概率对比图与 Wilson 区间森林图。
- Q3 的渗流阈值曲线和 Logistic 拟合。
- Q4 的热力图、等高线、成本前沿、三维导电通路、收敛带、三维代理面和校准图。

它的四个 `figs_part*.py` 模块约 965 行，加上统一 `figstyle.py`，共产出 18 张 PNG。高级感的主要来源不是单张图有多复杂，而是：

1. 模型对象可见。读者能看见圆柱、接触边、贯通路径、可行区和阈值，而不是只看最终数字。
2. 图形结构随问题变化。空间问题用 3D 与网络，概率问题用区间，优化问题用热图、等高线和前沿。
3. 页面有节奏。前 20 页几乎每 1--2 页出现一次图或表，推导、结果和解释交替出现。
4. 关键结果有视觉强调。阈值线、最终点、边界区、关键路径和不确定性在图上直接标出。

参考稿仍有明显缺陷：部分字体偏小、中文 glyph 不完整、三维图遮挡、代码附录过长，而且其周期边界和 Q4 定义域口径不能直接作为当前论文的科学依据。因此只学习表达结构，不学习其结论。

### 3.2 当前稿的现状

当前长篇首稿 13 页，正文只有两张正式图：

- `q3_threshold_evidence`：Wilson 下限相对 90% 的裕量图。
- `q4_cost_frontier`：成本--导通概率散点图。

这两张图干净、可读、结论明确，但都属于常规二维统计图，无法建立模型对象的空间直觉，也不能解释周期身份、接触网络、导电骨架、整数可行域和严格正定义域边界。

当前 `VISUAL_REQUIREMENTS.json` 有 28 项需求，仅 2 项被 current 图覆盖，26 项处于 open。更严重的是，其中大量需求来自整段 LaTeX、答案表、图环境或长段讨论，被错误地当成独立视觉需求。这说明当前系统不是“需求太少”，而是“需求质量和归并逻辑失控”。

### 3.3 已经完成、无需重做的基础

当前脏工作区已经包含以下有效基础，后续必须在其上增量修改：

- 新 v3.2 运行默认使用 exploration 与风险自适应 production 门禁。
- production 前可复验风险包，探索结果不会直接成为正式答案。
- Visual Sandbox 的 Hero 图已要求至少两个候选，并要求候选具有至少两种不同 `visual_structure`。
- 正式图已有 current/work/archive、结果绑定、哈希复验和失效规则。
- v3.4 已有 Research Package、Author Pass、长篇首稿、视觉需求池和独立冷读链。

这些机制解决了“什么时候进入正式结果链”和“草图不能直接冒充正式图”的一部分问题，但尚未解决“应该画什么”和“如何让模型对象可见”。

## 4. 谁的哪里好，最终如何组合

| 能力 | 参考工作区做得好 | 当前项目做得好 | 最终采用方式 |
|---|---|---|---|
| 求解正确性 | 快速给出完整四问结果 | 能识别周期身份、平端圆柱伪边和 Q4 严格正域 | 科学口径完全采用当前项目 |
| 视觉覆盖 | 18 张图覆盖几何、网络、概率、优化和验证 | 正式图必须绑定 current production | 学其覆盖结构，不迁移任何数据或结论 |
| Q1 表达 | 3D 结构和接触网络直接可见 | 当前几何 oracle 更严格，能区分胶囊与平端实体 | 用当前 oracle 数据重画 3D、网络和导电骨架 |
| Q2/Q3 表达 | 概率图、森林图、渗流曲线相互补充 | 当前 Wilson 区间与独立加密证据更严谨 | 保留当前区间口径，增加转变曲线和重复实验编码 |
| Q4 表达 | 热力图、等高线、前沿、3D 路径形成视觉高潮 | 当前严格正域与零允许敏感性区分更正确 | 用整数格点可行域和成本等高线突出正式域边界 |
| 页面节奏 | 前 20 页图文交替，读者持续看到对象与结果 | 当前稿答案表和推导紧凑 | 保留紧凑性，增加模型原生图，不复制代码页膨胀 |
| 工程速度 | 绘图脚本按问题拆分，求解后批量出图 | 当前结果链和正式晋级更可追溯 | 求解冻结后并行渲染各问正式图 |
| 评审边界 | 视觉表现强 | 能把条件答案、敏感性和正式答案分开 | 图中直接编码边界，不用图形升级科学主张 |

## 5. 根因分析

### 根因 1：视觉合同按 `unit_kind` 粗分，遗漏空间 exact oracle

`src/shumozizi/simple/modeling_units.py` 中 `_STRUCTURED_VISUAL_OUTPUT_UNIT_KINDS` 目前只包含 `optimization`、`data_modeling`、`simulation` 和 `coordination`，不包含 `exact_oracle`。因此 Q1 这种空间几何核心问题可以合法地没有任何结构化视觉输出，绘图阶段只剩最终导通判定，无法恢复粒子、接触边和贯通路径。

### 根因 2：路由按通用 purpose，不按数学对象

`src/shumozizi/paper/visual_requirements.py` 目前把 `model_understanding` 默认路由到通用结构图或 argument map，把 `mechanism` 路由到时间余量图，把 `boundary` 路由到不确定性带。它无法区分空间几何、周期单元、接触网络、概率转变、整数格点和可行域，所以会把 Q2/Q3 概率曲线推荐成流程图，把 Q1 空间对象推荐成通用示意图。

### 根因 3：论文抽取粒度太细，噪声被放大成 28 个需求

长篇正文中的答案表、图环境、完整段落和反复出现的边界说明被逐项转换为需求。当前系统缺少以下归并规则：

- 同一数学对象、同一论证角色、同一结果集合的需求合并。
- 已有图环境和答案表不再反向生成新图需求。
- 长 LaTeX、表格 token、引用标签和重复结论先清洗再入池。
- 一个图可以同时覆盖模型、机制和边界，不为每段文字生成一张图。

### 根因 4：AI 图候选选择只接受 `model_understanding`

`src/shumozizi/simple/paper_image_prompts.py` 的 `_candidate_score` 对非 `model_understanding` 直接返回低分；`_selected_hero_ids` 每问最多选择一个候选。因此真正需要 Hero 的决定性证据、活跃约束、可行域和边界不会进入候选竞争，最后容易只生成通用流程图。

### 根因 5：Sandbox 评审标准只问“快不快”，没有检查“模型是否可见”

当前评审记录只有最快机制、整栏价值、表格冗余和总理由，缺少：

- 核心模型对象是否真实可见。
- 是否针对当前题而非换标题即可复用。
- 机制、路径、活跃约束或可行域是否可见。
- 不确定性和结论边界是否可见。
- 在论文实际栏宽下的信息密度和文字可读性。

### 根因 6：正式 renderer 类型不足

当前正式绘图脚本只实现 Q3 裕量图和 Q4 成本散点。工作流虽有模板注册表，却没有足够的模型原生 renderer 处理：

- 周期单元内有限圆柱和回绕身份。
- 接触网络、左右电极和导电骨架。
- 平端实体距离与胶囊候选边差异。
- 整数格点可行域、活跃边界和成本等高线。
- 共同随机数下的邻近候选配对差异。

### 根因 7：视觉闭环发生得太晚

长篇首稿编译时只生成 open 需求，不阻断；最终 Candidate 才要求全部覆盖或实质 DROP。这样会在论文已经压缩成型后集中返工。视觉工作需要在首稿之后、正式 Candidate 之前有一次明确的 paper 内部 checkpoint，但不能恢复成 Author 动笔前的繁重清单。

### 根因 8：缺少匿名视觉竞争力评测

现有机械 QA 能发现路径、哈希、字号、裁切和输出缺失，但不能证明图对评委更有效。必须增加匿名 pairwise：同一科学结果下比较旧版与新版 PDF，评审只看三分钟可读性、主图记忆、模型对象可见性和边界表达。

## 6. 目标架构

```mermaid
flowchart LR
    A["题面与建模单元"] --> B["数学对象与论证角色标签"]
    B --> C["实验保存结构化视觉数据"]
    C --> D["对象感知的视觉需求归并"]
    D --> E["Visual Sandbox 生成结构不同的候选"]
    E --> F["Fresh reviewer 按模型可见性评选"]
    F --> G["current 数据正式 renderer 重绘"]
    G --> H["PNG/PDF 与来源绑定 QA"]
    H --> I["正文编排与图后论证"]
    I --> J["独立冷读与匿名 pairwise"]
    J --> K["Candidate PDF"]
```

关键变化是把“图是什么”提前到建模与实验输出合同，把“图画得怎样”留到 Sandbox，把“图是否正确”留给 current 数据绑定和科学审查，把“图是否有效”留给 PDF 冷读与匿名比较。四类判断不能混为一个分数。

## 7. 数据合同改造

### 7.1 为每个视觉输出增加数学对象标签

在保持 MODELING_UNITS 1.4 兼容的前提下，为 `visual_outputs[]` 增加以下字段；旧运行可缺省，新 v3.4 运行按题型要求：

```json
{
  "visual_question": "周期回绕身份如何改变接触图与贯通路径？",
  "takeaway": "回绕片段必须合并为同一物理粒子，否则会产生伪接触边。",
  "mathematical_object": "periodic_contact_network",
  "argument_role": "model_understanding",
  "candidate_archetypes": [
    "periodic_spatial_contact_scene",
    "network_flow_bottleneck"
  ],
  "required_visibility": [
    "periodic_boundary",
    "physical_particle_identity",
    "contact_edges",
    "electrodes",
    "conductive_backbone"
  ],
  "required_data": [
    "particles",
    "wrapped_fragments",
    "identity_map",
    "contact_edges",
    "electrode_edges",
    "conductive_path"
  ],
  "output_path": "results/raw/q1_periodic_contact_scene.json"
}
```

### 7.2 数学对象枚举

首批支持以下对象，不把具体题目名写进通用 schema：

- `spatial_geometry`
- `periodic_spatial_geometry`
- `contact_network`
- `periodic_contact_network`
- `geometric_oracle_comparison`
- `probability_transition`
- `uncertainty_threshold`
- `integer_feasible_region`
- `pareto_cost_reliability`
- `search_stability`
- `implementation_agreement`
- `shared_model_pipeline`

### 7.3 按对象触发结构化输出

不再只靠 `unit_kind` 判断是否需要 visual outputs。新规则为：

- 空间、集合、网络、场、轨迹、决策面、可行域、区间和不确定性对象，至少保存一项结构化视觉输出。
- `exact_oracle` 若涉及上述对象，必须纳入结构化输出检查。
- 仅解析标量、无结构可视化价值的 exact oracle 可以给出具体 waiver，不强迫画图。
- 输出必须位于 `results/raw/`，保持 JSON、字段复验和 production 绑定。

### 7.4 防止只保存最终标量

题型最低字段检查应按对象执行：

| 数学对象 | 最低结构字段 |
|---|---|
| 周期空间几何 | 对象坐标、边界、回绕片段、身份映射 |
| 接触网络 | 节点、边、电极、贯通路径或割集 |
| 概率转变 | 横轴取值、成功次数、样本量、区间、阈值 |
| 整数可行域 | 候选格点、可行标记、约束余量、成本、选中点 |
| Pareto 前沿 | 候选点、支配关系、正式域标记、敏感性域标记 |
| 稳定性 | 种子、预算或样本量、分位带、停止点 |

## 8. 对象感知的视觉路由

### 8.1 路由键

视觉 archetype 由以下组合决定：

```text
mathematical_object + argument_role + required_visibility + available_fields
```

`purpose` 只决定图在论证中的角色，不能单独决定图种。

### 8.2 首批路由矩阵

| 数学对象 | 论证角色 | 首选 archetype | 禁止的默认替代 |
|---|---|---|---|
| periodic_spatial_geometry | model_understanding | 3D 周期单元 + 正交剖面 | 通用流程图 |
| periodic_contact_network | decisive_evidence | 空间结构 + 接触网络 + 导电骨架三联图 | 单个导通/不导通柱形图 |
| geometric_oracle_comparison | boundary | 端部局部放大 + 被删除伪边对比 | 纯误差条 |
| probability_transition | decisive_evidence | 概率曲线 + Wilson 区间 + 阈值带 | 仅 Logistic 光滑曲线 |
| uncertainty_threshold | boundary | 区间下限裕量或阈值带 | 仅均值折线 |
| integer_feasible_region | decisive_evidence | 整数格点可行域 + 活跃边界 + 成本等高线 | 只列候选表 |
| pareto_cost_reliability | tradeoff | 正式域/敏感性域分层的前沿图 | 混在一起的散点图 |
| search_stability | stability | 多种子包络或样本量收敛带 | 单次 best 曲线 |

### 8.3 需求归并规则

`VISUAL_REQUIREMENTS` 生成器改为先抽取、再清洗、再归并：

1. 删除 LaTeX 环境外壳、引用标签、表格 token、已有图环境和过长原文。
2. 优先消费显式 `visual_outputs`，正文抽取只补充遗漏，不覆盖事前合同。
3. 以 `(question_id, mathematical_object, argument_role, source_result_ids)` 为主键归并。
4. 多段文字指向同一对象时合成一个短 `takeaway` 和一个 `visual_question`。
5. 一张图允许覆盖多个 requirement digest，但必须逐项声明覆盖关系。
6. 已有 current 图只要对象、角色、结果绑定和 digest 一致，即视为覆盖；不能靠复制文件伪升级。

验收不使用固定需求数量，而检查：无 LaTeX 噪声、无重复对象、每项需求都能明确回答“删除后论文失去什么”。

## 9. Visual Sandbox 改造

### 9.1 候选生成

每个 Hero insight 生成 2--4 个结构不同的候选，不是同一图换颜色：

- 结构 A：单一主视图，强调空间对象或可行域。
- 结构 B：2--3 面板证据链，强调对象到结论的因果阅读顺序。
- 结构 C：主视图 + 局部放大或剖面，强调临界边界。
- 结构 D：若有必要，用网络或决策面替代三维空间表达。

Supporting 图允许只有一个候选，但若承担正文整栏或决定性证据，也必须进入结构竞争。

### 9.2 候选评分字段

扩展 `visual_competition` 记录：

- `model_object_visibility`
- `domain_specificity`
- `mechanism_or_path_visibility`
- `constraint_or_boundary_visibility`
- `uncertainty_visibility`
- `paper_size_legibility`
- `information_density`
- `table_redundancy`
- `reading_order`
- `known_risks`

Fresh reviewer 只选择表达方案，不判断科学结论。任一候选如果换掉标题即可用于无关题目，`domain_specificity` 必须判低。

### 9.3 禁止 copy-only 晋级

Graduate 后只冻结 design reference。正式晋级必须满足：

- renderer 输入绑定 current production 结果。
- work 输出由 renderer 新生成。
- 正式输出哈希不能与 Sandbox 设计参考完全相同。
- promotion receipt 记录 renderer、输入哈希、输出哈希和覆盖需求。
- 若设计参考本身就是确定性 renderer 的预览，必须记录同源脚本与不同的正式数据绑定，不能仅复制文件。

## 10. 正式 renderer 库

### 10.1 组件化而非按题复制

在 `src/shumozizi/figures/` 或现有 figure template 层增加可复用 renderer 组件：

- `render_periodic_spatial_scene`
- `render_contact_network_backbone`
- `render_geometric_oracle_comparison`
- `render_probability_threshold_curve`
- `render_integer_feasible_region`
- `render_cost_reliability_frontier`
- `render_convergence_envelope`
- `render_implementation_agreement`

运行目录中的 `render_paper_figures.py` 只负责读取本题 JSON、组合面板、写入标题和注释，不重复底层样式和 QA 逻辑。

### 10.2 统一样式

建立一套安静、竞赛论文风格的多色系统：

- 正式答案：深青或深绿。
- 不可行/失败：暖红。
- 阈值和活跃边界：金色或黑色虚线。
- 敏感性/域外结果：灰色或叉形，不与正式答案同权重。
- 网络背景边：浅灰；导电骨架：高对比色。
- 3D 对象使用低透明度表面，关键边和路径保持实色。

颜色只作一层编码，必须同时使用线型、标记或区域边界，保证灰度打印可辨。

### 10.3 输出标准

- 同时输出 PNG 和 PDF。
- 正文宽图按 0.85--0.98 `\textwidth` 设计，单栏图按实际栏宽设计。
- 最终 PDF 100% A4 视图下最小有效文字不低于 8 pt。
- 3D 图必须有 2D 剖面、投影或局部放大帮助精确读取。
- 图题不复述图内标题；图内标题尽量短，复杂解释放图注和正文。
- 所有单位、阈值、正式域和敏感性域必须明确。

## 11. 当前 A 题的逐图方案

### 图 1：共享模型路线图

- 角色：`model_understanding`，Supporting。
- 对象：物理粒子 -> 周期身份恢复 -> 平端实体接触 -> 接触图 -> 导通事件 -> 概率 -> 阈值/成本。
- 价值：让四问共享同一原子事件的关系在前五页可见。
- 边界：只解释模型结构，不作为数值证据。
- 位置：问题分析或统一模型章节开头。

### 图 2：Q1 周期微结构、接触网络与导电骨架三联 Hero

- 面板 A：周期胞元内真实有限圆柱，显示原始片段与回绕片段身份。
- 面板 B：相同构型的接触网络，区分电极、普通接触和同粒子身份边。
- 面板 C：只保留左右贯通的导电骨架，突出真正决定导通的路径。
- 价值：这是当前论文最缺的主图，直接展示模型对象与判定机制。
- 数据：Q1 当前 production 的粒子坐标、identity map、接触边、导电路径。
- 位置：统一几何模型首次定义后，建议进入前五页。

### 图 3：Q1 周期身份与平端几何反例

- 左侧：一个跨边界粒子的片段合并示意，显示错误拆分会怎样改变网络。
- 右侧：胶囊候选边与平端实体距离的局部剖面，标出被删除伪边和最小裕量。
- 价值：解释为什么参考稿的简单中心线/片段口径不足，以及当前结论为什么更可靠。
- 位置：Q1 几何 oracle 或验证段。

### 图 4：Q2 给定配比的导通概率与区间

- 横轴：A 体积分数或对应粒子数。
- 纵轴：导通概率。
- 显示点估计、Wilson 区间、90% 阈值和样本量。
- 若四点全部饱和为 1，避免用空洞柱形图；使用紧凑森林图并在旁边说明饱和区。
- 价值：直接回答 Q2，并说明结论为何远离临界边界。

### 图 5：Q3 概率转变与 8 根阈值 Hero

- 横轴：A 粒子数 6--11。
- 纵轴：导通概率。
- 显示 Wilson 区间、90% 阈值、初始批次与独立加密批次。
- 8 根使用不同标记，7 根和 8 根之间的首次越过区域用浅色带强调。
- 可在右上角加入小面板显示 Wilson 下限相对 90% 的裕量，复用现有图的优点。
- 价值：同时回答“阈值在哪里”和“为什么 8 根证据足够”。

### 图 6：Q3 阈值换算与离散性

- 将整数粒子数与体积分数映射并列，突出 8 根对应的原始比例和按题意保留小数后的答案。
- 仅在文字难以解释离散跳跃时保留；否则与图 5 合并，避免重复。

### 图 7：Q4 整数可行域、成本等高线与活跃边界 Hero

- 横轴：`n_A`，纵轴：`n_B`。
- 每个整数格点显示可行/不可行或概率裕量。
- 叠加成本等高线、90% 可行边界、最低成本可行点 `1A+50B`。
- 严格正域 `n_A>=1,n_B>=1` 使用清晰边界；零允许域单独用灰区或边缘带表示。
- 价值：评委一眼看到为什么 `1A+50B` 是正式域内最低成本，而不只是散点排名。

### 图 8：Q4 临界前沿与零允许敏感性

- 保留现有成本--可靠性图的区间表达。
- 将 `1A+49B`、`1A+50B`、纯 A baseline 和 `0A+57B` 分层编码。
- 正式域与敏感性域在图例和背景上明确分开。
- 价值：显示临界反事实和定义域改变后的策略后果。

### 图 9：Q4 最优构型的导电骨架

- 从 `1A+50B` 的代表性成功样本中选择一个有登记 sample id 的构型。
- 显示 A、B 粒子、接触边和左右贯通骨架。
- 图注明确它是代表性机制案例，不是概率或最优性的单独证明。
- 若正式 production 未保存代表性样本，不在绘图阶段伪造；先增加结构化输出并重跑最小必要实验。

### 图 10：实现一致性与几何验证总览

- 2--3 个紧凑面板：Python/MATLAB 分类一致、胶囊/平端差异、临界点复算。
- 角色：`insight` 或 `decisive_evidence`，视是否直接支持主结论决定正文或附录。
- 不使用“全绿检查表”冒充科学竞争力；必须展示实际差异或数值一致性。

### 附录图 A：Monte Carlo 收敛与样本量

- 多种子或分位包络，不画单次收敛线。
- 标出停止样本量和阈值附近的区间收缩。

### 附录图 B：随机种子与临界稳定性

- 展示 Q3 的阈值位置、Q4 的前沿排序在多个随机流下是否稳定。

### 附录图 C：正式实现与独立 oracle 对照

- 展示分类、距离或概率差异，不用品牌名称代替独立性。

## 12. 论文页面重排

参考稿的前 20 页视觉节奏值得学习，但 45 页和长代码附录不值得复制。当前稿从 13 页扩展后，页数由真实论证决定，预计会自然落在约 18--24 页，不把该区间设为硬门。

建议阅读顺序：

| 页面区域 | 主要内容 | 视觉任务 |
|---|---|---|
| 第 1 页 | 摘要、四问关键数值、正式域边界 | 不放装饰图 |
| 第 2 页 | 直接答案表、问题递进和共享对象 | 图 1 紧凑路线图 |
| 第 3--5 页 | 数据、周期几何、统一接触图 | 图 2 Hero，图 3 Supporting |
| 第 6--8 页 | Q1 结果与 Q2 概率估计 | 图 4，必要表格 |
| 第 9--11 页 | Q3 临界搜索、独立加密和换算 | 图 5 Hero，图 6 可选 |
| 第 12--16 页 | Q4 可行域、前沿、敏感性和机制 | 图 7 Hero，图 8、图 9 |
| 第 17--19 页 | 几何/实现验证、讨论、局限 | 图 10，近端验证 |
| 文后 | 参考文献、核心伪代码、稳定性 | 附录图 A--C |

排版规则：

- 关键图之后必须有“观察 -> 机制 -> 决策后果”三句闭环。
- 不连续两页只放公式和表；也不连续堆两页大图而没有论证。
- 共享几何和概率判据只推导一次，各问只说明新增实体、约束和答案。
- 现有两张图保留其有效编码，但按新证据链决定合并、重绘或降为 Supporting。
- 完整代码走附件，正文只保留必要伪代码和最关键判断，避免参考稿后 25 页代码造成的虚假厚度。

## 13. 工程实施阶段

### 阶段 0：冻结当前基线

优先级：P0。预计 0.5 天。

动作：

1. 等当前任务完成或到达明确安全 checkpoint，不给活动任务发送消息。
2. 记录当前 13 页 PDF、两张 current 图、28/2/26 视觉需求统计和生成时间。
3. 保存当前图与参考稿的匿名 pairwise 基线包。
4. 不修改 production 结果，只做哈希和只读快照。

完成定义：后续可以证明视觉提升来自工作流改造，而不是更换科学答案。

### 阶段 1：补齐对象与结构化输出合同

优先级：P0。预计 1 天。

修改：

- `src/shumozizi/simple/modeling_units.py`
- 相关 schema 与测试夹具
- `src/shumozizi/simple/visual_requirements.py`

测试先行：

- 空间 `exact_oracle` 无 visual output 时拒绝进入实验。
- 纯标量 exact oracle 有具体 waiver 时仍可运行。
- 周期网络缺 identity map 或 contact edges 时拒绝。
- 概率转变缺 successes/trials/interval 时拒绝。

完成定义：Q1 在实验结束时已经拥有可直接绘图的真实结构数据。

### 阶段 2：重写对象感知路由与需求归并

优先级：P0。预计 1--1.5 天。

修改：

- `src/shumozizi/paper/visual_requirements.py`
- `schemas/paper_visual_requirements.schema.json`
- 论文 argument extraction 清洗层
- `tests/competition_first/test_paper_visual_requirements.py`

测试先行：

- 周期接触网络路由到空间 + 网络候选，不路由到通用 flowchart。
- Q3 概率转变路由到阈值曲线，不路由到 model evolution schematic。
- Q4 整数格点路由到 active constraint map。
- LaTeX 表格、已有 figure 环境和超长正文不会生成独立需求。
- 同一对象、角色和结果集合的重复段落被归并。

完成定义：当前 A 题需求池中的每项都短、可执行、无重复、无 LaTeX 噪声。

### 阶段 3：改造 Prompt 选择和 Visual Sandbox 评审

优先级：P0。预计 0.5--1 天。

修改：

- `src/shumozizi/simple/paper_image_prompts.py`
- `src/shumozizi/simple/visual_sandbox.py`
- `schemas/visual_competition.schema.json`
- `scripts/figures/visual_sandbox.py`

测试先行：

- 决定性证据、机制和边界可以成为 Hero 候选。
- 每问不再机械最多一个候选；改为全篇少量 Hero 预算 + supporting 按需。
- Hero 候选至少包含两种真正不同的视觉结构。
- reviewer 必须填写对象可见性、领域特异性、边界和论文尺寸可读性。
- copy-only graduate 被拒绝。

完成定义：候选竞争选出的不是“最好看的流程图”，而是最能显示当前数学对象和机制的方案。

### 阶段 4：实现正式 renderer 组件

优先级：P0。预计 1.5--2 天。

首批实现顺序：

1. 周期空间场景与接触网络骨架。
2. 概率阈值曲线与 Wilson 区间。
3. 整数可行域与成本等高线。
4. 前沿、敏感性和稳定性组件。

测试：

- 每个 renderer 使用最小 JSON fixture 生成 PNG/PDF。
- PNG/PDF 几何比例一致。
- 坐标、图例、单位、阈值、正式域和选中点均存在。
- 3D 输出非空、无遮挡关键路径，并有 2D 辅助面板。
- 字体、颜色和灰度区分通过机械检查和人工看图。

完成定义：运行目录脚本只组合本题数据，不再手工从最终标量重建结构。

### 阶段 5：回填当前 A 题视觉数据并正式出图

优先级：P0。预计 1 天。

动作：

1. 在安全 checkpoint 后读取当前 production 输出。
2. 判断 Q1/Q4 是否已保存粒子、身份、接触边、格点和代表样本。
3. 已有数据直接适配；缺失数据只重跑最小必要 production，不重跑无决策价值实验。
4. 为三个 Hero insight 各出 2--4 个 Sandbox 候选。
5. Fresh reviewer 选型后，用正式 renderer 在 `figures/work/` 重画。
6. 完成人工看图、PNG/PDF QA、来源绑定和 current 晋级。

完成定义：图 2、图 5、图 7 成为三张可记忆主图，图 3、4、8、9、10 按论证需要完成。

### 阶段 6：重排长篇论文

优先级：P1。预计 1 天。

动作：

- 更新 Research Package 中的 current 图清单和主张边界。
- 保持 objective answer 不变，除非新图暴露真实科学冲突。
- 重写前五页，使 Q1 Hero 在统一模型首次出现处进入正文。
- Q3 和 Q4 各自让主图紧邻直接答案和关键推导。
- 将稳定性图移入附录，删除重复表格和重复边界段落。
- 重新编译长篇首稿，逐页渲染检查。

完成定义：三分钟冷读可以找到四问答案、复述一句话贡献、指出三张主图及其论点，并说清 Q4 正式域与敏感性域的区别。

### 阶段 7：视觉 checkpoint 与最终评测

优先级：P0。预计 0.5--1 天。

增加 paper 内部 checkpoint，不新增顶层阶段：

- 高价值 open requirement 必须在 Candidate 前覆盖或由 Fresh reviewer 实质 DROP。
- 低价值需求可以 DROP，但必须说明删除后论文没有失去关键对象、机制或边界。
- 任何新 current 图必须已在正文被引用并有图后解释。

最终评测：

1. 机械 QA：路径、哈希、PNG/PDF、字体、裁切、重叠、空白、页码。
2. 科学 QA：正式图数值与 current production 一致，正式域和敏感性域不混淆。
3. 匿名 pairwise：旧 13 页稿 vs 新稿，隐藏文件名和版本信息。
4. 三分钟冷读：主图、直接答案、共享模型、边界和工作报告页定位。
5. 视觉节奏审计：模型首次出现、关键结果、核心机制和边界均有适当视觉支持。

## 14. 测试与验收矩阵

### 14.1 工程测试

```powershell
python -m pytest tests/competition_first/test_competition_first_v32.py -k visual_outputs
python -m pytest tests/competition_first/test_paper_visual_requirements.py
python -m pytest tests/competition_first/test_paper_image_workflow.py
python -m pytest tests/competition_first/test_debureaucracy_authoring.py -k visual
python -m pytest tests/competition_first/test_figure_promotion.py
python -m ruff check src scripts tools tests
```

完成针对性测试后再运行完整 `python -m pytest`。若完整套件受时间限制，必须报告已通过的范围和未完成原因，不能声称全量成功。

### 14.2 图形验收

每张正式图必须同时满足：

- 使用 current production 数据。
- 核心数学对象可见。
- 阈值、边界、选中点、单位和有效域可读。
- 删除该图会损失明确的理解或论证价值。
- 不重复表格能更高效表达的内容。
- 在 100% A4 视图和灰度打印下可辨。
- PNG/PDF 均可打开，几何一致，无文字越界和图例遮挡。

### 14.3 论文竞争力验收

匿名 reviewer 在三分钟内应能完成：

- 找到 Q1--Q4 的直接答案。
- 指出 Q1 周期接触图、Q3 阈值图和 Q4 可行域图。
- 说明每张 Hero 图支持的判断。
- 复述“同一接触图从确定导通、概率到机会约束优化”的共享主线。
- 识别 `1A+50B` 是严格正域正式答案，`0A+57B` 只是零允许敏感性。

pairwise 通过标准不是“看起来更花哨”，而是新版在以下维度多数胜出且没有科学退步：

- 模型对象可见性。
- 关键结果可定位性。
- 主图记忆度。
- 机制与边界解释。
- 页面节奏。
- 字体和图注可读性。

## 15. 速度控制

高级图不能重新拖慢求解。采用以下策略：

- analysis/experiment 阶段只保存结构数据，不做正式排版。
- exploration 可输出低分辨率诊断图，但不进入 current。
- production 冻结后，各问题 renderer 可并行运行。
- 统一图形组件和样式，减少每题重写绘图代码。
- 使用 deterministic JSON 和稳定 renderer，结果未变时不重复计算。
- 只因缺失结构字段重跑最小必要实验，不重跑已经闭合的概率或优化搜索。
- 将图形生成、PDF 编译和 QA 时间单独记录，区分求解耗时与协调等待。

目标参考值：production 结果冻结后，正文正式图批量生成控制在 15 分钟内，长篇 PDF 编译与渲染 QA 控制在 10 分钟内。该目标是工程性能指标，不是牺牲正确性的超时硬门。

## 16. 风险与回退

| 风险 | 处理方式 |
|---|---|
| Q1 生产结果没有保存坐标/接触边 | 增加结构化输出并最小重跑 Q1，不从图表阶段猜造 |
| 3D 图遮挡或信息过载 | 使用正交剖面、网络面板或局部放大替代 |
| 需求归并过度，漏掉真实边界 | 用 longform cold read 反向检查每个主张角色 |
| 需求归并不足，仍有大量 open | 检查 LaTeX 清洗和对象主键，不通过批量 DROP 掩盖 |
| 图形提升但论文更长更散 | 删除重复表格和研究过程，保留共享推导与三张 Hero |
| 图暴露当前结果冲突 | 按 science 修订回到 experiment 和 scientific challenge |
| 参考稿视觉诱导复制错误口径 | 所有图只绑定当前 run 的 production/current 事实 |
| 新门禁增加流程负担 | 只阻断高价值未闭合需求，低价值项由 reviewer 实质 DROP |

## 17. 推荐执行顺序

```text
P0-1  等当前任务到安全 checkpoint，冻结基线
P0-2  spatial exact_oracle 与数学对象视觉数据合同
P0-3  对象感知路由、正文噪声清洗和需求归并
P0-4  Sandbox 评分与 no-copy 正式晋级
P0-5  周期场景、接触网络、概率阈值、整数可行域 renderer
P0-6  当前 A 题三张 Hero 和 supporting 图正式晋级
P1-1  长篇论文重排与前五页重写
P0-7  PDF 冷读、匿名 pairwise、机械 QA
```

不能颠倒为“先扩写论文、最后补图”。Q1/Q4 的结构数据和主图必须先稳定，否则正文会围绕错误的视觉对象再次返工。

## 18. 最终完成定义

只有同时满足以下条件，才能认为达到参考稿那种效果并超过其科学可靠性：

1. Q1 的真实周期微结构、接触网络和导电骨架在正文可见。
2. Q3 的 8 根阈值由概率曲线、区间和独立加密共同表达。
3. Q4 的整数可行域、成本等高线、严格正域和零允许敏感性在图上明确分层。
4. 正文形成少量模型原生、可记忆的 Hero 图；本题优先竞争 Q1、Q3、Q4 三个候选，但不把固定数量当作放行条件。
5. Supporting 图覆盖关键机制、反例和边界，图数由论证决定。
6. 所有正式图均由 current production 数据和正式 renderer 生成，无 copy-only 晋级。
7. 当前视觉需求无 LaTeX 噪声、无重复对象；高价值需求全部覆盖或实质 DROP。
8. 新 PDF 在匿名 pairwise 中稳定胜过旧稿的模型可见性、主图记忆、结果定位和页面节奏。
9. 新图没有改变或夸大 objective answer、证据等级和定义域边界。
10. 求解、绘图、写作和审查耗时能够分解说明，视觉升级不重新引入长时间无效等待。
