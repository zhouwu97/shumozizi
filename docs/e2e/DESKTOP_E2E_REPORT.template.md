# Codex 桌面版 E2E 验收报告模板

> 状态：未执行。填写实际证据前，不得把本模板表述为验收通过。

## 基本信息

- 验收日期：
- 验收人：
- 仓库提交：
- 桌面版版本：
- Python / Typst / XeLaTeX 版本：
- Fixture：`tests/fixtures/e2e_linear_fit/`
- Run ID：

## 1. 环境诊断

- `python scripts/doctor.py` 结果：
- 必需项失败：
- 可选项告警及处理：

## 2. 第一次桌面任务：路线确认

- 初始化命令：
- 发送给桌面版 AI 的提示：
- `route_candidates.json` 路径：
- 候选路线是否数学上真正不同：
- 状态是否停在 `WAITING_HUMAN_ROUTE`：
- 未提前生成正式实验/论文的证据：
- 截图或任务链接：

## 3. 人工路线锁

- 选择的 `route_id`：
- 选择理由：
- `ROUTE_LOCK.json` 路径：
- Schema 与跨文件引用校验结果：

## 4. 第二次桌面任务：恢复、实验与论文

- 是否新建独立桌面任务：
- 恢复提示：
- 是否从 `state.json` 正确恢复：
- baseline / primary / robustness 执行记录 ID：
- 非零退出、哈希、基线和创新证据准入检查：
- accepted 结果与论文数值映射：
- PDF 路径和页数：

## 5. 第二次人工暂停

- 状态是否停在 `WAITING_HUMAN_FINAL`：
- `FINAL_REVIEW_MEMO.md` 路径：
- 是否在人工批准前保持未完成：
- 截图或任务链接：

## 6. 负向检查

| 场景 | 预期 | 实际 | 证据路径 | 结论 |
| --- | --- | --- | --- | --- |
| 修改执行后的源代码 | 准入失败 |  |  | 未执行 |
| 修改执行后的输出 | 准入失败 |  |  | 未执行 |
| 主模型缺少 accepted baseline | 准入失败 |  |  | 未执行 |
| 创新缺少 robustness/ablation | 准入失败 |  |  | 未执行 |

## 7. 最终结论

- 结论：未验收 / 通过 / 有条件通过 / 不通过
- 阻塞项：
- 后续修复：
- 审核签名：
