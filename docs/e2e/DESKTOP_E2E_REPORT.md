# Gate 0 Schema v2 E2E 报告

## 验证范围

- 基线 Git SHA：`152d0c1aceff632d1ed1e2257f942a70ab768760`
- Schema 版本：`2.0`
- 测试入口：`tests/test_gate0_e2e.py`
- PDF 引擎：Typst 0.15.0
- 运行形式：每次在隔离临时仓库创建完整运行目录，避免把测试批准回执混入真实比赛运行。

## 已验证链路

自动化 E2E 实际执行下列序列并断言最终状态为 `COMPLETE`：

```text
NEW
→ WAITING_HUMAN_ROUTE
→ ROUTE_LOCKED
→ MODEL_SPEC_READY
→ EXPERIMENTING
→ RESULTS_ACCEPTED
→ PAPER_DRAFTED
→ QA_RUNNING
→ BLOCKED
→ PAPER_DRAFTED
→ QA_RUNNING
→ WAITING_HUMAN_FINAL
→ COMPLETE
```

夹具会真实生成并复验：RUN_CONFIG_LOCK、路线批准请求/回执、执行记录、JSON Pointer 指标
provenance、RFC 8785 sealed result、evidence map、Typst evidence macro、最终 PDF、基础 evidence
report、QA aggregate 和最终批准请求/回执。测试批准者显式标记为 `human-test-fixture`，不得当作
真实比赛批准复用。

## 本轮新增验证

- Profile Schema v2 已覆盖 `generic`、`mcm`、`cumcm` 和 `diangong`；规则未完成官方核验的
  配置只产生 `official-confirmation-required` warning，不会被误判为通过。
- `paper-evidence-adapter` 复验多输入表达式、单位转换、舍入、生成文件哈希和 sealed result
  来源；`mechanical-qa-adapter` 复验页数、逐页空白、重复 caption、匿名字段、提交包文件和
  图表 QA 回执。两者均已接入 QA aggregate。
- 外部研究源已登记在 `knowledge/SOURCE_REGISTRY.json`，并绑定不可变 commit；模板实例化仅允许
  写入 `runs/<run_id>/code/`，外部仓库不会成为第二状态机、结果注册表或控制面。
- 固定条件回归 `ols-closed-form-v1` 已通过：输入 SHA256 为
  `41b8b37c8750e6e8b78e592cc635c0eb1498f05f529f21fde6b886545a83680c`，输出 SHA256 为
  `e3e463afadfc7f99f06e7a649f2b0086376a9f06ee2d74d63dc187da59b0d9b8`。篡改输入、篡改
  accepted sealed result 的负向测试均按预期阻断。

本轮自动化验证结果：`34 passed`；Ruff 检查通过；固定回归状态为 `pass`。

## 跨任务恢复

恢复只读取 `runs/<run_id>/state.json` 的状态与 revision，并通过 Schema 和跨文件哈希复验当前
阶段产物。聊天记录、Codex 任务 ID 与会话 ID 不参与状态判断。

## 基线 Tag 状态

尚未创建 `codex-native-baseline-v0.1`。项目规则禁止自动提交或打 Tag；应在真实 Codex 桌面
工作区完成两个人工暂停点、确认工作树内容并由维护者明确授权后创建。
