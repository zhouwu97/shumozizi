---
name: mathmodel-visual
description: 用真实结果生成由问题和 takeaway 驱动的数学建模图表，不强制固定图种或图数。
---

# 洞察驱动图表

每张图先回答三个问题：它回答什么、读者一眼看见什么、删除后论文失去什么。第三问答不出时不画。

每张图必须声明 role：`model_understanding`（帮助评委理解数学对象）、`decisive_evidence`（证明关键结果可信）、`insight`（揭示机制、阈值、边际收益或权衡）、`stability`（舍入、采样层级、数值稳定性）。`stability` 一律进入附录，不得占据正文版面——它对内部审计有价值，对评委的边际价值远低于机制与权衡。正文应有能回答"为什么最优解是这个结构"的图。

图表默认输出到 `figures/current/`，登记真实 `source`、`question`、`takeaway` 和可选 `limitations`。使用 `register_insight_figure` 绑定当前生产结果、输入、渲染脚本与 PNG/PDF 输出。结果或脚本变化后，图必须重新生成。

先为每个 `core_question=true` 的问题在 `FIGURE_PLAN.json` 2.1 写一条 `visual_decisions`：空间、流程、机制、阈值或权衡需要视觉证据时选 `required` 并说明原因；确实可由公式、直接答案表和短文完整表达时选 `waived` 并给出具体理由。不能通过缺少计划或把所有图设为可选来静默零图。

需要作为正文论证证据的图，写入 `FIGURE_PLAN.json` 2.1 并声明 `question_id`、`role`、`claim`、`source_result_ids`、`script`、`output`、`paper_section`、`caption`、`latex_label`、`explanation_anchor` 和 `required=true`。使用 `python scripts/figures/write_figure_plan.py <run_dir> --input <json>` 校验并原子写入；首版截止后只能修订既有图，不能新增图 ID。生成后检查该图已在目标 LaTeX 小节插入、标号、交叉引用并解释；缺任何一环，先补消费闭环再继续画下一张图。

按题目需要选择图种。不要默认要求每问有图、3D、收敛图、敏感性图、多种子图、雷达图或 evidence/publication 双份，也不靠输出份数凑数量。模板示例数据绝不能进入论文。
