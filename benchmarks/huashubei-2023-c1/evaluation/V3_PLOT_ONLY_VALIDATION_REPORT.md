# v3 仅绘图低 token 验证报告

## 范围与前置核对

- 时间：2026-07-22。
- 工作区：干净；分支为 `refactor/capability-first-v3`。
- 本地 `HEAD` 与 `origin/refactor/capability-first-v3` 同为
  `4fced067dff1ed5d10c6869e68ea3c853ed5aaca`。本次遵守“不联网”要求，未执行
  fetch，也未启动 legacy 审核、完整建模或论文写作。

## 选题与原图核对

- 旧题：`huashubei-2023-c1`，论文 B。
- 原论文：`benchmarks/huashubei-2023-c1/paper_b/paper_b.pdf`，第 2 页。
- 可比原图：图 1 为 EPDS 与婴儿睡眠时长的散点图及线性趋势线；图 2 为三类婴儿
  行为的计数柱图。
- 论文源文件：`benchmarks/huashubei-2023-c1/paper_b/main.typ`；其图像引用指向
  `runs/desktop-e2e-20260719-training/figures/`，该运行目录在当前工作区不存在。

## 停止原因

1. 目标历史 run 不存在，未发现可登记为 `current` 且 `execution_valid=true` 的 v3
   JSON 结果；因此 `scripts/figures/use_template.py` 无法合法取得 `--result-id` 输入。
2. PDF 仅提供渲染后的散点和柱形，未提供 390 条散点数据、精确分类计数或生成脚本。
   从像素反向数字化会引入未经验证的数据，超出“最小、可复现的数据提取”许可。
3. 四个已接入模板（ROC、预测边际网格、配对雨云、相关对图）均不匹配“单变量散点+趋势线”
   或“分类计数柱图”。强行套用模板会改变原图的证据类型，不能构成公平比较。

## v3 图与 Figure Contract

本次**未生成** v3 图、输入 JSON、Figure Contract 或 `figures/index.json`。这是有意停止，
不是生成失败：在缺少可审计输入时创建这些产物会制造不可追溯的证据链。

## 可比性与可推断边界

- 原图布局：一页内上下排列，散点图的连续关联与柱图的类别不平衡都可读；英文坐标轴与中文
  图注并存。
- v3 布局/可读性/证据表达：无合法 v3 图，不能评价，也不能声称优于或劣于原图。
- 不可推断：不能由 PDF 像素推断精确相关系数、回归系数、类别计数、样本外性能，亦不能推断
  v3 模板在本题上的视觉质量或证据表达效果。

## 恢复条件（不在本次范围内）

仅当恢复原始、可登记的 JSON 结果及其 result index，或提供可审计的原始表格数据，并接入与
散点/柱图匹配的 Figure Contract 模板后，才可进行一次公平的 1--2 图 v3 验证。
