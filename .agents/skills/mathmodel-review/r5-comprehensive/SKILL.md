---
name: mathmodel-review-r5-comprehensive
description: 新对话执行的全面盲审，输出 A-E 奖项估计、证据、置信度和降级原因。
---

# R5 全面盲审兼容入口

本目录保留用于兼容旧路径；正式执行规范位于顶层可发现 Skill：
`.agents/skills/mathmodel-review-r5-comprehensive/SKILL.md`。

不读取作者解释、前轮报告或上一轮修复意见，只读取当前冻结提交和原始题面。竞赛模式最多两轮，只有首轮出现 P0/P1 或评级低于 B 才允许第二轮；单轮 A/B 且无 P0/P1 即可进入人工最终核包。训练模式最多五轮。J0 不属于 R5 循环且只执行一次。
