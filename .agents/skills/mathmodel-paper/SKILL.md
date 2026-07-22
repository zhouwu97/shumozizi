---
name: mathmodel-paper
description: 使用 Capability-First v3 中真实执行且仍有效的结果撰写、编译和局部修订数学建模论文；用于完整论文、章节补丁和图表叙事。
---

# 证据驱动的数学建模论文

论文只有三项硬原则：数字来自真实执行；每问有直接答案；每个主张有证据和边界。不要用审批文件、评分表或虚构实验填充论文。

## 输入与可用结果

1. 读取 `state/run.json`、对应的建模与结果报告、`DECISIONS.md` 和 `results/index.json`。
2. 只使用 `status=current`、`execution_valid=true`、同合同组 registry incumbent，且 `results/quality.json` 中 `feasibility_valid=true`、`exact_recomputed=true`、`search_adequacy=passed`、`problem_effectiveness=progressed`、`result_role=accepted`、`paper_allowed=true` 的结果；这些字段还必须可回溯到已登记输出的路径、JSON 字段和哈希。若运行处于 `blocked`，或质量层缺失/失败，必须拒绝写入论文或提交事实；这同样排除仅恢复 baseline、联合覆盖不足、逐实体求和伪替并集、未通过独立挑战或未超过已验证下界的候选。若使用 `figures/` 中由科研模板生成的图，必须同时存在 `figures/index.json` 的 `status=current`、`paper_allowed=true`、`demo=false` 条目；演示模板输出不得引用。追溯信息只能写在不会渲染的注释中：Typst 使用 `// @result <result_id>` 和 `// @metric <result_id>.<metric> <number>`；LaTeX 使用同格式的 `%` 注释；Markdown 使用 HTML 注释。机械检查会验证它们与真实输出一致。
3. 采用已有 Typst 或 LaTeX 竞赛模板；比赛类型有对应模板时，按需参考 `skills/5writing/templates/` 中的对应目录，再复制到运行的 `paper/`。不要全量读取模板库，也不要因为模板存在而强行增加章节、图表或方法。源文件置于 `paper/`，章节置于 `paper/sections/`，最终编译为 `paper/final.pdf`。

## 每问必须说清楚

每个必答问题至少包含：题目要求、模型选择理由、核心公式、求解方法、关键结果、可信性检验、直接答案，以及局限与适用边界。共享模型可跨章节复用，但不能遗漏任何一个直接回答。

所有图表都先写普通 Markdown Figure Contract：回答的问题、核心结论、数据来源、每个 panel 的独立证据、选择该图的原因、黑白打印可读性，以及删除该图是否伤害论证。它是作者自检，不是 Schema、哈希门或回执。

## 近完成时的一次自审

只在论文接近完成时建立一次 Claim–Evidence 表：

| Claim | Evidence | Status | Action |
| --- | --- | --- | --- |
| 主模型优于 baseline | 图 3 / 表 4 | supported | 保留 |
| 极端场景稳定 | 单次运行 | partial | 弱化并说明 |
| 未验证的机理解释 | 无 | unsupported | 删除或补实验 |

不要建立自动 claim evaluator。发现结果替换后，只修改受影响章节、图表、摘要和结论；无需重新执行全文审查。

## 编译与交接

编译前删除占位符，确认题号、图表和单位一致。生成 `paper/final.pdf` 后更新 v3 状态到 `verify`，再调用 `$mathmodel-final-check`。严禁把失败路线、无效结果或被替代结果写成贡献。
