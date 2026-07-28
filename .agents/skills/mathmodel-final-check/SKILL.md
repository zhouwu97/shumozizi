---
name: mathmodel-final-check
description: 对 Competition-First v3.1 已编译论文执行机械 QA、当前事实复验和提交检查；不承担 final audit 或独立科学判断。
---

# 机械终检

在 `verify` 阶段运行：

```powershell
python scripts/qa/run_final_checks.py runs/<run-id>
```

它检查 PDF 可读性、匿名、占位符、乱码、裁切、空白页、当前结果与图表哈希、指标引用、数字一致性、模板和编译回执。通过只表示提交物和当前事实没有机械漂移，不证明数学正确性、最优性或论文说服力。

CUMCM v3.2 在机械 QA 通过后，用 `python scripts/paper/cumcm_adapter.py <run_dir> finalize --input <json>` 在既有 `paper/CUMCM_LAYOUT_AUDIT.json` 中补正文页数、图中文字、浮动体断句、公式溢出、跨章一致性、符号定义和 Word/PDF 检查。页数区间只触发说明或复核；发现论证发育不足或未解决版面问题才返工。不要新增第三份 CUMCM 审核文件。

PDF 盲评仍需存在或显式记录跳过原因；P0/P1、已验证反例、独立复算冲突、不可行和性质测试失败仍然阻断。不得创建 `final_review`、final-audit packet 或第三轮终审。
