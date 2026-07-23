---
name: mathmodel-optimizer-benchmark
description: 在同一问题定义、exact scorer、硬约束、评价预算和随机种子下公平比较启发式、数学规划或自定义优化路线。需要检验 incumbent 竞争力、比较 pymoo/SciPy/MATLAB 算法、记录多种子分布与 best-so-far 时调用；不把调用某个优化库本身当成充分求解证据。
---

# 优化器公平比较

1. 先冻结变量、边界、硬约束、目标方向和统一 exact scorer。所有算法只通过 `src/shumozizi/benchmarking/optimizer.py` 提供的带计数 scorer 获取论文可引用的精确评价；代理目标只能用于内部提案，并必须与 exact 结果分列。
2. 每个算法使用完全相同的 `evaluation_budget` 和 `seeds`。记录评价次数、首次可行位置、可行率、最佳精确目标、约束违反、运行时间和逐次轨迹。算法提前停止可以保留，但不得把较少预算和满预算结果直接宣传为公平胜负。
3. 按问题结构选择算法，而不是固定排行榜：`vendor/scientific-agent-skills/pymoo/` 提供连续、多目标和约束优化接口；`vendor/math-modeling-skills/solver-references/code-templates/` 仅是候选起点；小规模问题优先增加穷举、解析或数学规划基线。
4. 用独立 challenge 搜索攻击 incumbent，并由同一个 exact scorer 复算最终候选。若不同算法使用不同修复策略、精度或约束解释，必须先统一，否则结论只能称为路线探索，不能称为公平比较。
5. 将机器收据写入 `results/raw/`，图只展示真实 best-so-far、多种子分布、可行性和边界诊断。论文解释算法为何适合当前结构、预算下能支持什么结论，以及仍无法证明的全局最优性。
