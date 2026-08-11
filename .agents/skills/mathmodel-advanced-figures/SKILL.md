---
name: mathmodel-advanced-figures
description: 论文初稿完成后，按数据特征补充数量多、类型多、风格统一的高级图表，全面提升论文可视化水平。适用于整篇论文的视觉增强，不改动数据、模型与结论。当需要让论文"看起来像国奖论文"、补充 Nature 级图表、或初稿只有基础折线/柱状图时使用。
---

# 竞赛高级图补充（SECOND STEP）

借鉴 MathModel 的表达力，守住本项目的科学底线：**只增强表达，不修改数据、模型与结论；
所有图必须由 current production 数据生成，不得用模拟/合成数据冒充。**

## 触发时机

论文初稿（longform/main.tex）写完、production 结果冻结之后、提交之前，**必须**执行本
skill 一次。目标是让论文从"技术报告"变成"有高级图的竞赛论文"。

## 流程

### 1. 通读论文，按数据特征挑图种

先读 [figure-catalog.md](references/figure-catalog.md)，从论文每个结果的**数据特征**
反推图种（不要从图库名称反推数据）。每个图必须能回答：它要解释什么、读者一眼看见什么、
删除后论文失去什么。

### 2. 用 production 数据渲染，不造数据

正式图必须绑定 current production 结果。优先用本 skill 的现成模板：

```bash
python "<skill-directory>/scripts/render_advanced.py" \
  --template probability_curve --input results/raw/<result>.json --output figures/current/<fig>
```

支持模板（`--list` 查看）：`probability_curve`、`feasible_region`、
`pareto_frontier`、`ci_forest`、`group_violin`。若数据特征需要其他图种
（桑基、和弦、泰勒图等），按 [plot-recipes.md](references/plot-recipes.md) 的统一样式
手写，**数据从结果文件读**，不得硬编码。

### 2b. 结构解释图（TikZ，不碰数据证据）

共享模型路线图、问题递进、机制判定这类**结构解释图**走
[structure-spec.md](references/structure-spec.md)：写一个薄 structure spec
（template/nodes/edges/emphasis/math），用确定性 TikZ renderer 渲染：

```bash
python "<skill-directory>/scripts/render_structure.py" --spec <spec.json> --output figures/current/<fig>
```

模板：`shared_model_map`、`problem_progression`、`mechanism_decision`。
**边界**：`argument_role=decisive_evidence` 会被拒绝——结构图不承担数值证据，
证据图必须走数据 renderer。AI 决定语义（中心/关系/强调/公式），程序决定几何。

### 3. 全篇统一样式

所有图必须先 `apply_competition_style()`（`scripts/style.py`）：
seaborn 主题 + 语义调色板 + 中文字体（SimSun）+ DPI≥300。颜色语义：
正式答案深青、阈值金色虚线、敏感性灰、不可行暖红、骨架蓝。

### 4. 正确嵌入论文

每张新图：
- 保存到 `figures/current/`，PNG/PDF/SVG 三格式。
- 在正文对应位置 `\includegraphics`，配图号 + 图注。
- 图注后必须附一句"这张图展示了什么、能得出什么结论"（图即论证，不是装饰）。

### 5. 验收

- 每个问题正文配 2--3 张支撑图，全篇不同类型图不少于 12 张。
- 类型 ≥ 3 种（小提琴/箱线/森林/帕累托/肘图/灵敏度/混淆矩阵/PR/ROC/校准/误差带/收敛/分布
  等高级图），不全是折线/柱状。
- 每张 current 图被正文引用并配图注解读。
- 全篇配色/字体/DPI 一致。
- 所有数值与 production 结果一致；不改数据、模型与结论。

## 边界

- 只增强可视化，不改变答案、证据等级与定义域边界。
- 不改 science：若某图暴露结果冲突，回到 experiment，不为了好看改图。
- 图注解读必须诚实：区间是区间、拟合是拟合，不得把装饰当证据。
