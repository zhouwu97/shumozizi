---
name: mathmodel-advanced-figures
description: 论文初稿完成后，按数据特征补充类型丰富、风格统一的高级科研图表。适用于整篇论文的视觉增强，不改动数据、模型与结论；每个必答问题正文 2–3 张【硬门】，四问及以上全篇 13–18 张及至少 3 种 visual archetype【硬门】。
---

# 竞赛高级科研图补充（SECOND STEP）

吸收优秀科研图与 SCI-Box 母版表达力，守住本项目的科学底线：**只增强表达，不修改数据、模型与结论；所有图必须由 current production 数据生成，不得用模拟/合成数据冒充。**

## 触发时机与配额硬门

论文初稿写完、production 结果冻结之后，检查正文是否仍有未被视觉直观解释的数学关系、关键机制或边界；有缺口时执行本 skill。
- **逐问硬配额**：每个必答问题必须在正文消费 **2–3 张** current 正文图【硬门】；
- **全篇硬配额**：四问及以上正式稿，全篇正文消费 **13–18 张** current 正文图【硬门】且覆盖至少 **3 种**可审计 visual archetype【硬门】；少于四问按论证角色编辑复核；
- **Hero Figure 与 Supporting Figures**：核心问题配备 1 张高辨识度 Hero 图（展示整体解空间、渗流网络、帕累托前沿或核心机理）+ 必要 supporting 图，并包含全局/跨问结构图；不得为了数量机械拼凑重复图或装饰图。

---

## 流程

### 1. 先写图合同（claim-first），再挑母版
对每张计划中的正式图，先完成五点合同：
**核心结论一句话 → 证据链逐面板 → 图型分类 → current 数据来源 → 嵌入与解读契约**。
写不出一句话核心结论、或找不到 current 结果字段的图不画。确认后，从 SCI-Box 母版库或分类图表中按数据特征挑选最适合的图种（分布、概率、优化、关联、网络、分类等）。

### 2. SCI-Box 母版作为默认可视化来源（Direct / Adapted / Remix）
正式图必须绑定 current production 结果。优先采用 SCI-Box / 高级模板：

```bash
python "<skill-directory>/scripts/render_advanced.py" \
  --template probability_curve --input results/raw/<result>.json --output figures/current/<fig>
```

- **内置模板**：`probability_curve`（概率曲线/置信带）、`feasible_region`（可行域与等值线）、`pareto_frontier`（多目标前沿）、`ci_forest`（森林图/置信区间）、`group_violin`（分组小提琴图/分布对比）。
- **扩展与定制**：热力图、等高线、散点回归、误差带、收敛曲线等，按统一样式从结果文件读取数据绘制，允许根据赛题特征进行灵活 adapted 或 remix。
- **母版适配原则**：`auto` 优先 `direct` 安全直连，否则自动转 `master_adapted`（保留母版视觉语法与布局、剥离源论文语义）；绝不自动退回简化 `reimplemented`。

### 2b. 结构解释图（TikZ，不碰数据证据）
共享模型路线图、问题递进、机制判定等**结构解释图**走 TikZ renderer：

```bash
python "<skill-directory>/scripts/render_structure.py" --spec <spec.json> --output figures/current/<fig>
```

模板：`shared_model_map`、`problem_progression`、`mechanism_decision`。AI 决定语义，程序决定几何。

### 3. 全篇统一样式
所有图统一应用竞赛标准样式（`apply_competition_style()`）：
- Seaborn/Matplotlib 现代主题 + 语义调色板 + 中文字体（SimSun/Times New Roman）+ 高分辨率（DPI≥300）。
- 颜色语义一致：正式答案深青、阈值金色虚线、敏感性灰、不可行暖红、骨架蓝。

### 4. 正确嵌入论文并完成三步论证
每张新图：
- 保存到 `figures/current/`（PNG/PDF/SVG 格式）。
- 在正文对应位置 `\includegraphics`，配图号与图注。
- 正文围绕该图完成“**观察**（图显示了什么）→ **机制**（为什么呈现该形态）→ **结论**（对当前模型与答案意味着什么）”的完整论证。

### 5. 验收
- 每个必答问题正文消费 2–3 张 current 正文图；四问及以上全篇正文消费 13–18 张 current 正文图，且覆盖至少 3 种 visual archetype。
- 每张正式图都有明确论证职责与 current 数据来源。
- 核心问题拥有高质量 Hero 图，正文图文深度契合。
- 全篇配色、字体、DPI 风格高度统一。
- 所有数值与 production 结果严格一致。

---

## 边界

- 只增强可视化，不改变答案、证据等级与定义域边界。
- 不改 science：若某图暴露结果冲突，回到 experiment，不为了好看改图。
- 图注解读必须诚实：区间是区间、拟合是拟合，不得把装饰当证据。
