---
name: mathmodel-review-r4-format-visual
description: 独立检查最终 PDF 的模板、页边距、字体、公式、图表、匿名和提交包完整性。
---

# R4 格式与视觉审核

## 输入文件

- 当前 `state.json`、配置锁、比赛模板和 request 声明的 `final.pdf`；
- 绑定的 PDF、PNG/SVG、figure receipt、paper build receipt、字体与编译日志；
- 原始题面中规定的提交格式。

## 禁止读取

- 作者解释、聊天记录、R1-R3/R5/J0 报告或上一轮修复说明；
- 未在 request `read_paths` 中的源文件；
- 禁止修改 PDF、图表、论文源文件或 state。

## 执行步骤

1. 校验 request 绑定、PDF 哈希和最终 revision。
2. 用 Poppler/Typst 工具逐页渲染，检查 A4、页边距、页数、字体嵌入、匿名和文件大小。
3. 检查公式裁切、图例字号、坐标单位、灰度/色盲可读性、图表首次解释和页面溢出。
4. 核对 PDF 与 paper/figure receipt 的输出哈希一致。
5. 只写报告，不修改提交包。

## 基础 Skill 与脚本

- 基础能力：`pdf:pdf`、`skills/mathmodel-figure-templates`（匹配图型时首选）和 `skills/3coding-visual`（通用数据图 fallback）；
- `typst compile`；
- `python scripts/codex/validate_state.py runs/<run_id>`。

## Finding 证据格式

`evidence` 必须包含 PDF 页码、渲染图路径或 receipt 字段；版式问题记录测量值、模板要求和
实际值，图表问题记录图号、坐标轴、单位和输出哈希。

## 严重度

- P0：PDF 无法打开/编译、关键页面缺失、匿名或官方格式违规；
- P1：公式/图表不可读、核心数字被裁切、PDF 与生产回执不一致；
- P2：字号、间距、颜色、次要排版或附录问题。

## 通过条件

无 P0/P1，PDF 可编译且所有核心图表、字体、页边距、匿名和回执一致；verdict 为
`COMPLIANT`，否则为 `FIX_REQUIRED` 或 `NOT_COMPLIANT`。

## 输出格式

只写 request 的 `review_report.json`，verdict 只能使用既定三值，由协调器生成回执。

## 结束前自检

- [ ] 已逐页检查 PDF；
- [ ] 关键图表和公式有页码证据；
- [ ] 未修改任何生产文件；
- [ ] 报告与 request 身份字段和哈希匹配。
