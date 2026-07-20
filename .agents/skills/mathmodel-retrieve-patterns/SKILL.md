---
name: mathmodel-retrieve-patterns
description: 在路线竞争前读取当前题面和数据剖面，只从 verified 论文卡检索非同题模式，并冻结可复验的检索快照。
---

# 建模模式检索

本 Skill 是路线设计的只读前置步骤，不增加主状态或审批门。即使 verified 索引为空，也必须生成空检索快照并继续路线设计。

## 输入

1. 读取当前题面、附件清单和足够判断字段、规模、缺失、单位的数据剖面。
2. 只读取 `knowledge/indexes/papers_verified.json` 及其中命中的论文卡；禁止回退读取 `papers_provisional.json` 或旧 `papers.json`。
3. 必须提供当前题的 `canonical_problem_id` 和 `problem_asset_sha256`；任一身份相同即硬排除。
4. 旧题训练也不得在第一次独立问题拆解、路线候选冻结和第一次独立模型规格完成前开放同题论文；初次路线检索始终排除同题。

## 执行

1. 提取 `problem_type`、`data_structure`、`task_types`、关键词、问题链和数据约束。
2. 调用 `scripts/knowledge/retrieve_patterns.py`，按题型、数据结构、任务类型和关键词执行人工可解释加权检索。
3. 输出 `TASK_FINGERPRINT.json`、`RETRIEVED_PATTERNS.md`、`PATTERN_TRANSFER_PLAN.md`、`MODEL_STORYBOARD.md` 和 `RETRIEVAL_SNAPSHOT.json`。
4. 每个命中说明可迁移结构、当前题改造、需要重新验证的条件和不可迁移内容。
5. 没有高置信匹配时必须写明：
   `无高置信匹配，当前路线主要依据题面、数据和通用数学建模原则生成。`
6. verified 索引为空时还必须写明：`本轮没有使用经过验证的论文知识卡。`

## 结束检查

- 知识检索发生在候选路线生成之前；
- 没有复制论文数字、结论、代码或题目特定参数；
- 所有匹配都有可解释评分理由；
- 快照绑定 verified 索引、检索策略、任务指纹、选卡和同题排除的哈希；
- 当前运行状态未因知识产物改变。
