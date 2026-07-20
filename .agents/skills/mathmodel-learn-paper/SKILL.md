---
name: mathmodel-learn-paper
description: 读取一篇优秀数学建模论文及原题，生成 provisional Paper Card v2、证据图，并在独立审核后单卡晋级。
---

# 优秀论文学习

只生成知识资产，不修改 `runs/<run_id>/state.json`。论文卡制作对话无权把卡片标记 verified，也无权生成晋级回执。

## 输入

1. 读取一篇本地只读优秀论文及其原题；不得修改或复制原始文件到 Git 仓库。
2. 使用 `scripts/knowledge/inventory_sources.py` 获取来源相对路径与 SHA-256。
3. 若论文缺少原题、页面不可读或来源不明确，停止制作该卡并记录原因。
4. 在 `knowledge/reviews/paper_source_registry.json` 使用稳定 `source_id` 登记论文和官方题面身份；不得依赖扫描顺序生成 ID。

## 执行

1. 阅读摘要、问题链、模型、求解、验证、图表、评价、附录和来源页码。
2. 写入 `knowledge/cards/papers/<paper_id>.md`，使用 Card v2 front matter，至少包含：
   `paper_id`、`card_version`、`source_id`、`source_asset_sha256`、`canonical_problem_id`、
   `problem_asset_sha256`、`paper_asset_sha256`、`problem_type`、`data_structure`、`task_types`、
   `model_family`、`validation_methods`、`assumption_pattern`、`argument_pattern`、`failure_modes`、
   `transferable_patterns`、`non_transferable_context`、`evidence_locations`、`review_status` 和
   `authoring_session_id`。草稿状态只能是 `provisional` 或 `revision_required`。
3. 正文必须包含核心问题、各问问题链、共享数学对象、模型选择依据、baseline 设计、验证设计、论文论证结构、图表承担的作用、可迁移模式、不可迁移内容、论文不足、缺失验证、复现风险和来源页码。
4. 不自动判断论文“优秀程度”，不把原论文数字、结论或代码迁移到新题。
5. 为每个重要主张写入 `knowledge/reviews/evidence_maps/<paper_id>.json`，绑定页码、章节、
   图表/公式位置和原文片段 SHA-256，不能只检查章节标题。
6. 执行 `python scripts/knowledge/build_index.py`；草稿只能进入 provisional 索引。

## 独立审核与晋级

1. 用户必须在 Codex 桌面版新开独立顶层对话；审核会话不得等于 `authoring_session_id`。
2. 审核对话读取原论文、官方题面、Card v2 和 evidence map，写入
   `knowledge/reviews/reports/<paper_id>.json`，结论只能是 `verified`、`revision_required` 或 `rejected`。
3. 审核不能修改原卡；存在 open finding 时不能判 `verified`。
4. 只有审核结论为 `verified` 后，生产对话才能显式执行：
   `python scripts/knowledge/promote_card.py <paper_id>`。
5. 晋级命令逐卡生成绑定来源、卡片、证据图、审核报告和审核身份的 promotion receipt；禁止批量自动晋级历史卡。

## 结束检查

- 来源哈希与清点报告一致；
- 卡片不是摘要改写，明确记录缺陷和迁移边界；
- 原始材料和本机路径配置未进入 Git；
- provisional 与 verified 索引可以确定性重建；
- 未生成 promotion receipt 的卡片不能进入 verified 索引。
