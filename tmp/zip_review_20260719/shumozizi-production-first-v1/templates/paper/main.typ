// CUMCM 2026 电子版论文骨架
// 电子版不要加入承诺书和编号专用页，第一页必须是摘要专用页。

#set page(
  paper: "a4",
  margin: (top: 2.5cm, bottom: 2.5cm, left: 2.5cm, right: 2.5cm),
  numbering: "1",
  number-align: center,
)

#set text(
  font: ("Noto Serif CJK SC", "Source Han Serif SC", "SimSun"),
  size: 10.5pt,
  lang: "zh",
)

#set par(justify: true, leading: 0.75em, first-line-indent: 2em)
#show heading.where(level: 1): it => block(above: 1.2em, below: 0.8em)[
  #align(center)[#text(size: 15pt, weight: "bold")[#it.body]]
]
#show heading.where(level: 2): set text(size: 12pt, weight: "bold")
#show figure.caption: set text(size: 9pt)

// ---------- 摘要专用页 ----------
#counter(page).update(1)

#align(center)[
  #text(size: 20pt, weight: "bold")[题目：在此填写论文标题]
]

#v(1.2em)
#align(center)[#text(size: 14pt, weight: "bold")[摘　要]]

本文针对……问题，围绕问题一、问题二和问题三建立……模型。

对于问题一，……，得到……。

对于问题二，……，得到……。

对于问题三，……，得到……。

本文的主要贡献是……；结论适用于……，主要局限为……。

#v(0.8em)
#text(weight: "bold")[关键词：] 关键词一；关键词二；关键词三；关键词四

// 摘要页后必须强制分页，正文不得继续出现在第一页。
#pagebreak()

// ---------- 正文 ----------
= 问题重述与分析

按子问题说明输入、输出、约束、评价目标及问题之间的继承关系。

= 数据说明与预处理

说明官方附件、自主数据、缺失与异常处理、单位和必要变换。

= 模型假设

1. 假设一及依据。
2. 假设二及适用边界。

= 符号说明

#table(
  columns: (1fr, 2.2fr, 1fr),
  inset: 6pt,
  align: (center, left, center),
  [符号], [含义], [单位],
  [$x$], [决策变量说明], [—],
)

= 问题一

== 模型建立

写出问题专属变量、目标、约束和变量域。

== 求解方法

说明算法输入、输出、关键参数和停止条件。

== 结果、验证与解释

给出核心表图、基线或对照、有效性检查、结果解释和适用边界。

= 问题二

按“题目要求—模型—求解—结果—验证—解释—边界”完整展开。

= 问题三

按“题目要求—模型—求解—结果—验证—解释—边界”完整展开。

= 模型评价与改进

只写与本题模型有关的优点、误差来源、求解界、样本限制和推广边界。

= 结论

逐问给出可直接对应题目要求的最终结论，不重复堆叠全文。

= 参考文献

[1] 作者. 文献题名. 来源, 年份.

[2] 工具名称, 版本/型号, 开发机构/公司, 使用日期.
// 使用 AI 工具时按当年规则列出；未使用时删除本条。

= AI 工具使用声明

// 二选一，并按当年规则处理正文标注和支撑材料。
本参赛队在建模、代码或文字辅助环节使用了 AI 工具。具体工具、用途、关键交互、采纳内容和人工修改情况见支撑材料中的 `AI工具使用详情.pdf`。

// 未使用时改为：
// 本参赛队未使用任何 AI 工具。

= 附录

== 支撑材料文件列表

#table(
  columns: (0.7fr, 2.2fr, 2fr),
  inset: 5pt,
  [序号], [文件路径], [用途],
  [1], [`questions/q1/run.py`], [问题一求解程序],
  [2], [`AI工具使用详情.pdf`], [AI 工具使用披露],
)

== 完整源程序

// 按实际题号和文件补齐全部完整、可运行代码。
// 示例：
// #raw(read("../questions/q1/run.py"), lang: "python", block: true)

// 若确实没有使用程序，应按当年规范明确写：
// 本论文没有用到程序。
