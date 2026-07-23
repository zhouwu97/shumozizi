---
name: mathmodel-final-check
description: 对已通过独立 PDF 盲审的 Capability-First v3 论文执行机械 QA、追溯复验和 PDF 内容覆盖报告；仅在 verify 阶段、完整 PDF 即将提交时使用。
---

# 最终机械检查

机械 QA 复验提交物、当前结果、图表、模板和受控编译，不重新裁定数学正确性或比赛竞争力。

1. 只在独立科学红队、PDF 盲审和当前 PDF 都已准备好时运行：

   ```powershell
   python scripts/qa/run_final_checks.py runs/<run-id>
   ```

2. 它会检查 PDF 可读性、空白页、裁切、占位符、题号/结果标记、数字一致性、图表和结果漂移、模板匹配、编译回执及可选离线论文卡/贡献账本。失败时先定位实际文件或事实问题；不要手工修改 QA JSON。
3. `VERIFY_REPORT.md` 的内容密度、图表数、公式数和引用数只是人工定位线索，不能证明模型深入或结果有竞争力。科学正确性由独立红队，论文论证质量由 PDF 盲审决定。
4. 生产模式只有科学审查强度为 `qualified` 或 `strong`，并且机械 QA、盲审和当前 PDF 全部有效时才能进入 `complete`。`weak` 可以是科学上可写的结果，但必须显示为“不具竞争力”，不能伪装为交付完成。
5. 任何可见论文、图表或 PDF 的修改都会使盲审失效；回到 `paper_review` 建立新盲审包后再终检。
