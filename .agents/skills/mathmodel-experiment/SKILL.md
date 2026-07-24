---
name: mathmodel-experiment
description: 真实执行数学建模实验，比较路线、保存 current 结果、生成可验证图表数据并挖掘结果洞察。
---

# 高价值实验

代码写入 `code/`，输出写入 `results/raw/`，影响路线或论文的实验必须使用执行器登记。探索结果标为 diagnostic，不能进入论文。

优先 baseline、区分性 probe 与能推翻当前结论的实验。实验的价值来自改变路线、模型、主要结论、机制解释或贡献，不来自填满敏感性、多种子或收敛图清单。

真实结果后可以生成 `analysis/method_facts.json`。它的 true/false/unknown 只触发建议：随机求解器建议多种子，proxy 建议检查 exact 排序，时间切分检查泄漏，连续几何检查端点和离散误差。缺失或 unknown 绝不阻断。

写 `analysis/INSIGHTS.md`：每项分别记录观察、结果/图证据、机制解释、检验、论文价值和边界。没有可靠规律时明确写出。任何反例、独立复算冲突、不可行、性质失败或更优 incumbent 都先让相关结果、图表和论文失效。
