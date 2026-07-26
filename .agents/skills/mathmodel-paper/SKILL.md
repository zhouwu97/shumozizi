---
name: mathmodel-paper
description: 从 Competition-First v3.2 的当前真实结果组织、编译和修订数学建模论文。
---

# 贡献驱动论文

先写 `paper/STORYBOARD.md`：一句主旨、最强/最弱问题、核心贡献、章节作用、篇幅、核心图表和最后填写的摘要。再写最多三项真实的 `paper/CONTRIBUTION_BRIEF.md`，不能把常规方法组合包装为创新。

每个必答问题只硬性需要题目要求、方法/公式、结果、直接答案和必要限制。核心问题再加入路线选择、完整推导、比较、机制和验证；允许非对称篇幅。

核心问题必须把已挖出的规律真的写进论文：在 answer map 的该问条目用 `insight_ids` 引用实验阶段登记的机制、边际收益、活跃约束或权衡类规律。挖了却不引用会阻断编译——规律不能只作为旁路产物存在。

在 `analysis/answer_map.json` 或 `paper/answer-map.json` 中映射每题的 current result IDs 与直接答案位置。运行时自动生成 `paper/generated/argument_map.json`，不得手工维护哈希地图。缺少 storyboard、brief 或特定图只产生警告。

源码不占正文。PDF 内只保留核心算法伪代码、一段真正关键的数学判断代码和运行入口说明，`source_code_appendix.pdf_page_budget` 默认不超过 1 页，完整代码走 `mode: attachment`。确有赛事要求整篇源码时显式声明 `competition_requires_full` 并写明依据。

摘要最后写，包含关键困难、实质方法、关键数值、主要规律和可信边界，避免堆模型名称。小文字改动仅重新编译和机械 QA；影响结论或图表的改动重做 PDF 盲评；代码、数据、目标或主要结果改动回到实验和科学挑战。
