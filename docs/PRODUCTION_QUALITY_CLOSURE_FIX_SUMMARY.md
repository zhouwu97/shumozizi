# 生产闭环与竞赛质量双轴修复总结

## 1. 本轮结论

本轮已完成计划中的 P0 代码闭环：权威问题全集、路线批准语义、运行内 Profile 快照、审核阶段
材料策略、R5 A/B 双轴、失败审核定向修复和统一 Run Integrity 已落地，并接入状态推进、离线
校验与最终批准。Gate 0 最小端到端流程和全部本地测试通过。

当前可以确认工作流的关键状态与证据链在现有测试范围内不可被缺失 Manifest、伪造文本批准、
否定式人工回复、非人类批准人、缺失审核材料、R5 轴结论不一致或过期最终回执绕过。

不能据此宣称项目已完成作品级 production-ready：仓库中没有可直接用于本轮验收的陌生完整旧题
成品，因此 Gate 1 尚未执行；远端 GitHub Actions 也没有在本地修改后重新触发。

## 2. 主要修复

1. 修复 Windows Runner 规范路径与短路径别名混用导致的逐问验收越界误判。
2. 新增 `problem/PROBLEM_MANIFEST.json` 及 Schema，冻结全部题目、必做输出、依赖和题面哈希；
   路线批准、逐问验收、论文和终审以该 Manifest 为准。
3. 路线批准强制复验请求、候选、配置锁、Manifest、人工原始回复、批准人身份和路线锁字段；拒绝
   Codex/Agent 身份、否定回复和普通文本伪装产物。
4. Profile 改为运行内版本化快照，仓库全局 Profile 后续变化不再破坏历史 Run；快照篡改仍会
   被配置锁哈希拒绝。
5. 新增 Review Stage Policy，R1-R5/J0 的强制材料、可选材料、禁止输入、硬阻断和质量维度由系统
   固定，调用者不能缩减关键输入；R5/J0 不能读取前轮报告。
6. R5 新增 A 轴完整性、B 轴竞赛质量、联合结论、修复范围和重测范围。只有 A 轴通过，且 B 轴
   总分不低于 75、题目覆盖/模型深度/实验验证均不低于 60，才允许 `FINAL_CANDIDATE`。
7. 失败审核自动生成带来源报告哈希的 `REPAIR_PLAN.json`；审核回执绑定修复计划，P0/P1 finding
   不能通过审核，回执 decision 不能覆盖报告真实语义。
8. 新增 `verify_run_integrity(run_dir, target_state)`，统一检查配置、路线批准、Manifest、结果封存、
   逐问验收、生产回执、R1-R5/J0 和最终提交包；已接入离线校验、`QA_PASSED` 与
   `FINAL_APPROVED`。
9. `COMPLETE` 会重新检查 R1、全部必做题 R2、R3、R4、R5、J0 及最终人工批准绑定，旧回执或
   生产事实变化会阻断完成。
10. 更新 AGENTS、工作流文档、Route/Workflow/R5 Skills 和 Windows CI 编译入口，使说明与运行
    契约一致。

## 3. 验证结果

```text
python -m pytest -q
104 passed in 413.78s

python -m pytest tests/test_production_closure.py -q
9 passed

python -m ruff check src scripts tests
All checks passed!

git diff --check
通过

CI py_compile 等价命令
通过
```

`python scripts/doctor.py` 检查 Python 3.12.10、37 个 JSON Schema、项目包、jsonschema、rfc8785、
pypdf 和 Typst 0.15.0 均正常。唯一环境警告是未找到 PDFInfo；当前 Gate 0 使用 Typst/PDF 库的
路径已通过，但独立 PDFInfo 检查仍需在安装 Poppler 后验证。

## 4. CI 与工作区状态

`.github/workflows/validate.yml` 已纳入新增 Manifest、Acceptance、Approval、Integrity、Repair、
Review Policy 和 Reviews 入口的 `py_compile` 检查。本轮没有触发远端 GitHub Actions，因此只能
确认本地等价测试和编译通过，不能声明远端 CI 已恢复全绿。

当前 PR #2 的远端检查仍指向旧提交 `6aa1d52`：运行 `29691891967` 的 4 个失败均发生在
`test_question_acceptance`，错误是 Windows `RUNNER~1` 与 `runneradmin` 路径混用后调用
`Path.relative_to()`。本轮已在 `relative_inside()` 中统一规范根路径并通过本地回归；提交并由远端
重新运行后才能最终确认 CI 修复。

未跟踪的 `src/shumozizi.egg-info/`、`tmp/` 和 `yunxin/` 保持原状，没有删除、提交或纳入本轮
修复。按项目规则，本轮未创建提交，也未推送分支。

## 5. 剩余风险与下一门禁

下一步必须以一套陌生完整旧题执行 Gate 1，真实走完题面解析、人工路线确认、全部问级实验、
论文与图表生产、R1-R5/J0、自动定向返工和最终人工核包。Gate 1 需要同时验证：

- 每个必做问题均有可复现实验和直接论文答案；
- 人工只参与路线确认与最终提交确认；
- 审核失败可自动生成最小修复范围并正确刷新受影响回执；
- 最终 PDF、图表、源码、引用和提交格式达到作品级要求；
- R5 A/B 双轴与 J0 均通过，且评委视角不认为任何一问缺失或质量不足。

在 Gate 1 和远端 CI 均通过前，建议 PR 继续保持 Draft，不把当前状态表述为稳定产出高水平参赛
论文。
