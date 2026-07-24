---
name: mathmodel-paper
description: 从 Competition-First v3.1 的当前真实结果组织、编译和修订数学建模论文。
---

# 贡献驱动论文

先写 `paper/STORYBOARD.md`：一句主旨、最强/最弱问题、核心贡献、章节作用、篇幅、核心图表和最后填写的摘要。再写最多三项真实的 `paper/CONTRIBUTION_BRIEF.md`，不能把常规方法组合包装为创新。

每个必答问题只硬性需要题目要求、方法/公式、结果、直接答案和必要限制。核心问题再加入路线选择、完整推导、比较、机制和验证；允许非对称篇幅。

在 `analysis/answer_map.json` 或 `paper/answer-map.json` 中映射每题的 current result IDs 与直接答案位置。运行时自动生成 `paper/generated/argument_map.json`，不得手工维护哈希地图。缺少 storyboard、brief 或特定图只产生警告。

摘要最后写，包含关键困难、实质方法、关键数值、主要规律和可信边界，避免堆模型名称。小文字改动仅重新编译和机械 QA；影响结论或图表的改动重做 PDF 盲评；代码、数据、目标或主要结果改动回到实验和科学挑战。
