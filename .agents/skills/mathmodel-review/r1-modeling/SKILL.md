---
name: mathmodel-review-r1-modeling
description: 独立建模审核，检查题意、变量、目标、约束、算法和验证计划。
---

# R1 建模审核

只读取当前 `REVIEW_INPUT_MANIFEST.json` 声明的题面、附件、路线、模型规格、数据剖面和验证
材料。全新顶层任务必须先生成 `review_session.json`，报告绑定 session 哈希后才能物化回执。
结论区分 `ACCEPT`、`ACCEPT_WITH_MINOR_FIXES`、`SPEC_REVISION_REQUIRED`、
`ROUTE_REAPPROVAL_REQUIRED` 和 `BLOCKED_MISSING_INPUT`。只有题意解释或路线核心变化才允许要求
重新批准路线；规格补全和验证细化只重跑 R1。审核任务不得修改作者代码、结果和论文。
