---
name: mathmodel-final-check
description: 对已通过独立 PDF 盲审的 Capability-First v3 论文执行机械 QA、追溯复验，并准备第三轮最终交付审核；仅在 verify 和 final_review 阶段、完整论文即将提交时使用。
---

# 最终机械检查

机械 QA 复验提交物、当前结果、图表、模板和受控编译，不重新裁定数学正确性或比赛竞争力。

1. 只在独立科学红队、PDF 盲审和当前 PDF 都已准备好时运行：

   ```powershell
   python scripts/qa/run_final_checks.py runs/<run-id>
   ```

2. 它会检查 PDF 可读性、空白页、裁切、占位符、题号/结果标记、数字一致性、图表和结果漂移、模板匹配、编译回执及可选离线论文卡/贡献账本。失败时先定位实际文件或事实问题；不要手工修改 QA JSON。
3. `VERIFY_REPORT.md` 的内容密度、图表数、公式数和引用数只是人工定位线索，不能证明模型深入或结果有竞争力。科学正确性由独立红队，论文论证质量由 PDF 盲审决定。
4. 机械 QA 通过后进入 `final_review`，建立最终交付包：

   ```powershell
   python scripts/review/build_review_packet.py runs/<run-id> --kind final-audit
   ```

   协调任务必须实际调用 `create_thread` 新建第三个审核任务并用 `wait_threads` 等待。该任务调用 `$mathmodel-red-team`，只读冻结包且只能写 `review/FINAL_SUBMISSION_REVIEW.md`；协调任务使用新建任务返回的真实 `threadId` 导入，通过后才可进入 `complete`。不得由当前求解任务自行逐页检查后宣布终审通过。
5. 生产模式只有科学审查强度为 `qualified` 或 `strong`，三轮独立审核、机械 QA 和当前交付包全部有效时才能完成；`weak` 只能表示科学上可写，不能伪装为竞赛交付完成。任何论文、图表、结果、报告、提交表、QA 或 PDF 修改都会使相应审核失效；修复并重新编译后重走受影响的后续阶段。
