# 绘图配方与统一样式

所有正式图必须先应用全局样式，再绘图。样式只增强表达，不改变数据。

## 全局样式（必做）

```python
import sys
sys.path.insert(0, "<skill-directory>/scripts")
from style import apply_competition_style, TEAL, GOLD, GRAY, CORAL, BLUE, PALE_GOLD

apply_competition_style()   # seaborn whitegrid + 语义调色板 + SimSun + DPI 300
```

颜色语义（与 model-native renderer 全篇一致）：
- `TEAL #147D80` 正式答案/可行；`GOLD #D6A420` 阈值与活跃边界（金色虚线）；
- `GRAY #7A8793` 敏感性/域外；`CORAL #D95D4F` 不可行/失败；`BLUE #3E6FB0` 骨架/网络。

## 质量基线

- DPI ≥ 300；PNG/PDF/SVG 三格式输出。
- 每图有标题、坐标轴标签、单位、图例；文字不重叠。
- 中文用 SimSun（`font.sans-serif` 已含），避免方框乱码。
- 色盲与灰度可辨：颜色外至少再配一个通道（线型/标记/区域）。

## 常用配方

- 点估计 + 误差带：`ax.fill_between` + `sns.lineplot` + `ax.errorbar`（见 render_advanced probability_curve）。
- 可行域：`tricontourf` + 分层散点 + 选中星形（见 feasible_region）。
- CI 对比：`ax.errorbar(ypos, est, xerr=[...])` + 阈值竖线（见 ci_forest）。
- 分组分布：`sns.violinplot` + `sns.stripplot`（见 group_violin）。

## 新图种

若数据特征需要目录外图种（桑基/和弦/泰勒等），用 seaborn/matplotlib/plotly 手写，
**数据从 production 结果文件读**，保持同一全局样式，并回填到 `figure-catalog.md`。
