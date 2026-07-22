---
name: mathmodel-retrieve-patterns
description: 在路线竞争前读取当前题面和数据剖面，生成 TASK_FINGERPRINT，从仓内论文卡检索相关模式并输出迁移计划与模型故事板。
---

# 建模模式检索

本 Skill 是路线设计的只读前置步骤，不增加主状态、知识锁或审批门。检索失败不得阻断路线生成。

## 输入

1. 读取当前题面、附件清单和足够判断字段、规模、缺失、单位的数据剖面。
2. 读取 `knowledge/indexes/papers.json` 及命中的论文卡。
3. 禁止读取与当前旧题相同的论文卡用于基准 B 组，避免同题泄漏。

## 执行

1. 提取 `problem_type`、`data_structure`、`task_types`、关键词、问题链和数据约束。
2. 调用 `scripts/knowledge/retrieve_patterns.py`，按题型、数据结构、任务类型和关键词执行人工可解释加权检索。
3. 输出 `TASK_FINGERPRINT.json`、`RETRIEVED_PATTERNS.md`、`PATTERN_TRANSFER_PLAN.md` 和 `MODEL_STORYBOARD.md`。
4. 每个命中说明可迁移结构、当前题改造、需要重新验证的条件和不可迁移内容。
5. 没有高置信匹配时必须写明：
   `无高置信匹配，当前路线主要依据题面、数据和通用数学建模原则生成。`

## 结束检查

- 知识检索发生在候选路线生成之前；
- 没有复制论文数字、结论、代码或题目特定参数；
- 所有匹配都有可解释评分理由；
- 当前运行状态未因知识产物改变。
