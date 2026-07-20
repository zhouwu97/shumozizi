---
name: mathmodel-learn-paper
description: 读取一篇优秀数学建模论文及原题，生成包含可迁移模式、缺陷、不可迁移内容和来源页码的仓内论文卡，并更新简单索引。
---

# 优秀论文学习

只生成知识资产，不修改 `runs/<run_id>/state.json`，不创建知识锁、回执或批准门。

## 输入

1. 读取一篇本地只读优秀论文及其原题；不得修改或复制原始文件到 Git 仓库。
2. 使用 `scripts/knowledge/inventory_sources.py` 获取来源相对路径与 SHA-256。
3. 若论文缺少原题、页面不可读或来源不明确，停止制作该卡并记录原因。

## 执行

1. 阅读摘要、问题链、模型、求解、验证、图表、评价、附录和来源页码。
2. 写入 `knowledge/cards/papers/<paper_id>.md`，使用 YAML front matter：
   `paper_id`、`title`、`source_file`、`source_sha256`、`problem_type`、`data_structure`、`task_types`。
3. 正文必须包含核心问题、各问问题链、共享数学对象、模型选择依据、baseline 设计、验证设计、论文论证结构、图表承担的作用、可迁移模式、不可迁移内容、论文不足、缺失验证、复现风险和来源页码。
4. 不自动判断论文“优秀程度”，不把原论文数字、结论或代码迁移到新题。
5. 执行 `python scripts/knowledge/build_index.py` 更新 `knowledge/indexes/papers.json`。

## 结束检查

- 来源哈希与清点报告一致；
- 卡片不是摘要改写，明确记录缺陷和迁移边界；
- 原始材料和本机路径配置未进入 Git；
- 论文索引可以重新构建。
