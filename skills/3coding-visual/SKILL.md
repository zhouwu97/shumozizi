---
name: 3coding-visual
description: "数学建模编程实现与数据图表生成阶段。根据 ANALYSIS_MODELING_REPORT.md 编写可复现代码、运行求解、验证约束、输出 RESULTS_REPORT.md 并生成论文可用的数据驱动图表 PDF。"
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, Agent, WebSearch, WebFetch
---

# 编程实现与数据图表生成

本 skill 承接 `2analysis-modeling`。目标是把 `reports/ANALYSIS_MODELING_REPORT.md` 里的模型和算法落实为可复现程序，跑出可信结果，并生成论文中需要的数据型图表。

## 数学建模规范参考

如需领域判断，读取 `../_references/math_modeling_norms.md` 中的“题型防错速查”“代码实现与结果”“编码阶段常见错误”和“图表与可视化”小节。该文件只作为规范知识库，不新增本阶段的固定产物。

## 阶段边界

- 本阶段负责：代码、实验运行、结果、结果表、数据驱动图表。
- 本阶段不负责：技术路线图、算法流程图、系统架构图、概念示意图。这些先交给 `mathmodel-paper-image` 规划候选，正式可编辑图由 `4drawio` 重建。
- 本阶段不写论文正文，只为 `5writing` 提供可信数值和图表资产。


### Step 1: 代码结构

按 `plan.md` 中"项目目录结构"创建 `code/` 和 `figures/` 骨架，再开始写代码。子问题数不一定是 3，按赛题实际数量调整。


### Step 2: 逐子问题实现

按子问题顺序实现，不要一次性写完不跑。

每个子问题必须完成：

1. 读取所需数据。
2. 实现模型或算法。
3. 验证约束。
4. 输出核心结果。
5. 绘制丰富的图表。
6. 在 `reports/RESULTS_REPORT.md` 中写清楚方法、关键数值和校验结果。

优化类问题必须先保证可行解，再优化目标值。预测类问题必须做训练/验证划分或合理误差评估。评价类问题必须说明指标方向、归一化方法和权重来源。

### Step 3: 结果文件格式


AI 在实现、求解和作图过程中，必须把关键中间过程保存成数据并做好记录，例如清洗后的数据摘要、模型参数、迭代历史、约束检查、灵敏度分析过程、图表所用数据和运行日志。中间数据优先保存到 `figures/` 或 `code/outputs/`，并在 `reports/RESULTS_REPORT.md` 中说明文件用途。

`reports/RESULTS_REPORT.md` 推荐结构：

```markdown
# 计算结果

## 运行环境
## 数据读取与预处理
## 问题一结果
## 问题二结果
## 问题三结果
## 灵敏度分析
## 约束与一致性校验
## 与建模报告的一致性说明
## 可复现运行方式
```

所有数据和图表结果都必须出现在 `reports/RESULTS_REPORT.md` 中引用

### Step 4: 生成数据驱动图表

根据 `reports/ANALYSIS_MODELING_REPORT.md` 和 `reports/RESULTS_REPORT.md` 规划图表，生成 PDF 到 `figures/`。

**中文字体是硬性要求（此前最常见的失分点）。** 中文论文的数据图若用 matplotlib
默认字体，坐标轴/图例会变成英文、中文变豆腐块，属于国奖硬伤。因此每个作图脚本
**必须**在作图前引入本 skill 提供的字体引导模块：

```python
import sys
sys.path.insert(0, "<本 skill 路径>/scripts")   # 例如 skills/3coding-visual/scripts
from mpl_setup import apply_chinese_style

# profile 决定网格等"风格"参数；字体嵌入与负号修复始终生效。
apply_chinese_style()                          # 折线图/柱状图/散点图（默认）
apply_chinese_style(profile="heatmap")         # 热力图（关闭网格，避免切割色块）
apply_chinese_style(profile="geometry3d")      # 三维几何图（Axes3D 自管网格）
apply_chinese_style(profile="radar")           # 雷达图/极坐标
apply_chinese_style(profile="network")         # 网络图（配合 ax.axis("off")）
apply_chinese_style(profile="schematic")       # 示意图/技术路线图
apply_chinese_style(profile="image")           # 原始图像（imshow）

import matplotlib.pyplot as plt
plt.xlabel("波数 (cm$^{-1}$)")  # 之后所有标签、图例、注释一律中文
plt.ylabel("反射率 (%)")
```

**profile 选择原则**：字体嵌入（`pdf.fonttype=42`）与负号修复（`unicode_minus`）
是硬配置，所有图类型都生效。`axes.grid` 等风格参数随 profile 而变：

| 图类型 | profile | grid |
|---|---|---|
| 折线/柱状/散点 | `"line"`（默认） | True |
| 热力图 / imshow | `"heatmap"` / `"image"` | False |
| 三维几何图 | `"geometry3d"` | False |
| 雷达/极坐标 | `"radar"` | False |
| 网络图 | `"network"` | False |
| 示意图 | `"schematic"` | False |

**严禁**手动把 `font.sans-serif` 设成 `DejaVu Sans` 或直接输出英文标签图。

图表要求：

- PDF 矢量输出，适合论文。
- 不在图内写大标题，标题交给论文 caption（Typst 的 `caption:` 或 LaTeX 的 `\caption{}`）。
- **中文论文图表的坐标轴、图例、图内注释一律中文**；英文论文才用英文。
- 不生成流程图/架构图/路线图。
- **图种必须多样，不能只画折线/柱状。** 每个核心问题至少产出两类不同论证角色的高级图，
  例如小提琴/箱线/云雨（数据直觉）、带置信带的平滑/生存/达标曲线（机制）、SHAP/特征重要性
  （解释）、校准/PR/ROC/混淆矩阵（判别验证）、Bootstrap/森林图（不确定性）、灵敏度矩阵
  （决策稳健）。
- **数据图优先用 sci-box 母版模板（复制原脚本，只换数据入口）。** 选图顺序固定为：
  ① `skills/sci-box/scibox-figure` 母版模板（`scripts/figures/use_template.py --adaptation direct`，
  自动复制原模板脚本并只替换真实数据入口，保留 layout/panels/typography）→
  ② 模板深度改造/组合（`--adaptation manual` 或手工改复制脚本，允许拆/并/删面板）→
  ③ `scibox-diagram`（结构解释图）→ ④ 本题专用高级 Matplotlib/真实结构原型 →
  ⑤ 普通 scatter/heatmap/line → ⑥ bar（最后选择）。选模板前必须打开
  `skills/sci-box/scibox-figure/assets/previews/` 的 preview 实际看图，禁止只凭模板名选。
  数据支撑时画组合图（多个关联面板拼一张），不用单面板草率了事。目标是用图承担数据直觉、
  机制、决定性证据、边界等真实论证角色，不是凑到某个数量；第二阶段的图补充只应覆盖实验阶段
  遗漏的角色，不能替代实验阶段本身的丰富度。

流程、方法和机理解释图不得把 AI 生成的数字或公式当作正式结果；需要数据绑定时必须回到确定性 renderer。

图表可以由主程序或独立脚本生成，不强制固定脚本名。无论采用哪种方式，都必须保存图表对应的数据来源和生成记录。

#### Step 4 自检（提交前必做）

1. 至少抽查一张图 PDF：`pdftotext figures/xxx.pdf -` 应能看到中文标签，或用眼看
   PDF 确认无豆腐块、无残留英文轴名。
2. 若系统缺中文字体，`apply_chinese_style()` 会抛错——必须先装字体
   （Linux：`fonts-noto-cjk`/`fonts-wqy-zenhei`；Win/mac 通常自带），不要绕过。
3. `6verity` 的 `writing_check.sh` 会对每张被引用的图做"英文标签"硬检查，
   英文图会导致验收 FAIL；在本阶段就应消除，而非留到验收。

