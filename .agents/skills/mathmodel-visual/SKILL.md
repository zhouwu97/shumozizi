---
name: mathmodel-visual
description: 用真实结果生成由问题和 takeaway 驱动的数学建模图表，不强制固定图种或图数。
---

# 洞察驱动图表

每张图先回答三个问题：它回答什么、读者一眼看见什么、删除后论文失去什么。第三问答不出时不画。

图表默认输出到 `figures/current/`，登记真实 `source`、`question`、`takeaway` 和可选 `limitations`。使用 `register_insight_figure` 绑定当前生产结果、输入、渲染脚本与 PNG/PDF 输出。结果或脚本变化后，图必须重新生成。

按题目需要选择模型理解图、决定性证据图或洞察图。不要默认要求每问有图、3D、收敛图、敏感性图、多种子图、雷达图或 evidence/publication 双份。模板示例数据绝不能进入论文。
