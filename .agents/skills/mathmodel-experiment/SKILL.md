---
name: mathmodel-experiment
description: 真实执行数学建模实验，比较路线、保存 current 结果、生成可验证图表数据并挖掘结果洞察。
---

# 高价值实验

代码写入 `code/`，输出写入 `results/raw/`，影响路线或论文的实验必须使用执行器登记。探索结果标为 diagnostic，不能进入论文。

预算优先给搜索，不给复算。核心问题的搜索与深化耗时必须超过其验证与复算耗时，且核心搜索要占实际算力的 40% 以上——把复算跑成 exploration 不能稀释这条检查。建议分配：主路线深化与候选搜索 60%、竞争路线 15%、机制与敏感性 15%、独立复核 10%。

优先 baseline、区分性 probe 与能推翻当前结论的实验。实验的价值来自改变路线、模型、主要结论、机制解释或贡献，不来自填满敏感性、多种子或收敛图清单。

比较必须真的判胜负：赢家由统一 exact scorer 的实测结果决定，核心问题的赢家还要相对 baseline 达到事前声明的显著改善阈值。达不到时继续搜索、换更强路线，或用 `baseline_near_bound` 加实际界证据说明已接近上限。深化后的最终结果不得比比较阶段的赢家更差。路线预期上限明显落空时登记 `upside_shortfall` 的原因与决定，不要继续按原声明叙述优势。

exact 赢家只获得“候选主答案”身份。执行者只登记 `actual_endpoint_resolution` 与 `qualification_evidence` 的真实结果指标：路线升级由 exact 分数和事前阈值计算，endpoint 一致性由最终裁决、合理口径下的路线排序和行动后果计算，guard 与决策稳定性由预登记指标阈值计算。系统据此唯一派生 `promoted`、`fallback_selected` 或 `redesign_required`；不得手填布尔值覆盖结果。endpoint 未决或合理口径导致路线翻转时回到 `analysis`，搜索或验证不足时回到 `experiment`。论文的 `primary_result_id` 必须与系统派生结果一致。

真实结果后可以生成 `analysis/method_facts.json`。它的 true/false/unknown 只触发建议：随机求解器建议多种子，proxy 建议检查 exact 排序，时间切分检查泄漏，连续几何检查端点和离散误差。缺失或 unknown 绝不阻断。

规律挖掘和实验同等重要。核心问题必须产出带 `insight_id` 的结构化规律，每项记录观察、机制、真实结果证据和边界；其中至少一条属于机制、边际收益、活跃约束或权衡——只有反直觉描述不算理解。同时写 `analysis/INSIGHTS.md` 作为可读版本。任何反例、独立复算冲突、不可行、性质失败或更优 incumbent 都先让相关结果、图表和论文失效。
