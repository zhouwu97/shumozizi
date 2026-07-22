---
name: mathmodel-paper
description: 使用 Capability-First v3 中真实执行且仍有效的结果撰写、编译和局部修订数学建模论文；用于完整论文、章节补丁和图表叙事。
---

# 证据驱动的数学建模论文

论文只有三项硬原则：数字来自真实执行；每问有直接答案；每个主张有证据和边界。不要用审批文件、评分表或虚构实验填充论文。

## 输入与可用结果

1. 读取 `state/run.json`、对应的建模与结果报告、`DECISIONS.md` 和 `results/index.json`。
2. 只使用 production scope、`status=current`、`execution_valid=true`、同合同组 registry accepted/incumbent，且拥有完整独立 evidence chain 的结果：candidate generator 的原始 pool/trace、exact scorer 对硬约束和 exact objective 的独立重算，以及 search auditor 对覆盖、校准、挑战独立性和选择影响的独立审计。三段产物都必须与冻结合同的 adapter id/version、受控源路径和命令、输入输出哈希对应；generic runtime 验证来源链，不代替题目数学。生成器自己写入的 `feasibility`、`exact_recomputed`、`search_adequacy`、`problem_effectiveness` 或旧质量布尔字段均不能放行。`exploration`、legacy `diagnostic/unverified`、候选、拒绝、未评估、被替代或无完整 provenance 的结果必须拒绝写入论文、图表或提交事实；这同样排除仅复制 baseline、联合覆盖不足、逐实体求和伪替并集和弱/不可审计挑战者。若使用 `figures/` 中由科研模板生成的图，必须同时存在 `figures/index.json` 的 production scope、`status=current`、`paper_allowed=true`、`demo=false` 条目；演示模板输出不得引用。追溯信息只能写在不会渲染的注释中：Typst 使用 `// @result <result_id>` 和 `// @metric <result_id>.<metric> <number>`；LaTeX 使用同格式的 `%` 注释；Markdown 使用 HTML 注释。机械检查会验证它们与真实输出一致。
3. 采用已有 Typst 或 LaTeX 竞赛模板；比赛类型有对应模板时，按需参考 `skills/5writing/templates/` 中的对应目录，再复制到运行的 `paper/`。不要全量读取模板库，也不要因为模板存在而强行增加章节、图表或方法。源文件置于 `paper/`，章节置于 `paper/sections/`，最终编译为 `paper/final.pdf`。

## 轻量离线论文参考

只有 production 结果已经冻结后，才可按需读取 1-2 张已登记的离线论文卡。它们只用于改善当前论文的章节组织、模型解释表达、验证叙事和 Figure Contract；不是 `$mathmodel-learn-paper` 的运行入口，也不与本 Skill 合并。

不得迁移论文卡或其原论文中的数值、结论、代码、原公式段或实验结果，不得将其作为 citation、evidence 或 Claim-Evidence 表。论文中的每一个题目事实、指标、图表和结论仍必须来自本次 production accepted/current 结果与其独立证据链。

## 贡献账本

在起草和终稿自审时维护一个紧凑的 contribution ledger。每条贡献必须绑定当前运行的证据与限制，且只可归入题目特定的结构、模型、算法、实证或表达贡献：

| 问题/章节 | 类型 | 题目特定内容 | 当前运行证据 | 限制与诚实表述 |
| --- | --- | --- | --- | --- |
| Q? | 结构 / 模型 / 算法 / 实证 / 表达 | 对当前题目标、约束、数据或解释的具体适配 | production result、公式、实验或审计产物 | 适用条件、未验证部分，以及“创新”或“方法组合”的准确措辞 |

通用 Skill、质量协议、adapter、已有算法的直接调用和普通图表都不是数学创新。若证据只支持可复现的工程实现或既有方法组合，应如实称为“工程实现”或“方法组合”，说明其对当前题的适配与限制，不把它写成新模型、新算法或新实证发现。离线论文卡不能为账本提供事实或证据。

若要将某项题目特定工作写成数学创新，账本还必须绑定一条当前运行可重放的链：机制差异、可检验预测、带明确指标与方向的对照改善，以及单组件消融。可使用角色独立的 accepted/current 结果，或使用同一 current primary 的 exact scorer 中两个受控、哈希绑定的附属产物分别承载对照与消融；后一种适用于同组 registry 只保留一个 incumbent 的情形。两种模式都不能让一份结果或同一附属产物自证全部角色。该结构只约束证据角色与可追溯性，不自动裁定数学正确性，也不要求每题提出创新。缺少任一环时，应降级为方法组合或工程实现。

## 每问必须说清楚

每个必答问题至少包含：题目要求、模型选择理由、核心公式、求解方法、关键结果、可信性检验、直接答案，以及局限与适用边界。共享模型可跨章节复用，但不能遗漏任何一个直接回答。

## 五问内容蓝图

五问赛题不预设题意或算法；Q1-Q5 各自必须有独立、可定位的直接答案，而不是把答案隐含在总表、图注或前一问叙述中。每问至少覆盖：题目要求和采用解释、变量/数据/假设、核心模型或公式、实际求解过程、来自本次运行的结果、验证与限制、面向题目的直接答案；只有合同明确依赖时，才说明其消费的前序结果。

| 问题 | 必须可定位的直接回答 | 重点内容块 |
| --- | --- | --- |
| Q1 | 对 Q1 要求的完整结论、单位/对象与适用范围 | 题意解释、基础模型、最小可行求解、结果、验证/限制 |
| Q2 | 对 Q2 要求的完整结论，并说明是否依赖 Q1 | Q2 特有目标/约束、复用或调整的模型、实际计算、结果、验证/限制 |
| Q3 | 对 Q3 要求的完整结论，并说明是否依赖前序 | Q3 特有数据/情景/决策、模型或算法选择、实际计算、结果、验证/限制 |
| Q4 | 对 Q4 要求的完整结论，并说明是否依赖前序 | Q4 特有对象/尺度/耦合、模型或算法选择、实际计算、结果、验证/限制 |
| Q5 | 对 Q5 要求的完整结论，并说明是否依赖前序 | Q5 特有要求、模型或汇总逻辑、实际计算、结果、验证/限制 |

公式、图、表和引用必须服务于相应问题的直接答案：给出必要核心公式和真实结果图表，不以堆砌数量替代解释；引用只用于实际采用的外部定义、数据或方法背景，不能用论文卡补充证据或凑密度。

所有图表都先写普通 Markdown Figure Contract：回答的问题、核心结论、数据来源、每个 panel 的独立证据、选择该图的原因、黑白打印可读性，以及删除该图是否伤害论证。它是作者自检，不是 Schema、哈希门或回执。

## 近完成时的一次自审

只在论文接近完成时建立一次 Claim-Evidence 表：

| Claim | Evidence | Status | Action |
| --- | --- | --- | --- |
| 主模型优于 baseline | 图 3 / 表 4 | supported | 保留 |
| 极端场景稳定 | 单次运行 | partial | 弱化并说明 |
| 未验证的机理解释 | 无 | unsupported | 删除或补实验 |

不要建立自动 claim evaluator。发现结果替换后，只修改受影响章节、图表、摘要和结论；无需重新执行全文审查。

这张自审表只核对本次 production 运行的证据；离线论文卡不得作为其中的 citation、evidence 或 Claim-Evidence 输入。

## 编译与交接

编译前删除占位符，确认题号、图表和单位一致。生成 `paper/final.pdf` 后更新 v3 状态到 `verify`，再调用 `$mathmodel-final-check`。严禁把失败路线、无效结果或被替代结果写成贡献。
