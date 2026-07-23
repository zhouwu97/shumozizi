---
name: mathmodel-geometry-oracle
description: 为有限线段、球体、轨迹遮挡和空间相交问题建立数学语义明确、源码闭包独立的双实现 oracle。遇到几何/运动题需要投影裁剪、二次方程求交、端点/切线/退化反例或性质测试时调用；不用于一般绘图、论文润色或复用同一领域函数的伪独立验证。
---

# 几何独立 Oracle

先明确当前判定是球面相交、实心闭球体相交、最小距离，还是带前后顺序的视线遮挡。四种语义不能互换；半径、端点闭开性、时间区间和容差必须写入当前题的公式与测试。

1. 生产实现使用 `src/shumozizi/geometry/projection.py` 的投影裁剪思路；独立 oracle 使用 `src/shumozizi/geometry/quadratic.py` 的球面二次方程加端点内含。为当前运行生成脚本时，将两套公式分别写入不同的 `code/**/*.py`，不得互相 import，也不得共同引用 geometry、scorer、objective、constraints 或 simulation 领域模块。
2. oracle 至少覆盖端点、切线、退化线段、全内含和明确不相交；再检查平移与旋转不变性。用 `vendor/scientific-agent-skills/sympy/` 只辅助核对符号推导，不把同一推导自动翻译成两种语言后称为独立。
3. 通过 v3 执行器分别登记当前生产结果和 `kind=independent-oracle`。oracle JSON 必须包含不同 `formulation`、生产 formulation、边界集合和逐例比较结论；运行时会递归哈希本地 Python 源码闭包并拒绝共享领域依赖。
4. 若任务是遮挡，还要单独验证观察点、遮挡物和目标的前后顺序，以及有限目标的可见范围。单纯“线段与球相交”不能自动推出有效遮挡。

该 Skill 负责选择与检验两套数学路线，不替代题目特定推导，也不把协议收据当成正确性证明。
