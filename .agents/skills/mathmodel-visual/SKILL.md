---
name: mathmodel-visual
description: 用真实结果生成由问题和 takeaway 驱动的数学建模图表，不强制固定图种或图数。
---

# 洞察驱动图表

每张图先回答三个问题：它回答什么、读者一眼看见什么、删除后论文失去什么。第三问答不出时不画。

每张图必须声明 role：`model_understanding`（帮助评委理解数学对象）、`decisive_evidence`（证明关键结果可信）、`insight`（揭示机制、阈值、边际收益或权衡）、`stability`（舍入、采样层级、数值稳定性）。`stability` 一律进入附录，不得占据正文版面——它对内部审计有价值，对评委的边际价值远低于机制与权衡。正文应有能回答"为什么最优解是这个结构"的图。

图表默认输出到 `figures/current/`，登记真实 `source`、`question`、`takeaway` 和可选 `limitations`。使用 `register_insight_figure` 绑定当前生产结果、输入、渲染脚本与 PNG/PDF 输出。结果或脚本变化后，图必须重新生成。

按题目需要选择图种。不要默认要求每问有图、3D、收敛图、敏感性图、多种子图、雷达图或 evidence/publication 双份，也不靠输出份数凑数量。模板示例数据绝不能进入论文。
