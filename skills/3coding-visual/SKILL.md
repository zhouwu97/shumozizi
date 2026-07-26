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
- 本阶段不负责：技术路线图、算法流程图、系统架构图、概念示意图。这些交给 `4drawio`。
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
apply_chinese_style()          # 找不到中文字体会直接抛错，杜绝静默产出英文图

import matplotlib.pyplot as plt
plt.xlabel("波数 (cm$^{-1}$)")  # 之后所有标签、图例、注释一律中文
plt.ylabel("反射率 (%)")
```

该模块已处理：跨平台中文字体选择、负号显示、`pdf.fonttype=42`（文字可被提取，
便于验收）。**严禁**手动把 `font.sans-serif` 设成 `DejaVu Sans` 或直接输出英文标签图。

图表要求：

- PDF 矢量输出，适合论文。
- 不在图内写大标题，标题交给论文 caption（Typst 的 `caption:` 或 LaTeX 的 `\caption{}`）。
- **中文论文图表的坐标轴、图例、图内注释一律中文**；英文论文才用英文。
- 不生成流程图/架构图/路线图。

图表可以由主程序或独立脚本生成，不强制固定脚本名。无论采用哪种方式，都必须保存图表对应的数据来源和生成记录。

#### Step 4 自检（提交前必做）

1. 至少抽查一张图 PDF：`pdftotext figures/xxx.pdf -` 应能看到中文标签，或用眼看
   PDF 确认无豆腐块、无残留英文轴名。
2. 若系统缺中文字体，`apply_chinese_style()` 会抛错——必须先装字体
   （Linux：`fonts-noto-cjk`/`fonts-wqy-zenhei`；Win/mac 通常自带），不要绕过。
3. `6verity` 的 `writing_check.sh` 会对每张被引用的图做"英文标签"硬检查，
   英文图会导致验收 FAIL；在本阶段就应消除，而非留到验收。
