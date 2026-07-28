---
name: mathmodel-visual
description: 用真实结果生成由问题和 takeaway 驱动的数学建模图表，不强制固定图种或图数。
---

# 洞察驱动图表

每张图先回答三个问题：它回答什么、读者一眼看见什么、删除后论文失去什么。第三问答不出时不画。

先读 [visual-pattern-cards.md](references/visual-pattern-cards.md)，从题目的数学对象选择视觉原型，不从图库名称反推图。二维或三维都不是质量标签：空间、场或三变量结构才使用 3D；精确比较阈值、区间和剖面时优先 2D。核心标准是一张图能否联合呈现数学对象、机制、约束边界、最终决策，以及不确定性或对照。

每张图必须声明 role：`model_understanding`（帮助评委理解数学对象）、`decisive_evidence`（证明关键结果可信）、`insight`（揭示机制、阈值、边际收益或权衡）、`stability`（舍入、采样层级、数值稳定性）。`stability` 一律进入附录，不得占据正文版面——它对内部审计有价值，对评委的边际价值远低于机制与权衡。正文应有能回答"为什么最优解是这个结构"的图。

图表默认输出到 `figures/current/`，登记真实 `source`、`question`、`takeaway` 和可选 `limitations`。使用 `register_insight_figure` 绑定当前生产结果、输入、渲染脚本与 PNG/PDF 输出。结果或脚本变化后，图必须重新生成。

在 analysis 阶段先列出 `mathematical_objects` 和 `visual_questions`。在模型输出合同中声明 `visual_outputs`，至少按实际需要保存候选解、可行边界、活跃约束、搜索轨迹、Pareto 点、状态轨迹或不确定性样本；只保存最终标量时先修模型输出，不能让绘图阶段猜造结构数据。

先为每个 `core_question=true` 的问题在 `FIGURE_PLAN.json` 2.2 写一条 `visual_decisions`：空间、流程、机制、阈值或权衡需要视觉证据时选 `required` 并说明原因；确实可由公式、直接答案表和短文完整表达时选 `waived` 并给出具体理由。不能通过缺少计划或把所有图设为可选来静默零图。旧 2.1 文件只作兼容读取，新计划使用 2.2。

需要作为正文论证证据的图，除原有来源和 LaTeX 字段外，还声明 `visual_archetype`、`renderer`、`visual_question`、`expected_observation` 和 `decision_consequence`。renderer 由结构与已有计算选择，不强制 MATLAB。使用 `python scripts/figures/write_figure_plan.py <run_dir> --input <json>` 校验并原子写入；首版截止后只能修订既有图，不能新增图 ID。生成后检查该图已在目标 LaTeX 小节插入、标号、交叉引用并解释；缺任何一环，先补消费闭环再继续画下一张图。

用 `audit_figure_information_value()` 查看五维建议分：数学对象、机制、约束/边界、最终决策、不确定性/对照各 0--2 分，正文主图建议至少 6 分。该分数只根据原型判断设计机会，不是门禁；必须打开 PNG/PDF 检查是否真的兑现。以下情况应返修：空间题无布局或剖面，多目标题无 Pareto/可行域，动态题无状态轨迹和控制量，不确定性题只有均值，热力图只是彩色数字表，主图只比较算法分数，或图后正文没有观察、机制和决策后果。

按题目需要选择图种。不要默认要求每问有图、3D、收敛图、敏感性图、多种子图、雷达图或 evidence/publication 双份，也不靠输出份数凑数量。模板示例数据绝不能进入论文。
