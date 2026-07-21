---
name: mathmodel-review-r1-modeling
description: 独立建模审核，检查题意、变量、目标、约束、算法和验证计划。
---

# R1 建模审核兼容入口

本目录保留用于兼容旧路径；正式执行规范位于顶层可发现 Skill：
`.agents/skills/mathmodel-review-r1-modeling/SKILL.md`。

兼容入口同样要求在正式实验前复验 `analysis/MINIMUM_SCIENTIFIC_CONTRACT.md`，并判断题目目标、
模型输出、评价指标、positive control、失败判据和 fallback 是否闭合。Reviewer finding 只陈述
问题、证据、影响、反例、建议验证方式和严重度建议；返工等级与影响范围由生产主 AI 裁决。
审核任务不得修改作者代码、结果和论文。
