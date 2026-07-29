---
name: mathmodel-visual
description: 用真实结果生成由问题和 takeaway 驱动的数学建模图表，不强制固定图种或图数。
---

# 洞察驱动图表

每张图先回答三个问题：它回答什么、读者一眼看见什么、删除后论文失去什么。第三问答不出时不画。

先读 [visual-pattern-cards.md](references/visual-pattern-cards.md)，从题目的数学对象选择视觉原型，不从图库名称反推图。二维或三维都不是质量标签：空间、场或三变量结构才使用 3D；精确比较阈值、区间和剖面时优先 2D。核心标准是一张图能否联合呈现数学对象、机制、约束边界、最终决策，以及不确定性或对照。

每张图必须声明 role：`model_understanding`（帮助评委理解数学对象）、`decisive_evidence`（证明关键结果可信）、`insight`（揭示机制、阈值、边际收益或权衡）、`stability`（舍入、采样层级、数值稳定性）。`stability` 一律进入附录，不得占据正文版面——它对内部审计有价值，对评委的边际价值远低于机制与权衡。正文应有能回答"为什么最优解是这个结构"的图。

图表先输出到 `figures/work/<figure_id>/<version>/`，登记真实 `source`、`question`、`takeaway` 和可选 `limitations`；人工看图和机械 QA 通过后再晋级 `figures/current/`，旧版进入 `figures/archive/`。使用 `register_insight_figure` 绑定当前生产结果、输入、渲染脚本与 PNG/PDF 输出。结果或脚本变化后，图必须重新生成。

在 analysis 阶段先列出 `mathematical_objects` 和 `visual_questions`。在模型输出合同中声明 `visual_outputs`，至少按实际需要保存候选解、可行边界、活跃约束、搜索轨迹、Pareto 点、状态轨迹或不确定性样本；只保存最终标量时先修模型输出，不能让绘图阶段猜造结构数据。

新运行使用 `FIGURE_PLAN.json` 2.3，把科学证据需要与竞赛阅读需要分开。每个核心问题按 `scope=Qx` 声明 `evidence_need` 和 `presentation_need`；数据结构本身决定统计单位、删失、聚合或模型选择时，再增加 `scope=whole_paper` 的数据画像判断。`evidence_need=required` 表示缺图会使关键科学证据不完整，继续作为编译硬门；`presentation_need=required` 表示公式和表格虽足以证明，但缺图会使评委难以迅速理解，初期只产生 advisory。两者都可在有具体理由时 `waived`，纯解析题不强制主图。旧 2.1/2.2 只作兼容读取。

每张 2.3 图还声明 `presentation_role`：`data_portrait`、`question_hero`、`supporting` 或 `appendix`。一个问题只确定承担主叙事的 hero figure，不按题号凑固定图数；其余图只有承担独立证据任务时才进正文。纯呈现图可读取当前运行内已冻结的 `problem/`、`analysis/` 或 `results/raw/` 文件，不得为数据画像伪造实验结果；晋级后用 `scripts/figures/register_presentation_figure.py` 登记输入、脚本、输出和人工看图回执。

需要作为正文论证证据或主叙事入口的图，除原有来源和 LaTeX 字段外，还声明 `visual_archetype`、`information_structure`、`renderer`、`visual_question`、`expected_observation`、`decision_consequence`、`generic_chart_considered`、`generic_chart_rejected_because` 和 `mechanism_annotation`。空间、集合、网络、场、决策面、区间或不确定性结构不能把普通柱形图/折线图作为唯一主图；确实最合适时必须用 `generic_chart_override_reason` 说明。renderer 由结构与已有计算选择，不强制 MATLAB。使用 `python scripts/figures/write_figure_plan.py <run_dir> --input <json>` 校验并原子写入；首版后若 PDF 评审暴露新的证据缺口，可以新增带 `review_finding` 的图，候选 PDF 冻结后不再扩图。生成后检查该图已在目标 LaTeX 小节插入、标号、交叉引用并解释；缺任何一环，先补消费闭环再继续画下一张图。

图不能由脚本直接覆盖 `figures/current/`。每次修改使用新版本目录 `figures/work/<figure_id>/<version>/` 同时生成 PNG/PDF，先独立打开检查，再执行 `python scripts/figures/promote_figure_candidate.py` 晋级。普通统计图检查文件可读和 PNG/PDF 宽高比；`diagram` 还必须输出同目录 layout JSON，检查画布边界、节点内文字、文字重叠、最小字号、箭头穿字和节点连接点居中。机械 QA 通过后仍要填写人工看图结论；同一候选版本不得反复覆盖。

用 `audit_figure_information_value()` 查看五维建议分：数学对象、机制、约束/边界、最终决策、不确定性/对照各 0--2 分，正文主图建议至少 6 分。该分数只根据原型判断设计机会，不是门禁；必须打开 PNG/PDF 检查是否真的兑现。以下情况应返修：空间题无布局或剖面，多目标题无 Pareto/可行域，动态题无状态轨迹和控制量，不确定性题只有均值，热力图只是彩色数字表，主图只比较算法分数，或图后正文没有观察、机制和决策后果。

按题目需要选择图种。不要默认要求每问有图、3D、收敛图、敏感性图、多种子图、雷达图或 evidence/publication 双份，也不靠输出份数凑数量。模板示例数据绝不能进入论文。
