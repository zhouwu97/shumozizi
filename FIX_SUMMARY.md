# 工作流修复总结报告

基于 `C:\Users\haha\Desktop\报告.md` 的综合审计，对 `shumozizi-review` 仓库 (`fix/objective-paper-workflow` 分支，commit `415291b`) 完成了 5 项 P0 结构性缺陷修复。

---

## 修复清单

### P0-#1：语义歧义门禁不可绕过（`review.py`）

**问题：** `selection_confidence="medium"` 可以绕过用户裁决。AI 只要不填 `"ambiguous"`，就能将 `sum_per_entity` vs `intersection_all` 这类完全改变答案的歧义当成"建模假设"放行。

**修复：**
- 新增 `_derive_semantic_conflict_fields()` — 从结构化 `aggregation` 枚举机器判定冲突，不依赖 AI 自评
- 定义冲突聚合对：`(sum_per_entity, intersection_all)`, `(sum_per_entity, union_any)`, `(multiobjective, intersection_all)`, `(multiobjective, sum_per_entity)`
- 自动填充 `distinct_aggregation_count`, `changes_primary_result`, `changes_strategy`, `language_uniquely_resolves`, `user_decision_required`
- 当 `user_decision_required == true` 时，无论 AI 自评 `selection_confidence` 为何，均强制要求 `human_confirmation_required=true` 和 `selection_basis="user_decision"`
- `_human_ambiguity_binding()` 同步更新，机器冲突也触发人工裁决文件校验
- 机器派生字段在 `import_objective_semantics_review()` 中持久化回盘

**影响文件：**
- `src/shumozizi/simple/review.py` — 新增 `_derive_semantic_conflict_fields()`, `_SEMANTIC_CONFLICT_PAIRS`；修改 `_validate_objective_assessment`, `_human_ambiguity_binding`, `import_objective_semantics_review`
- `schemas/objective_semantics_assessment.schema.json` — 新增 6 个可选字段
- `tests/test_objective_semantics_review.py` — 新增 3 个回归测试

---

### P0-#2：科学审查改为逐问裁决（`review.py` + `schema` + `CLI`）

**问题：** `competition_strength` 和 `verdict` 是整次 run 单一全局字段。Q1 的强几何证据和 Q5 的动作挑战可以间接替 Q3 的无效第三弹背书。

**修复：**
- Schema v1.6 新增 `question_reviews` 数组（每项含 `question_id`, `verdict`, `competition_strength`, `evidence_ids`, `blocking_findings`）
- `import_scientific_review()` 新增 `question_reviews` 参数
- `_validate_question_reviews()` — 逐问校验全覆盖必答问题、verdict/strength 合法性
- `scientific_review_status()` — 逐问模式下任一必答问题非 pass → `allowed=false`；任一问题 strength 不达标 → `submission_ready=false`
- CLI `import_review.py` 新增 `--per-question Q1=pass,strong Q3=needs_rework,weak` 参数

**影响文件：**
- `src/shumozizi/simple/review.py`
- `schemas/simple_review_summary.schema.json` — v1.6
- `scripts/review/import_review.py`

---

### P0-#3：固定动作删除消融检查（`review.py` + `schema`）

**问题：** 现有 `action-activation-challenge` 仅针对 `action_cardinality == "variable"`（如 Q5 的 0-15 枚）。固定要求投 3 枚的 Q3 完全不被检查——第三弹边际贡献为 0 也能标记 `qualified`。

**修复：**
- 新增 `fixed-action-utilization` 证据类型
- Schema 定义：`fixedActionUtilization` 含 `required_action_count`, `full_objective`, `marginal_gains`, `tolerance`, `all_required_actions_material`, `verdict`
- `_require_competition_strength_evidence()` 新增固定动作检查段：
  - 对所有 `action_cardinality == "fixed"` 且 `allowed_action_count >= 2` 的问题要求 `fixed-action-utilization` 证据
  - 任一动作边际贡献 ≤ tolerance → 阻断 `qualified/strong`
  - 要求联合重搜或降级为 weak

**影响文件：**
- `src/shumozizi/simple/review.py`
- `schemas/red_team_semantic_output.schema.json`

---

### P0-#4：目标语义哈希级联失效（`review.py`）

**问题：** 重新解释 Q5 目标后，只撤销审查结论 (`scientific_review.verdict = "revoked"`)，不标记旧结果/质量/图/Excel 为 stale。旧 30.55 结果仍然留在结果索引中作为 `current`。

**修复：**
- 新增 `_stale_results_for_objective_change()` — 目标语义变化后自动将未绑定新目标哈希的 `production` 结果从 `current` → `superseded`
- `import_objective_semantics_review()` 在摘要撤销后调用此函数
- 同时调用 `update_simple_state(phase="analysis")` 强制回退至分析阶段
- `register_result()` 新增 `objective_semantics_sha256` 可选参数
- Schema 新增 `objective_semantics_sha256` 字段

**影响文件：**
- `src/shumozizi/simple/review.py`
- `src/shumozizi/simple/results.py`
- `schemas/simple_result_index.schema.json`

---

### P0-#5：科学审查包去标签化（`review.py`）

**问题：** `_copy_packet_tree()` 通过 `shutil.copy2` 全量复制 `results/raw/` 到 `candidate_results/`。文件名含 `quality/verified/accepted/best/final` 的文件和 JSON 内字段均被泄露给盲审者。

**修复：**
- 新增 `_PACKET_LABEL_EXCLUDE` 正则 — 匹配 `quality`, `verified`, `accepted`, `best`, `final`, `paper_allowed`, `search_adequacy`, `competition_strength`, `qualified`, `strong`, `current`, `candidate_accepted`
- 新增 `_packet_should_exclude()` — 在 `_copy_packet_tree()` 中拦截文件名含标签的文件
- 测试增强：`test_paper_requires_current_scientific_review_and_packet_is_sanitized` 新增 quality-labeled 文件泄露断言

**影响文件：**
- `src/shumozizi/simple/review.py`
- `tests/test_independent_review_workflow.py`

---

## 额外修复

- **AGENTS.md 阶段链同步：** 阶段链补全 `final_review`，主动能力列表补全 13 项（含 geometry-visual, geometry-oracle, optimizer-benchmark），红队描述更新为包含目标语义预审

---

## 测试结果

```
114 passed in 342.29s (0:05:42)
```

测试覆盖：
- `test_objective_semantics_review.py` — 7 项（含 3 项新回归测试）
- `test_semantic_schemas.py`
- `test_independent_review_workflow.py`
- `test_review_contracts.py`
- `test_review_closures.py`
- `test_review_change_levels.py`
- `test_review_modes.py`
- `test_review_scope_invalidation.py`

---

## 尚未修复的 P1 项（建议后续提交）

以下 P1 项需要更长时间设计，不阻塞本次合并：

1. **搜索充分性拆分** — `cardinality_coverage` vs `within_cardinality_search` 仍是合并的
2. **红队 production_value 来源绑定** — 仍由脚本自报，未强制 `json_pointer + sha256` 从冻结候选读取
3. **连续几何数值证书** — 仍是布尔打勾，未强制 `derived_error_bound = spacing × lipschitz` 复算
4. **论文编译前 argument_outline 硬门** — `compile_paper()` 仍未检查 `argument_outline.json`
5. **`$research-writing-skill` 名称绑定** — 仍未建立 `mathmodel-research-writing` Skill
6. **完整源码附录范围** — `sufficiency.py` 仍强制全量 `code/**/*.{py,m}`，与 Skill 描述不一致

---

## 建议

```text
保留 origin/fix/objective-paper-workflow
暂不合并 main
本次 5 项 P0 修复后可合并
P1 项在下一次提交中处理
```
