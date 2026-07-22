# 旧论文与 v3 绘图能力对比

## 对比对象

- 旧论文：`benchmarks/huashubei-2023-c1/paper_b/paper_b.pdf` 第 2 页。
- 新图：`figures/v3_visual_proxy_replot.png`。
- 并排图：`figures/old-vs-v3-visual-proxy.png`。

## 可见改善

1. 散点图使用透明度降低点遮挡，趋势线与点云以色盲友好蓝/橙区分；轴标签显式给出小时单位。
2. 类别柱图从零开始，补充近似数量标签，并使用颜色加纹理的冗余编码，使灰度打印仍可区分类别。
3. 两幅图采用一致字号、网格强度和 A/B 面板标识，层级比旧页更清楚。
4. 图内直接声明 `VISUAL PROXY`、`approximate` 与原始记录缺失，避免视觉改进被误读为新的实证结果。

## 不能得出的结论

原始 390 条观测和精确类别计数不在当前工作区。新图的散点与柱高是根据旧 PDF 的可见范围、趋势和柱高构造的确定性视觉代理，因此不能比较相关系数、显著性、精确计数、模型性能或科学结论。

## 可复验信息

- current 运行结果：`q1_visual_proxy_not_for_paper_v4`；类型为 `visual-proxy`。
- 输出：PNG、PDF、SVG 与并排 PNG 均已生成。
- `figqa.py` 检查两个 PNG 可读且无登记文字边界重叠。
- `verify_current_result_files()` 已复验当前输入、脚本和输出哈希。
