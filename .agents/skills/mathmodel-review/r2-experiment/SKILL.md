---
name: mathmodel-review-r2-experiment
description: 独立实验复现审核，检查数据划分、指标、约束、随机性、代码和图表来源。
---

# R2 实验复现审核

从干净输入运行执行清单，复核当前结果和图表。每条 finding 必须声明 `change_level` 和
`affected_questions`。结论只能是 `REPRODUCIBLE`、`REPRODUCIBLE_WITH_WARNINGS` 或
`BLOCKED`，不得修改生产文件。
