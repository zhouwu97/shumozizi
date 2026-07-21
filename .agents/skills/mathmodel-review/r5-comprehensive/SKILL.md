---
name: mathmodel-review-r5-comprehensive
description: 新对话执行的全面盲审，输出 A-E 奖项估计、证据、置信度和降级原因。
---

# R5 全面盲审兼容入口

本目录保留用于兼容旧路径；正式执行规范位于顶层可发现 Skill：
`.agents/skills/mathmodel-review-r5-comprehensive/SKILL.md`。

不读取作者解释、前轮报告或上一轮修复意见，只读取当前冻结提交和原始题面。每条 finding
按 v3 reviewer 合同只陈述问题、证据、影响、反例、建议验证方式和严重度建议；返工等级与
影响范围由生产主 AI 裁决。取消固定三轮或五轮上限：完整 R5 只由核心模型、数据/数字、结论、
主图变化或 P0/P1 重新打开触发，总时间建议为比赛预算的 5%–10%。局部修改只做 scoped
recheck，不生成完整竞赛评分。正式规范以顶层 Skill 为准。
