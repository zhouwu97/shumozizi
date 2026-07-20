---
name: mathmodel-route
description: 读取数学建模题面与附件，完成题意解析、关键歧义、2–3 条实质不同的候选路线、基线、创新、验证、成本和风险设计。用于完整工作流的路线竞争阶段，完成后必须停在人工路线确认点。
---

# 数学建模路线竞争

只做路线设计，不写完整建模报告、正式代码、实验或论文。

## 前置检查

1. 读取 `runs/<run_id>/state.json`，只在 `NEW` 或人工要求重新提案时执行。
2. 读取 `problem_source` 指向的全部题面和附件，不修改原文件。
3. 对表格和数据只做足以判断路线的结构、字段、规模、缺失和单位检查。
4. 先调用 `$mathmodel-retrieve-patterns`，读取其生成的 `TASK_FINGERPRINT.json`、
   `RETRIEVED_PATTERNS.md`、`PATTERN_TRANSFER_PLAN.md`、`MODEL_STORYBOARD.md` 和
   `RETRIEVAL_SNAPSHOT.json`。
   检索失败时记录原因并继续，不得把知识产物升级为审批门。
5. 如需领域规范，读取 `skills/_references/math_modeling_norms.md` 的相关小节。

## 候选路线

生成 2–3 条数学本质或关键假设真正不同的路线。不能只把随机森林、XGBoost、神经网络
包装成三条路线。每条路线必须包含：

- 题意解释与关键歧义处理；
- 数学本质；
- 共享数学对象和各问如何递进；
- 借鉴模式、针对当前题的改造和明确不可迁移内容；
- 当前数据是否支持核心参数和验证；
- 简单可靠基线；
- 正式主模型；
- 本题特定创新；
- 对照、消融、误差或敏感性验证；
- 计算成本与比赛可行性；
- 数据、可辨识性和计算风险；
- 主路线失败后的退路。

推荐路线必须解释为何适合评分目标、数据、时间和可解释性，被拒路线也要写具体理由。
不得只比较模型名称，必须比较完整研究路线和论文主线。

## 输出和暂停

1. 按 `schemas/route_candidates.schema.json` 写入 `brief/route_candidates.json`，并绑定当前
   `knowledge/RETRIEVAL_SNAPSHOT.json` 的路径与 SHA-256。
2. 按 `schemas/problem_manifest.schema.json` 写入 `problem/PROBLEM_MANIFEST.json`，完整列出题号、
   `required`、required outputs、依赖和题面来源；路线批准请求必须绑定其哈希。
3. 写入人工可读的 `brief/ROUTE_BRIEF.md`，内容与 JSON 一致。
4. 通过 `StateService.transition()` 更新 `state.json`：
   - `status`: `WAITING_HUMAN_ROUTE`
   - `completed_stages`: 加入 `route_proposal`
   - `active_stage`: `human_route_review`
   - `route_locked`: `false`
5. 创建绑定配置锁、候选路线和问题全集的 `brief/route_approval_request.json`。
6. 执行 `python scripts/codex/validate_state.py runs/<run_id>`。
   路线批准物化后，`ROUTE_LOCK.json` 必须只保存检索快照引用，不复制整个知识索引。
7. 向用户总结候选路线、推荐理由和需要确认的歧义，然后停止。

不得替用户写入已批准的 `ROUTE_LOCK.json`，也不得继续调用分析、实验或论文 Skill。
