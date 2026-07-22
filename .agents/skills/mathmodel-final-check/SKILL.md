---
name: mathmodel-final-check
description: 对 Capability-First v3 论文执行一次机械 QA 和一次整体科学审查；仅在完整 PDF 即将提交时使用，重大修复后最多做一次定向复查。
---

# 最终机械检查与整体审查

先检查确定性提交错误，再用完整产物做一次整体审查。机械通过不代表模型优秀，审查意见也不替代真实执行。

## 机械 QA

运行：

```powershell
python scripts/qa/run_final_checks.py runs/<run-id>
```

该命令输出 `qa/mechanical-qa.json`、`qa/contact-sheet.png` 和 `reports/VERIFY_REPORT.md`。它阻断 PDF 缺失/损坏、空白页、明显裁切或文字重叠、占位符、失效结果引用、current 结果哈希变化、指标来源变化及关键数值不一致等确定性错误。图表/表格编号只从图注和表题推断，目前作为 warning，避免正文正常引用造成误报。匿名投稿时追加 `--anonymous`，并可用 `--anonymous-term` 传入队名、学校等禁止词。必要时可单独使用 `tools/qa/figqa.py`、`pdf_qa.py` 或 `make_contact_sheet.py` 定位问题。

## 一次整体科学审查

读完整论文、代码、`results/index.json`、机械报告和联系表，写入 `qa/FINAL_REVIEW.md`。只检查：

- 是否覆盖全部必答问题并逐问直接回答；
- 模型是否对准题目目标；
- 关键结果是否有信息量，baseline 是否公平，正控制是否通过；
- 是否存在不可辨识、泄漏、不可行或不合理外推；
- 主张是否夸大，失败路线是否被包装为贡献；
- 最限制奖项竞争力的一项问题。

按 P0（基本无效/未回答）、P1（显著影响提交）、P2（局部缺口）、P3（可选优化）分级。只有 P0/P1 才触发一次定向修复；格式小改或 P2/P3 不得再开完整审查。核心模型、数据或结论发生重大变化时，允许一次定向复查并说明范围。
