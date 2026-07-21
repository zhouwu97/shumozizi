---
name: mathmodel-review-r4-format-visual
description: 独立检查最终 PDF 的模板、页边距、字体、公式、图表、匿名和提交包完整性。
---

# R4 格式与视觉审核

## 执行主体

本 Skill 只能在用户新开的独立 Codex 桌面版顶层对话中执行。用户只负责提交审核请求；当前
对话中的审核 AI 必须自动完成领取、校验、渲染、测量、视觉判断和报告写入，不得要求用户辅助
检查 PDF 或代填报告。禁止使用子 Agent、fork、生产聊天上下文或生产主对话直接执行本审核。

## 输入文件

- 本轮 manifest、request、session、配置锁、比赛规则、官方模板和 `final.pdf`；
- 绑定的 PDF、PNG/SVG、figure receipt、paper build receipt、字体与编译日志；
- 原始题面中规定的提交格式。

## 禁止读取

- 作者解释、聊天记录、R1-R3/R5/J0 报告或上一轮修复说明；
- 未在 request `read_paths` 中的源文件；
- 禁止修改 PDF、图表、论文源文件或 state。

## 执行步骤

先读取并复验 request 强制绑定的 `review/FORMAT_AUDIT.json`。A4、页边距、字体嵌入、摘要、
关键词、匿名、裁切、文本重叠、引用链接和图片 DPI 等机器硬失败不能被人工视觉结论覆盖。

1. 校验 manifest、request、session、PDF 哈希和最终 revision。
2. 用 Poppler/Typst 工具逐页渲染，检查 A4、页边距、页数、字体嵌入、匿名和文件大小。
3. 检查公式裁切、图例字号、坐标单位、灰度/色盲可读性、图表首次解释和页面溢出。
4. 独立评价最拥挤页面、最难读图表、字号层级、公式负担、图表与正文扫描路径、摘要信息密度、
   留白主次和图注自解释性；验证评委能否在两分钟内找到各问答案。
5. 核对 PDF 与 paper/figure receipt 的输出哈希一致。
6. 只写报告，不修改提交包。

## 双结论

报告必须把两个结论明确分开写入文字证据，不得用一个 `COMPLIANT` 代替：

- `FORMAT_HARD_COMPLIANCE`：只回答官方模板、匿名、页面规格、裁切、缺字、文件可打开、字体与
  附件硬要求，结论为 `PASS` 或 `FAIL`；
- `PRESENTATION_QUALITY`：评价扫描效率、层级、图表、公式、摘要和页面密度，结论为
  `STRONG`、`ADEQUATE` 或 `WEAK`，并指出最影响评委阅读的一处问题。

`FORMAT_HARD_COMPLIANCE=PASS` 只代表没有违规，不代表排版优秀。展示质量问题按实际影响给
P1-P3；除非导致不可评审，否则不得伪装成硬格式失败。

## 基础 Skill 与脚本

- 基础能力：`pdf:pdf`、`skills/mathmodel-figure-templates`（匹配图型时首选）和 `skills/3coding-visual`（通用数据图 fallback）；
- `typst compile`；
- `python scripts/codex/validate_state.py runs/<run_id>`。

## Finding 证据格式

`evidence` 必须包含 PDF 页码、渲染图路径或 receipt 字段；版式问题记录测量值、模板要求和
实际值，图表问题记录图号、坐标轴、单位和输出哈希。每条 finding 同时声明
`change_level`、`affected_questions`、`change_class`、`route_impact` 和
`changed_route_core_fields`；问题所在阶段不得替代路线影响判断，只有最终有效等级为 `L5`
才要求路线重新批准。

## 严重度

- P0：PDF 无法打开/编译、关键页面缺失、匿名或官方格式违规；
- P1：公式/图表不可读、核心数字被裁切、PDF 与生产回执不一致；
- P2：字号、间距、颜色、次要排版或附录问题。

## 通过条件

`FORMAT_HARD_COMPLIANCE=PASS`、无 P0/P1，PDF 可编译且所有核心图表、字体、页边距、匿名和
回执一致；verdict 为 `COMPLIANT`。展示质量为 `WEAK` 时即使硬合规也使用 `FIX_REQUIRED`；
硬合规失败时使用 `NOT_COMPLIANT`。

## 输出格式

只写 request 的 `review_report.json`，verdict 只能使用既定三值，由协调器生成回执。

## 结束前自检

- [ ] 已逐页检查 PDF；
- [ ] 关键图表和公式有页码证据；
- [ ] 未修改任何生产文件；
- [ ] 报告与 request 身份字段和哈希匹配。
